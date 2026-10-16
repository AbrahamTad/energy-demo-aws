
# Import required libraries
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Load database settings for local development
env_path = Path(__file__).resolve().parent.parent / "database" / ".env"
load_dotenv(env_path)

# Connect to PostgreSQL (Ubuntu or Docker)
def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5
    )
