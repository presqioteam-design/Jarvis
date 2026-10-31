import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { collection, orderBy, query, where } from "firebase/firestore";
import type { ChatMessage } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { errorText, sendChat } from "../lib/api";
import { useUser } from "../lib/auth";
import Icon, { Logo } from "../components/Icon";
import { LoadMore, usePaged } from "../lib/paging";

const SUGGESTIONS = ["What happened today?", "Who is interested?", "Which leads need my attention?"];

export default function Chat() {
  const user = useUser()!;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // the last 24 hours only (the server deletes older messages): newest 30 live, older ones on scroll up
  const [since] = useState(() => new Date(Date.now() - 24 * 3600_000).toISOString());
  const history = usePaged<ChatMessage>(
    query(collection(db, userPath(user.uid, "chats")), where("createdAt", ">=", since), orderBy("createdAt", "desc")),
    `chats:${user.uid}`,
    30,
  );
  const messages = [...history.rows].reverse();
  const newestId = messages[messages.length - 1]?.id;
  const keepFromBottom = useRef<number | null>(null);
  // the top marker is on screen for a moment before the first scroll to the newest message:
  // only start loading older messages after that
  const [primed, setPrimed] = useState(false);
  useEffect(() => {
    if (!history.ready) return;
    const t = setTimeout(() => setPrimed(true), 800);
    return () => clearTimeout(t);
  }, [history.ready]);

  useEffect(() => {
    if (history.error) setError("Couldn't load the chat history. Check that the Firestore rules are published.");
  }, [history.error]);

  // a new message (or Jarvis typing): scroll the list, not the page, to the bottom
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [newestId, busy]);

  // older messages added above: keep what you were reading in place
  const loadOlder = () => {
    const el = listRef.current;
    if (el) keepFromBottom.current = el.scrollHeight - el.scrollTop;
    void history.loadMore();
  };
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && keepFromBottom.current !== null && !history.loading) {
      el.scrollTop = el.scrollHeight - keepFromBottom.current;
      keepFromBottom.current = null;
    }
  }, [messages.length, history.loading]);

  async function send(message: string) {
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    setText("");
    try {
      await sendChat(message.trim()); // the API saves both messages; the listener shows them
    } catch (e) {
      setError(errorText(e, "Jarvis couldn't answer just now. Check your connection and try again in a minute."));
      setText(message);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(text);
  };

  return (
    <div className="chat">
      <header className="chat-head">
        <Logo size={36} />
        <div>
          <div className="chat-name">Jarvis</div>
          <div className="muted small">
            <span className="online" /> Your Presqio sales assistant
          </div>
        </div>
      </header>

      <div className="messages" ref={listRef}>
        {history.ready && <LoadMore root={listRef} more={history.more && primed} loading={history.loading} onVisible={loadOlder}
          done={!history.more && messages.length > 0 ? "Chats are kept for 24 hours" : ""} />}
        {messages.length === 0 && !busy && (
          <div className="chat-empty">
            <Logo size={48} />
            <h2>Ask me about your outreach</h2>
            <p className="muted">I can tell you who replied, who's interested and what I did today.</p>
            <p className="muted small">Chats are kept for 24 hours.</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.text}
            {m.channel === "telegram" && <span className="via">via Telegram</span>}
          </div>
        ))}
        {busy && (
          <div className="msg assistant typing" aria-label="Jarvis is typing">
            <span /><span /><span />
          </div>
        )}
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="chips">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>
            {s}
          </button>
        ))}
      </div>
      <form className="composer" onSubmit={onSubmit}>
        <label htmlFor="chat-input" className="sr-only">Message Jarvis</label>
        <input id="chat-input" className="input" placeholder="Ask Jarvis anything…" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
        <button className="btn primary send" type="submit" disabled={busy || !text.trim()} aria-label="Send">
          <Icon name="send" size={18} />
        </button>
      </form>
    </div>
  );
}
