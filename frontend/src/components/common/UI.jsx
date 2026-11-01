import { AlertCircle, CheckCircle2, LoaderCircle, SearchX } from "lucide-react";

const severityStyles = {
  high: "bg-rose-50 text-rose-700 ring-rose-200",
  critical: "bg-rose-50 text-rose-700 ring-rose-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-blue-50 text-blue-700 ring-blue-200",
};
const statusStyles = {
  pending: "bg-amber-50 text-amber-700",
  draft: "bg-slate-100 text-slate-600",
  in_review: "bg-violet-50 text-violet-700",
  approved: "bg-emerald-50 text-emerald-700",
  changes_requested: "bg-rose-50 text-rose-700",
  open: "bg-slate-100 text-slate-600",
  current: "bg-emerald-50 text-emerald-700",
  expiring_soon: "bg-amber-50 text-amber-700",
  review_overdue: "bg-rose-50 text-rose-700",
  expired: "bg-rose-50 text-rose-700",
  not_yet_valid: "bg-amber-50 text-amber-700",
  inactive: "bg-slate-100 text-slate-600",
  rejected: "bg-rose-50 text-rose-700",
};

export function Badge({ children, tone = "neutral" }) {
  const style = tone === "severity" ? severityStyles[String(children).toLowerCase()] : tone === "status" ? statusStyles[String(children).toLowerCase()] : "bg-slate-100 text-slate-600";
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${style || statusStyles.pending} ${tone === "severity" ? "ring-1 ring-inset" : ""}`}>{String(children || "unknown").replaceAll("_", " ")}</span>;
}

export function PageHeader({ eyebrow, title, description, action }) {
  return <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
    <div><p className="eyebrow mb-2">{eyebrow}</p><h1 className="text-2xl font-bold tracking-tight text-ink-900 sm:text-[28px]">{title}</h1>{description && <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>}</div>
    {action && <div className="shrink-0">{action}</div>}
  </div>;
}

export function LoadingState({ label = "Loading..." }) {
  return <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-slate-500" role="status"><LoaderCircle className="h-4 w-4 animate-spin" />{label}</div>;
}
export function ErrorState({ message, onRetry }) {
  return <div className="card flex flex-col items-center px-5 py-10 text-center"><AlertCircle className="mb-3 h-8 w-8 text-rose-500" /><h3 className="font-semibold text-slate-800">We couldn't load this data</h3><p className="mt-2 max-w-md text-sm text-slate-500">{message}</p>{onRetry && <button onClick={onRetry} className="btn-secondary mt-4">Try again</button>}</div>;
}
export function EmptyState({ title = "Nothing here yet", description = "When data is available, it will appear here.", icon: Icon = SearchX }) {
  return <div className="flex flex-col items-center px-5 py-12 text-center"><Icon className="mb-3 h-8 w-8 text-slate-300" /><h3 className="font-semibold text-slate-700">{title}</h3><p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p></div>;
}
export function SuccessMessage({ children }) {
  return <div role="status" className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />{children}</div>;
}
export function ErrorMessage({ children }) {
  return <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{children}</div>;
}
