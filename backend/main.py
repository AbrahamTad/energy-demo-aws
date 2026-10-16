
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row

from db import get_connection

app = FastAPI(title="EnergyDemo API", version="1.0.0")

# Home endpoint
@app.get("/")
def home():
    return {"message": "Welcome to EnergyDemo Python API"}

# Read energy records from PostgreSQL
@app.get("/api/energy")
def get_energy():
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, source, production, unit
                    FROM energy_records
                    ORDER BY id
                    """
                )
                records = cursor.fetchall()

        return {
            "project": "Energy Demo",
            "status": "working",
            "records": records
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


# Validate new energy records
class EnergyCreate(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    production: float = Field(ge=0)
    unit: str = Field(default="kWh", max_length=10)


# Create a new energy record in PostgreSQL
@app.post("/api/energy", status_code=201)
def create_energy(record: EnergyCreate):
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO energy_records
                        (source, production, unit)
                    VALUES (%s, %s, %s)
                    RETURNING id, source, production, unit
                    """,
                    (record.source, record.production, record.unit)
                )
                new_record = cursor.fetchone()

        return new_record

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )


# Update an existing energy record
@app.put("/api/energy/{record_id}")
def update_energy(record_id: int, record: EnergyCreate):
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    UPDATE energy_records
                    SET source = %s,
                        production = %s,
                        unit = %s
                    WHERE id = %s
                    RETURNING id, source, production, unit
                    """,
                    (
                        record.source,
                        record.production,
                        record.unit,
                        record_id
                    )
                )
                updated_record = cursor.fetchone()

        if updated_record is None:
            raise HTTPException(
                status_code=404,
                detail="Energy record not found"
            )

        return updated_record

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )

# Delete an energy record by its ID
@app.delete("/api/energy/{record_id}")
def delete_energy(record_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM energy_records
                    WHERE id = %s
                    RETURNING id
                    """,
                    (record_id,)
                )
                deleted_record = cursor.fetchone()

        # Return 404 if the record does not exist
        if deleted_record is None:
            raise HTTPException(
                status_code=404,
                detail="Energy record not found"
            )

        return {"message": "Record deleted successfully"}

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database operation failed"
        )
