# db.py
import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


def get_conn():
    """
    Return a psycopg2 connection to Postgres.
    autocommit=True so we don't have to call conn.commit() manually.
    """
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def ensure_schema():
    """
    Ensure users/subscriptions tables exist and migrate legacy schema if present.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'subscriptions'
                """
            )
            columns = {row[0] for row in cur.fetchall()}

            legacy_schema = "email" in columns and "user_id" not in columns

            legacy_table = "subscriptions_legacy"
            if legacy_schema:
                cur.execute(
                    """
                    SELECT to_regclass('public.subscriptions_legacy')
                    """
                )
                legacy_exists = cur.fetchone()[0] is not None
                if legacy_exists:
                    legacy_table = "subscriptions_legacy_1"
                cur.execute(f"ALTER TABLE subscriptions RENAME TO {legacy_table}")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    oidc_sub TEXT UNIQUE,
                    email TEXT UNIQUE NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    item_keywords TEXT NOT NULL,
                    halls TEXT,
                    last_notified_date DATE
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS login_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    uses_left INTEGER NOT NULL DEFAULT 2
                );
                """
            )
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'login_tokens' AND column_name = 'uses_left'
                    ) THEN
                        ALTER TABLE login_tokens ADD COLUMN uses_left INTEGER NOT NULL DEFAULT 2;
                    END IF;
                END $$;
                """
            )

            if legacy_schema:
                cur.execute(
                    """
                    INSERT INTO users (email)
                    SELECT DISTINCT email FROM """
                    + legacy_table
                    + """
                    ON CONFLICT (email) DO NOTHING
                    """
                )
                cur.execute(
                    """
                    INSERT INTO subscriptions (user_id, item_keywords, halls, last_notified_date)
                    SELECT u.id, s.item_keywords, s.halls, s.last_notified_date
                    FROM """
                    + legacy_table
                    + """ s
                    JOIN users u ON u.email = s.email
                    ON CONFLICT (user_id) DO UPDATE SET
                        item_keywords = EXCLUDED.item_keywords,
                        halls = EXCLUDED.halls,
                        last_notified_date = EXCLUDED.last_notified_date
                    """
                )
