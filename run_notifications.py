# run_notifications.py

import json
from datetime import datetime
from dining_checker import find_keyword_matches, send_email
import os
from dotenv import load_dotenv
from db import get_conn

load_dotenv()


def get_subscriptions():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, item_keywords, halls, last_notified_date
                FROM subscriptions;
            """)
            rows = cur.fetchall()
    return rows

def update_last_notified(email: str, date_str: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE subscriptions SET last_notified_date = %s WHERE email = %s",
                (date_str, email),
            )



def main():
    today = datetime.now().strftime("%Y-%m-%d")
    subs = get_subscriptions()

    for email, item_keywords_json, halls_json, last_date in subs:
        # One email per day max
        if last_date == today:
            continue

        try:
            keywords = json.loads(item_keywords_json)
        except Exception:
            keywords = []

        hall_filter = None
        if halls_json:
            try:
                hall_filter = set(json.loads(halls_json))
            except Exception:
                hall_filter = None

        # combined_matches_by_hall = {hall: {keyword: [dishes...]}}
        combined = {}

        for kw in keywords:
            if not kw:
                continue
            matches_by_hall = find_keyword_matches(kw)

            for hall, dishes in matches_by_hall.items():
                if hall_filter and hall not in hall_filter:
                    continue

                hall_entry = combined.setdefault(hall, {})
                kw_entry = hall_entry.setdefault(kw, [])
                kw_entry.extend(dishes)

        if combined:
            # Build a nice email body
            lines = []
            for hall, kw_map in combined.items():
                lines.append(f"{hall}:")
                for kw, dishes in kw_map.items():
                    lines.append(f"  {kw}:")
                    for dish in sorted(set(dishes)):
                        lines.append(f"    - {dish}")
                lines.append("")

            matches_text = "\n".join(lines)
            subject = f"[Dining] Your tracked items are on the menu today! ({today})"
            body = (
                f"Hi,\n\n"
                f"We found the following dishes matching your interests:\n\n"
                f"{matches_text}\n"
                f"You’re receiving this because you subscribed on the dining alerts site.\n"
            )

            print(f"Emailing {email} about keywords: {', '.join(keywords)}")
            send_email(email, subject, body)
            update_last_notified(email, today)
        else:
            print(f"No matches today for {email} (keywords: {', '.join(keywords)})")


if __name__ == "__main__":
    main()
