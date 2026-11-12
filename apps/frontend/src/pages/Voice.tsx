import { lazy, Suspense, useEffect, useRef, useState } from "react";
import Orb from "../components/Orb";
import Presentation from "../components/Presentation";
import type { AvatarFocus } from "../components/Avatar";
import Icon from "../components/Icon";
import type { CallState, Task } from "../lib/voice";
import { clockOf, useCall } from "../lib/call";
import { prepareVoice, voiceShow, warmUp } from "../lib/api";
import type { Display } from "../lib/display";

// three.js is only downloaded when someone switches to the avatar
const Avatar = lazy(() => import("../components/Avatar"));

type Look = "orb" | "avatar";
const LOOK_KEY = "jarvis.voice.look";
const savedLook = (): Look => {
  try { return localStorage.getItem(LOOK_KEY) === "avatar" ? "avatar" : "orb"; } catch { return "orb"; }
};
const PRESENT_MS = 15000;   // how long a command's result card stays up
const BOARD_MS = 45000;     // a visual (overview, Trading Lab) stays longer, and while Jarvis talks it through

const STATUS: Record<CallState | "idle", string> = {
  idle: "",   // the button below already says it
  connecting: "Connecting…",
  listening: "Listening",
  thinking: "Working on it",
  speaking: "Jarvis is speaking",
  ended: "Call ended",
  error: "Call failed",
};

