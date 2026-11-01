import { useEffect, useState } from "react";
import { ArrowRight, CircleAlert, FileCheck2, FilePlus2, ShieldAlert, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { api, errorMessage, unwrapList } from "../services/api";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/common/UI";
import { getTimeBasedGreeting } from "../utils/timeGreeting";

const Metric = ({ label, value, note, icon: Icon, color }) => <div className="card p-5"><div className="flex items-start justify-between"><div><p className="text-sm font-medium text-slate-500">{label}</p><p className="mt-3 text-3xl font-bold tracking-tight text-ink-900">{value ?? "—"}</p><p className="mt-1 text-xs text-slate-400">{note}</p></div><div className={`rounded-xl p-2.5 ${color}`}><Icon size={19} /></div></div></div>;

export default function DashboardPage() {
  const [greeting, setGreeting] = useState(() => getTimeBasedGreeting());
  const [reviews, setReviews] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true); setError("");
    try {
      const [reviewData, analyticsData] = await Promise.all([api.reviews(), api.analytics()]);
      setReviews(unwrapList(reviewData).slice(0, 5));
      setAnalytics(analyticsData?.data || analyticsData);
    } catch (err) { setError(errorMessage(err)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  useEffect(() => {
    let timeoutId;
    const updateGreeting = () => {
      setGreeting(getTimeBasedGreeting());
      timeoutId = window.setTimeout(
        updateGreeting,
        60_000 - (Date.now() % 60_000) + 10,
      );
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        window.clearTimeout(timeoutId);
        updateGreeting();
      }
    };

    updateGreeting();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.clearTimeout(timeoutId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);
  const severity = analytics?.issues_by_severity || {};
  const common = analytics?.frequent_guidelines || analytics?.most_common_violations || [];
  return <>
    <PageHeader eyebrow="Overview" title={greeting} description="Keep every piece of content confidently on-brand." action={<Link to="/content/new" className="btn-primary"><FilePlus2 size={17} />New content review</Link>} />
    {error && <div className="mb-5"><ErrorState message={error} onRetry={load} /></div>}
    {loading ? <LoadingState label="Loading workspace overview..." /> : <>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Workspace metrics">
        <Metric label="Content reviews" value={analytics?.total_reviews ?? "—"} note="All time" icon={FileCheck2} color="bg-violet-50 text-violet-700" />
        <Metric label="Issues detected" value={analytics?.total_issues ?? "—"} note="Across reviewed content" icon={ShieldAlert} color="bg-rose-50 text-rose-700" />
        <Metric label="Pending approvals" value={analytics?.pending_approvals ?? "—"} note="Needs a human review" icon={CircleAlert} color="bg-amber-50 text-amber-700" />
        <Metric label="High severity" value={severity.high ?? severity.High ?? "—"} note="Prioritize before publishing" icon={TrendingUp} color="bg-blue-50 text-blue-700" />
      </section>
      <section className="mt-6 grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <div className="card">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="font-semibold text-ink-900">Recent reviews</h2><p className="mt-1 text-xs text-slate-500">Latest content moving through your workspace</p></div><Link to="/reviews" className="inline-flex items-center gap-1 text-sm font-semibold text-ink-700 hover:text-ink-900">View queue <ArrowRight size={15} /></Link></div>
          {reviews.length ? <div className="divide-y divide-slate-100">{reviews.map((item) => <Link key={item.id} to={`/reviews/${item.id}`} className="flex items-center justify-between gap-3 px-5 py-4 hover:bg-slate-50/70"><div className="min-w-0"><p className="truncate text-sm font-semibold text-slate-800">{item.title || item.name || "Untitled review"}</p><p className="mt-1 text-xs text-slate-400">{item.content_type || item.type || "Content"}{item.submitted_at ? ` · ${new Date(item.submitted_at).toLocaleDateString()}` : ""}</p></div><div className="flex shrink-0 items-center gap-3"><span className="hidden text-xs text-slate-500 sm:inline">{item.issue_count ?? item.findings?.length ?? 0} issues</span><Badge tone="status">{item.status || "pending"}</Badge></div></Link>)}</div> : <EmptyState title="Your review history starts here" description="Submit content to see analysis and reviews in this space." />}
        </div>
        <div className="card">
          <div className="border-b border-slate-100 px-5 py-4"><h2 className="font-semibold text-ink-900">Most triggered guidelines</h2><p className="mt-1 text-xs text-slate-500">Patterns worth keeping an eye on</p></div>
          {common.length ? <div className="space-y-5 p-5">{common.slice(0, 5).map((item, index) => { const count = item.count ?? item.issue_count ?? 0; const max = Math.max(...common.map((entry) => entry.count ?? entry.issue_count ?? 1)); return <div key={item.id || item.name || item.guideline || index}><div className="mb-2 flex justify-between gap-3 text-sm"><span className="truncate font-medium text-slate-700">{item.name || item.guideline || item.title || "Guideline"}</span><span className="shrink-0 text-slate-400">{count}</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-ink-500" style={{ width: `${Math.max(4, (count / max) * 100)}%` }} /></div></div>; })}</div> : <EmptyState title="No guideline trends yet" description="Analytics will appear as your team reviews content." />}
        </div>
      </section>
      <section className="mt-5 grid gap-4 sm:grid-cols-3">
        {[["High", severity.high ?? severity.High], ["Medium", severity.medium ?? severity.Medium], ["Low", severity.low ?? severity.Low]].map(([label, value]) => <div className="card flex items-center justify-between p-4" key={label}><div className="flex items-center gap-3"><Badge tone="severity">{label.toLowerCase()}</Badge><span className="text-sm text-slate-500">severity issues</span></div><strong className="text-lg text-ink-900">{value ?? "—"}</strong></div>)}
      </section>
    </>}
  </>;
}
