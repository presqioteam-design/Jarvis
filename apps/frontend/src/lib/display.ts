/** A visual Jarvis's on-screen character presents during a call (built by the API's services/screen.py). */
export type Tone = "up" | "down" | null | undefined;

export type Stat = { label: string; value: string; tone?: Tone; note?: string };

export type BarsChart = { type: "bars"; title: string; items: { label: string; value: number; text: string }[] };

export type LineChart = {
  type: "line";
  title: string;
  points: [string, number][];                                     // [time, price]
  marks: { at: number; kind: "buy" | "sell"; label: string }[];   // index into points
  band: [number, number] | null;                                  // e.g. the opening range
};

export type Display = {
  title: string;
  subtitle?: string;
  stats?: Stat[];
  charts?: (BarsChart | LineChart)[];
  rows?: { title?: string; items: { label: string; detail?: string; value?: string; tone?: Tone }[] } | null;
};
