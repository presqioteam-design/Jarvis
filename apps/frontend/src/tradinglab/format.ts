import type { Currency } from "./api";

const fmt = (currency: Currency, digits: number) =>
  new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", { style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: digits });

export const money = (v: number, currency: Currency, digits = 2) => fmt(currency, digits).format(v);

/** "+₹24.31", "−$3.02": the sign is always written, so gain and loss never rely on colour alone. */
export function signed(v: number, currency: Currency | "%") {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const n = Math.abs(v);
  return currency === "%" ? `${sign}${n.toFixed(2)}%` : `${sign}${money(n, currency)}`;
}

export const tone = (v: number) => (v > 0 ? "tl-up" : v < 0 ? "tl-down" : "");

export function shortDate(iso: string, withYear = true) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-IN", withYear ? { day: "numeric", month: "short", year: "numeric" } : { weekday: "short", day: "numeric", month: "short" });
}

/** Price with sensible decimals for the chart axis and labels. */
export const price = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
