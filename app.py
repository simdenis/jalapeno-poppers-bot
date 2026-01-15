from flask import Flask, render_template, request, session, redirect, url_for
import os
import json
import secrets
import hashlib
from datetime import date, datetime, timedelta
from functools import wraps
from collections import Counter
from dotenv import load_dotenv
from db import get_conn, ensure_schema
from dining_checker import DINING_URLS, find_keyword_details, send_email


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is not set")

SEND_WELCOME = os.getenv("SEND_WELCOME_EMAILS", "false").lower() == "true"
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
MIT_EMAIL_DOMAIN = "mit.edu"
MAGIC_TOKEN_TTL_MINUTES = int(os.getenv("MAGIC_TOKEN_TTL_MINUTES", "30"))
LOGIN_RATE_LIMIT_ENABLED = os.getenv("LOGIN_RATE_LIMIT_ENABLED", "true").lower() == "true"
LOGIN_RATE_LIMIT_WINDOW_MINUTES = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_MINUTES", "10"))
LOGIN_RATE_LIMIT_MAX = int(os.getenv("LOGIN_RATE_LIMIT_MAX", "3"))
UNSUBSCRIBE_TOKEN_TTL_DAYS = int(os.getenv("UNSUBSCRIBE_TOKEN_TTL_DAYS", "30"))
RATE_LIMIT_BYPASS_EMAILS = {
    "simdenis@mit.edu",
}

# ------------------ DB SETUP ------------------


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("index", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def get_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf():
    token = request.form.get("csrf_token", "")
    return token and token == session.get("csrf_token")


def _is_admin_email(email: str) -> bool:
    return email.lower() in ADMIN_EMAILS


def _is_mit_email(email: str) -> bool:
    return email.lower().endswith(f"@{MIT_EMAIL_DOMAIN}")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _upsert_user_by_email(email: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, oidc_sub FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                return row[0]

            cur.execute(
                "INSERT INTO users (email) VALUES (%s) RETURNING id",
                (email,),
            )
            return cur.fetchone()[0]


def _create_login_token(email: str) -> str:
    user_id = _upsert_user_by_email(email)
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = datetime.utcnow() + timedelta(minutes=MAGIC_TOKEN_TTL_MINUTES)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM login_tokens WHERE expires_at < NOW()
                """
            )
            cur.execute(
                """
                INSERT INTO login_tokens (token_hash, user_id, expires_at, uses_left)
                VALUES (%s, %s, %s, %s)
                """,
                (token_hash, user_id, expires_at, 2),
            )
    return token


def _is_rate_limited(email: str) -> bool:
    if not LOGIN_RATE_LIMIT_ENABLED:
        return False
    if email.lower() in RATE_LIMIT_BYPASS_EMAILS:
        return False
    window_start = datetime.utcnow() - timedelta(minutes=LOGIN_RATE_LIMIT_WINDOW_MINUTES)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM login_tokens lt
                JOIN users u ON u.id = lt.user_id
                WHERE u.email = %s AND lt.created_at >= %s
                """,
                (email, window_start),
            )
            count = cur.fetchone()[0]
    return count >= LOGIN_RATE_LIMIT_MAX


def _create_unsubscribe_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires_at = datetime.utcnow() + timedelta(days=UNSUBSCRIBE_TOKEN_TTL_DAYS)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM unsubscribe_tokens WHERE expires_at < NOW()"
            )
            cur.execute(
                """
                INSERT INTO unsubscribe_tokens (token_hash, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token_hash, user_id, expires_at),
            )
    return token


def _consume_unsubscribe_token(token: str):
    token_hash = _hash_token(token)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id FROM unsubscribe_tokens
                WHERE token_hash = %s AND expires_at > NOW()
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "DELETE FROM unsubscribe_tokens WHERE token_hash = %s",
                    (token_hash,),
                )
                return row[0]
    return None


def _consume_login_token(token: str):
    token_hash = _hash_token(token)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, uses_left FROM login_tokens
                WHERE token_hash = %s AND expires_at > NOW()
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            if row:
                user_id, uses_left = row
                uses_left -= 1
                if uses_left <= 0:
                    cur.execute(
                        "DELETE FROM login_tokens WHERE token_hash = %s",
                        (token_hash,),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE login_tokens SET uses_left = %s
                        WHERE token_hash = %s
                        """,
                        (uses_left, token_hash),
                    )
                return user_id
    return None


