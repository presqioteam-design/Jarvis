/** Trading Lab API (tradinglab/jarvis_api.py on the server). Paper money only. */
import { call } from "../lib/api";

export type MarketKey = "IN" | "US";
export type Currency = "INR" | "USD";
export type Rules = {
  pot: number; range_minutes: number; max_stop_pct: number; trail_after_pct: number; trail_pct: number;
  no_entry_last_minutes: number; exit_before_close_minutes: number; charges: boolean;
};
export type MarketInfo = { name: string; currency: Currency; open: string; close: string; stocks: string[] };
export type Totals = { pnl: number; withdrawn: number; trades: number; wins: number; days: number };
export type Config = {
  version: 2; startDate: string; potPerStock: number; startedAt: string;
  pots: Record<MarketKey, Record<string, number>>; totals: Record<MarketKey, Totals>; progress: Partial<Record<MarketKey, string>>;
};
export type MarketDay = { currency: Currency; pnl: number; withdrawn: number; trades: number; wins: number; pots: number; cumPnl: number; cumWithdrawn: number };
export type StockDay = { market: MarketKey; potStart: number; potEnd: number; pnl: number; withdrawn: number; traded: boolean };
export type DayRecord = { date: string; markets: Partial<Record<MarketKey, MarketDay>>; stocks: Record<string, StockDay> };

type Base = { rules: Rules; markets: Record<MarketKey, MarketInfo>; configured: boolean; defaultStart: string; minStart: string; busy: boolean; error: string;
  priceCallsToday: number; lastClosed: Record<MarketKey, string> };
export type LabView = (Base & { started: false }) | (Base & { started: true; config: Config; days: DayRecord[] });

export type Candle = { time: string; open: number; high: number; low: number; close: number; volume: number };
/** A trade. While it's still held (today, live), sellTime/sellPrice are null and open/last/stop say where it stands. */
export type Trade = {
  buyTime: string; buyPrice: number; qty: number; sellTime: string | null; sellPrice: number | null; best: number;
  charges: number; pnl: number; pnlPct: number; reason: string; exit: string;
  open?: boolean; last?: number; lastTime?: string; stop?: number; trailing?: boolean;
};
export type LiveState = "range" | "watching" | "holding" | "sold" | "no_trade";
export type LiveStock = { state: LiveState; note: string; pnl: number; price: number | null; time: string | null; done: boolean; trade: Trade | null };
export type LiveMarket = {
  open: boolean; nextOpen: string; day: string;
  state: { day: string; checkedAt?: string; holiday: boolean; stopped: string; stocks: Record<string, LiveStock> } | null;
};
export type LiveView = { markets: Record<MarketKey, LiveMarket> };
export type StockReplay =
  | { symbol: string; market: MarketKey; currency: Currency; candles: Candle[]; range: { high: number; low: number; until: string } | null;
      trade: Trade | null; note: string; pnl: number; potStart: number; error?: undefined }
  | { symbol: string; market: MarketKey; error: string };
export type DayReplay = { date: string; stocks: StockReplay[] };

export const getLab = () => call<LabView>("/tradinglab");
export const startLab = (startDate: string) => call<LabView>("/tradinglab/start", { startDate });
export const refreshLab = () => call<LabView>("/tradinglab/refresh", {});
export const getDay = (date: string) => call<DayReplay>(`/tradinglab/day/${date}`);
export const getLive = () => call<LiveView>("/tradinglab/live");
/** Run a live check now if the last is over 4 minutes old (only open markets); returns the live view. */
export const checkLiveNow = () => call<LiveView>("/tradinglab/live/check", {});

/** True when the stock's day loaded (it has candles), false when the server sent an error instead. */
export const loaded = (s: StockReplay): s is Extract<StockReplay, { candles: Candle[] }> => "candles" in s;
