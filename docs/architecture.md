# Architecture

## Components

| Component | Runs on | Job |
|---|---|---|
| `apps/agent` | Your PC | Reads ActivityWatch's local API every 5 minutes, tags each event with a category, and writes it to Firestore. |
| `apps/api` | Render | The brain: builds daily summaries, answers chat, runs scheduled jobs, talks to the LLM and Telegram. |
| `apps/web` | Cloudflare Pages | Dashboard. Signs in with Firebase Auth and reads Firestore with live listeners; calls the API only for chat. |
| `apps/cron` | Cloudflare Workers | Cron Triggers that POST to `/jobs/*` on the API. They also wake the free Render instance. |
| Firestore | Firebase | Single source of truth. |

## Request flows

**Activity sync.** ActivityWatch → agent (every 5 min) → `users/{uid}/events`.

**Hourly focus check.** Cron → `POST /jobs/focus-check` → API counts app switches in the last 30 min → if over the threshold, writes a nudge and sends a Telegram message.

**Morning brief / evening review.** Cron → `POST /jobs/morning-brief` or `/jobs/daily-review` → API aggregates events and tasks → LLM writes the text → stored in `summaries/{date}` → sent to Telegram.

**Chat (web).** Dashboard → `POST /chat` with a Firebase ID token → API verifies the token, loads today's summary as context, calls the LLM, stores both messages in `chats`.

**Chat (Telegram).** Telegram → `POST /telegram/webhook` (checked with a secret header and your chat ID) → same chat handler → reply via the Bot API.

## Security

- Only the agent and API hold the Firebase service-account key. The browser uses Firebase Auth and the rules in `firebase/firestore.rules`.
- `/jobs/*` requires the `X-Cron-Secret` header.
- `/chat` requires a Firebase ID token whose UID matches `JARVIS_UID`.
- `/telegram/webhook` requires Telegram's secret-token header and only answers `TELEGRAM_CHAT_ID`.
