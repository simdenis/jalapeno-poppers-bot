# db.py
import os
from dotenv import load_dotenv
import psycopg

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


def get_conn():
    """
    Return a psycopg3 connection to Postgres.
    autocommit=True so we don't have to call conn.commit() manually.
    """
    return psycopg.connect(DATABASE_URL, autocommit=True)
