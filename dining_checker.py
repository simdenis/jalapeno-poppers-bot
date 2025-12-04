# dining_checker.py
import os
import smtplib
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

DINING_URLS = {
    "Simmons Hall": "http://mit.cafebonappetit.com/cafe/simmons/",
    "Maseeh Hall": "http://mit.cafebonappetit.com/cafe/the-howard-dining-hall-at-maseeh/",
    "New Vassar": "http://mit.cafebonappetit.com/cafe/new-vassar/",
    "Baker House": "http://mit.cafebonappetit.com/cafe/baker/",
    "McCormick": "http://mit.cafebonappetit.com/cafe/mccormick/",
    "Next House": "http://mit.cafebonappetit.com/cafe/next/",
}
from dotenv import load_dotenv

load_dotenv()
def fetch_menu(url: str) -> str:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text

def menu_contains_item(html: str, keywords: list[str]) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ").lower()
    for kw in keywords:
        if kw.lower() in text:
            return True
    return False

def find_item_locations(keywords: list[str]) -> list[str]:
    hits = []
    for hall, url in DINING_URLS.items():
        try:
            html = fetch_menu(url)
            if menu_contains_item(html, keywords):
                hits.append(hall)
        except Exception as e:
            print(f"[WARN] Failed to check {hall}: {e}")
    return hits

# email settings from env
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_FROM = EMAIL_USER

def send_email(to_email: str, subject: str, body: str):
    if not (EMAIL_USER and EMAIL_PASSWORD):
        print("[ERROR] email not configured")
        return

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)

# dining_checker.py (add these imports if not already at top)
# from bs4 import BeautifulSoup
# import requests

def extract_menu_items(html: str) -> list[str]:
    """
    Extract individual menu item names from a Bon Appetit / MIT dining menu page.
    NOTE: You may want to tweak the CSS selectors once you inspect the real HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = set()

    # Try a few likely patterns; adjust after inspecting actual markup
    # Example selectors – you should fine-tune based on the site:
    candidates = soup.select(
        ".station__item-title, .menu__item, .item__name, .ba-menu-item__title"
    )

    if not candidates:
        # Fallback: grab all <span> / <div> that look like food names
        for tag in soup.find_all(["span", "div"]):
            text = tag.get_text(strip=True)
            if not text:
                continue
            # Heuristic: skip very short or obviously non-food text
            if len(text) < 3:
                continue
            if any(bad in text.lower() for bad in ["breakfast", "lunch", "dinner", "allergen", "calories"]):
                continue
            items.add(text)
    else:
        for el in candidates:
            text = el.get_text(strip=True)
            if text:
                items.add(text)

    return sorted(items)


def get_all_menu_items() -> list[str]:
    """
    Fetch all dining halls and return a deduplicated list of menu items.
    """
    all_items = set()
    for hall, url in DINING_URLS.items():
        try:
            html = fetch_menu(url)
            for item in extract_menu_items(html):
                all_items.add(item)
        except Exception as e:
            print(f"[WARN] Failed to extract items for {hall}: {e}")
    return sorted(all_items)


def categorize_item(name: str) -> str:
    """
    Simple heuristic categorization of food items based on keywords.
    """
    n = name.lower()

    fried_keywords = ["fries", "tots", "poppers", "sticks", "wings", "nuggets"]
    mains_keywords = ["burger", "chicken", "beef", "pasta", "pizza", "sandwich", "taco", "bowl"]
    sides_keywords = ["salad", "slaw", "rice", "beans", "veggies", "vegetable", "side"]
    dessert_keywords = ["cookie", "cake", "brownie", "pie", "ice cream", "pudding"]

    if any(k in n for k in fried_keywords):
        return "Fried & Snacks"
    if any(k in n for k in mains_keywords):
        return "Mains"
    if any(k in n for k in sides_keywords):
        return "Sides & Salads"
    if any(k in n for k in dessert_keywords):
        return "Desserts"
    return "Other"


def categorize_items(items: list[str]) -> dict:
    """
    Group items into categories. Returns {category: [items...]}.
    """
    categories = {
        "Fried & Snacks": [],
        "Mains": [],
        "Sides & Salads": [],
        "Desserts": [],
        "Other": [],
    }
    for item in items:
        cat = categorize_item(item)
        categories.setdefault(cat, []).append(item)

    for cat in categories:
        categories[cat].sort()
    return categories
# dining_checker.py

def extract_menu_items(html: str) -> list[str]:
    """
    Extract menu item names from the MIT / Bon Appetit menu page.

    You should tweak the selectors after inspecting the real HTML,
    but this gives you a structured place to do it.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = set()

    # TODO: inspect MIT dining HTML and tune this.
    # Here are some generic guesses:
    selectors = [
        ".ba-menu-item__title",
        ".station__item-title",
        ".menu__item-title",
        ".menu-item__title",
    ]
    candidates = []
    for sel in selectors:
        candidates.extend(soup.select(sel))

    if not candidates:
        # fallback heuristic
        for tag in soup.find_all(["span", "div"]):
            text = tag.get_text(strip=True)
            if not text:
                continue
            if len(text) < 3:
                continue
            # skip obvious non-food bits
            if any(bad in text.lower() for bad in ["breakfast", "lunch", "dinner", "calories", "allergen"]):
                continue
            items.add(text)
    else:
        for el in candidates:
            text = el.get_text(strip=True)
            if text:
                items.add(text)

    return sorted(items)


def find_keyword_matches(keyword: str) -> dict:
    """
    For a keyword like 'shrimp', return:
      {
        "Simmons Hall": ["Shrimp Tacos", "Garlic Shrimp Pasta"],
        "Maseeh Hall": ["Shrimp Stir Fry"],
        ...
      }
    """
    keyword_lower = keyword.lower()
    results = {}

    for hall, url in DINING_URLS.items():
        try:
            html = fetch_menu(url)
            items = extract_menu_items(html)
            matches = [name for name in items if keyword_lower in name.lower()]
            if matches:
                results[hall] = matches
        except Exception as e:
            print(f"[WARN] Failed to search {hall}: {e}")

    return results
