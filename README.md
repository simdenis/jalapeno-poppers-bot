# Jalapeno Poppers

Get an email when your favorite foods (your "magic words") show up on MIT
dining hall menus.

## Why it exists

MIT dining menus change daily. This app lets you track specific foods and
get a single, concise email when they appear.

## What it does

- MIT-only magic-link login to manage your subscription.
- One subscription per user (email + keywords + optional hall filter).
- Daily email notifications with matches and meal types.
- Unsubscribe links in every email.

## How it works

- Flask web app for sign-in and profile management.
- Postgres stores users + subscriptions.
- A scheduled GitHub Action runs `run_notifications.py` every morning.
- Fly.io hosts the web app; Neon hosts Postgres.

## Screens (routes)

- `/` Home (subscribe/update, stats summary)
- `/profile` Profile (today's matches + today's menu)
- `/stats` Public community stats
- `/debug/subscriptions` Admin-only raw table (set `ADMIN_EMAILS`)

## Local setup

```bash
git clone https://github.com/simdenis/jalapeno-poppers-bot.git
cd jalapeno-poppers-bot

# create and activate venv (recommended)
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

## Run locally

```bash
export FLASK_SECRET_KEY="dev"
export DATABASE_URL="postgresql://..."
export EMAIL_USER="you@gmail.com"
export EMAIL_PASSWORD="your-app-password"
export BASE_URL="http://localhost:5000"

python app.py
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
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
Settings -> Secrets and variables -> Actions.

Required secrets:
- `DATABASE_URL`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USER`
- `EMAIL_PASSWORD`
- `BASE_URL`

Optional:
- `DEBUG_ALWAYS_NOTIFY` (set to `true` for testing)

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

## Adapting for other universities

1) Update `DINING_URLS` in `dining_checker.py` to the dining hall URLs.
2) Update the email domain allowlist in `app.py`:
   - Replace `MIT_EMAIL_DOMAIN` with your domain (e.g., `example.edu`).
3) Adjust login messaging in the templates if needed.
4) Update branding in `templates/index.html` and `templates/profile.html`.
