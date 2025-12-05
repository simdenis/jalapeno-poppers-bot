from flask import Flask, render_template, request
import os
import sqlite3
import json
from dotenv import load_dotenv
from dining_checker import DINING_URLS
from db import get_conn

load_dotenv()

ADMIN_DEBUG_TOKEN = os.getenv("ADMIN_DEBUG_TOKEN")

app = Flask(__name__)

# ---------- DB SETUP ----------

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    email TEXT PRIMARY KEY,
                    item_keywords TEXT NOT NULL,
                    halls TEXT,
                    last_notified_date DATE
                );
            """)


# run once when the module is imported (works for gunicorn + local)
init_db()

# ---------- CONSTANTS ----------

DINING_HALLS = sorted(DINING_URLS.keys())

# ---------- ROUTES ----------

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

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_keywords, halls FROM subscriptions WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()

    if row:
        current_kw_json, current_halls_json = row
        current_keywords = json.loads(current_kw_json) if current_kw_json else []

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

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE subscriptions SET item_keywords = %s, halls = %s WHERE email = %s",
                    (json.dumps(current_keywords), halls_json, email),
                )

    else:
        # New user
        keywords_json = json.dumps(new_keywords)
        halls_json = json.dumps(halls_list) if halls_list else None
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO subscriptions (email, item_keywords, halls, last_notified_date) "
                    "VALUES (%s, %s, %s, NULL)",
                    (email, keywords_json, halls_json),
                )

    return render_template(
        "index.html",
        message=f"Subscribed! We’ll watch for dishes matching: {', '.join(new_keywords)}. "
                f"(You can add more magic words later with the same email.)",
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

@app.route("/debug/subscriptions")
def debug_subscriptions():
    """Very simple debug view to inspect subscriptions.
       Protected by ?token=... so random people can't see it.
       REMOVE OR LOCK DOWN once you're done debugging.
    """
    token = request.args.get("token", "")
    if not ADMIN_DEBUG_TOKEN or token != ADMIN_DEBUG_TOKEN:
        return "Forbidden", 403

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, item_keywords, halls, last_notified_date "
                "FROM subscriptions"
            )
            rows = cur.fetchall()

    # build quick HTML table
    html = ["<h1>Subscriptions</h1><table border='1' cellpadding='4'>"]
    html.append("<tr><th>Email</th><th>Keywords (JSON)</th><th>Halls (JSON)</th><th>Last notified</th></tr>")
    for email, kw_json, halls_json, last_date in rows:
        html.append(
            f"<tr>"
            f"<td>{email}</td>"
            f"<td><code>{kw_json}</code></td>"
            f"<td><code>{halls_json}</code></td>"
            f"<td>{last_date}</td>"
            f"</tr>"
        )
    html.append("</table>")
    return "\n".join(html)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
