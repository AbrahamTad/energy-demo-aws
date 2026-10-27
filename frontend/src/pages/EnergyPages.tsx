import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/context";
import {
  EnergyCards,
  EnergyFeedback,
  EnergyMix,
  ExportButton,
  ProductionChart,
} from "../components/Energy";
import { useEnergy } from "../lib/energy-context";
import { sourceStyle } from "../lib/sources";
import { Icon } from "../components/Icon";
import { formatEnergy } from "../lib/energy";

function SnapshotHeader() {
  const { fetchedAt, loading, refresh, error } = useEnergy();
  return (
    <div className="snapshot-toolbar">
      <span className={`status-pill ${error ? "warning" : ""}`}>
        <span className="tiny-dot" />
        {error
          ? "Refresh needed"
          : loading
            ? "Connecting"
            : fetchedAt
              ? "Snapshot connected"
              : "Not connected"}
      </span>
      <span className="muted fetched-at">
        {fetchedAt
          ? `Fetched at ${fetchedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
          : "Waiting for energy data"}
      </span>
      <button
        className="icon-button"
        aria-label="Refresh energy data"
        disabled={loading}
        onClick={refresh}
      >
        <Icon name="refresh" size={17} />
      </button>
    </div>
  );
}

function ProductionPanel({ filter = false }: { filter?: boolean }) {
  const { data } = useEnergy();
  const [selected, setSelected] = useState("All sources");
  const records =
    data?.records.filter(
      (r) => selected === "All sources" || r.source === selected,
    ) ?? [];
  return (
    <section className="panel production-panel">
      <div className="panel-title">
        <div>
          <h2>Production by source</h2>
          <p className="muted">A snapshot of your energy landscape.</p>
        </div>
        {filter && (
          <select
            aria-label="Filter energy source"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option>All sources</option>
            {data?.records.map((r) => (
              <option key={r.source}>{r.source}</option>
            ))}
          </select>
        )}
      </div>
      {records.length ? (
        <ProductionChart records={records} />
      ) : (
        <div className="chart-empty">
          Your source breakdown will appear here.
        </div>
      )}
      <div className="panel-bottom">
        <span>
          <Icon name="shield" size={15} /> Values returned by the energy service
        </span>
        <span>kWh</span>
      </div>
    </section>
  );
}

export function HomePage() {
  const { data } = useEnergy();
  const total = data?.records.reduce((sum, r) => sum + r.production, 0);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR ENERGY, AT A GLANCE</p>
          <h1>A brighter perspective.</h1>
          <p className="page-description">
            Good energy starts with understanding where it comes from.
          </p>
        </div>
        <SnapshotHeader />
      </div>
      <section className="welcome-banner">
        <div>
          <span className="banner-tag">
            <Icon name="leaf" size={15} /> A more thoughtful energy future
          </span>
          <h2>
            Small insights.
            <br />
            Meaningful change.
          </h2>
          <p>
            Bring your energy sources into focus.
            <br />
            One connected view, from solar to storage.
          </p>
          <Link className="button lime" to="/energy">
            Explore dashboard <Icon name="arrow" size={17} />
          </Link>
        </div>
        <div className="energy-orbit" aria-hidden="true">
          <div className="orbit-ring ring-one" />
          <div className="orbit-ring ring-two" />
          <div className="orbit-center">
            <Icon name="bolt" size={50} />
          </div>
          <span className="orbit-node orbit-sun">
            <Icon name="sun" size={26} />
          </span>
          <span className="orbit-node orbit-wind">
            <Icon name="wind" size={25} />
          </span>
          <span className="orbit-node orbit-water">
            <Icon name="water" size={23} />
          </span>
          <span className="orbit-label">POWERED BY POSSIBILITY</span>
        </div>
      </section>
      <div className="section-heading">
        <div>
          <h2>Your energy overview</h2>
          <p className="muted">
            {total === undefined
              ? "Connect to your source snapshot."
              : `${formatEnergy(total)} kWh across ${data?.records.length} energy sources.`}
          </p>
        </div>
        <Link className="text-link" to="/energy">
          View dashboard <Icon name="arrow" size={16} />
        </Link>
      </div>
      <EnergyFeedback />
      <EnergyCards />
      <div className="dashboard-grid">
        <ProductionPanel />
        <EnergyMix />
      </div>
      <section className="account-callout">
        <div className="callout-icon">
          <Icon name="shield" size={27} />
        </div>
        <div>
          <h2>Your energy. Your space.</h2>
          <p className="muted">
            Create an account to manage your profile and account security.
          </p>
        </div>
        <Link to="/register" className="button secondary">
          Create an account <Icon name="arrow" size={16} />
        </Link>
      </section>
    </>
  );
}

export function EnergyPage() {
  const { data } = useEnergy();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">MEASURE. UNDERSTAND. MOVE FORWARD.</p>
          <h1>Energy dashboard</h1>
          <p className="page-description">
            Your sources, brought together in one place.
          </p>
        </div>
        <ExportButton />
      </div>
      <SnapshotHeader />
      <EnergyFeedback />
      <EnergyCards />
      <div className="dashboard-grid">
        <ProductionPanel filter />
        <EnergyMix />
      </div>
      <section className="panel table-panel">
        <div className="panel-title">
          <div>
            <h2>Source details</h2>
            <p className="muted">
              Current readings from your connected energy service.
            </p>
          </div>
          <span className="subtle-badge">
            {data?.records.length ?? 0} sources
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">
              Energy source values for the current snapshot
            </caption>
            <thead>
              <tr>
                <th scope="col">Energy source</th>
                <th scope="col">Production</th>
                <th scope="col">Share of snapshot</th>
                <th scope="col">Unit</th>
              </tr>
            </thead>
            <tbody>
              {data?.records.map((r) => {
                const total = data.records.reduce(
                  (sum, record) => sum + record.production,
                  0,
                );
                return (
                  <tr key={r.source}>
                    <th scope="row">
                      <span className="table-source">
                        <span
                          className="source-icon"
                          style={{
                            background: sourceStyle(r.source).background,
                            color: sourceStyle(r.source).color,
                          }}
                        >
                          <Icon name={sourceStyle(r.source).icon} size={17} />
                        </span>
                        {r.source}
                      </span>
                    </th>
                    <td>{formatEnergy(r.production)}</td>
                    <td>
                      {total ? ((r.production / total) * 100).toFixed(1) : 0}%
                    </td>
                    <td>kWh</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!data?.records.length && (
          <p className="empty-table">No readings available.</p>
        )}
      </section>
    </>
  );
}

export function UserDashboardPage() {
  const { profile } = useAuth();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR PERSONAL WORKSPACE</p>
          <h1>Welcome{profile?.name ? `, ${profile.name}` : " back"}.</h1>
          <p className="page-description">
            A clear view of your account and connected energy.
          </p>
        </div>
        <SnapshotHeader />
      </div>
      <div className="account-summary">
        <section className="panel">
          <span className="feature-icon">
            <Icon name="user" />
          </span>
          <h2>Your profile</h2>
          <p className="muted">{profile?.email}</p>
          <Link className="text-link" to="/profile">
            Manage profile <Icon name="arrow" size={16} />
          </Link>
        </section>
        <section className="panel">
          <span className="feature-icon">
            <Icon name="shield" />
          </span>
          <h2>Account security</h2>
          <p className="muted">
            Email {profile?.emailVerified ? "verified" : "verification needed"}{" "}
            · Secure session
          </p>
          <Link className="text-link" to="/settings">
            Security settings <Icon name="arrow" size={16} />
          </Link>
        </section>
      </div>
      <div className="section-heading">
        <div>
          <h2>Connected energy</h2>
          <p className="muted">
            The shared source snapshot. Personal readings will appear when a
            data source is connected.
          </p>
        </div>
        <Link to="/energy" className="text-link">
          Open dashboard <Icon name="arrow" size={16} />
        </Link>
      </div>
      <EnergyFeedback />
      <EnergyCards />
      <div className="dashboard-grid">
        <ProductionPanel />
        <EnergyMix />
      </div>
    </>
  );
}
