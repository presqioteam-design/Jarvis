/**
 * Firestore data model. Every collection sits under users/{uid}/ (the admin).
 * The API writes these from Python, so keep field names in sync with
 * apps/api/app/services/*.py.
 */

export type Language = "en" | "hi" | "te";

/** Kinds of business Jarvis finds; keep in sync with apps/api/app/services/categories.py */
export const CATEGORIES = [
  { key: "hotels", label: "Hotels" },
  { key: "hospitals", label: "Hospitals & clinics" },
  { key: "schools", label: "Schools & colleges" },
  { key: "restaurants", label: "Restaurants & cafés" },
  { key: "factories", label: "Factories & warehouses" },
  { key: "retail", label: "Supermarkets & retail" },
  { key: "security", label: "Security agencies" },
  { key: "gyms", label: "Gyms, salons & spas" },
  { key: "coaching", label: "Coaching & training centres" },
] as const;
export type CategoryKey = (typeof CATEGORIES)[number]["key"];
/** Leads saved before categories existed are hotels. */
export const categoryLabel = (key?: string) => CATEGORIES.find((c) => c.key === key)?.label ?? "Hotels";

/** users/{uid}/campaigns/{id} — one scan: a whole city, or a square around a spot */
export interface Campaign {
  name: string;
  kind?: "city" | "area";
  city?: string;                 // set once the place is found on the map
  area: { label: string; lat: number; lon: number; radiusM: number };   // radiusM 0 = whole city
  query: string;                 // what to search for, e.g. "hotels"
  category?: CategoryKey;        // missing on scans from before categories: hotels
  status: "searching" | "ready" | "failed" | "active" | "paused" | "done";
  error?: string;                // set when status is "failed"
  createdAt: string;
  stats: { found: number; withEmail: number; withPhone: number; emailed: number; replied: number; interested: number };
  scan?: { phase: "map" | "osm" | "websites" | "done"; squaresDone: number; found: number; queue: unknown[] };
}

/** One area's totals, stored inside its city's summary */
export interface AreaSummary {
  city: string;
  area: string;
  total: number;
  withEmail: number;
  withPhone: number;
  statuses: Partial<Record<LeadStatus, number>>;
  categories?: Partial<Record<CategoryKey, number>>;   // missing on old summaries: all hotels
}

/** users/{uid}/cities/{city-slug} — totals per city and per area, kept by the API.
 *  Pages read this one doc instead of thousands of leads (free Firestore: 50k reads a day). */
export interface CitySummary {
  city: string;
  total: number;
  withEmail: number;
  withPhone: number;
  statuses: Partial<Record<LeadStatus, number>>;
  areas: Record<string, AreaSummary>;   // keyed by areaKey, e.g. "hyderabad--madhapur"
  updatedAt: string;
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

/** users/{uid}/leads/{id} — one business with an email. id = "{source}_{sourceId}" so re-imports don't duplicate */
export interface Lead {
  campaignId: string;
  name: string;
  address: string;
  city?: string;
  area?: string;                 // locality, e.g. "Madhapur"
  areaKey?: string;              // "hyderabad--madhapur"
  category?: CategoryKey;        // missing on old leads: hotels
  lat: number;
  lon: number;
  phone?: string;
  website?: string;
  emails: string[];              // found by the crawler; first one is used
  source: "tomtom" | "osm" | "manual";
  status: LeadStatus;
  language?: Language;           // preferred language once known
  crawled?: boolean;             // website already read for contacts
  followUps: number;             // emails sent so far in the sequence (0 = first)
  emailedTo?: string;            // the address the sequence goes to
  lastMessageId?: string;        // for threading follow-ups
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
  channel: "web" | "telegram" | "voice";
  createdAt: string;
}

/** users/{uid}/settings/main */
export interface Settings {
  dailyEmailLimit: number;       // new first emails per day, e.g. 20
  followUpDays: number[];        // days after the first email, e.g. [3, 7]
  sendWindow: { start: string; end: string };  // local time, e.g. "10:00"–"18:00"
  signature: string;
}
