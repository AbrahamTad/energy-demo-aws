import { Component } from "react";
import type { ReactNode } from "react";
import { HashRouter, Link, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth } from "./auth/AuthProvider";
import { EnergyProvider } from "./components/Energy";
import { Layout } from "./components/Layout";
import { ThemeProvider } from "./components/Theme";
import { EnergyPage, HomePage, UserDashboardPage } from "./pages/EnergyPages";
import {
  LoginPage,
  RegisterPage,
  ResetPasswordPage,
  VerifyPage,
} from "./pages/AuthPages";
import { ProfilePage, SettingsPage } from "./pages/AccountPages";

class AppErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="error-page">
        <h1>Let’s try that again.</h1>
        <p>
          Something interrupted this page. Reload to return to your workspace.
        </p>
        <button
          className="button primary"
          onClick={() => window.location.reload()}
        >
          Reload page
        </button>
      </main>
    ) : (
      this.props.children
    );
  }
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="energy" element={<EnergyPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="verify" element={<VerifyPage />} />
        <Route path="reset-password" element={<ResetPasswordPage />} />
        <Route element={<RequireAuth />}>
          <Route path="dashboard" element={<UserDashboardPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route
          path="*"
          element={
            <section className="error-page">
              <p className="eyebrow">A SMALL DETOUR</p>
              <h1>Page not found.</h1>
              <p>Let’s get you back to somewhere brighter.</p>
              <Link to="/" className="button primary">
                Back to home
              </Link>
            </section>
          }
        />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <AppErrorBoundary>
      <HashRouter>
        <ThemeProvider>
          <AuthProvider>
            <EnergyProvider>
              <AppRoutes />
            </EnergyProvider>
          </AuthProvider>
        </ThemeProvider>
      </HashRouter>
    </AppErrorBoundary>
  );
}
