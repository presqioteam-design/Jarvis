/**
 * The Jarvis call lives here, above the pages, so it keeps going while you move between
 * Home, Leads, Chat and back. It ends only when you hang up or tell Jarvis to.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { VoiceCall, type CallState } from "./voice";

type Allowance = { callsLeft: number | null; callsPerDay: number; maxSeconds: number };

type Call = {
  state: CallState | "idle";
  live: boolean;
  you: string;
  jarvis: string;
  error: string;
  muted: boolean;
  seconds: number;
  allowance: Allowance | null;
  begin: () => Promise<void>;
  end: () => void;
  toggleMute: () => void;
  levels: () => { you: number; jarvis: number };
};

const CallContext = createContext<Call | null>(null);

export function useCall(): Call {
  const c = useContext(CallContext);
  if (!c) throw new Error("useCall needs <CallProvider>");
  return c;
}

export const isLive = (s: CallState | "idle") => s === "connecting" || s === "listening" || s === "thinking" || s === "speaking";

export const clockOf = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

export function CallProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CallState | "idle">("idle");
  const [you, setYou] = useState("");
  const [jarvis, setJarvis] = useState("");
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  const call = useRef<VoiceCall | null>(null);
  const live = isLive(state);

  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [live]);

  // once the call is over, clear the last lines so the screen is clean for the next one
  useEffect(() => {
    if (state !== "ended") return;
    const id = setTimeout(() => { setYou(""); setJarvis(""); }, 1800);
    return () => clearTimeout(id);
  }, [state]);

  // keep the screen on during a call (a sleeping phone pauses the mic); the browser drops
  // the lock whenever the page is hidden, so take it again on return
  useEffect(() => {
    if (!live || !("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    const take = () => {
      if (document.visibilityState === "visible")
        navigator.wakeLock.request("screen").then((l) => { lock = l; }).catch(() => undefined);
    };
    take();
    document.addEventListener("visibilitychange", take);
    return () => {
      document.removeEventListener("visibilitychange", take);
      void lock?.release().catch(() => undefined);
    };
  }, [live]);

  // signing out (or closing the app shell) ends the call
  useEffect(() => () => call.current?.stop(), []);

  const begin = useCallback(async () => {
    if (call.current && isLive(state)) return;
    setError("");
    setYou("");
    setJarvis("");
    setSeconds(0);
    setMuted(false);
    const c = new VoiceCall({
      state: setState,
      caption: (who, text) => (who === "you" ? setYou(text) : setJarvis(text)),
      error: setError,
      info: setAllowance,
    });
    call.current = c;
    await c.start();
  }, [state]);

  const end = useCallback(() => call.current?.stop(), []);

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      call.current?.setMuted(!m);
      return !m;
    });
  }, []);

  const levels = useCallback(() => call.current?.levels() ?? { you: 0, jarvis: 0 }, []);

  return (
    <CallContext.Provider value={{ state, live, you, jarvis, error, muted, seconds, allowance, begin, end, toggleMute, levels }}>
      {children}
    </CallContext.Provider>
  );
}
