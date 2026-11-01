import { fetchAuthSession } from "aws-amplify/auth";

export class AdminError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function adminRequest<T>(
  path: string,
  values?: object,
  signal?: AbortSignal,
): Promise<T> {
  const token = (await fetchAuthSession()).tokens?.accessToken?.toString();
  if (!token) throw new AdminError(401, "Sign in again to use admin.");
  const result = await fetch(`/api/admin/${path}`, {
    method: values ? "POST" : "GET",
    signal,
    cache: "no-store",
    credentials: "omit",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(values ? { "Content-Type": "application/json" } : {}),
    },
    body: values ? JSON.stringify(values) : undefined,
  });
  if (!result.ok) {
    const body = await result.json().catch(() => ({}));
    throw new AdminError(
      result.status,
      typeof body.error === "string"
        ? body.error
        : "Admin is temporarily unavailable.",
    );
  }
  return result.json() as Promise<T>;
}

export type AdminStatus = {
  checked_at: string;
  services: Record<string, string>;
  api_gateway: string;
  lambda: string;
  private_access: string;
  email_daily_limit: number;
};
export type AdminUser = { id: string; status: string; enabled: boolean };
export type AdminRecord = {
  source: string;
  production: number;
  unit: string;
  id?: string;
  measured_at?: string;
};
export type AdminPage = {
  users?: AdminUser[];
  records?: AdminRecord[];
  next_cursor: string | null;
};
export type EmailTest = {
  id: string;
  recipient: string;
  status: string;
  message_id: string;
  updated_at: string;
};
