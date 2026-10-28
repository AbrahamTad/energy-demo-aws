import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../auth/context";
import {
  deleteUserRecord,
  listUserRecords,
  RecordApiError,
  saveUserRecord,
} from "../lib/user-energy";
import type { UserEnergyRecord } from "../lib/user-energy";
import { formatEnergy } from "../lib/energy";
import { ProductionChart } from "./Energy";
import { Field } from "./Forms";
import { Icon } from "./Icon";

// The parent is keyed by Cognito sub: logout/account changes discard all rows,
// errors, pending fetches and editing state rather than sharing a public cache.
export function UserRecords() {
  const { profile } = useAuth();
  const [records, setRecords] = useState<UserEnergyRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [editing, setEditing] = useState<UserEnergyRecord | null>(null);
  const [source, setSource] = useState("");
  const [production, setProduction] = useState("");
  const [measured, setMeasured] = useState(() =>
    new Date().toISOString().slice(0, 16),
  );
  const request = useRef<AbortController | null>(null);
  const owner = profile?.subject;
  const handleError = useCallback((failure: unknown) => {
    if (
      failure instanceof RecordApiError &&
      [401, 403].includes(failure.status)
    ) {
      setRecords([]);
      setCursor(null);
      setEditing(null);
      setSource("");
      setProduction("");
      setSuccess("");
    }
    setError(
      failure instanceof Error
        ? failure.message
        : "Could not load your records.",
    );
  }, []);
  const load = useCallback(
    async (after: string | null = null) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      try {
        const page = await listUserRecords(after, controller.signal);
        if (controller.signal.aborted) return;
        setRecords((previous) =>
          after
            ? Array.from(
                new Map(
                  [...previous, ...page.records].map((r) => [r.id, r]),
                ).values(),
              )
            : page.records,
        );
        setCursor(page.next_cursor);
        setError("");
      } catch (failure) {
        if (!controller.signal.aborted) handleError(failure);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [handleError],
  );
  useEffect(() => {
    const initialRead = window.setTimeout(() => {
      if (owner) void load();
    }, 0);
    return () => {
      clearTimeout(initialRead);
      request.current?.abort();
    };
  }, [load, owner]);
  function reset() {
    setEditing(null);
    setSource("");
    setProduction("");
    setMeasured(new Date().toISOString().slice(0, 16));
  }
  function edit(record: UserEnergyRecord) {
    setEditing(record);
    setSource(record.source);
    setProduction(String(record.production));
    setMeasured(new Date(record.measured_at).toISOString().slice(0, 16));
    setError("");
    setSuccess("");
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const amount = Number(production);
    if (
      !source.trim() ||
      !Number.isFinite(amount) ||
      amount < 0 ||
      amount > 1e9 ||
      !Number.isFinite(Date.parse(measured + "Z"))
    ) {
      setError("Check your source, production, and timestamp.");
      return;
    }
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const record = await saveUserRecord(
        {
          source: source.trim(),
          production: amount,
          unit: "kWh",
          measured_at: new Date(measured + "Z").toISOString(),
        },
        editing?.id,
      );
      setRecords((previous) =>
        editing
          ? previous.map((r) => (r.id === record.id ? record : r))
          : [record, ...previous],
      );
      reset();
      setSuccess("Record saved. Only your account can access it.");
    } catch (failure) {
      handleError(failure);
    } finally {
      setBusy(false);
    }
  }
  async function remove(record: UserEnergyRecord) {
    if (busy || !window.confirm(`Delete your ${record.source} record?`)) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await deleteUserRecord(record.id);
      setRecords((previous) => previous.filter((r) => r.id !== record.id));
      if (editing?.id === record.id) reset();
      setSuccess("Record deleted.");
    } catch (failure) {
      handleError(failure);
    } finally {
      setBusy(false);
    }
  }
  const totals = Array.from(
    records.reduce(
      (map, r) => map.set(r.source, (map.get(r.source) ?? 0) + r.production),
      new Map<string, number>(),
    ),
    ([source, production]) => ({ source, production, unit: "kWh" as const }),
  );
  return (
    <section aria-label="Your private energy records">
      <div className="section-heading">
        <div>
          <h2>Your energy records</h2>
          <p className="muted">
            Private to your account. Public energy data is stored separately.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={loading || busy}
          onClick={() => {
            setLoading(true);
            void load();
          }}
        >
          <Icon name="refresh" size={16} />
          Refresh records
        </button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {success && (
        <p className="form-success" role="status">
          {success}
        </p>
      )}
      <div className="settings-grid">
        <section className="panel">
          <h2>{editing ? "Edit energy record" : "Add energy record"}</h2>
          <form className="form" onSubmit={save}>
            <fieldset disabled={busy || loading}>
              <Field
                label="Energy source"
                name="source"
                required
                maxLength={64}
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="e.g. Rooftop solar"
              />
              <Field
                label="Production (kWh)"
                name="production"
                type="number"
                required
                min={0}
                max={1e9}
                step={0.001}
                value={production}
                onChange={(e) => setProduction(e.target.value)}
              />
              <Field
                label="Recorded at (UTC)"
                name="measured_at"
                type="datetime-local"
                required
                min="2000-01-01T00:00"
                max="2100-12-31T23:59"
                value={measured}
                onChange={(e) => setMeasured(e.target.value)}
              />
              <button className="button primary">
                {busy ? "Saving…" : editing ? "Save record" : "Add record"}
              </button>
              {editing && (
                <button
                  type="button"
                  className="button secondary"
                  onClick={reset}
                >
                  Cancel edit
                </button>
              )}
            </fieldset>
          </form>
        </section>
        <section className="panel">
          <h2>Loaded readings by source</h2>
          <p className="muted">
            Sum of the {records.length} records currently loaded. Not a live
            power measurement.
          </p>
          {totals.length ? (
            <ProductionChart records={totals} />
          ) : (
            <p className="empty-table">
              {loading
                ? "Loading your records…"
                : "No readings yet. Add your first record to get started."}
            </p>
          )}
        </section>
      </div>
      <section className="panel table-panel">
        <h2>Your saved readings</h2>
        {loading && (
          <p role="status" className="muted">
            Loading records…
          </p>
        )}
        <div className="table-scroll">
          <table>
            <caption className="sr-only">
              Private energy records for your account
            </caption>
            <thead>
              <tr>
                <th>Source</th>
                <th>Production</th>
                <th>Recorded at (UTC)</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id}>
                  <th scope="row">{record.source}</th>
                  <td>{formatEnergy(record.production)} kWh</td>
                  <td>
                    {new Date(record.measured_at)
                      .toISOString()
                      .slice(0, 16)
                      .replace("T", " ")}
                  </td>
                  <td>
                    <div className="record-actions">
                      <button
                        className="button secondary small"
                        disabled={busy || loading}
                        onClick={() => edit(record)}
                        aria-label={`Edit ${record.source} record`}
                      >
                        Edit
                      </button>
                      <button
                        className="button secondary small"
                        disabled={busy || loading}
                        onClick={() => void remove(record)}
                        aria-label={`Delete ${record.source} record`}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cursor && (
          <button
            className="button secondary"
            disabled={loading || busy}
            onClick={() => {
              setLoading(true);
              void load(cursor);
            }}
          >
            Load more records
          </button>
        )}
      </section>
    </section>
  );
}