export default function Voice() {
  // the call itself lives in CallProvider, so leaving this page doesn't hang up
  const { state, live, you, jarvis, error, muted, seconds, allowance, begin, end, toggleMute, levels, tasks } = useCall();
  const [look, setLook] = useState<Look>(savedLook);
  const pick = (l: Look) => {
    setLook(l);
    try { localStorage.setItem(LOOK_KEY, l); } catch { /* private mode: just not remembered */ }
  };

  // the newest command: "work" while it runs, "present" for a while after its result arrives
  const task = tasks[0];
  const [shownUntil, setShownUntil] = useState(0);
  const [, tick] = useState(0);
  const [dismissed, setDismissed] = useState("");
  useEffect(() => {
    if (!task?.result) return;
    const ms = task.display ? BOARD_MS : PRESENT_MS;
    setShownUntil(Date.now() + ms);
    const id = setTimeout(() => tick((n) => n + 1), ms + 50);
    return () => clearTimeout(id);
  }, [task?.id, task?.result]);
  const showing = !!task?.result && task.id !== dismissed && (Date.now() < shownUntil || (!!task.display && state === "speaking"));
  const stageRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const focus: AvatarFocus = !task ? null : !task.result ? "work" : showing ? "present" : null;

  // what the card shows; kept for a moment after it's done so it can fade out
  const cardOn = !!(focus && task && (look === "avatar" || focus === "present"));
  const [card, setCard] = useState<{ task: Task; focus: "work" | "present" } | null>(null);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    if (cardOn && task && focus) {
      setCard({ task, focus });
      setLeaving(false);
      return;
    }
    setLeaving(true);
    const id = setTimeout(() => { setCard(null); setLeaving(false); }, 450);
    return () => clearTimeout(id);
  }, [cardOn, task, focus]);

  // today's numbers for the avatar's room (its wall panels and ticker), refreshed every few minutes
  const [wall, setWall] = useState<Display | null>(null);
  useEffect(() => {
    if (look !== "avatar") return;
    const load = () => voiceShow("overview").then((r) => setWall(r.display)).catch(() => undefined);
    void load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [look]);

  useEffect(() => {
    warmUp(); // wake the server while you read the page
    if (!live) void prepareVoice(); // and have Jarvis's briefing ready before you tap
  }, []);

  const clock = clockOf(seconds);

  return (
    <div className={`voice-page state-${state} look-${look}`}>
      <div className="hud hud-top">
        <span className="hud-title">J.A.R.V.I.S</span>
        <span className="hud-sub">PRESQIO · SALES ASSISTANT</span>
        <span className="hud-toggle" role="group" aria-label="How Jarvis looks">
          <button type="button" aria-pressed={look === "orb"} onClick={() => pick("orb")}>ORB</button>
          <button type="button" aria-pressed={look === "avatar"} onClick={() => pick("avatar")}>AVATAR</button>
        </span>
        <span className="hud-right">
          {live && <span className="rec" aria-hidden="true" />}
          {live ? (allowance ? `${clock} / ${String(Math.floor(allowance.maxSeconds / 60)).padStart(2, "0")}:00` : clock) : "STANDBY"}
        </span>
      </div>
      <span className="hud-corner tl" aria-hidden="true" />
      <span className="hud-corner tr" aria-hidden="true" />
      <span className="hud-corner bl" aria-hidden="true" />
      <span className="hud-corner br" aria-hidden="true" />
      <span className="hud-rail left" aria-hidden="true" />
      <span className="hud-rail right" aria-hidden="true" />


      {look === "avatar" && (
        <Suspense fallback={null}>
          <Avatar state={state} levels={levels} focus={focus} onFail={() => pick("orb")} frame={stageRef} card={cardRef} wall={wall} />
        </Suspense>
      )}
      {/* the character holds this card up; with the orb it floats at the top instead. It fades out rather than vanishing. */}
      {card && (
        <div ref={cardRef} className={`char-card ${card.focus} ${card.focus === "present" && card.task.display ? "board" : ""} ${look === "orb" ? "floating" : ""} ${leaving ? "leaving" : ""}`} aria-live="polite">
          <div className="char-card-head">
            {card.focus === "work" ? "EXTRACTING" : card.task.display ? "ON SCREEN" : "RESULT"}
            {card.focus === "present" && (
              <button type="button" className="char-card-close" onClick={() => setDismissed(card.task.id)} aria-label="Close">×</button>
            )}
          </div>
          {card.focus === "work" ? (
            <>
              <div className="char-card-cmd">{card.task.command}</div>
              <div className="char-card-scan" aria-hidden="true" />
            </>
          ) : card.task.display ? (
            <Presentation display={card.task.display} />
          ) : (
            <>
              <div className="char-card-cmd">{card.task.command}</div>
              <div className="char-card-body">{card.task.result}</div>
            </>
          )}
        </div>
      )}

      {/* the orb, or the empty box the 3D character stands in */}
      <div ref={stageRef} className="orb-wrap">
        {look === "orb" && <Orb state={state} levels={levels} />}
      </div>

      <div className="voice-status" aria-live="polite">{STATUS[state]}</div>

      <div className="captions" aria-live="polite">
        {you && <p className="cap-you"><span>YOU</span>{you}</p>}
        {jarvis && <p className="cap-jarvis"><span>JARVIS</span>{jarvis}</p>}
        {!you && !jarvis && !live && !error && (
          <p className="cap-hint">Ask about today's emails and replies, or say things like “send five emails in Hitech City” or “pause auto”.</p>
        )}
        {error && <p className="cap-error" role="alert">{error}</p>}
      </div>

      <div className="voice-controls">
        {live ? (
          <>
            <button className={`round-btn ${muted ? "on" : ""}`} onClick={toggleMute} aria-pressed={muted} aria-label={muted ? "Unmute" : "Mute"}>
              <Icon name={muted ? "micOff" : "mic"} size={22} />
            </button>
            <button className="round-btn end" onClick={end} aria-label="End call">
              <Icon name="phone" size={24} />
            </button>
          </>
        ) : (
          <button className="call-btn" onClick={() => void begin()} onPointerDown={() => void prepareVoice()}>
            <Icon name="mic" size={22} />
            {state === "ended" || state === "error" ? "Call again" : "Talk to Jarvis"}
          </button>
        )}
      </div>
      <p className="voice-foot">
        Works best with headphones.{" "}
        {allowance
          ? `${allowance.callsLeft === null ? "Up to" : `${allowance.callsLeft} of ${allowance.callsPerDay} calls left today · up to`} ${Math.round(allowance.maxSeconds / 60)} min each.`
          : "Daily limits keep calls within the free voice allowance."}
      </p>
    </div>
  );
}
