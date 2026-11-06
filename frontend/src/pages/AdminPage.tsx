import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import { Link, useLocation } from "react-router-dom";
import { adminRequest, AdminError } from "../lib/admin";
import type { AdminPage as Page, AdminStatus, EmailTest } from "../lib/admin";
import "./admin.css";

import { CustomerMessages } from "./CustomerMessages";

const sections = [
  "Overview",
  "Users",
  "Energy records",
  "Email testing",
  "System status",
  "Customer messages",
] as const;
type Section = (typeof sections)[number];
type EmailDraft = {
  id: string;
  recipient: string;
  result: EmailTest | null;
  attempted: boolean;
};

export function AdminPage() {
  const location = useLocation();
  const [access, setAccess] = useState<
    "checking" | "verify" | "granted" | "denied"
  >("checking");
  const [error, setError] = useState("");
  const [challenge, setChallenge] = useState("");
  const [busy, setBusy] = useState(false);
  const [section, setSection] = useState<Section>(() =>
    location.pathname === "/admin/messages" ? "Customer messages" : "Overview",
  );
  // Keep the same request ID across tabs and access rechecks after focus changes.
  const [emailDraft, setEmailDraft] = useState<EmailDraft>(() => ({
    id: crypto.randomUUID(),
    recipient: "",
    result: null,
    attempted: false,
  }));
  const generation = useRef(0);
  const check = useCallback(async (signal?: AbortSignal) => {
    const attempt = ++generation.current;
    setAccess("checking");
    setError("");
    try {
      const result = await adminRequest<{ verified: boolean }>(
        "session",
        undefined,
        signal,
      );
      if (result?.verified !== true)
        throw new Error(
          "The admin service returned an invalid verification response.",
        );
      if (!signal?.aborted && attempt === generation.current)
        setAccess("granted");
    } catch (e) {
      if (signal?.aborted || attempt !== generation.current) return;
      setAccess(
        e instanceof AdminError && e.status === 428 ? "verify" : "denied",
      );
      setError(e instanceof Error ? e.message : "Admin is unavailable.");
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void check(controller.signal), 0);
    const focus = () => void check(controller.signal);
    window.addEventListener("focus", focus);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      window.removeEventListener("focus", focus);
    };
  }, [check]);
  const report = useCallback((e: unknown) => {
    setError(e instanceof Error ? e.message : "The request failed.");
    if (e instanceof AdminError && [401, 403, 428].includes(e.status)) {
      ++generation.current;
      setAccess(e.status === 428 ? "verify" : "denied");
      setChallenge("");
    }
  }, []);
  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true);
    setError("");
    const values = challenge
      ? { challenge, code: String(fields.get("code")) }
      : { password: String(fields.get("password")) };
    form.reset();
    try {
      const result = await adminRequest<{ challenge?: string }>(
        "session",
        values,
      );
      if (result.challenge) setChallenge(result.challenge);
      else {
        setChallenge("");
        await check();
      }
    } catch (e) {
      report(e);
      setChallenge("");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="admin-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">ENERGYDEMO / ADMINISTRATION</p>
          <h1>Admin workspace</h1>
          <p>Manage with clarity. Keep personal energy private.</p>
        </div>
        <span className="admin-badge">Cognito protected</span>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {access === "checking" && (
        <p role="status">Verifying current admin access…</p>
      )}
      {access === "denied" && (
        <div className="admin-panel">
          <h2>Admin access unavailable</h2>
          <p>
            Access requires current admin membership and a preferred
            authenticator MFA method.
          </p>
          <Link className="button secondary" to="/settings">
            Open security settings
          </Link>{" "}
          <button className="button secondary" onClick={() => void check()}>
            Check again
          </button>
        </div>
      )}
      {access === "verify" && (
        <div className="admin-panel admin-verification">
          <h2>Confirm admin access</h2>
          <p>
            Verify your password, then your authenticator code. Verification
            lasts up to 15 minutes for this session.
          </p>
          <form className="form" onSubmit={(e) => void verify(e)}>
            <label>
              {challenge ? "Authenticator code" : "Current password"}
              <input
                key={challenge || "password"}
                name={challenge ? "code" : "password"}
                type={challenge ? "text" : "password"}
                autoComplete={challenge ? "one-time-code" : "current-password"}
                inputMode={challenge ? "numeric" : undefined}
                pattern={challenge ? "[0-9]{6}" : undefined}
                maxLength={challenge ? 6 : 128}
                required
                disabled={busy}
              />
            </label>
            <button className="button primary" disabled={busy}>
              {busy
                ? "Verifying…"
                : challenge
                  ? "Verify authenticator"
                  : "Continue"}
            </button>
          </form>
        </div>
      )}
      {access === "granted" && (
        <>
          <nav className="admin-tabs" aria-label="Admin sections">
            {sections.map((name) => (
              <button
                key={name}
                aria-current={section === name ? "page" : undefined}
                onClick={() => {
                  setSection(name);
                  setError("");
                }}
              >
                {name}
              </button>
            ))}
          </nav>
          <div className="admin-privacy">
            <strong>Privacy by default</strong>
            <span>
              User directory is read-only. Personal records are limited to your
              own account.
            </span>
          </div>
          {section === "Customer messages" && <CustomerMessages />}
          {(section === "Overview" || section === "System status") && (
            <Status
              key={section}
              overview={section === "Overview"}
              report={report}
            />
          )}
          {section === "Users" && (
            <Records key="users" path="users" report={report} />
          )}
          {section === "Energy records" && <Energy report={report} />}
          {section === "Email testing" && (
            <Email
              report={report}
              draft={emailDraft}
              setDraft={setEmailDraft}
            />
          )}
        </>
      )}
    </section>
  );
}

