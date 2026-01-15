# run_notifications.py

import os
import json
from datetime import date
from dotenv import load_dotenv

from db import yessy, ensure_schema
from dining_checker import find_keyword_details, send_email
load_dotenv()
DEBUG_ALWAYS_NOTIFY = os.getenv("DEBUG_ALWAYS_NOTIFY", "false").lower() == "true"


def get_subscriptions():
    """
    Return list of (email, keywords_list, halls_list, last_notified_date)
    from Postgres.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.email, s.item_keywords, s.halls, s.last_notified_date
                FROM subscriptions s
                JOIN users u ON u.id = s.user_id
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
                WHERE user_id = (SELECT id FROM users WHERE email = %s)
                """,
                (when, email),
            )


def main():
    ensure_schema()
    today = date.today()
    subscriptions = get_subscriptions()

    for email, keywords, halls, last_notified in subscriptions:
        # Clean up keywords: strip whitespace, drop empties
        keywords = [k.strip() for k in keywords if k and k.strip()]
        if not keywords:
            continue

        # Only send at most once per day per user
        if not DEBUG_ALWAYS_NOTIFY:
            if last_notified is not None and last_notified >= today:
                continue

        # Find detailed matches: hall -> keyword -> {meals}
        details = find_keyword_details(keywords, halls_filter=halls)

        if not details:
            continue

        lines = [
            f"Dining alerts for {today.isoformat()}",
            "",
            f"Magic words: {', '.join(keywords)}",
            "",
            "Matches:",
        ]

        # Example structure in email:
        # Simmons Hall:
        #   - jalapeno — Lunch, Dinner
        #   - shrimp — Dinner
        for hall_name in sorted(details.keys()):
            hall_data = details[hall_name]
            lines.append(f"{hall_name}:")

            for kw in sorted(hall_data.keys()):
                meals = sorted(hall_data[kw])
                meal_str = ", ".join(meals)
                lines.append(f"  - {kw} — {meal_str}")

            lines.append("")  # blank line between halls


        body = "\n".join(lines)
        subject = "MIT Dining Alerts 🌶️"

        send_email(email, subject, body)

        # Mark as notified today
        update_last_notified(email, today)


if __name__ == "__main__":
    main()
