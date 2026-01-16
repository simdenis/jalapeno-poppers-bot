Get an email when your favorite foods (your “magic words”) appear on MIT dining hall menus.

## How it works

- Flask web app with MIT-only magic-link login to manage subscriptions.
- PostgreSQL stores users (email) and one subscription per user.
- GitHub Actions runs `run_notifications.py` daily:
  - Scrapes MIT dining menus.
  - Checks each subscriber’s magic words.
  - Sends at most one alert email per day if any match.
- Fly.io hosts the web app; Neon hosts Postgres.

## Features

- Magic-link login for `@mit.edu` addresses
- Subscribe/update/remove magic words and halls
- Profile page with today’s matches and a menu feed
- Public stats page (top keywords, halls, subscribers)
- Unsubscribe links in notification emails

## Local setup

```bash
git clone https://github.com/simdenis/jalapeno-poppers-bot.git
cd jalapeno-poppers-bot

# create and activate venv (optional but recommended)
python3 -m venv .venv
source .venv/bin/activate   # on macOS/Linux

pip install -r requirements.txt
```

## Deploy (Fly + Neon)

1) Create a Neon Postgres project and copy the connection string.
2) Create a Fly app and set secrets:
```bash
fly launch --no-deploy
fly secrets set -a <your-app-name> \
  FLASK_SECRET_KEY="..." \
  DATABASE_URL="postgresql://..." \
  EMAIL_HOST="smtp.gmail.com" \
  EMAIL_PORT="587" \
  EMAIL_USER="you@gmail.com" \
  EMAIL_PASSWORD="your-app-password" \
  BASE_URL="https://<your-app-name>.fly.dev"
```
3) Deploy:
```bash
fly deploy
```

## GitHub Actions (daily notifications)

The scheduled workflow uses repo secrets. In GitHub:
Settings → Secrets and variables → Actions.

Required secrets:
- `DATABASE_URL`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USER`
- `EMAIL_PASSWORD`
- `BASE_URL`

Optional:
- `DEBUG_ALWAYS_NOTIFY`

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
- `LOGIN_RATE_LIMIT_ENABLED` (`true`/`false`, default `true`)
- `LOGIN_RATE_LIMIT_WINDOW_MINUTES` (default `10`)
- `LOGIN_RATE_LIMIT_MAX` (default `3`)
- `UNSUBSCRIBE_TOKEN_TTL_DAYS` (default `30`)
- `MENU_CACHE_ENABLED` (`true`/`false`, default `true`)

## Auth behavior

- Only `@mit.edu` accounts can sign in.
- Login uses emailed magic links; subscription management is gated behind login.
- On first login, existing legacy subscriptions (if any) are attached by email.

## Pages

- `/` Home (subscribe/update, stats summary)
- `/profile` Profile (matches, menu feed, inline removal)
- `/stats` Public community stats
- `/debug/subscriptions` Admin-only raw table (set `ADMIN_EMAILS`)

## Adapting for other universities

1) Update `DINING_URLS` in `dining_checker.py` to the dining hall URLs.
2) Update the email domain allowlist in `app.py`:
   - Replace `MIT_EMAIL_DOMAIN` with your domain (e.g., `example.edu`).
3) Adjust login messaging in templates if needed.
4) If the menu HTML structure differs, update `find_keyword_details` and
   `find_keyword_snippets` in `dining_checker.py` to parse the correct elements.
5) Update branding in `templates/index.html` and `templates/profile.html`.
