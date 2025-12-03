import os
import smtplib
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

# Load env vars (email settings)
load_dotenv()


load_dotenv()  # loads variables from .env into the environment

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")        # e.g. your Gmail address
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # Gmail app password
EMAIL_TO = os.getenv("EMAIL_TO", EMAIL_USER)  # default: send to yourself


# 1) URLs to monitor — replace these with the actual URLs you find
DINING_URLS = {
    "Simmons Hall": "http://mit.cafebonappetit.com/cafe/simmons/",
    "Maseeh Hall": "http://mit.cafebonappetit.com/cafe/the-howard-dining-hall-at-maseeh/",
    "New Vassar": "http://mit.cafebonappetit.com/cafe/new-vassar/",
    "Baker House": "http://mit.cafebonappetit.com/cafe/baker/",
    "McCormick": "http://mit.cafebonappetit.com/cafe/mccormick/",
    "Next House": "http://mit.cafebonappetit.com/cafe/next/",
}

# 2) Keywords to search for (case-insensitive)
KEYWORDS = [
    "jalapeño popper",
    "jalapeno popper",
    "jalapeño poppers",
    "jalapeno poppers",
]


def fetch_menu(url: str) -> str:
    """Download the menu page and return its raw HTML text."""
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def menu_contains_poppers(html: str) -> bool:
    """Return True if any of the KEYWORDS appear in the page text."""
    # Very simple: just search the full visible text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ").lower()
    for kw in KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def find_popper_locations() -> list:
    """Check all dining URLs and return a list of halls that have poppers."""
    hits = []
    for hall, url in DINING_URLS.items():
        try:
            html = fetch_menu(url)
            if menu_contains_poppers(html):
                hits.append(hall)
        except Exception as e:
            # You can log / print errors; don't crash the whole check
            print(f"[WARN] Failed to check {hall} ({url}): {e}")
    return hits


def send_email(subject: str, body: str):
    """Send an email using the configured SMTP settings."""
    if not (EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO):
        print("[ERROR] Email settings not configured; skipping email.")
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)

    print("[INFO] Email sent.")

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    hits = find_popper_locations()

    if hits:
        halls_list = "\n".join(f"- {hall}" for hall in hits)
        subject = f"[MIT Dining] Jalapeño poppers today! 🌶️🧀 ({today})"
        body = (
            "Alert from your jalapeño monitoring service.\n\n"
            "Jalapeño poppers were detected in the menu at:\n\n"
            f"{halls_list}\n\n"
            "Go forth and feast.\n"
        )
    else:
        subject = f"[MIT Dining] No jalapeño poppers today 😢 ({today})"
        body = (
            "We checked the MIT dining menus you track and found:\n\n"
            "- 0 occurrences of jalapeño poppers.\n\n"
            "Sorry. Maybe tomorrow.\n"
        )

    print(f"[{today}] Sending email. Poppers found? {bool(hits)}")
    send_email(subject, body)


if __name__ == "__main__":
    main()

