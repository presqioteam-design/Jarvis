import { NavLink, Outlet, useLocation } from "react-router-dom";
import { logOut, useUser } from "../lib/auth";
import Icon, { Logo, type IconName } from "./Icon";

const NAV: { to: string; label: string; icon: IconName; soon?: boolean }[] = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/campaigns", label: "Find hotels", icon: "campaign" },
  { to: "/leads", label: "Leads", icon: "leads" },
  { to: "/voice", label: "Talk to Jarvis", icon: "mic" },
  { to: "/chat", label: "Ask Jarvis", icon: "chat" },
  { to: "/settings", label: "Settings", icon: "settings", soon: true },
];

/** Phone tab bar: Jarvis sits in the middle as the raised main button, like an app's home action. */
const TABS: { to: string; label: string; icon: IconName }[] = [
  { to: "/dashboard", label: "Home", icon: "dashboard" },
  { to: "/campaigns", label: "Hotels", icon: "campaign" },
  { to: "/leads", label: "Leads", icon: "leads" },
  { to: "/chat", label: "Chat", icon: "chat" },
];

export default function Layout() {
  const user = useUser();
  const { pathname } = useLocation();
  const title = NAV.find((n) => pathname.startsWith(n.to))?.label ?? "Jarvis";
  const onVoice = pathname.startsWith("/voice");
  const tab = (t: (typeof TABS)[number]) => (
    <NavLink key={t.to} to={t.to} className={({ isActive }) => `tabbar-item ${isActive ? "active" : ""}`}>
      <Icon name={t.icon} size={22} />
      <span>{t.label}</span>
    </NavLink>
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo size={28} />
          <div>
            <div className="brand-name">JARVIS</div>
            <div className="brand-sub">for Presqio</div>
          </div>
        </div>

        <nav className="nav" aria-label="Main">
          {NAV.map((n) =>
            n.soon ? (
              <span key={n.to} className="navlink disabled" aria-disabled="true">
                <Icon name={n.icon} />
                <span>{n.label}</span>
                <span className="soon">Soon</span>
              </span>
            ) : (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => `navlink ${isActive ? "active" : ""}`}>
                <Icon name={n.icon} />
                <span>{n.label}</span>
              </NavLink>
            ),
          )}
        </nav>

        <div className="profile">
          {user?.photoURL ? (
            <img src={user.photoURL} alt="" className="avatar" referrerPolicy="no-referrer" />
          ) : (
            <span className="avatar fallback">{(user?.displayName ?? "A")[0]}</span>
          )}
          <div className="profile-text">
            <div className="profile-name">{user?.displayName ?? "Admin"}</div>
            <div className="muted small ellipsis">{user?.email}</div>
          </div>
          <button className="icon-btn" onClick={logOut} title="Sign out" aria-label="Sign out">
            <Icon name="logout" size={18} />
          </button>
        </div>
      </aside>

      <header className={`appbar ${onVoice ? "on-voice" : ""}`}>
        <Logo size={30} />
        <div className="appbar-title">
          <span className="appbar-brand">JARVIS</span>
          <span className="appbar-page">{onVoice ? "Voice" : title}</span>
        </div>
        {user?.photoURL ? (
          <img src={user.photoURL} alt="" className="avatar" referrerPolicy="no-referrer" />
        ) : (
          <span className="avatar fallback">{(user?.displayName ?? "A")[0]}</span>
        )}
        <button className="icon-btn" onClick={logOut} title="Sign out" aria-label="Sign out">
          <Icon name="logout" size={20} />
        </button>
      </header>

      <main className={`main ${onVoice ? "main-voice" : ""}`}>
        <Outlet />
      </main>

      <nav className={`tabbar ${onVoice ? "on-voice" : ""}`} aria-label="Main">
        {TABS.slice(0, 2).map(tab)}
        <NavLink to="/voice" className={({ isActive }) => `tabbar-item tab-jarvis ${isActive ? "active" : ""}`} aria-label="Talk to Jarvis">
          <span className="tab-jarvis-orb"><Logo size={38} /></span>
          <span>Jarvis</span>
        </NavLink>
        {TABS.slice(2).map(tab)}
      </nav>
    </div>
  );
}
