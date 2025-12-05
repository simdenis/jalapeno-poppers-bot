# db.py
import os
from dotenv import load_dotenv
import psycopg

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

def get_conn():
    # autocommit for our simple use case
    return psycopg.connect(DATABASE_URL, autocommit=True)
