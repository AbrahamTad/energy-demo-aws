import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  fetchAuthSession,
  fetchUserAttributes,
  getCurrentUser,
  signOut,
} from "aws-amplify/auth";
import { Hub } from "aws-amplify/utils";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { cognitoConfig, sharedInMemoryStorage } from "./client";
import type { UserProfile } from "./client";
import { AuthContext, useAuth } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(Boolean(cognitoConfig));
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const signingOut = useRef(false);
  const refresh = useCallback(async () => {
    if (!cognitoConfig || signingOut.current) return;
    const current = ++generation.current;
    try {
      const session = await fetchAuthSession();
      if (!session.tokens?.accessToken) throw new Error("No session");
      const [user, attributes] = await Promise.all([
        getCurrentUser(),
        fetchUserAttributes(),
      ]);
      if (current === generation.current && !signingOut.current) {
        setProfile({
          subject: user.userId,
          email: attributes.email ?? "",
          emailVerified: attributes.email_verified === "true",
          name: attributes.name ?? "",
        });
        setNotice("");
      }
    } catch {
      if (current === generation.current) setProfile(null);
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, []);
  const logout = useCallback(async () => {
    if (signingOut.current) return;
    signingOut.current = true;
    ++generation.current;
    // Remove protected content immediately, including on network failure.
    setProfile(null);
    try {
      await signOut({ global: true });
      setNotice("You have been signed out.");
    } catch {
      setNotice(
        "Signed out of this page. We could not confirm sign-out on other devices; please try again when connected.",
      );
    } finally {
      await sharedInMemoryStorage.clear();
      ++generation.current;
      setProfile(null);
      setLoading(false);
      signingOut.current = false;
    }
  }, []);
  useEffect(() => {
    if (!cognitoConfig) return;
    const initialRead = window.setTimeout(() => {
      void refresh();
    }, 0);
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      if (
        payload.event === "signedOut" ||
        payload.event === "tokenRefresh_failure"
      ) {
        ++generation.current;
        setProfile(null);
        setLoading(false);
        if (payload.event === "tokenRefresh_failure")
          setNotice("Your session ended. Please sign in again.");
      }
      if (payload.event === "signedIn") void refresh();
    });
    const onFocus = () => {
      void refresh();
    };
    window.addEventListener("focus", onFocus);
    const interval = window.setInterval(onFocus, 60_000);
    const invalidate = () => {
      ++generation.current;
    };
    return () => {
      invalidate();
      clearTimeout(initialRead);
      unsubscribe();
      window.removeEventListener("focus", onFocus);
      clearInterval(interval);
    };
  }, [refresh]);
  return (
    <AuthContext.Provider
      value={{
        profile,
        loading,
        configured: Boolean(cognitoConfig),
        notice,
        refresh,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function RequireAuth() {
  const { profile, loading } = useAuth();
  const location = useLocation();
  if (loading)
    return (
      <div className="loading-page" role="status">
        Checking your session…
      </div>
    );
  return profile ? (
    <Outlet />
  ) : (
    <Navigate to="/login" replace state={{ from: location.pathname }} />
  );
}
