import { useEffect } from "react";
import Orb from "../components/Orb";
import Icon from "../components/Icon";
import type { CallState } from "../lib/voice";
import { clockOf, useCall } from "../lib/call";
import { prepareVoice, warmUp } from "../lib/api";

const STATUS: Record<CallState | "idle", string> = {
  idle: "Tap to talk to Jarvis",
  connecting: "Connecting…",
  listening: "Listening",
  thinking: "Working on it",
  speaking: "Jarvis is speaking",
  ended: "Call ended",
  error: "Call failed",
};

export default function Voice() {
  // the call itself lives in CallProvider, so leaving this page doesn't hang up
  const { state, live, you, jarvis, error, muted, seconds, allowance, begin, end, toggleMute, levels } = useCall();

  useEffect(() => {
    warmUp(); // wake the server while you read the page
    if (!live) void prepareVoice(); // and have Jarvis's briefing ready before you tap
  }, []);

  const clock = clockOf(seconds);

  return (
    <div className={`voice-page state-${state}`}>
      <div className="hud hud-top">
        <span className="hud-title">J.A.R.V.I.S</span>
        <span className="hud-sub">PRESQIO · SALES ASSISTANT</span>
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

      <aside className="hud-panel left" aria-hidden="true">
        <h4>SYSTEM</h4>
        <dl>
          <dt>CORE</dt><dd>{live ? "ONLINE" : state === "error" ? "FAULT" : "STANDBY"}</dd>
          <dt>LINK</dt><dd>{state === "connecting" ? "HANDSHAKE" : live ? "GEMINI LIVE" : "—"}</dd>
          <dt>VOICE</dt><dd>{muted ? "MUTED" : live ? "OPEN" : "—"}</dd>
          <dt>MODE</dt><dd>SALES OPS</dd>
        </dl>
      </aside>
      <aside className="hud-panel right" aria-hidden="true">
        <h4>SESSION</h4>
        <dl>
          <dt>TIME</dt><dd>{live ? clock : "00:00"}</dd>
          <dt>LIMIT</dt><dd>{allowance ? `${Math.round(allowance.maxSeconds / 60)} MIN` : "—"}</dd>
          <dt>CALLS</dt><dd>{allowance?.callsLeft != null ? `${allowance.callsLeft} LEFT` : "—"}</dd>
          <dt>USER</dt><dd>BOSS</dd>
        </dl>
      </aside>

      <div className="orb-wrap">
        <Orb state={state} levels={levels} />
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
