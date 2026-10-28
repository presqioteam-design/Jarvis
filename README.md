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

Run a job by hand: `curl -X POST localhost:8000/jobs/daily-report -H "X-Cron-Secret: <CRON_SECRET>"`

## Accounts and keys (all free, no card)

| Service | Used for | Env var |
|---|---|---|
| Firebase (Spark) | Auth, Firestore | `service-account.json`, `apps/frontend/.env` |
| TomTom developer | Hotel search | `TOMTOM_API_KEY` |
| Google AI Studio | Gemini | `GEMINI_API_KEY` |
| Gmail + App Password | Sending and reading email | `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` |
| Telegram @BotFather | Alerts, chat | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

## Deploying (later)
- **API on Render:** New → Blueprint → this repo; fill in the env vars from `apps/api/.env.example`.
- **Dashboard on Cloudflare Pages:** build `yarn install && yarn ui:build`, output `apps/frontend/dist`.
- **Cron worker:** `cd apps/cron && npx wrangler secret put API_URL && npx wrangler secret put CRON_SECRET && npx wrangler deploy`.
- **Telegram webhook:** `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<API_URL>/telegram/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>"`

## Outreach rules
- Every email has an opt-out line; anyone who opts out goes on the do-not-contact list and is never contacted again.
- Keep to 20–40 new emails a day from the Gmail account.
- Phone calls are not automated yet. If added, India's TRAI telemarketing rules (DLT registration, NCPR do-not-disturb checks) apply.
