"""Existing public endpoint; this Lambda's role can only query the public table."""
from botocore.exceptions import BotoCoreError, ClientError
from energy_store import PublicRepository
from energy_validation import ApiError, response


def lambda_handler(event, context):
    if event.get("routeKey") != "GET /api/energy":
        return response(404, {"error": "Route not found."})
    try:
        return response(200, {"project": "EnergyDemo", "status": "working",
                              "records": PublicRepository().list()})
    except ApiError as error:
        return response(error.status, {"error": error.message})
    except (BotoCoreError, ClientError, KeyError):
        return response(503, {"error": "The energy service is temporarily unavailable."})
