import { auth } from "./firebase";

const API_URL = import.meta.env.VITE_API_URL as string;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** The API's own explanation for refusals (e.g. the daily scan limit), else `fallback`. */
export const errorText = (e: unknown, fallback: string) =>
  e instanceof ApiError && e.status !== 401 && e.status < 500 ? e.message : fallback;

async function call<T>(path: string, body: unknown): Promise<T> {
  const token = await auth.currentUser?.getIdToken();
  const res = await fetch(`${API_URL}${path}`, {
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

export const startVoiceSession = () =>
  call<{ url: string; maxSeconds: number; callsLeft: number | null; callsPerDay: number }>("/voice/session", {});
export const voiceCommand = (command: string) => call<{ result: string }>("/voice/command", { command });
export const sendChat = (message: string) => call<{ reply: string }>("/chat", { message });
export const blockLead = (leadId: string) => call<{ ok: true }>(`/leads/${leadId}/block`, {});
export const scanPlace = (place: string, radiusKm: number | null) => call<{ id: string }>("/campaigns", { place, radiusKm });
export const resumeScan = (id: string) => call<{ ok: true }>(`/campaigns/${id}/resume`, {});
export const setLeadStatus = (ids: string[], status: "new" | "ready" | "not_interested") => call<{ ok: true }>("/leads/status", { ids, status });
export const approveAllWithEmail = (city: string, area: string | null) => call<{ approved: number }>("/leads/approve-all", { city, area });