function Status({
  overview,
  report,
}: {
  overview: boolean;
  report: (e: unknown) => void;
}) {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setStatus(null);
      try {
        const data = await adminRequest<AdminStatus>(
          "status",
          undefined,
          signal,
        );
        if (!signal?.aborted) setStatus(data);
      } catch (e) {
        if (!signal?.aborted) report(e);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [report],
  );
  useEffect(() => {
    const c = new AbortController();
    const timer = window.setTimeout(() => void refresh(c.signal), 0);
    return () => {
      window.clearTimeout(timer);
      c.abort();
    };
  }, [refresh]);
  return (
    <div className="admin-panel">
      <div className="admin-panel-heading">
        <h2>{overview ? "Your system at a glance" : "System status"}</h2>
        <button
          className="button secondary small"
          disabled={loading}
          onClick={() => void refresh()}
        >
          Refresh
        </button>
      </div>
      {loading && <p role="status">Checking AWS services…</p>}
      {status && (
        <>
          <div className="admin-stats">
            {Object.entries(status.services).map(([name, value]) => (
              <div className="admin-stat" key={name}>
                <span>{name.replaceAll("_", " ")}</span>
                <strong
                  className={
                    value === "unavailable" || value === "disabled"
                      ? "admin-warning"
                      : ""
                  }
                >
                  {value}
                </strong>
              </div>
            ))}
          </div>
          <dl className="admin-facts">
            <dt>API Gateway</dt>
            <dd>{status.api_gateway}</dd>
            <dt>Lambda</dt>
            <dd>{status.lambda}</dd>
            <dt>Private record access</dt>
            <dd>{status.private_access}</dd>
            <dt>Email safety limit</dt>
            <dd>{status.email_daily_limit} tests / UTC day</dd>
          </dl>
          <p className="admin-caption">
            Checked {new Date(status.checked_at).toLocaleString()}. Status
            reflects these live checks, not historical uptime.
          </p>
        </>
      )}
    </div>
  );
}

function Energy({ report }: { report: (e: unknown) => void }) {
  const [scope, setScope] = useState("public");
  return (
    <>
      <label className="admin-scope">
        Record collection{" "}
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="public">Public energy records</option>
          <option value="mine">My personal records</option>
        </select>
      </label>
      <Records key={scope} path={`records/${scope}`} report={report} />
    </>
  );
}

