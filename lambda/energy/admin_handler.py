"""Read-only admin API and server-verified Cognito TOTP step-up."""
import json
import os
import time
import uuid
import boto3
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from admin_common import client, control, field, get, identity, live, payload, put, reserve, text, token_key
from energy_auth import verified_claims
from energy_store import table
from energy_validation import ApiError, public_record, private_record, record_id, response
from boto3.dynamodb.conditions import Key


def session(event, claims, user):
    raw = event.get("body") or "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and len(raw.encode()) <= 4096 else None
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        raise ApiError(400, "Invalid session request.")
    values = payload(event, ["password"] if "password" in parsed else ["challenge", "code"])
    cognito, pool = client("cognito-idp"), os.environ["COGNITO_USER_POOL_ID"]
    app = os.environ["ADMIN_COGNITO_CLIENT_ID"]
    now, binding = int(time.time()), token_key(event)
    reserve("AUTH#" + claims["sub"] + "#" + str(now // 60), 5, now + 120)
    if "password" in values:
        result = cognito.admin_initiate_auth(UserPoolId=pool, ClientId=app,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": user["Username"], "PASSWORD": text(values["password"], 128)})
        if result.get("ChallengeName") != "SOFTWARE_TOKEN_MFA" or not result.get("Session"):
            raise ApiError(403, "A Cognito authenticator challenge is required.")
        challenge = str(uuid.uuid4())
        put("CHALLENGE#" + challenge, {"binding": binding, "session": result["Session"],
            "username": user["Username"]}, now + 180)
        return {"challenge": challenge}
    key = "CHALLENGE#" + record_id(values["challenge"])
    saved = get(key)
    if not live(saved) or field(saved, "binding") != binding:
        raise ApiError(403, "The MFA challenge expired. Start again.")
    # Consume before contacting Cognito: concurrent requests cannot reuse it.
    client("dynamodb").delete_item(TableName=control(), Key={"pk": {"S": key}},
        ConditionExpression="binding=:binding", ExpressionAttributeValues={":binding": {"S": binding}})
    code = text(values["code"], 6)
    if len(code) != 6 or not code.isdigit():
        raise ApiError(400, "Enter a six-digit authenticator code.")
    result = cognito.admin_respond_to_auth_challenge(UserPoolId=pool, ClientId=app,
        ChallengeName="SOFTWARE_TOKEN_MFA", Session=field(saved, "session"),
        ChallengeResponses={"USERNAME": field(saved, "username"), "SOFTWARE_TOKEN_MFA_CODE": code})
    token = result.get("AuthenticationResult", {}).get("AccessToken", "")
    verified = verified_claims({"headers": {"authorization": "Bearer " + token}}, expected_client=app)
    if verified["sub"] != claims["sub"]:
        raise ApiError(403, "The MFA identity did not match.")
    expires = min(int(claims["exp"]), now + 900)
    put("PROOF#" + binding, {"subject": claims["sub"]}, expires)
    return {"verified_until": expires}


def page_token(event, owner, route):
    query = event.get("queryStringParameters") or {}
    if set(query) - {"cursor"}:
        raise ApiError(400, "Only cursor is supported; ownership cannot be selected.")
    if not query.get("cursor"):
        return None
    saved = get("CURSOR#" + record_id(query["cursor"]))
    if not live(saved) or field(saved, "owner") != owner or field(saved, "route") != route:
        raise ApiError(400, "Invalid or expired page cursor.")
    return json.loads(field(saved, "value"))


def next_cursor(value, owner, route):
    if not value:
        return None
    identifier = str(uuid.uuid4())
    put("CURSOR#" + identifier, {"owner": owner, "route": route, "value": json.dumps(value)}, int(time.time()) + 900)
    return identifier


def status():
    checks = {}
    for name, action in {
        "public_database": lambda: client("dynamodb").describe_table(TableName=os.environ["PUBLIC_ENERGY_TABLE"])["Table"]["TableStatus"],
        "admin_database": lambda: client("dynamodb").describe_table(TableName=control())["Table"]["TableStatus"],
        "cognito": lambda: client("cognito-idp").describe_user_pool(UserPoolId=os.environ["COGNITO_USER_POOL_ID"])["UserPool"].get("Status", "available"),
        "email": lambda: "enabled" if client("sesv2").get_account().get("SendingEnabled") else "disabled",
    }.items():
        try:
            checks[name] = action()
        except (ClientError, BotoCoreError, KeyError):
            checks[name] = "unavailable"
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "services": checks,
            "api_gateway": "request reached Lambda", "lambda": "responding",
            "private_access": "own records only", "email_daily_limit": 10}


def lambda_handler(event, context):
    try:
        route = event.get("routeKey", "")
        allowed = {"POST /api/admin/session", "GET /api/admin/session", "GET /api/admin/users",
                   "GET /api/admin/records/public", "GET /api/admin/records/mine", "GET /api/admin/status"}
        if route not in allowed or not route.startswith(event.get("requestContext", {}).get("http", {}).get("method", "!") + " "):
            raise ApiError(404, "Route not found.")
        claims, user = identity(event, step_up=route != "POST /api/admin/session")
        owner = claims["sub"]
        if route == "POST /api/admin/session":
            if event.get("queryStringParameters"):
                raise ApiError(400, "Query parameters are not supported here.")
            result = session(event, claims, user)
            put("AUDIT#" + str(uuid.uuid4()), {"actor": owner, "route": route,
                "at": int(time.time()), "outcome": "success"}, int(time.time()) + 30 * 86400)
            return response(200, result)
        cursor = page_token(event, owner, route)
        if route == "GET /api/admin/session":
            result = {"verified": True}
        elif route.endswith("/users"):
            options = {"UserPoolId": os.environ["COGNITO_USER_POOL_ID"], "Limit": 25, "AttributesToGet": ["sub"]}
            if cursor:
                options["PaginationToken"] = cursor
            page = client("cognito-idp").list_users(**options)
            # Deliberately exclude email, name, phone, raw attributes and username.
            users = [{"id": next((a["Value"] for a in u.get("Attributes", []) if a["Name"] == "sub"), ""),
                      "status": u.get("UserStatus", "UNKNOWN"), "enabled": bool(u.get("Enabled"))} for u in page.get("Users", [])]
            result = {"users": users, "next_cursor": next_cursor(page.get("PaginationToken"), owner, route)}
        elif route.endswith("/public"):
            options = {"KeyConditionExpression": Key("dataset").eq("PUBLIC"), "Limit": 25}
            if cursor:
                options["ExclusiveStartKey"] = {"dataset": "PUBLIC", "source": cursor}
            page = table("PUBLIC_ENERGY_TABLE").query(**options)
            result = {"records": [public_record(r) for r in page.get("Items", [])],
                      "next_cursor": next_cursor(page.get("LastEvaluatedKey", {}).get("source"), owner, route)}
        elif route.endswith("/mine"):
            credentials = client("sts").assume_role(RoleArn=os.environ["ADMIN_PRIVATE_ROLE_ARN"],
                RoleSessionName="admin-own-records", DurationSeconds=900,
                Tags=[{"Key": "user_sub", "Value": owner}])["Credentials"]
            private = boto3.resource("dynamodb", aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"]).Table(os.environ["USER_ENERGY_TABLE"])
            options = {"KeyConditionExpression": Key("user_sub").eq(owner), "Limit": 25, "ConsistentRead": True}
            if cursor:
                options["ExclusiveStartKey"] = {"user_sub": owner, "record_id": record_id(cursor)}
            page = private.query(**options)
            result = {"records": [private_record(r) for r in page.get("Items", [])],
                "next_cursor": next_cursor(page.get("LastEvaluatedKey", {}).get("record_id"), owner, route)}
        else:
            result = status()
        put("AUDIT#" + str(uuid.uuid4()), {"actor": owner, "route": route,
            "at": int(time.time()), "outcome": "success"}, int(time.time()) + 30 * 86400)
        return response(200, result)
    except ApiError as error:
        return response(error.status, {"error": error.message})
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(429, {"error": "Too many attempts or challenge already consumed."})
        if code in {"NotAuthorizedException", "CodeMismatchException", "ExpiredCodeException", "UserNotFoundException"}:
            return response(403, {"error": "Admin verification failed. Start again."})
        return response(503, {"error": "The admin service is temporarily unavailable."})
    except (BotoCoreError, KeyError, ValueError, TypeError, RuntimeError):
        return response(503, {"error": "The admin service is temporarily unavailable."})
