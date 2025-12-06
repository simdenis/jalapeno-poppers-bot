Get an email when your favorite foods (your “magic words”) appear on MIT dining hall menus.

## How it works

- Flask web app on Render for subscribe / unsubscribe.
- PostgreSQL stores one row per email (keywords, halls, last_notified_date).
- GitHub Actions runs `run_notifications.py` daily:
  - Scrapes MIT dining menus.
  - Checks each subscriber’s magic words.
  - Sends at most one alert email per day if any match.

## Local setup

```bash
git clone https://github.com/simdenis/jalapeno-poppers-bot.git
cd jalapeno-poppers-bot

# create and activate venv (optional but recommended)
python3 -m venv .venv
source .venv/bin/activate   # on macOS/Linux

pip install -r requirements.txt