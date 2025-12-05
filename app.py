from flask import Flask, render_template, request
import os
import json
from datetime import date
from dotenv import load_dotenv

from db import get_conn
from dining_checker import DINING_URLS

load_dotenv()

app = Flask(__name__)

ADMIN_DEBUG_TOKEN = os.getenv("ADMIN_DEBUG_TOKEN")

# ------------------ DB SETUP ------------------


def init_db():
    """
    Create the subscriptions table in Postgres if it does not exist.
    We store keywords and halls as JSON-encoded TEXT for simplicity.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    email TEXT PRIMARY KEY,
                    item_keywords TEXT NOT NULL,
                    halls TEXT,
                    last_notified_date DATE
                );
                """
            )


# Run once at import time so gunicorn + local both get the table.
init_db()

DINING_HALLS = sorted(DINING_URLS.keys())


# ------------------ ROUTES ------------------


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        message="",
        halls=DINING_HALLS,
    )


@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip()
    keywords_str = request.form.get("keywords", "").strip()
    halls_selected = request.form.getlist("halls")
    halls_list = halls_selected or None

    # Parse magic words: comma-separated, allow spaces inside phrases
    new_keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

    if not email or not new_keywords:
        return render_template(
            "index.html",
            message="Please provide an email and at least one magic word (comma-separated).",
            halls=DINING_HALLS,
        )

    # Look up existing subscription
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_keywords, halls FROM subscriptions WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()

            if row:
                current_kw_json, current_halls_json = row
                current_keywords = (
                    json.loads(current_kw_json) if current_kw_json else []
                )

                # Merge keywords
                for kw in new_keywords:
                    if kw not in current_keywords:
                        current_keywords.append(kw)

                # Merge halls
                if current_halls_json:
                    stored_halls = json.loads(current_halls_json)
                else:
                    stored_halls = []

                if halls_list:
                    for h in halls_list:
                        if h not in stored_halls:
                            stored_halls.append(h)

                halls_json = json.dumps(stored_halls) if stored_halls else None

                cur.execute(
                    """
                    UPDATE subscriptions
                    SET item_keywords = %s, halls = %s
                    WHERE email = %s
                    """,
                    (json.dumps(current_keywords), halls_json, email),
                )
            else:
                # New subscriber
                keywords_json = json.dumps(new_keywords)
                halls_json = json.dumps(halls_list) if halls_list else None
                cur.execute(
                    """
                    INSERT INTO subscriptions
                    (email, item_keywords, halls, last_notified_date)
                    VALUES (%s, %s, %s, NULL)
                    """,
                    (email, keywords_json, halls_json),
                )

    return render_template(
        "index.html",
        message=(
            "Subscribed! We’ll watch for dishes matching: "
            f"{', '.join(new_keywords)}. "
            "(You can add more magic words later with the same email.)"
        ),
        halls=DINING_HALLS,
    )


@app.route("/unsubscribe", methods=["POST"])
def unsubscribe():
    email = request.form.get("email", "").strip()

    if not email:
        return render_template(
            "index.html",
            message="Please provide an email to unsubscribe.",
            halls=DINING_HALLS,
        )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE email = %s", (email,))
            affected = cur.rowcount

    if affected == 0:
        msg = "No active subscriptions found for that email."
    else:
        msg = "You’ve been unsubscribed from all alerts for this email."

    return render_template(
        "index.html",
        message=msg,
        halls=DINING_HALLS,
    )


# --------------- DEBUG VIEW (admin only) ---------------


@app.route("/debug/subscriptions")
def debug_subscriptions():
    """
    Simple HTML table showing all subscriptions.
    Protected by ?token=ADMIN_DEBUG_TOKEN.
    """
    token = request.args.get("token", "")
    if not ADMIN_DEBUG_TOKEN or token != ADMIN_DEBUG_TOKEN:
        return "Forbidden", 403

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT email, item_keywords, halls, last_notified_date
                FROM subscriptions
                ORDER BY email
                """
            )
            rows = cur.fetchall()

    html = [
        "<h1>Subscriptions</h1>",
        "<table border='1' cellpadding='4'>",
        "<tr><th>Email</th><th>Keywords (JSON)</th>"
        "<th>Halls (JSON)</th><th>Last notified</th></tr>",
    ]

    for email, kw_json, halls_json, last_notified in rows:
        html.append(
            "<tr>"
            f"<td>{email}</td>"
            f"<td><code>{kw_json}</code></td>"
            f"<td><code>{halls_json}</code></td>"
            f"<td>{last_notified}</td>"
            "</tr>"
        )

    html.append("</table>")
    return "\n".join(html)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
