# run_notifications.py

import os
import json
from datetime import date
from dotenv import load_dotenv

from db import get_conn
from dining_checker import find_item_locations, send_email

load_dotenv()


def get_subscriptions():
    """
    Return list of (email, keywords_list, halls_list, last_notified_date)
    from Postgres.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT email, item_keywords, halls, last_notified_date
                FROM subscriptions
                """
            )
            rows = cur.fetchall()

    subs = []
    for email, kw_json, halls_json, last_notified in rows:
        try:
            keywords = json.loads(kw_json) if kw_json else []
        except Exception:
            keywords = []

        try:
            halls = json.loads(halls_json) if halls_json else None
        except Exception:
            halls = None

        subs.append((email, keywords, halls, last_notified))

    return subs


def update_last_notified(email: str, when: date):
    """
    Set last_notified_date for a given email.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE subscriptions
                SET last_notified_date = %s
                WHERE email = %s
                """,
                (when, email),
            )


def main():
    today = date.today()
    subscriptions = get_subscriptions()

    for email, keywords, halls, last_notified in subscriptions:
        # Clean up keywords: strip whitespace, drop empties
        keywords = [k.strip() for k in keywords if k and k.strip()]
        if not keywords:
            continue

        # Only send at most once per day per user
        if last_notified is not None and last_notified >= today:
            continue

        # Find which dining halls contain ANY of these keywords
        # halls is either a list of hall names or None (meaning "all halls")
        hall_hits = find_item_locations(keywords, halls_filter=halls)

        # If no hall has any of the magic words, skip sending an email
        if not hall_hits:
            continue

        # Build a simple email body: only halls, no dish names
        lines = [
            f"Dining alerts for {today.isoformat()}",
            "",
            f"Magic words: {', '.join(keywords)}",
            "",
            "Found at:",
        ]

        for hall_name in hall_hits:
            lines.append(f"  - {hall_name}")

        body = "\n".join(lines)
        subject = "MIT Dining Alerts 🌶️"

        send_email(email, subject, body)

        # Mark as notified today
        update_last_notified(email, today)


if __name__ == "__main__":
    main()
