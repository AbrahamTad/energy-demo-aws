"""Real RSA JWT verification and Moto DynamoDB; never contacts AWS/JWKS."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda/energy"))
import handler
import user_handler
import energy_auth
import energy_store

POOL = "eu-north-1_OfflineFixture"
CLIENT = "fixtureclient"
ISSUER = "https://cognito-idp.eu-north-1.amazonaws.com/" + POOL
OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": "eu-north-1",
            "AWS_EC2_METADATA_DISABLED": "true", "PUBLIC_ENERGY_TABLE": "public-energy",
            "USER_ENERGY_TABLE": "user-energy", "COGNITO_USER_POOL_ID": POOL, "COGNITO_CLIENT_ID": CLIENT,
        })
        self.env.start(); self.addCleanup(self.env.stop)
        self.aws = mock_aws(); self.aws.start(); self.addCleanup(self.aws.stop)
        energy_store.table.cache_clear(); energy_auth.settings.cache_clear()
        self.addCleanup(energy_store.table.cache_clear); self.addCleanup(energy_auth.settings.cache_clear)
        db = boto3.resource("dynamodb", region_name="eu-north-1")
        for name, partition, sort in [("public-energy", "dataset", "source"), ("user-energy", "user_sub", "record_id")]:
            db.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": partition, "KeyType": "HASH"}, {"AttributeName": sort, "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": partition, "AttributeType": "S"}, {"AttributeName": sort, "AttributeType": "S"}])
        self.keys = patch.object(energy_auth.PyJWKClient, "get_signing_key_from_jwt", return_value=SimpleNamespace(key=self.key.public_key()))
        self.keys.start(); self.addCleanup(self.keys.stop)

    def token(self, owner=OWNER, changes=None, key=None):
        claims = {"iss": ISSUER, "sub": owner, "client_id": CLIENT, "token_use": "access",
                  "iat": int(time.time()) - 1, "exp": int(time.time()) + 900, "scope": "aws.cognito.signin.user.admin"}
        claims.update(changes or {})
        return jwt.encode(claims, key or self.key, algorithm="RS256", headers={"kid": "fixture"})

    def call(self, method="GET", identifier=None, values=None, owner=OWNER, token=None, query=None):
        event = {"version": "2.0", "routeKey": method + " /api/me/energy" + ("/{record_id}" if identifier else ""),
                 "requestContext": {"http": {"method": method}}, "headers": {"authorization": "Bearer " + (token or self.token(owner))},
                 "pathParameters": {"record_id": identifier} if identifier else None,
                 "queryStringParameters": query, "body": json.dumps(values) if values is not None else None}
        result = user_handler.lambda_handler(event, None)
        return result["statusCode"], json.loads(result["body"]) if result["body"] else None

    def values(self):
        return {"source": "Solar", "production": 12.125, "unit": "kWh", "measured_at": "2026-10-27T10:00:00Z"}

    def test_crud_and_missing_records(self):
        self.assertEqual(self.call()[1], {"records": [], "next_cursor": None})
        status, created = self.call("POST", values=self.values())
        self.assertEqual(status, 201); identifier = created["id"]
        self.assertEqual(self.call(identifier=identifier)[1]["production"], 12.125)
        self.assertEqual(len(self.call()[1]["records"]), 1)
        changed = {**self.values(), "production": 77}
        self.assertEqual(self.call("PUT", identifier, changed)[1]["production"], 77)
        self.assertEqual(self.call("DELETE", identifier)[0], 204)
        for method in ["GET", "PUT", "DELETE"]:
            self.assertEqual(self.call(method, identifier, self.values())[0], 404)

    def test_cross_user_reads_updates_deletes_and_cursor_are_isolated(self):
        identifier = self.call("POST", values=self.values())[1]["id"]
        for method in ["GET", "PUT", "DELETE"]:
            self.assertEqual(self.call(method, identifier, self.values(), owner=OTHER)[0], 404)
        self.assertEqual(self.call(owner=OTHER)[1]["records"], [])
        self.assertEqual(self.call(owner=OTHER, query={"cursor": identifier})[1]["records"], [])
        self.assertEqual(self.call(identifier=identifier)[1]["production"], 12.125)

    def test_public_endpoint_reads_only_public_partition_and_whitelists_fields(self):
        self.call("POST", values=self.values())
        public = energy_store.table("PUBLIC_ENERGY_TABLE")
        public.put_item(Item={"dataset": "PUBLIC", "source": "Wind", "production": Decimal("7.5"), "unit": "kWh", "unexpected": "not exposed"})
        public.put_item(Item={"dataset": "OTHER", "source": "Private", "production": Decimal("5"), "unit": "kWh"})
        result = handler.lambda_handler({"routeKey": "GET /api/energy"}, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["records"], [{"source": "Wind", "production": 7.5, "unit": "kWh"}])
        self.assertIn("no-store", result["headers"]["Cache-Control"])

    def test_empty_public_table_has_no_hardcoded_fallback(self):
        self.assertEqual(json.loads(handler.lambda_handler({"routeKey": "GET /api/energy"}, None)["body"])["records"], [])

    def test_rejects_id_tokens_wrong_client_issuer_expiry_scope_and_signature(self):
        invalid = [{"token_use": "id", "aud": CLIENT}, {"client_id": "otherclient"}, {"iss": "https://example.invalid"},
                   {"exp": int(time.time()) - 10}, {"iat": int(time.time()) + 600}, {"scope": "other"}, {"sub": "not-a-uuid"}]
        for changes in invalid:
            with self.subTest(changes=changes): self.assertEqual(self.call(token=self.token(changes=changes))[0], 401)
        self.assertEqual(self.call(token=self.token(key=self.other_key))[0], 401)
        self.assertEqual(self.call(token="not-a-jwt")[0], 401)
        hs = jwt.encode({"sub": OWNER}, "test-only-symmetric-key-for-invalid-algorithm", algorithm="HS256", headers={"kid": "fixture"})
        self.assertEqual(self.call(token=hs)[0], 401)

    def test_forged_gateway_claims_do_not_replace_a_token(self):
        event = {"routeKey": "GET /api/me/energy", "requestContext": {"authorizer": {"jwt": {"claims": {"sub": OWNER}}}}}
        self.assertEqual(user_handler.lambda_handler(event, None)["statusCode"], 401)

    def test_required_claims_and_missing_authorization(self):
        for missing in ["exp", "iat", "sub", "iss", "token_use", "client_id"]:
            payload = jwt.decode(self.token(), self.key.public_key(), algorithms=["RS256"], options={"verify_aud": False})
            del payload[missing]
            token = jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": "fixture"})
            self.assertEqual(self.call(token=token)[0], 401)
        self.assertEqual(user_handler.lambda_handler({"headers": {}}, None)["statusCode"], 401)

    def test_invalid_inputs_and_owner_injection(self):
        for change in [{"user_sub": OTHER}, {"source": ""}, {"production": -1}, {"production": True}, {"production": "12"},
                       {"production": float("nan")}, {"production": 1.0001}, {"unit": "MWh"}, {"measured_at": "yesterday"}, {"measured_at": "2026-10-27"}]:
            with self.subTest(change=change): self.assertEqual(self.call("POST", values={**self.values(), **change})[0], 400)
        self.assertEqual(self.call(identifier="bad-id")[0], 400)
        self.assertEqual(self.call(query={"owner": OTHER})[0], 400)

    def test_pagination_has_no_owner_in_the_cursor(self):
        for _ in range(26): self.call("POST", values=self.values())
        first = self.call()[1]
        self.assertEqual(len(first["records"]), 25)
        second = self.call(query={"cursor": first["next_cursor"]})[1]
        self.assertEqual(len(second["records"]), 1)
        self.assertIsNone(second["next_cursor"])

    def test_database_and_jwks_failures_return_sanitized_errors(self):
        with patch.object(energy_store.UserRepository, "list", side_effect=ClientError({"Error": {"Code": "ThrottlingException", "Message": "sensitive"}}, "Query")):
            status, payload = self.call()
            self.assertEqual(status, 503); self.assertNotIn("sensitive", str(payload))
        with patch.object(energy_auth.PyJWKClient, "get_signing_key_from_jwt", side_effect=jwt.PyJWKClientConnectionError("unreachable")):
            self.assertEqual(self.call()[0], 503)
