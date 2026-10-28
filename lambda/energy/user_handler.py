"""Private CRUD API: every DynamoDB key is derived from a verified access JWT."""
from botocore.exceptions import BotoCoreError, ClientError
from energy_auth import subject
from energy_store import UserRepository
from energy_validation import ApiError, body, record_id, response


def lambda_handler(event, context):
    try:
        owner = subject(event)  # Ignore requestContext claims and client owner fields.
        method = event.get("requestContext", {}).get("http", {}).get("method")
        identifier = (event.get("pathParameters") or {}).get("record_id")
        route = event.get("routeKey")
        allowed = {"GET /api/me/energy", "POST /api/me/energy", "GET /api/me/energy/{record_id}",
                   "PUT /api/me/energy/{record_id}", "DELETE /api/me/energy/{record_id}"}
        if route not in allowed or not route.startswith(str(method) + " "):
            raise ApiError(404, "Route not found.")
        repo = UserRepository()
        query = event.get("queryStringParameters") or {}
        if set(query) - {"cursor"}:
            raise ApiError(400, "Only the cursor query parameter is supported.")
        if identifier:
            identifier = record_id(identifier)
            if method == "GET":
                return response(200, repo.get(owner, identifier))
            if method == "PUT":
                return response(200, repo.update(owner, identifier, body(event)))
            if method == "DELETE":
                repo.delete(owner, identifier)
                return response(204)
        elif method == "GET":
            cursor = record_id(query["cursor"]) if query.get("cursor") else None
            return response(200, repo.list(owner, cursor))
        elif method == "POST":
            return response(201, repo.create(owner, body(event)))
        raise ApiError(404, "Route not found.")
    except ApiError as error:
        return response(error.status, {"error": error.message})
    except (BotoCoreError, ClientError, KeyError, RuntimeError):
        # No exception bodies, tokens, database items, or user data in logs/output.
        return response(503, {"error": "The record service is temporarily unavailable."})
