import { useEffect, useRef, useState, type FormEvent } from "react";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import type { ChatMessage } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { errorText, sendChat } from "../lib/api";
import { useUser } from "../lib/auth";
import Icon, { Logo } from "../components/Icon";

const SUGGESTIONS = ["What happened today?", "Who is interested?", "Which leads need my attention?"];

export default function Chat() {
  const user = useUser()!;
  const [messages, setMessages] = useState<(ChatMessage & { id: string })[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = query(collection(db, userPath(user.uid, "chats")), orderBy("createdAt", "desc"), limit(50));
    return onSnapshot(
      q,
      (s) => setMessages(s.docs.map((d) => ({ id: d.id, ...(d.data() as ChatMessage) })).reverse()),
      () => setError("Couldn't load the chat history. Check that the Firestore rules are published."),
    );
  }, [user.uid]);

  // scroll only the message list (scrollIntoView would also scroll the page on phones)
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, busy]);

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
        {messages.length === 0 && !busy && (
          <div className="chat-empty">
            <Logo size={48} />
            <h2>Ask me about your outreach</h2>
            <p className="muted">I can tell you who replied, who's interested and what I did today.</p>
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
