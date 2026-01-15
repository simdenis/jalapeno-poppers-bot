Get an email when your favorite foods (your “magic words”) appear on MIT dining hall menus.

## How it works

- Flask web app with MIT-only magic-link login to manage subscriptions.
- PostgreSQL stores users (email) and one subscription per user.
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
```

## Environment variables

Required:
- `DATABASE_URL` (Postgres connection string)
- `FLASK_SECRET_KEY` (session signing secret)
- `EMAIL_USER` (SMTP username)
- `EMAIL_PASSWORD` (SMTP app password)

Optional:
- `EMAIL_HOST` (default `smtp.gmail.com`)
- `EMAIL_PORT` (default `587`)
- `SEND_WELCOME_EMAILS` (`true`/`false`)
- `ADMIN_EMAILS` (comma-separated list for `/debug/subscriptions`)
- `DEBUG_ALWAYS_NOTIFY` (`true`/`false`, for dev)
- `BASE_URL` (public app URL, used to generate magic login links)
- `MAGIC_TOKEN_TTL_MINUTES` (default `30`)

## Auth behavior

- Only `@mit.edu` accounts can sign in.
- Login uses emailed magic links; subscription management is gated behind login.
- On first login, existing legacy subscriptions (if any) are attached by email.
