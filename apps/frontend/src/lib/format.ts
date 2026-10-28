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
