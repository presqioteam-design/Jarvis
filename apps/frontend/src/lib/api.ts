import { auth } from "./firebase";

const API_URL = import.meta.env.VITE_API_URL as string;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/**
 * The API's own explanation for refusals (e.g. the daily scan limit, or 503 when the free
 * database quota is used up), else `fallback`.
 */
export const errorText = (e: unknown, fallback: string) =>
  e instanceof ApiError && e.message && e.status !== 401 && (e.status < 500 || e.status === 503) ? e.message : fallback;

/** POSTs `body` as JSON; without a body it's a GET. */
async function call<T>(path: string, body?: unknown): Promise<T> {
  const token = await auth.currentUser?.getIdToken();
  const res = await fetch(`${API_URL}${path}`, body === undefined
    ? { headers: { Authorization: `Bearer ${token}` } }
    : {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
  if (!res.ok) {
    // FastAPI sends {"detail": "..."}; show that sentence when there is one
    const text = await res.text();
    let detail = "";
    try {
      detail = typeof JSON.parse(text).detail === "string" ? JSON.parse(text).detail : "";
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail || text);
  }
  return res.json() as Promise<T>;
}

/** Wake the free Render server early (it sleeps after 15 min), so a call starts without the wait. */
export const warmUp = () => fetch(`${API_URL}/health`).catch(() => undefined);

/** Let the server gather Jarvis's briefing before the call, so tapping Call starts faster. */
export const prepareVoice = () => call<{ ok: boolean }>("/voice/prepare", {}).catch(() => undefined);

export const startVoiceSession = () =>
  call<{ url: string; maxSeconds: number; callsLeft: number | null; callsPerDay: number }>("/voice/session", {});
export const voiceCommand = (command: string) => call<{ result: string }>("/voice/command", { command });
export const sendChat = (message: string) => call<{ reply: string }>("/chat", { message });
export const blockLead = (leadId: string) => call<{ ok: true }>(`/leads/${leadId}/block`, {});
export const scanPlace = (place: string, radiusKm: number | null, category: string) =>
  call<{ id: string }>("/campaigns", { place, radiusKm, category });
export const resumeScan = (id: string) => call<{ ok: true }>(`/campaigns/${id}/resume`, {});
export const setLeadStatus = (ids: string[], status: "new" | "ready" | "not_interested") => call<{ ok: true }>("/leads/status", { ids, status });
export const approveAllWithEmail = (city: string, area: string | null, category: string | null = null) =>
  call<{ approved: number }>("/leads/approve-all", { city, area, category });

export type SendingSettings = {
  enabled: boolean;
  perRun: number;
  dailyAuto: number;
  dailyCap: number;
  from: string;
  until: string;
  days: number[];          // 0 = Monday … 5 = Saturday
  followUps: boolean;
  followUpDays: [number, number];
};
export type SendingView = {
  settings: SendingSettings;
  runsPerDay: number;
  sentToday: number;
  limits: { earliest: string; latest: string; maxPerRun: number; maxDaily: number; days: number[] };
};
export const getSending = () => call<SendingView>("/settings/sending");
export const saveSending = (patch: Partial<SendingSettings>) => call<SendingView>("/settings/sending", patch);

export type FindingSettings = { categories: string[]; exploreEnabled: boolean; areasPerNight: number };
export type ExploreCity = {
  id: string; city: string; skipped: boolean; prioritised: boolean; areasListed: boolean;
  areas: number; areasDone: number; next: string | null; found: number;
};
export type FindingView = {
  settings: FindingSettings;
  categories: { key: string; label: string }[];
  maxAreasPerNight: number;
  queue: ExploreCity[];
  tonight: { areas: number; added: number; done: string[] };
};
export const getFinding = () => call<FindingView>("/settings/finding");
export const saveFinding = (patch: Partial<FindingSettings>) => call<FindingView>("/settings/finding", patch);
export const prioritiseCity = (city: string) => call<FindingView & { note: string }>("/settings/explore/prioritise", { city });
export const skipCity = (id: string, skipped: boolean) => call<FindingView>("/settings/explore/skip", { id, skipped });

export type EmailSettings = { senderName: string; phone: string; website: string };
export type EmailsView = { settings: EmailSettings; categories: { key: string; label: string }[] };
export type EmailPreview = { from: string; emails: { label: string; subject: string; body: string }[] };
export const getEmails = () => call<EmailsView>("/settings/emails");
export const saveEmails = (patch: Partial<EmailSettings>) => call<EmailsView>("/settings/emails", patch);
export const previewEmails = (body: Partial<EmailSettings> & { category: string; name: string; area: string }) =>
  call<EmailPreview>("/settings/emails/preview", body);

export type DncEntry = { key: string; kind: "email" | "phone"; reason: string; business: string; area: string; createdAt: string };
export type BouncedLead = { id: string; name: string; email: string; area: string; city: string; category: string };
export type DncView = { entries: DncEntry[]; bounced: BouncedLead[] };
export const getDnc = () => call<DncView>("/settings/dnc");
export const blockAddress = (address: string) => call<DncView>("/settings/dnc/block", { address });
export const unblockAddress = (key: string) => call<DncView & { restored: number }>("/settings/dnc/unblock", { key });

export type UsageMeter = { key: string; label: string; used: number; limit: number; resetsAt: string; note: string };
export type DatabaseUsage =
  | { reads: number; writes: number; deletes: number; limits: { reads: number; writes: number; deletes: number }; resetsAt: string; error?: undefined }
  | { error: "permission"; serviceAccount: string; project: string; resetsAt: string }
  | { error: "unavailable"; resetsAt: string };
export type UsageView = { meters: UsageMeter[]; database: DatabaseUsage };
export const getUsage = () => call<UsageView>("/settings/usage");
