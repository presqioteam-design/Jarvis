import { useEffect, useState } from "react";
import { onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { auth, googleProvider } from "./lib/firebase";
import Today from "./pages/Today";
import Chat from "./pages/Chat";

type Page = "today" | "chat";

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [page, setPage] = useState<Page>("today");

  useEffect(() => onAuthStateChanged(auth, setUser), []);

  if (user === undefined) return <div className="center muted">Loading…</div>;

  if (!user) {
    return (
      <div className="center">
        <div className="card signin">
          <Logo />
          <h1>Jarvis</h1>
          <p className="muted">Sign in to see your day.</p>
          <button className="btn primary" onClick={() => signInWithPopup(auth, googleProvider)}>
            Sign in with Google
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand">
          <Logo />
          <span>JARVIS</span>
        </div>
        <button className={`navlink ${page === "today" ? "active" : ""}`} onClick={() => setPage("today")}>
          Today
        </button>
        <button className={`navlink ${page === "chat" ? "active" : ""}`} onClick={() => setPage("chat")}>
          Ask Jarvis
        </button>
        <button className="navlink signout" onClick={() => signOut(auth)}>
          Sign out
        </button>
      </nav>
      <main className="main">
        {page === "today" ? <Today user={user} onAsk={() => setPage("chat")} /> : <Chat user={user} />}
      </main>
    </div>
  );
}

function Logo() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true" fill="none" stroke="#38BDF8" strokeWidth="2">
      <circle cx="16" cy="16" r="13" />
      <circle cx="16" cy="16" r="6" />
      <path d="M16 3v5M16 24v5M3 16h5M24 16h5" />
    </svg>
  );
}
