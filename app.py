# app.py
from flask import Flask, render_template, request
import sqlite3
import json
from dining_checker import DINING_URLS  # reuse hall names
from dotenv import load_dotenv
import os
load_dotenv()
app = Flask(__name__)
DB_PATH = os.getenv("DB_PATH", "subscriptions.db")
DINING_HALLS = sorted(DINING_URLS.keys())


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        email TEXT PRIMARY KEY,
        item_keywords TEXT NOT NULL,   -- JSON list of strings
        halls TEXT,                    -- JSON list of hall names or NULL for "any hall"
        last_notified_date TEXT        -- "YYYY-MM-DD" of last email
    );
    """)
    conn.commit()
    conn.close()


@app.before_first_request
def setup_db():
    init_db()

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

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # See if user already exists
    cur.execute("SELECT item_keywords, halls FROM subscriptions WHERE email = ?", (email,))
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

        cur.execute(
            "UPDATE subscriptions SET item_keywords = ?, halls = ? WHERE email = ?",
            (json.dumps(current_keywords), halls_json, email),
        )
    else:
        # New user
        keywords_json = json.dumps(new_keywords)
        halls_json = json.dumps(halls_list) if halls_list else None
        cur.execute(
            "INSERT INTO subscriptions (email, item_keywords, halls, last_notified_date) "
            "VALUES (?, ?, ?, NULL)",
            (email, keywords_json, halls_json),
        )

    conn.commit()
    conn.close()

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

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM subscriptions WHERE email = ?", (email,))
    affected = cur.rowcount
    conn.commit()
    conn.close()

    if affected == 0:
        msg = "No active subscriptions found for that email."
    else:
        msg = "You’ve been unsubscribed from all alerts for this email."

    return render_template(
        "index.html",
        message=msg,
        halls=DINING_HALLS,
    )
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
