import { useLocation, useNavigate } from "react-router-dom";
import { clockOf, useCall } from "../lib/call";
import Icon, { Logo } from "./Icon";

const LABEL = { connecting: "Connecting…", listening: "Listening", thinking: "Working on it", speaking: "Jarvis is speaking" } as const;

/** While a call runs and you're on another page: who's talking, the timer, mute, hang up. Tap to go back. */
export default function CallBanner() {
  const { state, live, muted, seconds, toggleMute, end } = useCall();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  if (!live || pathname.startsWith("/voice")) return null;
  return (
    <div className={`call-banner state-${state}`} role="status">
      <button className="call-banner-main" onClick={() => navigate("/voice")} aria-label="Back to the call with Jarvis">
        <span className="call-banner-orb"><Logo size={26} /></span>
        <span className="call-banner-text">
          <strong>On call with Jarvis</strong>
          <span>{LABEL[state as keyof typeof LABEL]} · {clockOf(seconds)}</span>
        </span>
      </button>
      <button className={`call-banner-btn ${muted ? "on" : ""}`} onClick={toggleMute} aria-pressed={muted} aria-label={muted ? "Unmute" : "Mute"}>
        <Icon name={muted ? "micOff" : "mic"} size={18} />
      </button>
      <button className="call-banner-btn end" onClick={end} aria-label="End call">
        <Icon name="phone" size={18} />
      </button>
    </div>
  );
}
