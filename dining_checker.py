# dining_checker.py

import os
import smtplib
from email.message import EmailMessage
from typing import Dict, List, Set
from datetime import date
import re
import unicodedata
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from db import get_conn


# ----------------------------
# Dining hall configuration
# ----------------------------

DINING_URLS = {
    "Simmons Hall": "http://mit.cafebonappetit.com/cafe/simmons/",
    "Maseeh Hall": "http://mit.cafebonappetit.com/cafe/the-howard-dining-hall-at-maseeh/",
    "New Vassar": "http://mit.cafebonappetit.com/cafe/new-vassar/",
    "Baker House": "http://mit.cafebonappetit.com/cafe/baker/",
    "McCormick": "http://mit.cafebonappetit.com/cafe/mccormick/",
    "Next House": "http://mit.cafebonappetit.com/cafe/next/",
}


# ----------------------------
# Environment / email setup
# ----------------------------

load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST") or "smtp.gmail.com"
_email_port_str = os.getenv("EMAIL_PORT") or "587"
EMAIL_PORT = int(_email_port_str)
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
MENU_CACHE_ENABLED = os.getenv("MENU_CACHE_ENABLED", "true").lower() == "true"


# ----------------------------
# Core scraping helpers
# ----------------------------

def _get_cached_menu(hall: str, menu_date: date) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT html FROM menu_cache
                WHERE hall = %s AND menu_date = %s
                """,
                (hall, menu_date),
            )
            row = cur.fetchone()
    return row[0] if row else None


def _set_cached_menu(hall: str, menu_date: date, html: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO menu_cache (hall, menu_date, html)
                VALUES (%s, %s, %s)
                ON CONFLICT (hall, menu_date) DO UPDATE
                SET html = EXCLUDED.html, fetched_at = NOW()
                """,
                (hall, menu_date, html),
            )


def fetch_menu(hall: str, url: str) -> str:
    """Fetch raw HTML for a dining hall menu."""
    today = date.today()
    if MENU_CACHE_ENABLED:
        cached = _get_cached_menu(hall, today)
        if cached:
            return cached
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    html = resp.text
    if MENU_CACHE_ENABLED:
        _set_cached_menu(hall, today, html)
    return html


def _normalize_text(text: str) -> str:
    # Strip accents, lowercase, and normalize separators to spaces.
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _tokenize(text: str) -> list[str]:
    text = _normalize_text(text)
    return text.split() if text else []


def _contains_sequence(tokens: list[str], phrase_tokens: list[str]) -> bool:
    if not phrase_tokens:
        return False
    if len(phrase_tokens) > len(tokens):
        return False
    for i in range(len(tokens) - len(phrase_tokens) + 1):
        if tokens[i : i + len(phrase_tokens)] == phrase_tokens:
            return True
    return False


def page_contains_any_keyword(html: str, keywords: list[str]) -> bool:
    """
    Return True if ANY of the keywords appears (case-insensitive)
    in the plain text of the page.
    """
    soup = BeautifulSoup(html, "html.parser")
    tokens = _tokenize(soup.get_text(separator=" "))

    for kw in keywords:
        kw_tokens = _tokenize(kw)
        if _contains_sequence(tokens, kw_tokens):
            return True
    return False