function Records({
  path,
  report,
}: {
  path: string;
  report: (e: unknown) => void;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([null]);
  const [loading, setLoading] = useState(true);
  const cursor = history[history.length - 1];
  useEffect(() => {
    const c = new AbortController();
    void adminRequest<Page>(
      path + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""),
      undefined,
      c.signal,
    )
      .then((data) => {
        if (!c.signal.aborted) setPage(data);
      })
      .catch((e) => {
        if (!c.signal.aborted) report(e);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [path, cursor, report]);
  const users = path === "users";
  const rows = users ? page?.users : page?.records;
  return (
    <div className="admin-panel">
      <div className="admin-panel-heading">
        <h2>{users ? "User directory" : "Energy records"}</h2>
        <span className="admin-badge">Read only</span>
      </div>
      <p className="admin-caption">
        {users
          ? "Account IDs and account status only. Names, email addresses and phone numbers are hidden."
          : "Public data or your own records. This view cannot select another account."}
      </p>
      {loading && <p role="status">Loading records…</p>}
      {rows && rows.length === 0 && <p>No records in this collection.</p>}
      {page && !!rows?.length && (
        <div className="admin-table-scroll">
          <table>
            <caption className="sr-only">
              {users ? "User directory" : "Energy records"}, page{" "}
              {history.length}
            </caption>
            <thead>
              <tr>
                {(users
                  ? ["Account ID", "Status", "Access"]
                  : ["Source", "Production", "Measured at"]
                ).map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users
                ? page.users?.map((u) => (
                    <tr key={u.id}>
                      <td>
                        <code>{u.id}</code>
                      </td>
                      <td>{u.status}</td>
                      <td>{u.enabled ? "Enabled" : "Disabled"}</td>
                    </tr>
                  ))
                : page.records?.map((r) => (
                    <tr key={r.id || r.source}>
                      <td>{r.source}</td>
                      <td>
                        {r.production.toLocaleString()} {r.unit}
                      </td>
                      <td>
                        {r.measured_at
                          ? new Date(r.measured_at).toLocaleString()
                          : "Public snapshot"}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="admin-pagination">
        <button
          className="button secondary small"
          disabled={loading || history.length === 1}
          onClick={() => {
            setLoading(true);
            setPage(null);
            setHistory((h) => h.slice(0, -1));
          }}
        >
          Previous
        </button>
        <span>Page {history.length}</span>
        <button
          className="button secondary small"
          disabled={loading || !page?.next_cursor}
          onClick={() => {
            if (page?.next_cursor) {
              setLoading(true);
              setPage(null);
              setHistory((h) => [...h, page.next_cursor]);
            }
          }}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function Email({
  report,
  draft,
  setDraft,
}: {
  report: (e: unknown) => void;
  draft: EmailDraft;
  setDraft: Dispatch<SetStateAction<EmailDraft>>;
}) {
  const [recipients, setRecipients] = useState<string[]>([]);
  const { id, recipient, result, attempted } = draft;
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    void adminRequest<{ recipients: string[] }>("email", undefined, c.signal)
      .then((data) => {
        if (!c.signal.aborted) {
          setRecipients(data.recipients);
          setDraft((d) =>
            d.recipient ? d : { ...d, recipient: data.recipients[0] || "" },
          );
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) report(e);
      });
    return () => c.abort();
  }, [report, setDraft]);
  async function send(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setDraft((d) => ({ ...d, attempted: true }));
    try {
      const value = await adminRequest<EmailTest>("email", { id, recipient });
      setDraft((d) => ({ ...d, result: value }));
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    try {
      const value = await adminRequest<EmailTest>(`email?id=${id}`);
      setDraft((d) => ({ ...d, result: value }));
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  const terminal =
    result &&
    ["delivered", "bounced", "complaint", "failed", "rejected"].includes(
      result.status,
    );
  return (
    <div className="admin-panel">
      <h2>Email delivery test</h2>
      <p>
        A fixed EnergyDemo test message, sent only to an approved SES-verified
        address. One test per admin per 60 seconds; ten across the account per
        UTC day.
      </p>
      <form className="form" onSubmit={(e) => void send(e)}>
        <label>
          Verified test recipient
          <select
            value={recipient}
            disabled={busy || attempted}
            onChange={(e) =>
              setDraft((d) => ({ ...d, recipient: e.target.value }))
            }
          >
            {recipients.map((address) => (
              <option key={address}>{address}</option>
            ))}
          </select>
        </label>
        <button
          className="button primary"
          disabled={busy || !recipient || !!result}
        >
          {busy
            ? "Please wait…"
            : attempted
              ? "Check same request safely"
              : "Send test email"}
        </button>
      </form>
      {attempted && !result && (
        <p className="admin-caption">
          The outcome may be pending. Keep this request ID: <code>{id}</code>.
          Retry uses the same ID.
        </p>
      )}
      {result && (
        <div className="admin-email-result" role="status">
          <h3>Delivery status: {result.status}</h3>
          <p>
            Request <code>{result.id}</code>
          </p>
          {result.message_id && (
            <p>
              SES message <code>{result.message_id}</code>
            </p>
          )}
          <p>
            Accepted means SES queued the message. Delivered means the recipient
            server accepted it; inbox placement is not guaranteed. Unknown
            outcomes are never automatically resent.
          </p>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            Refresh delivery status
          </button>
          {terminal && (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => {
                setDraft((d) => ({
                  ...d,
                  id: crypto.randomUUID(),
                  result: null,
                  attempted: false,
                }));
              }}
            >
              Start a new test
            </button>
          )}
        </div>
      )}
    </div>
  );
}
