import { useEffect, useState } from "react";
import { onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { auth, googleProvider } from "./lib/firebase";
import Overview from "./pages/Overview";
import Chat from "./pages/Chat";

type Page = "overview" | "chat";

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [page, setPage] = useState<Page>("overview");

  useEffect(() => onAuthStateChanged(auth, setUser), []);

  if (user === undefined) return <div className="center muted">Loading…</div>;

  if (!user) {
    return (
      <div className="center">
        <div className="card signin">
          <Logo />
          <h1>Jarvis</h1>
          <p className="muted">Sign in to manage Presqio outreach.</p>
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
        <button className={`navlink ${page === "overview" ? "active" : ""}`} onClick={() => setPage("overview")}>
          Overview
        </button>
        <button className={`navlink ${page === "chat" ? "active" : ""}`} onClick={() => setPage("chat")}>
          Ask Jarvis
        </button>
        <button className="navlink signout" onClick={() => signOut(auth)}>
          Sign out
        </button>
      </nav>
      <main className="main">
        {page === "overview" ? <Overview user={user} onAsk={() => setPage("chat")} /> : <Chat user={user} />}
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
