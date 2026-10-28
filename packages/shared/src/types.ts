/**
 * Firestore data model. Every collection sits under users/{uid}/.
 * Keep apps/api/app/models.py in sync with this file.
 */

export type Category = "deep" | "meeting" | "comms" | "browsing" | "away" | "other";

/** users/{uid}/events/{id} — written by the desktop agent */
export interface ActivityEvent {
  start: string;          // ISO timestamp
  duration: number;       // seconds
  app: string;            // e.g. "Code.exe", "Google Chrome"
  title: string;          // window title
  url?: string;           // browser tab URL, when available
  afk: boolean;           // true when the user was away
  category: Category;     // assigned by the agent using settings.categoryRules
  date: string;           // YYYY-MM-DD in the user's time zone (for querying a day)
  source: string;         // ActivityWatch bucket id
}

export interface AppTotal {
  app: string;
  seconds: number;
}

/** users/{uid}/summaries/{YYYY-MM-DD} — written by the API */
export interface DailySummary {
  date: string;
  focusSeconds: number;
  meetingSeconds: number;
  activeSeconds: number;
  contextSwitches: number;
  topApps: AppTotal[];
  timeline: { category: Category; start: string; seconds: number }[];
  morningBrief?: string;
  eveningReview?: string;
  updatedAt: string;
}

export type TaskStatus = "todo" | "in_progress" | "done";

/** users/{uid}/tasks/{id} — written by the dashboard and API */
export interface Task {
  title: string;
  status: TaskStatus;
  plannedFor: string;     // YYYY-MM-DD
  carriedOver?: boolean;
  remindAt?: string;      // ISO timestamp
  createdAt: string;
}

/** users/{uid}/chats/{id} — written by the API */
export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  channel: "web" | "telegram";
  createdAt: string;
}

/** users/{uid}/nudges/{id} — written by the API, dismissed by the dashboard */
export interface Nudge {
  text: string;
  kind: "focus" | "reminder" | "break";
  createdAt: string;
  dismissed: boolean;
}

/** users/{uid}/settings/main — written by the dashboard */
export interface Settings {
  timezone: string;                // e.g. "Asia/Kolkata"
  workStart: string;               // "09:00"
  workEnd: string;                 // "18:00"
  focusGoalMinutes: number;        // e.g. 240
  categoryRules: { match: string; category: Category }[];  // substring of app or title
}
