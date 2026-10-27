import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { energyCsv, formatEnergy, parseEnergy } from "../lib/energy";
import type { EnergyRecord } from "../lib/energy";
import { Icon } from "./Icon";
import { EnergyContext, useEnergy } from "../lib/energy-context";
import type { EnergyState } from "../lib/energy-context";
import { sourceStyle } from "../lib/sources";

export function EnergyProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<EnergyState, "refresh">>({
    data: null,
    loading: true,
    error: "",
    fetchedAt: null,
  });
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(() => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    void (async () => {
      try {
        const response = await fetch("/api/energy", {
          signal: request.signal,
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok)
          throw new Error(
            response.status === 429
              ? "The service is busy. Wait a moment, then refresh."
              : "The energy service is unavailable. Please try again.",
          );
        const data = parseEnergy(await response.json());
        if (!request.signal.aborted)
          setState({ data, loading: false, error: "", fetchedAt: new Date() });
      } catch (error) {
        if (!request.signal.aborted)
          setState((previous) => ({
            ...previous,
            loading: false,
            error:
              error instanceof Error
                ? error.message
                : "Could not load energy data.",
          }));
      }
    })();
  }, []);
  const refresh = useCallback(() => {
    setState((previous) => ({ ...previous, loading: true, error: "" }));
    load();
  }, [load]);
  useEffect(() => {
    load();
    return () => controller.current?.abort();
  }, [load]);
  return (
    <EnergyContext.Provider value={{ ...state, refresh }}>
      {children}
    </EnergyContext.Provider>
  );
}

export function EnergyFeedback() {
  const { data, loading, error, refresh } = useEnergy();
  if (error)
    return (
      <div className="notice error" role="alert">
        <div>
          <strong>Energy data couldn’t be refreshed</strong>
          <p>
            {error}
            {data ? " The last fetched snapshot is shown below." : ""}
          </p>
        </div>
        <button
          className="button secondary"
          onClick={refresh}
          disabled={loading}
        >
          Try again
        </button>
      </div>
    );
  if (loading && !data)
    return (
      <div
        className="skeleton-grid"
        role="status"
        aria-label="Loading energy data"
      >
        {[0, 1, 2, 3].map((i) => (
          <div className="skeleton" key={i} />
        ))}
        <span className="sr-only">Loading energy data…</span>
      </div>
    );
  if (data?.records.length === 0)
    return (
      <div className="notice">
        <Icon name="leaf" />
        <div>
          <strong>No energy records yet</strong>
          <p>Refresh when your energy source has published a snapshot.</p>
        </div>
      </div>
    );
  return null;
}

export function EnergyCards() {
  const { data } = useEnergy();
  if (!data?.records.length) return null;
  const total = data.records.reduce((sum, r) => sum + r.production, 0);
  return (
    <div className="stats-grid">
      {data.records.map((record) => {
        const style = sourceStyle(record.source);
        return (
          <article className="stat-card" key={record.source}>
            <div className="stat-top">
              <span>{record.source} energy</span>
              <span
                className="source-icon"
                style={{ color: style.color, background: style.background }}
              >
                <Icon name={style.icon} />
              </span>
            </div>
            <p className="stat-value">
              {formatEnergy(record.production)}
              <span>kWh</span>
            </p>
            <div className="stat-foot">
              <span className="tiny-dot" style={{ background: style.color }} />
              {total ? Math.round((record.production / total) * 100) : 0}% of
              this snapshot
            </div>
          </article>
        );
      })}
    </div>
  );
}

export function ProductionChart({ records }: { records: EnergyRecord[] }) {
  const max = Math.max(...records.map((r) => r.production), 1);
  return (
    <figure className="bar-chart">
      <figcaption className="sr-only">
        Energy production by source in kilowatt-hours. Exact values are listed
        below.
      </figcaption>
      {records.map((record) => (
        <div className="bar-row" key={record.source}>
          <span>{record.source}</span>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${(record.production / max) * 100}%`,
                background: sourceStyle(record.source).color,
              }}
            />
          </div>
          <strong>
            {formatEnergy(record.production)} <small>kWh</small>
          </strong>
        </div>
      ))}
      <div className="chart-caption">
        Current source totals · no historical readings supplied
      </div>
    </figure>
  );
}

export function EnergyMix() {
  const { data } = useEnergy();
  if (!data?.records.length) return null;
  const total = data.records.reduce((sum, r) => sum + r.production, 0);
  let progress = 0;
  const gradient = total
    ? data.records
        .map((r) => {
          const start = progress;
          progress += (r.production / total) * 100;
          return `${sourceStyle(r.source).color} ${start}% ${progress}%`;
        })
        .join(",")
    : "var(--line) 0% 100%";
  return (
    <section className="panel mix-panel">
      <div className="panel-title">
        <h2>Energy mix</h2>
        <Icon name="leaf" />
      </div>
      <p className="muted">Every source, one clear picture.</p>
      <div
        className="donut"
        role="img"
        aria-label={`Total ${formatEnergy(total)} kWh; source shares listed below`}
        style={{ background: `conic-gradient(${gradient})` }}
      >
        <div>
          <span>Total energy</span>
          <strong>{formatEnergy(total)}</strong>
          <span>kWh</span>
        </div>
      </div>
      <ul className="mix-legend">
        {data.records.map((record) => (
          <li key={record.source}>
            <span>
              <i style={{ background: sourceStyle(record.source).color }} />
              {record.source}
            </span>
            <strong>
              {total ? ((record.production / total) * 100).toFixed(1) : 0}%
            </strong>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ExportButton() {
  const { data } = useEnergy();
  function download() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob([energyCsv(data.records)], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "energy-snapshot.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <button
      className="button secondary"
      onClick={download}
      disabled={!data?.records.length}
    >
      <Icon name="download" size={16} /> Export CSV
    </button>
  );
}
