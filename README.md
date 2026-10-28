# Jarvis — sales assistant for Presqio

Jarvis finds hotels in an area, emails them about [Presqio](https://presqio.pages.dev/) (attendance and payroll), tracks replies, and reports to the admin on Telegram and the dashboard. Everything runs on free tiers.

```
TomTom / OpenStreetMap ─► find hotels ─┐
Hotel websites ─────────► find emails ─┤
                                       ▼
React dashboard ◄──live──► Firestore ◄──► FastAPI (Render) ◄──► Gemini (free tier)
(Cloudflare Pages)                          │   ▲     ▲
                                            │   │     └── Cloudflare Cron (daily report, email queue)
                       Gmail (send / read) ◄┘   └──────── Telegram bot (alerts, chat with admin)
```

## Repo layout

```
jarvis/
├── apps/
│   ├── api/          FastAPI backend, "the brain" (deploys to Render)
│   ├── frontend/     React + Vite dashboard (deploys to Cloudflare Pages)
│   └── cron/         Cloudflare Worker with Cron Triggers that call the API
├── packages/
│   └── shared/       TypeScript types for the Firestore data model
├── firebase/         Firestore security rules and indexes
├── docs/             Architecture notes
└── render.yaml       Render blueprint for apps/api
```

## Data model (Firestore)

Everything lives under the admin's user document, so security rules stay simple.

| Path | Written by | What it holds |
|---|---|---|
| `users/{uid}/campaigns/{id}` | web, api | An area search, e.g. "Hotels in Madhapur" |
| `users/{uid}/leads/{id}` | api, web | One hotel: contact details, status, next step |
| `users/{uid}/messages/{id}` | api | Every email sent and received |
| `users/{uid}/dnc/{key}` | api, web | Do-not-contact list (emails and phones) |
| `users/{uid}/activity/{id}` | api | What Jarvis did, for the feed and daily report |
| `users/{uid}/chats/{id}` | api | Admin ↔ Jarvis chat (web and Telegram) |
| `users/{uid}/settings/main` | web | Daily email limit, follow-up days, signature |

Full field list: [`packages/shared/src/types.ts`](packages/shared/src/types.ts).

## Local development

```bash
# API
cd apps/api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in the keys
cd ../.. && yarn api:dev         # localhost:8000

# Dashboard
yarn install && yarn ui:dev     # needs apps/frontend/.env, runs on localhost:3000
```

Run a job by hand: `curl -X POST localhost:8000/jobs/check-replies -H "X-Cron-Secret: <CRON_SECRET>"`

## Accounts and keys (all free, no card)

| Service | Used for | Env var |
|---|---|---|
| Firebase (Spark) | Auth, Firestore | `service-account.json`, `apps/frontend/.env` |
| TomTom developer | Hotel search | `TOMTOM_API_KEY` |
| Google AI Studio | Gemini | `GEMINI_API_KEY` |
| Gmail + App Password | Sending and reading email | `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` |
| Telegram @BotFather | Alerts, chat | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

## Deploying (all free)

| Part | Where | Notes |
|---|---|---|
| Backend `apps/api` | Render free plan (Docker) | Sleeps after 15 min idle; Telegram and the cron worker wake it |
| Dashboard `apps/frontend` | Cloudflare Pages | Static site |
| Scheduled jobs `apps/cron` | Cloudflare Workers | Checks replies every 30 min (9:30 AM–8 PM IST), daily report at 7 PM |

### 1. GitHub
```bash
gh auth login
gh repo create presqio-jarvis --private --source . --push
```

### 2. Backend on Render
1. render.com → **New → Blueprint** → pick the repo. It reads `render.yaml` and builds `apps/api/Dockerfile`.
2. Fill in the values it asks for:
   - `JARVIS_UID`, `GEMINI_API_KEY`, `TOMTOM_API_KEY`, `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: same as in your local `apps/api/.env`
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: paste the whole contents of `apps/api/service-account.json`
   - `CORS_ORIGINS`: your Pages address from step 3, e.g. `https://presqio-jarvis.pages.dev` (fill it in after step 3)
3. Deploy, then check `https://<your-service>.onrender.com/health` returns `{"ok":true}`.
4. On startup the API registers the Telegram webhook itself (`TELEGRAM_MODE=webhook`). Message the bot `help` to check.
5. Test sending with `send 1` in Telegram. If the Render logs show an SMTP connection error, Render is blocking email ports on the free plan; see "If email is blocked" below.

> ⚠️ Don't run `yarn api:dev` on your computer while Render is live: local mode switches Telegram back to polling and disconnects the deployed bot. To go back to Render afterwards, restart the Render service so it re-registers the webhook.

### 3. Dashboard on Cloudflare Pages
1. dash.cloudflare.com → **Workers & Pages → Create → Pages → Connect to Git** → pick the repo.
2. Build command `yarn install && yarn ui:build`, build output directory `apps/frontend/dist`.
3. Environment variables: everything in `apps/frontend/.env`, with `VITE_API_URL` set to your Render URL. Add `NODE_VERSION` = `20`.
4. Firebase console → **Authentication → Settings → Authorized domains** → add your `*.pages.dev` address, or Google sign-in is refused.
5. Put the Pages address into Render's `CORS_ORIGINS`.

### 4. Cron worker on Cloudflare
```bash
cd apps/cron
npx wrangler login
npx wrangler secret put API_URL       # https://<your-service>.onrender.com
npx wrangler secret put CRON_SECRET   # copy CRON_SECRET from Render → Environment
npx wrangler deploy
```

### 5. Firestore rules
Firebase console → Firestore → **Rules** → paste `firebase/firestore.rules` → **Publish**.

### If email is blocked on Render
Render may block outgoing SMTP on free instances. Options: run the backend on your own computer (`yarn api:dev`, with Cloudflare Tunnel for a public URL), or switch `apps/api/app/services/mailer.py` to the Gmail API, which sends over HTTPS.

### Free-tier limits to keep in mind
- Firestore Spark: 50k reads and 20k writes a day. A whole-city scan uses a lot of both; scan at most one city a day.
- Gmail: stay within `DAILY_EMAIL_CAP` (50).
- TomTom: about 2,500 searches a day; the Hyderabad scan used ~460.

## Outreach rules
- Every email has an opt-out line; anyone who opts out goes on the do-not-contact list and is never contacted again.
- Keep to 20–40 new emails a day from the Gmail account.
- Phone calls are not automated yet. If added, India's TRAI telemarketing rules (DLT registration, NCPR do-not-disturb checks) apply.
