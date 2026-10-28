import { NavLink, Outlet } from "react-router-dom";
import { logOut, useUser } from "../lib/auth";
import Icon, { Logo, type IconName } from "./Icon";

const NAV: { to: string; label: string; icon: IconName; soon?: boolean }[] = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/campaigns", label: "Find hotels", icon: "campaign" },
  { to: "/leads", label: "Leads", icon: "leads" },
  { to: "/chat", label: "Ask Jarvis", icon: "chat" },
  { to: "/settings", label: "Settings", icon: "settings", soon: true },
];

export default function Layout() {
  const user = useUser();

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

      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
