# Architecture

## Components

| Component | Runs on | Job |
|---|---|---|
| `apps/api` | Render (Docker, free plan) | The brain: finds and enriches leads, sends and reads email, classifies replies, answers the admin, runs scheduled jobs. |
| `apps/frontend` | Cloudflare Pages | Dashboard. Signs in with Firebase Auth and reads Firestore with live listeners; calls the API for chat and actions. |
| `apps/cron` | Cloudflare Workers | Cron Triggers that POST to `/jobs/*` on the API. They also wake the free Render instance. |
| Firestore | Firebase | Single source of truth. |

## Lead lifecycle

```
new ─► ready ─► emailed ─► replied ─► interested ─► demo ─► customer
 │                │           └──► not_interested / unsubscribed
 └► no_contact    └──► bounced
```

## Flows

**Find leads.** Dashboard → `POST /campaigns` (area + radius) → background task geocodes the area, searches TomTom and OpenStreetMap, merges duplicates, crawls hotel websites for emails and phones (skipping chain/booking-site addresses) → saves `leads` as `new` (has a contact) or `no_contact` → Telegram summary. The admin approves leads (`ready`) or blocks them (`POST /leads/{id}/block` → `dnc`).

**Outreach.** Cron → `/jobs/send-emails` → sends today's quota of first emails and due follow-ups through Gmail SMTP → logs `messages` and `activity`. *(step 3)*

**Replies.** Cron → `/jobs/check-inbox` → reads Gmail over IMAP, matches replies by `In-Reply-To` → Gemini classifies them → updates the lead, alerts the admin on Telegram. *(step 4)*

**Daily report.** Cron (19:00 IST, Mon–Sat) → `POST /jobs/daily-report` → counts today's `activity` → Telegram.

**Replies (scheduled).** Cron every 30 min (9:30 AM–8 PM IST) → `POST /jobs/check-replies` → reads Gmail over IMAP. This also keeps the free Render instance awake during the day; long jobs ping `/health` themselves.

**Telegram.** Locally the API long-polls Telegram. Deployed (`TELEGRAM_MODE=webhook`) it registers `/telegram/webhook` on startup, so each message also wakes the instance.

**Chat.** Dashboard (`POST /chat` with a Firebase ID token) or Telegram (`/telegram/webhook`) → same handler → Gemini answers from pipeline counts, leads needing attention and the last 24 hours of activity.

## Security

- Only the API holds the Firebase service-account key. The browser uses Firebase Auth and the rules in `firebase/firestore.rules`.
- `/jobs/*` requires the `X-Cron-Secret` header.
- `/chat` requires a Firebase ID token whose UID matches `JARVIS_UID`.
- `/telegram/webhook` requires Telegram's secret-token header and only answers `TELEGRAM_CHAT_ID`.
