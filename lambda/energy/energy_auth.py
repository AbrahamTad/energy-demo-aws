"""Verify access-token signatures against a fixed Cognito JWKS issuer."""
from functools import lru_cache
import os
import re
from uuid import UUID

import jwt
from jwt import PyJWKClient
from energy_validation import ApiError


@lru_cache(maxsize=1)
def settings():
    pool, client = os.environ["COGNITO_USER_POOL_ID"], os.environ["COGNITO_CLIENT_ID"]
    if not re.fullmatch(r"eu-north-1_[A-Za-z0-9]+", pool) or not re.fullmatch(r"[a-z0-9]{1,128}", client):
        raise RuntimeError("Invalid Cognito deployment configuration")
    issuer = "https://cognito-idp.eu-north-1.amazonaws.com/" + pool
    return issuer, client, PyJWKClient(issuer + "/.well-known/jwks.json", timeout=2,
                                      cache_jwk_set=True, lifespan=300, cache_keys=False)


def subject(event):
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise ApiError(401, "A valid access token is required.")
    token = authorization[7:]
    if not token or len(token) > 8192 or "," in token:
        raise ApiError(401, "A valid access token is required.")
    issuer, client, keys = settings()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or not 1 <= len(header["kid"]) <= 128:
            raise jwt.InvalidTokenError()
        key = keys.get_signing_key_from_jwt(token).key
        # Cognito access tokens bind the client via client_id, not ID-token aud.
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=issuer,
            options={"require": ["exp", "iat", "iss", "sub", "token_use", "client_id"], "verify_aud": False})
        owner = claims["sub"]
        if claims["token_use"] != "access" or claims["client_id"] != client or str(UUID(owner)) != owner:
            raise jwt.InvalidTokenError()
        if "aws.cognito.signin.user.admin" not in claims.get("scope", "").split():
            raise jwt.InvalidTokenError()
        return owner
    except jwt.PyJWKClientConnectionError:
        raise ApiError(503, "The identity service is temporarily unavailable.") from None
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise ApiError(401, "A valid access token is required.") from None
