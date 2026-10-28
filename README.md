# Jarvis — personal work monitor

A personal assistant that watches how you work, summarises your day, and nudges you when you drift.

```
Your PC                      Firebase                Cloudflare / Render             External
─────────                    ────────                ───────────────────             ────────
ActivityWatch ─► agent ──sync──► Firestore ◄──read/write── FastAPI (Render) ──► Claude / Gemini / Ollama
                                  ▲    ▲                    ▲   │            ──► Telegram bot
                     Firebase Auth│    │live listeners      │   └──fetch───► Calendar · Gmail · GitHub
                                  └── React dashboard (Cloudflare Pages)
                                                            │
                                    Cloudflare Cron Trigger ┘ (8 AM brief · hourly check · 7 PM review)
```

## Repo layout

```
jarvis/
├── apps/
│   ├── agent/        Python desktop agent: ActivityWatch → Firestore (runs on your PC)
│   ├── api/          FastAPI backend, "the brain" (deploys to Render)
│   ├── web/          React + Vite dashboard (deploys to Cloudflare Pages)
│   └── cron/         Cloudflare Worker with Cron Triggers that call the API
├── packages/
│   └── shared/       TypeScript types for the Firestore data model
├── firebase/         Firestore security rules and indexes
├── docs/             Architecture and data-model notes
├── render.yaml       Render blueprint for apps/api
├── pnpm-workspace.yaml
└── package.json
```

## Data model (Firestore)

Everything lives under one user document, so security rules stay simple.

| Path | Written by | What it holds |
|---|---|---|
| `users/{uid}/events/{id}` | agent | One activity event: app, window title, start, duration |
| `users/{uid}/summaries/{YYYY-MM-DD}` | api | Daily stats, morning brief, evening review |
| `users/{uid}/tasks/{id}` | web, api | Planned tasks and their status |
| `users/{uid}/chats/{id}` | api | Chat messages with Jarvis (web and Telegram) |
| `users/{uid}/nudges/{id}` | api | Focus alerts shown on the dashboard |
| `users/{uid}/settings/main` | web | Work hours, focus apps, goals |

Full field list: [`packages/shared/src/types.ts`](packages/shared/src/types.ts).

## Setup, in order

### 1. Firebase
1. Create a project at console.firebase.google.com (the free Spark plan is enough to start).
2. Enable **Authentication → Google** and **Firestore** (production mode).
3. Deploy the rules: `npx firebase-tools deploy --only firestore --project <id>` from the `firebase/` folder.
4. **Project settings → Service accounts → Generate new private key.** Save it as `apps/agent/service-account.json` (gitignored). The API gets the same JSON as an environment variable.
5. **Project settings → General → Your apps → Web app.** Copy the config into `apps/web/.env`.
6. Sign in to the dashboard once, then copy your UID from **Authentication → Users**. The agent and API need it as `JARVIS_UID`.

### 2. Desktop agent (your PC)
```bash
# install ActivityWatch first: https://activitywatch.net
cd apps/agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # fill in JARVIS_UID
python agent.py
```
To run it at login, use Task Scheduler (Windows), a LaunchAgent (macOS) or a systemd user service (Linux).

### 3. Backend on Render
1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, pick the repo. It reads `render.yaml`.
3. Fill in the environment variables it asks for (see `apps/api/.env.example`).
4. Local dev: `cd apps/api && pip install -r requirements.txt && uvicorn app.main:app --reload`.

### 4. Dashboard on Cloudflare Pages
- Build command: `pnpm install && pnpm --filter web build`
- Build output directory: `apps/web/dist`
- Environment variables: everything in `apps/web/.env.example`
- Local dev: `pnpm install && pnpm dev:web`

### 5. Cron worker on Cloudflare
```bash
cd apps/cron
npx wrangler secret put API_URL       # https://jarvis-api.onrender.com
npx wrangler secret put CRON_SECRET   # same value as the API's CRON_SECRET
npx wrangler deploy
```
The schedules in `wrangler.toml` are in UTC and set for IST (UTC+5:30) on weekdays.

### 6. Telegram (optional)
1. Create a bot with @BotFather and copy the token.
2. Message your bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID.
3. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `TELEGRAM_WEBHOOK_SECRET` on Render.
4. Register the webhook:
   `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<API_URL>/telegram/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>"`

## Build order (suggested)

1. **Week 1:** Firebase + agent. Confirm events show up in Firestore.
2. **Week 2:** API `/jobs/daily-review` + dashboard "Today" page.
3. **Week 3:** Chat (web + Telegram) and the cron worker.
4. **Later:** Google Calendar integration (`apps/api/app/services/calendar.py`), focus mode, weekly reports.

## Free-tier notes
- Render's free web service sleeps when idle; the first request after a sleep can take up to a minute. The cron worker's calls wake it.
- Set `LLM_PROVIDER=ollama` for fully local, free summaries during development. Ollama only works where the API can reach it (your PC), not on Render.
- Check each service's current free-tier limits before relying on them.
