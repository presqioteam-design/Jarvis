export function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export function timeAgo(iso: string, now = Date.now()): string {
  const min = Math.round((now - new Date(iso).getTime()) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  if (min < 24 * 60) return `${Math.floor(min / 60)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function percent(part: number, whole: number): string {
  return whole ? `${Math.round((part / whole) * 100)}%` : "0%";
}

/** "https://www.hotel.com/x" -> "hotel.com"; returns the input if it isn't a valid URL */
export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Same rule as slug() in apps/api/app/services/leads.py: "Hitech City" -> "hitech-city" */
export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "other";
}

export const areaKey = (city: string, area: string) => `${slug(city)}--${slug(area)}`;

/** "09:30".."20:00" every half hour, both ends included. */
export function halfHours(from: string, to: string): string[] {
  const out: string[] = [];
  const [h0, m0] = from.split(":").map(Number);
  const [h1, m1] = to.split(":").map(Number);
  for (let t = h0 * 60 + m0; t <= h1 * 60 + m1; t += 30) out.push(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  return out;
}

/** "13:30" -> "1:30 PM" */
export const ampm = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};
