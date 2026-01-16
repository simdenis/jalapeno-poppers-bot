# dining_checker.py

import os
import smtplib
import json
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


def _set_cached_menu(hall: str, menu_date: date, payload: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO menu_cache (hall, menu_date, html)
                VALUES (%s, %s, %s)
                ON CONFLICT (hall, menu_date) DO UPDATE
                SET html = EXCLUDED.html, fetched_at = NOW()
                """,
                (hall, menu_date, payload),
            )


def fetch_menu(hall: str, url: str) -> str | None:
    """Fetch menu HTML for today from the MIT cafe page."""
    today = date.today()
    if MENU_CACHE_ENABLED:
        cached = _get_cached_menu(hall, today)
        if cached:
            return cached

    resp = requests.get(
        url,
        headers={"User-Agent": "jalapeno-poppers/1.0"},
        timeout=15,
    )
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


def _extract_items_by_meal_from_root(root) -> dict[str, list[str]]:
    meal_labels = {"breakfast", "brunch", "lunch", "dinner"}
    items_by_meal: dict[str, list[str]] = {}

    item_selectors = [
        "[data-menu-item]",
        "[data-item-name]",
        ".menu-item",
        ".menu-item-name",
        ".menu-item-title",
        ".menu__item",
        ".menu__item-name",
        ".item-name",
    ]
    item_elements = []
    for selector in item_selectors:
        item_elements.extend(root.select(selector))

    if not item_elements:
        item_elements = root.select("li")

    for elem in item_elements:
        text = elem.get_text(" ", strip=True)
        if not text or len(text) > 120:
            continue
        meal = None

        tag_match = re.search(r"\[(.*?)\]", text)
        if tag_match:
            tag_text = tag_match.group(1).lower()
            if "br" in tag_text:
                meal = "Brunch"
            elif "b" in tag_text:
                meal = "Breakfast"
            elif "l" in tag_text:
                meal = "Lunch"
            elif "d" in tag_text:
                meal = "Dinner"

        # Clean display text after we parse tags.
        text = re.sub(r"\s*\[[^\]]+\]\s*", " ", text)
        text = re.sub(r"\s*nutrition\s*\+\s*ingredients\s*$", "", text, flags=re.IGNORECASE)
        text = " ".join(text.split())

        if not meal:
            prev_heading = elem.find_previous(["h1", "h2", "h3", "h4", "h5"])
            if prev_heading:
                heading_text = prev_heading.get_text(" ", strip=True).lower()
                for label in meal_labels:
                    if label in heading_text:
                        meal = label.capitalize()
                        break

        items_by_meal.setdefault(meal or "Unspecified", []).append(text)

    return items_by_meal


def _extract_items_by_meal(html: str) -> dict[str, list[str]]:
    """
    Extract item labels grouped by meal/daypart from weekly-menu HTML.
    """
    soup = BeautifulSoup(html, "html.parser")

    def _find_today_container(target_date: date):
        iso = target_date.isoformat()
        candidates = []
        for elem in soup.find_all(attrs={"data-date": True}):
            if iso in elem.get("data-date", ""):
                candidates.append(elem)
        if candidates:
            return candidates[0]

        for elem in soup.find_all(attrs={"data-day": True}):
            if iso in elem.get("data-day", ""):
                candidates.append(elem)
        if candidates:
            return candidates[0]

        label_variants = {
            target_date.strftime("%b %d"),
            target_date.strftime("%B %d"),
            target_date.strftime("%a, %b %d"),
            target_date.strftime("%A, %b %d"),
            "Today",
        }
        for elem in soup.find_all(["section", "div", "article"]):
            text = elem.get_text(" ", strip=True)
            if any(label in text for label in label_variants):
                return elem
        return None

    def _extract_items_from_json(obj) -> dict[str, list[str]]:
        items: dict[str, list[str]] = {}

        def add_item(meal: str | None, label: str):
            items.setdefault(meal or "Unspecified", []).append(label)

        def walk(node, current_meal: str | None = None):
            if isinstance(node, dict):
                dayparts = node.get("dayparts") or node.get("dayParts")
                if isinstance(dayparts, list):
                    for dp in dayparts:
                        label = None
                        if isinstance(dp, dict):
                            label = dp.get("label") or dp.get("name")
                        walk(dp, label or current_meal)

                for key in ("items", "menu_items", "menuItems"):
                    val = node.get(key)
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict):
                                label = item.get("label") or item.get("name")
                                if label:
                                    add_item(current_meal, label)

                for value in node.values():
                    walk(value, current_meal)
            elif isinstance(node, list):
                for item in node:
                    walk(item, current_meal)

        walk(obj)
        return items

    def _try_parse_json(text: str):
        text = text.strip()
        if not text:
            return None
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                return None
        patterns = [
            r"window\.__PRELOADED_STATE__\s*=\s*({.*});",
            r"window\.__INITIAL_STATE__\s*=\s*({.*});",
            r"__NEXT_DATA__\s*=\s*({.*});",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    continue
        return None

    for script in soup.find_all("script"):
        data = _try_parse_json(script.string or script.get_text())
        if data:
            items = _extract_items_from_json(data)
            if any(items.values()):
                return items

    today_container = _find_today_container(date.today())
    root = today_container if today_container is not None else soup
    return _extract_items_by_meal_from_root(root)




def extract_week_by_day(html: str) -> dict[str, dict[str, list[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    results: dict[str, dict[str, list[str]]] = {}
    containers = []
    for elem in soup.find_all(attrs={"data-date": True}):
        containers.append((elem.get("data-date", ""), elem))
    for elem in soup.find_all(attrs={"data-day": True}):
        containers.append((elem.get("data-day", ""), elem))

    if not containers:
        results["Unspecified"] = _extract_items_by_meal_from_root(soup)
        return results

    for label, elem in containers:
        items = _extract_items_by_meal_from_root(elem)
        if items:
            results[label or "Unspecified"] = items
    return results


def _find_keyword_details_from_items(
    items_by_meal: dict[str, list[str]],
    keywords: list[str]
) -> Dict[str, Set[str]]:
    kw_list = [k.strip() for k in keywords if k and k.strip()]
    kw_list = list(dict.fromkeys(kw_list))
    if not kw_list:
        return {}

    matches: Dict[str, Set[str]] = {}
    for meal_label, items in items_by_meal.items():
        for item in items:
            item_tokens = _tokenize(item)
            for kw in kw_list:
                if _contains_sequence(item_tokens, _tokenize(kw)):
                    matches.setdefault(kw, set()).add(meal_label)
    return matches


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
        if not html:
            continue
        items_by_meal = _extract_items_by_meal(html)
        if not any(items_by_meal.values()):
            # Fallback: scan lines if menu items aren't detected
            soup = BeautifulSoup(html, "html.parser")
            lines = [ln.strip() for ln in soup.get_text(separator="\n").splitlines()]
            lines = [ln for ln in lines if ln]
            items_by_meal = {"Unspecified": lines}
        snippets: list[str] = []
        for items in items_by_meal.values():
            for item in items:
                item_tokens = _tokenize(item)
                matched = False
                for kw in kw_list:
                    if _contains_sequence(item_tokens, _tokenize(kw)):
                        matched = True
                        break
                if matched and item not in snippets:
                    snippets.append(item)
                if len(snippets) >= max_lines:
                    break
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
            if not html:
                continue
            items_by_meal = _extract_items_by_meal(html)
            if _find_keyword_details_from_items(items_by_meal, keywords):
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
        if not html:
            continue

        items_by_meal = _extract_items_by_meal(html)
        hall_matches = _find_keyword_details_from_items(items_by_meal, kw_list)

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
