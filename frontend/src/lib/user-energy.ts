import { fetchAuthSession } from "aws-amplify/auth";

export type UserEnergyRecord = {
  id: string;
  source: string;
  production: number;
  unit: "kWh";
  measured_at: string;
  updated_at: string;
};
export type RecordValues = Pick<
  UserEnergyRecord,
  "source" | "production" | "unit" | "measured_at"
>;
export type RecordPage = {
  records: UserEnergyRecord[];
  next_cursor: string | null;
};
export class RecordApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
const isId = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);

export function parseUserRecord(value: unknown): UserEnergyRecord {
  if (!value || typeof value !== "object")
    throw new Error("The record service returned invalid data.");
  const r = value as UserEnergyRecord;
  if (
    !isId(r.id) ||
    typeof r.source !== "string" ||
    !r.source.trim() ||
    r.source.length > 64 ||
    typeof r.production !== "number" ||
    !Number.isFinite(r.production) ||
    r.production < 0 ||
    r.production > 1e9 ||
    r.unit !== "kWh" ||
    typeof r.measured_at !== "string" ||
    !Number.isFinite(Date.parse(r.measured_at)) ||
    typeof r.updated_at !== "string" ||
    !Number.isFinite(Date.parse(r.updated_at))
  )
    throw new Error("The record service returned invalid data.");
  return {
    id: r.id,
    source: r.source,
    production: r.production,
    unit: r.unit,
    measured_at: r.measured_at,
    updated_at: r.updated_at,
  };
}

async function request(
  path: string,
  method = "GET",
  values?: RecordValues,
  signal?: AbortSignal,
) {
  const session = await fetchAuthSession();
  const token = session.tokens?.accessToken?.toString();
  if (!token)
    throw new RecordApiError(
      401,
      "Your session ended. Sign in again to access your records.",
    );
  const result = await fetch("/api/me/energy" + path, {
    method,
    signal,
    cache: "no-store",
    credentials: "omit",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(values ? { "Content-Type": "application/json" } : {}),
    },
    body: values ? JSON.stringify(values) : undefined,
  });
  if (!result.ok) {
    const messages: Record<number, string> = {
      401: "Your session ended. Sign out and sign in again to access your records.",
      403: "Your session is not authorized for this record service.",
      404: "Record not found. It may have been removed.",
      429: "Too many requests. Wait a moment and try again.",
    };
    let message =
      messages[result.status] ??
      "The record service is temporarily unavailable. Please try again.";
    if (result.status === 400) {
      const payload = await result.json().catch(() => ({}));
      message =
        typeof payload.error === "string"
          ? payload.error
          : "Check your record values.";
    }
    throw new RecordApiError(result.status, message);
  }
  return result.status === 204 ? null : await result.json();
}

export async function listUserRecords(
  cursor: string | null = null,
  signal?: AbortSignal,
): Promise<RecordPage> {
  if (cursor && !isId(cursor)) throw new Error("Invalid page cursor.");
  const page = await request(
    cursor ? `?cursor=${encodeURIComponent(cursor)}` : "",
    "GET",
    undefined,
    signal,
  );
  if (
    !page ||
    !Array.isArray(page.records) ||
    (page.next_cursor !== null && !isId(page.next_cursor))
  )
    throw new Error("The record service returned an invalid page.");
  return {
    records: page.records.map(parseUserRecord),
    next_cursor: page.next_cursor,
  };
}
export async function saveUserRecord(values: RecordValues, id?: string) {
  if (id && !isId(id)) throw new Error("Invalid record ID.");
  // Explicit field allowlist: never send sub, owner, email, or arbitrary fields.
  const payload = {
    source: values.source,
    production: values.production,
    unit: "kWh" as const,
    measured_at: values.measured_at,
  };
  return parseUserRecord(
    await request(id ? `/${id}` : "", id ? "PUT" : "POST", payload),
  );
}
export async function deleteUserRecord(id: string) {
  if (!isId(id)) throw new Error("Invalid record ID.");
  await request(`/${id}`, "DELETE");
}
