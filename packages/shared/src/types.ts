/**
 * Firestore data model. Every collection sits under users/{uid}/ (the admin).
 * The API writes these from Python, so keep field names in sync with
 * apps/api/app/services/*.py.
 */

export type Language = "en" | "hi" | "te";

/** users/{uid}/campaigns/{id} — one area search, e.g. "Hotels in Madhapur" */
export interface Campaign {
  name: string;
  area: { label: string; lat: number; lon: number; radiusM: number };
  query: string;                 // what to search for, e.g. "hotel"
  status: "draft" | "active" | "paused" | "done";
  createdAt: string;
  stats: { found: number; emailed: number; replied: number; interested: number };
}

export type LeadStatus =
  | "new"             // found, not yet checked
  | "ready"           // has an email, approved for outreach
  | "no_contact"      // no email or phone found
  | "emailed"         // first email sent, waiting
  | "replied"         // replied, needs a look
  | "interested"
  | "demo"            // demo booked
  | "customer"
  | "not_interested"
  | "unsubscribed"
  | "bounced";

/** users/{uid}/leads/{id} — one hotel. id = "{source}_{sourceId}" so re-imports don't duplicate */
export interface Lead {
  campaignId: string;
  name: string;
  address: string;
  lat: number;
  lon: number;
  phone?: string;
  website?: string;
  emails: string[];              // found by the crawler; first one is used
  source: "tomtom" | "osm" | "manual";
  status: LeadStatus;
  language?: Language;           // preferred language once known
  followUps: number;             // follow-up emails sent after the first one
  nextActionAt?: string;         // ISO; when Jarvis should do the next step
  lastContactAt?: string;
  notes?: string;
  createdAt: string;
  updatedAt: string;
}

export type ReplyKind = "interested" | "question" | "not_now" | "unsubscribe" | "other";

/** users/{uid}/messages/{id} — every email sent or received */
export interface EmailMessage {
  leadId: string;
  direction: "out" | "in";
  subject: string;
  body: string;
  messageId: string;             // RFC 822 Message-ID, used to match replies
  inReplyTo?: string;
  followUpNo?: number;           // 0 = first email
  kind?: ReplyKind;              // set on incoming replies by the AI
  at: string;
}

/** users/{uid}/dnc/{key} — do-not-contact; key is a lowercased email or digits-only phone */
export interface DoNotContact {
  reason: string;
  createdAt: string;
}

/** users/{uid}/activity/{id} — what Jarvis did, for the dashboard feed and daily report */
export interface Activity {
  type: "lead_found" | "email_sent" | "reply" | "alert" | "status_change" | "error";
  text: string;
  leadId?: string;
  at: string;
}

/** users/{uid}/chats/{id} — admin ↔ Jarvis, from the dashboard or Telegram */
export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  channel: "web" | "telegram";
  createdAt: string;
}

/** users/{uid}/settings/main */
export interface Settings {
  dailyEmailLimit: number;       // new first emails per day, e.g. 20
  followUpDays: number[];        // days after the first email, e.g. [3, 7]
  sendWindow: { start: string; end: string };  // local time, e.g. "10:00"–"18:00"
  signature: string;
}
