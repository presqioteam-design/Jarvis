export function duration(seconds = 0): string {
  const m = Math.floor(seconds / 60);
  const h = Math.floor(m / 60);
  return h ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
}

/** YYYY-MM-DD in the browser's time zone */
export function localDate(d = new Date()): string {
  return d.toLocaleDateString("en-CA");
}

export function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export const CATEGORY_COLORS: Record<string, string> = {
  deep: "#38BDF8",
  meeting: "#F5A524",
  comms: "#7C6CF0",
  browsing: "#F472B6",
  other: "#64748B",
  away: "#3A4555",
};

export const CATEGORY_LABELS: Record<string, string> = {
  deep: "Deep work",
  meeting: "Meetings",
  comms: "Chat & email",
  browsing: "Browsing",
  other: "Other",
  away: "Away",
};
