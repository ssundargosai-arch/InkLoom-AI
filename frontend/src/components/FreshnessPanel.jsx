import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Clock3, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../services/api";
import {
  EmptyState,
  ErrorMessage,
  LoadingState,
} from "./common/UI";

function alertHref(alert) {
  if (alert.resource_type === "source") {
    return `/sources?source_id=${encodeURIComponent(alert.resource_id)}#source-${encodeURIComponent(alert.resource_id)}`;
  }
  return `/guidelines#guideline-${encodeURIComponent(alert.resource_id)}`;
}

function friendlyAlertType(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

export default function FreshnessPanel({ resourceType, canRun = false }) {
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setOverview(await api.freshnessOverview());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runCheck = async () => {
    setRunning(true);
    setError("");
    try {
      await api.runFreshnessCheck();
      await load();
    } catch (err) {
      const message = errorMessage(err);
      await load();
      setError(message);
    } finally {
      setRunning(false);
    }
  };

  const alerts = (overview?.alerts || []).filter(
    (alert) => alert.resource_type === resourceType,
  );
  const resolvedAlerts = (overview?.recent_alerts || []).filter(
    (alert) =>
      alert.resource_type === resourceType && alert.status === "resolved",
  );
  const lastRun = overview?.last_run;

  return (
    <section className="card mb-5 p-4 sm:p-5" aria-labelledby={`${resourceType}-freshness-title`}>
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <div className="flex items-center gap-2">
            <Clock3 size={17} className="text-ink-600" />
            <h2 id={`${resourceType}-freshness-title`} className="font-semibold text-ink-900">
              Freshness monitoring
            </h2>
          </div>
          {lastRun && (
            <p className="mt-1 text-xs text-slate-500">
              Last check: {new Date(lastRun.completed_at || lastRun.started_at).toLocaleString()}
              {" · "}{lastRun.status}
              {" · "}{lastRun.alerts_created} new alert{lastRun.alerts_created === 1 ? "" : "s"}
            </p>
          )}
        </div>
        {canRun && (
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 text-xs"
            disabled={running}
            onClick={runCheck}
          >
            <RefreshCw size={14} className={running ? "animate-spin" : ""} />
            {running ? "Checking…" : "Run freshness check"}
          </button>
        )}
      </div>
      {error && <div className="mt-3"><ErrorMessage>{error}</ErrorMessage></div>}
      {lastRun?.status === "failed" && lastRun.error && (
        <div className="mt-3"><ErrorMessage>{lastRun.error}</ErrorMessage></div>
      )}
      {loading ? (
        <LoadingState label="Loading freshness status…" />
      ) : alerts.length ? (
        <ul className="mt-3 divide-y divide-amber-100 rounded-lg border border-amber-100 bg-amber-50/60">
          {alerts.map((alert) => (
            <li key={alert.id} className="flex items-start gap-2 p-3">
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-700" />
              <div className="min-w-0 text-sm">
                <Link className="font-semibold text-ink-800 underline" to={alertHref(alert)}>
                  {alert.resource_name}
                </Link>
                <p className="text-xs text-slate-600">
                  {friendlyAlertType(alert.alert_type)} · {alert.message}
                </p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2">
          <EmptyState
            title={lastRun ? "No freshness alerts" : "No freshness check has run yet"}
            description={
              lastRun
                ? "Active records are within their validity and review windows."
                : "Run a manual check or wait for the scheduled check to evaluate record validity."
            }
          />
        </div>
      )}
      {!canRun && (
        <p className="mt-2 text-xs text-slate-500">
          Only Admins can start a manual freshness check.
        </p>
      )}
      {!!resolvedAlerts.length && (
        <details className="mt-3 text-xs text-slate-500">
          <summary className="cursor-pointer">Resolved alert history ({resolvedAlerts.length})</summary>
          <ul className="mt-2 space-y-1">
            {resolvedAlerts.slice(0, 10).map((alert) => (
              <li key={alert.id}>
                {alert.resource_name} · {friendlyAlertType(alert.alert_type)}
                {alert.resolved_at ? ` · Resolved ${new Date(alert.resolved_at).toLocaleString()}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
