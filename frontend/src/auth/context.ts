import { createContext, useContext } from "react";
import type { UserProfile } from "./client";
export type AuthState = {
  profile: UserProfile | null;
  loading: boolean;
  configured: boolean;
  notice: string;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};
export const AuthContext = createContext<AuthState | null>(null);
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required");
  return value;
}
export function safeReturnPath(value: unknown) {
  return typeof value === "string" &&
    ["/dashboard", "/profile", "/settings"].includes(value)
    ? value
    : "/dashboard";
}