def _get_subscription(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT item_keywords, halls, last_notified_date
                FROM subscriptions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None

    kw_json, halls_json, last_notified = row
    try:
        keywords = json.loads(kw_json) if kw_json else []
    except Exception:
        keywords = []
    try:
        halls = json.loads(halls_json) if halls_json else []
    except Exception:
        halls = []
    return {
        "keywords": keywords,
        "halls": halls,
        "last_notified": last_notified,
    }


# Run once at import time so gunicorn + local both get the table.
ensure_schema()

DINING_HALLS = sorted(DINING_URLS.keys())


# ------------------ ROUTES ------------------


@app.route("/", methods=["GET"])
def index():
    login_next = request.args.get("next", "")
    keyword_counts = Counter()
    hall_counts = Counter()
    total_subscriptions = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_keywords, halls FROM subscriptions")
            rows = cur.fetchall()

    for kw_json, halls_json in rows:
        total_subscriptions += 1
        try:
            keywords = json.loads(kw_json) if kw_json else []
        except Exception:
            keywords = []
        try:
            halls = json.loads(halls_json) if halls_json else []
        except Exception:
            halls = []

        keyword_counts.update([k for k in keywords if k])
        hall_counts.update([h for h in halls if h])

    return render_template(
        "index.html",
        message="",
        halls=DINING_HALLS,
        csrf_token=get_csrf_token(),
        is_logged_in="user_id" in session,
        user_email=session.get("user_email", ""),
        profile_url=url_for("profile"),
        total_subscriptions=total_subscriptions,
        top_keywords=keyword_counts.most_common(5),
        top_halls=hall_counts.most_common(5),
        login_next=login_next,
    )

@app.route("/login/start", methods=["POST"])
def login_start():
    if not validate_csrf():
        return "Bad Request", 400

    email = request.form.get("email", "").strip().lower()
    next_url = request.form.get("next", "")
    if next_url.startswith("/"):
        session["post_login_redirect"] = next_url

    if not email or not _is_mit_email(email):
        return render_template(
            "index.html",
            message="Please use your @mit.edu email to sign in.",
            halls=DINING_HALLS,
            csrf_token=get_csrf_token(),
            is_logged_in=False,
            user_email="",
            login_next=next_url,
        )

    if _is_rate_limited(email):
        return render_template(
            "index.html",
            message="Too many login links requested. Try again in a few minutes.",
            halls=DINING_HALLS,
            csrf_token=get_csrf_token(),
            is_logged_in=False,
            user_email="",
            login_next=next_url,
        )

    token = _create_login_token(email)
    base_url = BASE_URL or request.url_root.rstrip("/")
    magic_link = f"{base_url}{url_for('magic_login')}?token={token}"

    body_lines = [
        "MIT Dining Alerts login link",
        "",
        "Click to sign in:",
        magic_link,
        "",
        f"This link expires in {MAGIC_TOKEN_TTL_MINUTES} minutes.",
    ]
    try:
        send_email(email, "Your MIT Dining Alerts sign-in link", "\n".join(body_lines))
    except Exception as e:
        print(f"[WARN] Failed to send login link to {email}: {e}")
        return render_template(
            "index.html",
            message="We couldn’t send the login email. Please try again later.",
            halls=DINING_HALLS,
            csrf_token=get_csrf_token(),
            is_logged_in=False,
            user_email="",
            login_next=next_url,
        )

    return render_template(
        "index.html",
        message="Check your email for a sign-in link.",
        halls=DINING_HALLS,
        csrf_token=get_csrf_token(),
        is_logged_in=False,
        user_email="",
        login_next=next_url,
    )


@app.route("/auth/magic", methods=["GET", "POST"])
def magic_login():
    if request.method == "POST":
        token = request.form.get("token", "")
        if not token:
            return "Invalid login link", 400

        user_id = _consume_login_token(token)
        if not user_id:
            return "Login link expired or invalid", 400

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                if not row:
                    return "Invalid login", 400
                email = row[0]

        session["user_id"] = user_id
        session["user_email"] = email
        return redirect(session.pop("post_login_redirect", url_for("index")))

    token = request.args.get("token", "")
    if not token:
        return "Invalid login link", 400
    return render_template("magic_login.html", token=token)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET"])
@login_required
def profile():
    subscription = _get_subscription(session["user_id"])
    matches = None
    if subscription and subscription["keywords"]:
        try:
            halls_filter = subscription["halls"] or None
            matches = find_keyword_details(subscription["keywords"], halls_filter=halls_filter)
        except Exception as e:
            print(f"[WARN] Failed to load menu matches for profile: {e}")
    return render_template(
        "profile.html",
        subscription=subscription,
        matches=matches,
        user_email=session.get("user_email", ""),
        profile_url=url_for("profile"),
        csrf_token=get_csrf_token(),
    )


@app.route("/profile/remove-keyword", methods=["POST"])
@login_required
def remove_keyword():
    if not validate_csrf():
        return "Bad Request", 400

    keyword = request.form.get("keyword", "").strip()
    if not keyword:
        return redirect(url_for("profile"))

    subscription = _get_subscription(session["user_id"])
    if not subscription:
        return redirect(url_for("profile"))

    keywords = [k for k in subscription["keywords"] if k != keyword]
    halls = subscription["halls"] or []
    halls_json = json.dumps(halls) if halls else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE subscriptions
                SET item_keywords = %s, halls = %s
                WHERE user_id = %s
                """,
                (json.dumps(keywords), halls_json, session["user_id"]),
            )

    return redirect(url_for("profile"))


@app.route("/profile/remove-hall", methods=["POST"])
@login_required
def remove_hall():
    if not validate_csrf():
        return "Bad Request", 400

    hall = request.form.get("hall", "").strip()
    if not hall:
        return redirect(url_for("profile"))

    subscription = _get_subscription(session["user_id"])
    if not subscription:
        return redirect(url_for("profile"))

    halls = [h for h in subscription["halls"] if h != hall]
    keywords = subscription["keywords"] or []
    halls_json = json.dumps(halls) if halls else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE subscriptions
                SET item_keywords = %s, halls = %s
                WHERE user_id = %s
                """,
                (json.dumps(keywords), halls_json, session["user_id"]),
            )

    return redirect(url_for("profile"))


