import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useUser } from "./lib/auth";
import { Logo } from "./components/Icon";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<SignedOut><Login /></SignedOut>} />
      <Route element={<SignedIn><Layout /></SignedIn>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/chat" element={<Chat />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

/** Pages that need a signed-in admin; everyone else goes to /login. */
function SignedIn({ children }: { children: ReactNode }) {
  const user = useUser();
  if (user === undefined) return <Splash />;
  return user ? children : <Navigate to="/login" replace />;
}

/** The login page; once signed in, go straight to the dashboard. */
function SignedOut({ children }: { children: ReactNode }) {
  const user = useUser();
  if (user === undefined) return <Splash />;
  return user ? <Navigate to="/dashboard" replace /> : children;
}

function Splash() {
  return (
    <div className="splash" aria-label="Loading">
      <Logo size={48} />
    </div>
  );
}
