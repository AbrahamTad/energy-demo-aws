import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/context";
import { useTheme } from "../lib/theme";
import { Icon } from "./Icon";

const navigation = [
  { to: "/", label: "Home", icon: "home" },
  { to: "/energy", label: "Energy dashboard", icon: "chart" },
  { to: "/dashboard", label: "My dashboard", icon: "user" },
  { to: "/profile", label: "Profile", icon: "shield" },
  { to: "/settings", label: "Settings", icon: "settings" },
] as const;

export function Layout() {
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const { profile, logout, notice } = useAuth();
  const { dark, setTheme } = useTheme();
  const { pathname } = useLocation();
  const menuOpen = menuPath === pathname;
  const setMenuOpen = (open: boolean) => setMenuPath(open ? pathname : null);
  const title =
    navigation.find((item) => item.to === pathname)?.label ?? "Your account";
  useEffect(() => {
    document.title = `${title} · EnergyDemo`;
    document
      .querySelector<HTMLElement>("#main-content")
      ?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [pathname, title]);
  useEffect(() => {
    if (!menuOpen) return;
    const panel = document.querySelector<HTMLElement>("#sidebar");
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel?.querySelector<HTMLElement>("a, button")?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuPath(null);
      if (event.key === "Tab") {
        const focusable = panel?.querySelectorAll<HTMLElement>("a, button");
        const first = focusable?.[0];
        const last = focusable?.[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("keydown", close);
      document.body.style.overflow = previousOverflow;
      document
        .querySelector<HTMLElement>(".mobile-menu")
        ?.focus({ preventScroll: true });
    };
  }, [menuOpen]);
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.querySelector<HTMLElement>("#main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      {menuOpen && (
        <button
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <aside
        className={`sidebar ${menuOpen ? "open" : ""}`}
        aria-label="Main navigation"
        id="sidebar"
      >
        <button
          className="icon-button sidebar-close"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        >
          <Icon name="close" />
        </button>
        <Link to="/" className="brand">
          <span className="brand-icon">
            <Icon name="bolt" size={23} />
          </span>
          energy<span className="brand-light">demo</span>
          <span className="brand-period">.</span>
        </Link>
        <div className="workspace">
          <span className="workspace-icon">
            <Icon name="leaf" size={18} />
          </span>
          <div>
            <strong>Energy workspace</strong>
            <span>Small steps. Better energy.</span>
          </div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {navigation.map((item) => (
            <NavLink to={item.to} end={item.to === "/"} key={item.to}>
              <Icon name={item.icon} size={19} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Icon name="leaf" size={24} />
            <strong>A clearer view of energy.</strong>
            <p>
              Understand your sources.
              <br />
              Make every kilowatt count.
            </p>
            <Link to="/energy">
              Explore your energy <Icon name="arrow" size={16} />
            </Link>
          </div>
          <div className="sidebar-footer">
            <span className="tiny-dot" />
            Energy, connected.
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-title">
            <button
              className="icon-button mobile-menu"
              aria-label={menuOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={menuOpen}
              aria-controls="sidebar"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <Icon name={menuOpen ? "close" : "menu"} />
            </button>
            <span>
              Workspace <span className="breadcrumb-slash">/</span>{" "}
              <strong>{title}</strong>
            </span>
          </div>
          <div className="header-actions">
            <button
              className="icon-button"
              aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
              onClick={() => setTheme(dark ? "light" : "dark")}
            >
              <Icon name={dark ? "sun" : "moon"} size={19} />
            </button>
            <span className="header-divider" />
            {profile ? (
              <>
                <Link className="user-link" to="/profile">
                  <span className="avatar">
                    {(profile.name || profile.email).slice(0, 1).toUpperCase()}
                  </span>
                  <span>{profile.name || "My account"}</span>
                </Link>
                <button
                  className="icon-button"
                  onClick={() => void logout()}
                  aria-label="Sign out"
                >
                  <Icon name="logout" size={19} />
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="header-login">
                  Log in
                </Link>
                <Link className="button primary small" to="/register">
                  Get started <Icon name="arrow" size={15} />
                </Link>
              </>
            )}
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          <Outlet />
        </main>
        <footer className="page-footer">
          <span>
            EnergyDemo <span aria-hidden="true">·</span> A little more clarity.
            A little less impact.
          </span>
          <Link to="/settings">
            Preferences <Icon name="settings" size={14} />
          </Link>
        </footer>
      </div>
    </div>
  );
}