@app.route("/stats", methods=["GET"])
def stats():
    keyword_counts = Counter()
    hall_counts = Counter()
    total_subscriptions = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_keywords, halls FROM subscriptions")
            rows = cur.fetchall()

    for kw_json, halls_json in rows:
        total_subscriptions += 1
        try:
            keywords = json.loads(kw_json) if kw_json else []
        except Exception:
            keywords = []
        try:
            halls = json.loads(halls_json) if halls_json else []
        except Exception:
            halls = []

        keyword_counts.update([k for k in keywords if k])
        hall_counts.update([h for h in halls if h])

    return render_template(
        "stats.html",
        total_subscriptions=total_subscriptions,
        keyword_counts=keyword_counts.most_common(20),
        hall_counts=hall_counts.most_common(10),
    )


@app.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    if not validate_csrf():
        return "Bad Request", 400

    email = session.get("user_email", "").strip()
    keywords_str = request.form.get("keywords", "").strip()
    halls_selected = request.form.getlist("halls")
    halls_list = halls_selected or None

    # Parse magic words: comma-separated, allow spaces inside phrases
    new_keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

    if not email or not new_keywords:
        return render_template(
            "index.html",
            message="Please provide at least one magic word (comma-separated).",
            halls=DINING_HALLS,
            csrf_token=get_csrf_token(),
            is_logged_in=True,
            user_email=email,
        )

    # Look up existing subscription
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_keywords, halls FROM subscriptions WHERE user_id = %s",
                (session["user_id"],),
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
                    WHERE user_id = %s
                    """,
                    (json.dumps(current_keywords), halls_json, session["user_id"]),
                )
            else:
                # New subscriber
                keywords_json = json.dumps(new_keywords)
                halls_json = json.dumps(halls_list) if halls_list else None
                cur.execute(
                    """
                    INSERT INTO subscriptions
                    (user_id, item_keywords, halls, last_notified_date)
                    VALUES (%s, %s, %s, NULL)
                    """,
                    (session["user_id"], keywords_json, halls_json),
                )

                if SEND_WELCOME:
                    try:
                        body_lines = [
                            "Welcome to MIT Dining Alerts 🌶️",
                            "",
                            "We'll email you when your magic words show up on the dining menus:",
                            f"  • {', '.join(new_keywords)}",
                            "",
                            "You can update your magic words or unsubscribe any time from the site.",
                        ]
                        send_email(
                            email,
                            "Welcome to MIT Dining Alerts 🌶️",
                            "\n".join(body_lines),
                        )
                    except Exception as e:
                        print(f"[WARN] Failed to send welcome email to {email}: {e}")

    return render_template(
        "index.html",
        message=(
            "Subscribed! We’ll watch for dishes matching: "
            f"{', '.join(new_keywords)}. "
            "(You can add more magic words later from this account.)"
        ),
        halls=DINING_HALLS,
        csrf_token=get_csrf_token(),
        is_logged_in=True,
        user_email=email,
    )


@app.route("/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    if not validate_csrf():
        return "Bad Request", 400

    email = session.get("user_email", "").strip()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE user_id = %s", (session["user_id"],))
            affected = cur.rowcount

    if affected == 0:
        msg = "No active subscriptions found for that email."
    else:
        msg = "You’ve been unsubscribed from all alerts for this email."

    return render_template(
        "index.html",
        message=msg,
        halls=DINING_HALLS,
        csrf_token=get_csrf_token(),
        is_logged_in=True,
        user_email=email,
    )


@app.route("/unsubscribe/confirm", methods=["GET", "POST"])
def unsubscribe_confirm():
    if request.method == "POST":
        token = request.form.get("token", "")
        if not token:
            return "Invalid unsubscribe link", 400

        user_id = _consume_unsubscribe_token(token)
        if not user_id:
            return "Unsubscribe link expired or invalid", 400

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM subscriptions WHERE user_id = %s", (user_id,))

        return render_template(
            "index.html",
            message="You’ve been unsubscribed from all alerts for this email.",
            halls=DINING_HALLS,
            csrf_token=get_csrf_token(),
            is_logged_in="user_id" in session,
            user_email=session.get("user_email", ""),
        )

    token = request.args.get("token", "")
    if not token:
        return "Invalid unsubscribe link", 400
    return render_template("unsubscribe_confirm.html", token=token)


# --------------- DEBUG VIEW (admin only) ---------------


@app.route("/debug/subscriptions")
@login_required
def debug_subscriptions():
    """
    Simple HTML table showing all subscriptions.
    Protected by ADMIN_EMAILS allowlist.
    """
    if not _is_admin_email(session.get("user_email", "")):
        return "Forbidden", 403

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.email, s.item_keywords, s.halls, s.last_notified_date
                FROM subscriptions s
                JOIN users u ON u.id = s.user_id
                ORDER BY u.email
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5001)), debug=True)
