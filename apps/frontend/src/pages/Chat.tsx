import { useEffect, useRef, useState, type FormEvent } from "react";
import type { User } from "firebase/auth";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import type { ChatMessage } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { sendChat } from "../lib/api";

const SUGGESTIONS = ["What happened today?", "Who is interested?", "Which leads need my attention?"];

export default function Chat({ user }: { user: User }) {
  const [messages, setMessages] = useState<(ChatMessage & { id: string })[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = query(collection(db, userPath(user.uid, "chats")), orderBy("createdAt", "desc"), limit(50));
    return onSnapshot(q, (s) => setMessages(s.docs.map((d) => ({ id: d.id, ...(d.data() as ChatMessage) })).reverse()));
  }, [user.uid]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages.length]);

  async function send(message: string) {
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    setText("");
    try {
      await sendChat(message.trim()); // the API saves both messages; the listener shows them
    } catch (e) {
      setError("Jarvis didn't answer. The server may be waking up; try again in a minute.");
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
      <div className="messages">
        {messages.length === 0 && <p className="muted">Ask about your leads, replies and outreach.</p>}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.text}
            {m.channel === "telegram" && <span className="via">via Telegram</span>}
          </div>
        ))}
        {busy && <div className="msg assistant muted">Thinking…</div>}
        <div ref={endRef} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="chips">
        {SUGGESTIONS.map((s) => (
          <button key={s} className="chip" onClick={() => send(s)} disabled={busy}>
            {s}
          </button>
        ))}
      </div>
      <form className="row" onSubmit={onSubmit}>
        <label htmlFor="chat-input" className="sr-only">Message Jarvis</label>
        <input id="chat-input" className="input" placeholder="Ask Jarvis anything…" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn primary" type="submit" disabled={busy}>Send</button>
      </form>
    </div>
  );
}
