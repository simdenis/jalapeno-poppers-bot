# run_notifications.py

import os
import json
import hashlib
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

from db import get_conn, ensure_schema
from dining_checker import find_keyword_details, send_email
load_dotenv()
DEBUG_ALWAYS_NOTIFY = os.getenv("DEBUG_ALWAYS_NOTIFY", "false").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
UNSUBSCRIBE_TOKEN_TTL_DAYS = int(os.getenv("UNSUBSCRIBE_TOKEN_TTL_DAYS", "30"))


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


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_unsubscribe_token_for_email(email: str) -> str | None:
    if not BASE_URL:
        return None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if not row:
                return None
            user_id = row[0]

            token = os.urandom(24).hex()
            token_hash = _hash_token(token)
            expires_at = datetime.utcnow() + timedelta(days=UNSUBSCRIBE_TOKEN_TTL_DAYS)
            cur.execute(
                """
                INSERT INTO unsubscribe_tokens (token_hash, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token_hash, user_id, expires_at),
            )
            return token


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
            f"MIT Dining Alerts — {today.isoformat()}",
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


        unsubscribe_token = _create_unsubscribe_token_for_email(email)
        unsubscribe_link = (
            f"{BASE_URL}/unsubscribe/confirm?token={unsubscribe_token}"
            if unsubscribe_token
            else None
        )
        if unsubscribe_token:
            lines.extend(
                [
                    "",
                    "Unsubscribe:",
                    unsubscribe_link,
                ]
            )

        body = "\n".join(lines)
        subject = "MIT Dining Alerts — today’s matches"
        html_lines = []
        html_lines.append("<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', Arial, sans-serif; line-height: 1.5;\">")
        html_lines.append(f"<h2 style=\"margin: 0 0 8px;\">MIT Dining Alerts — {today.isoformat()}</h2>")
        html_lines.append(f"<p style=\"margin: 0 0 12px; color: #6b7280;\">Magic words: {', '.join(keywords)}</p>")
        html_lines.append("<div>")
        for hall_name in sorted(details.keys()):
            hall_data = details[hall_name]
            html_lines.append(f"<h3 style=\"margin: 12px 0 6px;\">{hall_name}</h3>")
            html_lines.append("<ul style=\"margin: 0 0 8px; padding-left: 18px;\">")
            for kw in sorted(hall_data.keys()):
                meals = sorted(hall_data[kw])
                meal_str = ", ".join(meals)
                html_lines.append(f"<li><strong>{kw}</strong> — {meal_str}</li>")
            html_lines.append("</ul>")
        html_lines.append("</div>")
        if unsubscribe_link:
            html_lines.append(
                f"<p style=\"margin: 16px 0 0;\">Unsubscribe: <a href=\"{unsubscribe_link}\">{unsubscribe_link}</a></p>"
            )
        html_lines.append("</div>")
        html_body = "".join(html_lines)

        send_email(email, subject, body, html_body=html_body)

        # Mark as notified today
        update_last_notified(email, today)


if __name__ == "__main__":
    main()
