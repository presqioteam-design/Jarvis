import { auth } from "./firebase";

const API_URL = import.meta.env.VITE_API_URL as string;

async function call<T>(path: string, body: unknown): Promise<T> {
  const token = await auth.currentUser?.getIdToken();
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const sendChat = (message: string) => call<{ reply: string }>("/chat", { message });
