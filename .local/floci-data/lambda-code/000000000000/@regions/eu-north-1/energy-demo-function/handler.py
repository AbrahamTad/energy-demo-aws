import json

def lambda_handler(event, context):
    # Return sample energy data
    records = [
        {"source": "Solar", "production": 125, "unit": "kWh"},
        {"source": "Wind", "production": 80, "unit": "kWh"},
        {"source": "Hydro", "production": 150, "unit": "kWh"},
        {"source": "Battery", "production": 45, "unit": "kWh"}
    ]

    return {
        "statusCode": 200,
        "body": json.dumps({
            "project": "EnergyDemo",
            "status": "working",
            "records": records
        })
    }