def find_keyword_snippets(
    keywords: list[str],
    halls_filter=None,
    max_lines: int = 3
) -> dict[str, list[str]]:
    """
    Return short menu text snippets per hall that contain the keywords.
    """
    kw_list = [k.strip() for k in keywords if k and k.strip()]
    kw_list = list(dict.fromkeys(kw_list))
    if not kw_list:
        return {}

    if halls_filter:
        allowed_halls = set(halls_filter)
    else:
        allowed_halls = set(DINING_URLS.keys())

    results: dict[str, list[str]] = {}

    for hall, url in DINING_URLS.items():
        if hall not in allowed_halls:
            continue
        try:
            html = fetch_menu(hall, url)
        except Exception as e:
            print(f"[WARN] Failed to fetch menu for {hall}: {e}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        lines = [ln.strip() for ln in soup.get_text(separator="\n").splitlines()]
        lines = [ln for ln in lines if ln]

        snippets: list[str] = []
        for line in lines:
            line_tokens = _tokenize(line)
            matched = False
            for kw in kw_list:
                if _contains_sequence(line_tokens, _tokenize(kw)):
                    matched = True
                    break
            if matched and line not in snippets:
                snippets.append(line)
            if len(snippets) >= max_lines:
                break

        if snippets:
            results[hall] = snippets

    return results


def find_item_locations(keywords: list[str], halls_filter = None) -> list[str]:
    """
    For a list of keywords like ["jalapeno"], return a list of dining hall
    names where ANY of those keywords appears somewhere on the menu page.

    Example:
        ["jalapeno"] -> ["Simmons Hall", "Maseeh Hall"]
    """
    if halls_filter:
        halls_to_check = {h for h in halls_filter}
    else:
        halls_to_check = set(DINING_URLS.keys())

    hits: list[str] = []

    for hall, url in DINING_URLS.items():
        if hall not in halls_to_check:
            continue

        try:
            html = fetch_menu(hall, url)
            if page_contains_any_keyword(html, keywords):
                hits.append(hall)
        except Exception as e:
            print(f"[WARN] Failed to check {hall}: {e}")

    return hits



def find_keyword_details(
    keywords: List[str],
    halls_filter
) -> Dict[str, Dict[str, Set[str]]]:
    """
    For a list of keywords like ["jalapeno", "shrimp"], return a structure:

        {
          "Simmons Hall": {
            "jalapeno": {"Breakfast", "Dinner"},
            "shrimp": {"Dinner"},
          },
          "New Vassar": {
            "shrimp": {"Dinner"},
          },
          ...
        }

    Meal detection is heuristic: we look for 'breakfast', 'lunch', 'dinner'
    headings in the page text and treat text between them as that meal.
    If no headings are found, matches go under '(unspecified meal)'.
    """
    # Normalize keywords
    kw_list = [k.strip() for k in keywords if k and k.strip()]
    kw_list = list(dict.fromkeys(kw_list))  # de-duplicate, preserve order
    if not kw_list:
        return {}

    # Halls to check
    if halls_filter:
        allowed_halls = set(halls_filter)
    else:
        allowed_halls = set(DINING_URLS.keys())

    results: Dict[str, Dict[str, Set[str]]] = {}

    for hall, url in DINING_URLS.items():
        if hall not in allowed_halls:
            continue

        try:
            html = fetch_menu(hall, url)
        except Exception as e:
            print(f"[WARN] Failed to fetch menu for {hall}: {e}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        text_lower = _normalize_text(text)

        # --- Build meal segments heuristically ---
        meal_names = ["breakfast", "brunch", "lunch", "dinner"]
        markers = []

        for meal in meal_names:
            idx = text_lower.find(meal)
            if idx != -1:
                markers.append((idx, meal))

        markers.sort(key=lambda x: x[0])  # sort by position

        segments = []  # list of (meal_label, segment_text_lower)

        if markers:
            for i, (start_idx, meal) in enumerate(markers):
                if i + 1 < len(markers):
                    end_idx = markers[i + 1][0]
                else:
                    end_idx = len(text_lower)
                segment = text_lower[start_idx:end_idx]
                segments.append((meal.capitalize(), _tokenize(segment)))
        else:
            # No explicit meal markers found; treat entire text as one segment
            segments.append(("(unspecified meal)", _tokenize(text_lower)))

        hall_matches: Dict[str, Set[str]] = {}

        # For each segment and each keyword, see where it appears
        for meal_label, seg_tokens in segments:
            for kw in kw_list:
                kw_tokens = _tokenize(kw)
                if _contains_sequence(seg_tokens, kw_tokens):
                    if kw not in hall_matches:
                        hall_matches[kw] = set()
                    hall_matches[kw].add(meal_label)

        if hall_matches:
            results[hall] = hall_matches

    return results


# ----------------------------
# Email sending
# ----------------------------

def send_email(to_email: str, subject: str, body: str, html_body: str | None = None) -> None:
    """
    Send a UTF-8 email using Gmail SMTP and an app password.
    """
    if not EMAIL_USER or not EMAIL_PASSWORD:
        raise RuntimeError("EMAIL_USER or EMAIL_PASSWORD not set")

    msg = EmailMessage()
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)  # UTF-8 by default
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=5) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
