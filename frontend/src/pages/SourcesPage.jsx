import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  FileCheck2,
  History,
  LibraryBig,
  Pencil,
  Plus,
  Search,
  ToggleLeft,
  ToggleRight,
  XCircle,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import FreshnessPanel from "../components/FreshnessPanel";
import { api, errorMessage, unwrapList } from "../services/api";
import {
  Badge,
  EmptyState,
  ErrorMessage,
  ErrorState,
  LoadingState,
  PageHeader,
  SuccessMessage,
} from "../components/common/UI";
import { useAuth } from "../contexts/AuthContext";

const initialForm = {
  name: "",
  description: "",
  source_type: "document",
  content: "",
  guideline_id: "",
  url: "",
  source_date: "",
  valid_from: "",
  valid_until: "",
  review_interval_days: "90",
  approval_status: "pending",
};
const MAX_SOURCE_SIZE = 10 * 1024 * 1024;

function lifecycleLabel(source) {
  if (!source.is_active) return "Inactive";
  if (source.lifecycle_status === "expired") return "Expired";
  if (source.lifecycle_status === "not_yet_valid") return "Not yet valid";
  return (source.approval_status || "pending")
    .replaceAll("_", " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

export default function SourcesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedSourceId = searchParams.get("source_id");
  const relatedClaim = searchParams.get("claim");
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const canReview = isAdmin || user?.role === "reviewer";
  const [sources, setSources] = useState([]);
  const [guidelines, setGuidelines] = useState([]);
  const [form, setForm] = useState(initialForm);
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [activeFilter, setActiveFilter] = useState("all");
  const [freshnessFilter, setFreshnessFilter] = useState("all");
  const [versionsFor, setVersionsFor] = useState(null);
  const [versions, setVersions] = useState([]);
  const [versionsError, setVersionsError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [sourceResponse, guidelineResponse] = await Promise.all([
        api.sources(),
        api.guidelines(),
      ]);
      setSources(unwrapList(sourceResponse));
      setGuidelines(unwrapList(guidelineResponse));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, []);

  const visible = useMemo(
    () =>
      sources.filter((source) => {
        const searchable = [
          source.name,
          source.description,
          source.content,
          source.source_type,
          source.url,
        ]
          .join(" ")
          .toLowerCase();
        return (
          (!linkedSourceId || String(source.id) === linkedSourceId) &&
          searchable.includes(search.toLowerCase()) &&
          (statusFilter === "all" ||
            (statusFilter === "expired"
              ? source.lifecycle_status === "expired"
              : source.approval_status === statusFilter)) &&
          (freshnessFilter === "all" ||
            source.freshness_status === freshnessFilter) &&
          (activeFilter === "all" ||
            String(Boolean(source.is_active)) === activeFilter)
        );
      }),
    [sources, search, statusFilter, freshnessFilter, activeFilter, linkedSourceId],
  );

  useEffect(() => {
    if (!linkedSourceId || loading) return;
    document
      .getElementById(`source-${linkedSourceId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [linkedSourceId, loading, sources]);

  const resetForm = () => {
    setForm(initialForm);
    setFile(null);
    setEditing(null);
    setFileError("");
  };

  const startEdit = (source) => {
    setEditing(source.id);
    setFile(null);
    setForm({
      name: source.name || "",
      description: source.description || "",
      source_type: source.source_type || "document",
      content: source.content || "",
      guideline_id: source.guideline_id ? String(source.guideline_id) : "",
      url: source.url || "",
      source_date: source.source_date || "",
      valid_from: source.valid_from || source.source_date || "",
      valid_until: source.valid_until || source.expiry_date || "",
      review_interval_days: String(source.review_interval_days || 90),
      approval_status: source.approval_status === "draft" ? "draft" : "pending",
    });
    setError("");
    setNotice("");
  };

  const save = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!form.name.trim() || (!form.content.trim() && !file)) {
      setError("Enter a source title and evidence content or upload a supported file.");
      return;
    }
    setSaving(true);
    const body = {
      ...form,
      guideline_id: form.guideline_id ? Number(form.guideline_id) : null,
      url: form.url.trim() || null,
      description: form.description.trim() || null,
      source_date: form.source_date || null,
      valid_from: form.valid_from || null,
      valid_until: form.valid_until || null,
      review_interval_days: Number(form.review_interval_days),
    };
    try {
      if (editing) {
        if (file) {
          setError("Replace source content by pasting text; uploading a replacement file is not supported.");
          return;
        }
        const editBody = { ...body };
        delete editBody.approval_status;
        const updated = await api.updateSource(editing, editBody);
        setSources((current) =>
          current.map((source) => source.id === editing ? updated : source),
        );
        setNotice("Evidence source updated. Changes to approved evidence require approval again.");
      } else if (file) {
        await api.uploadSource({ ...body, file });
        setNotice("Evidence source saved and submitted for approval.");
        await load();
      } else {
        await api.createSource(body);
        setNotice(
          body.approval_status === "draft"
            ? "Evidence draft saved."
            : "Evidence source saved and submitted for approval.",
        );
        await load();
      }
      resetForm();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const decide = async (source, status) => {
    const note = status === "rejected"
      ? window.prompt("Why is this evidence source being rejected?")
      : undefined;
    if (status === "rejected" && (note === null || !note.trim())) return;
    setReviewing(source.id);
    setError("");
    try {
      const updated = await api.reviewSource(source.id, status, note);
      setSources((current) => current.map((item) => item.id === updated.id ? updated : item));
      setNotice(status === "approved" ? "Evidence source approved for claim matching." : "Evidence source rejected.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setReviewing(null);
    }
  };

  const reverify = async (source) => {
    setReviewing(source.id);
    setError("");
    try {
      const updated = await api.verifySourceFreshness(source.id);
      setSources((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice("Evidence freshness verification recorded.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setReviewing(null);
    }
  };

  const deactivate = async (source) => {
    const nextActive = !source.is_active;
    const action = nextActive ? "reactivate" : "deactivate";
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} “${source.name}”? ${nextActive ? "Reactivated evidence returns to pending approval." : "It will no longer be eligible for claim matching."}`)) return;
    setError("");
    try {
      const updated = nextActive
        ? await api.updateSource(source.id, { is_active: true })
        : await api.deleteSource(source.id);
      if (nextActive) {
        setSources((current) => current.map((item) => item.id === source.id ? updated : item));
      } else {
        setSources((current) => current.map((item) =>
          item.id === source.id
            ? { ...item, is_active: false, lifecycle_status: "inactive" }
            : item,
        ));
      }
      setNotice(`Evidence source ${action}d.`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const showVersions = async (source) => {
    setVersionsFor(source);
    setVersions([]);
    setVersionsError("");
    try {
      setVersions(unwrapList(await api.sourceVersions(source.id)));
    } catch (err) {
      setVersionsError(errorMessage(err));
    }
  };

  const chooseFile = (selected) => {
    setFileError("");
    if (!selected) {
      setFile(null);
      return;
    }
    if (!/\.(txt|md|pdf)$/i.test(selected.name)) {
      setFileError("Choose a UTF-8 TXT, Markdown, or PDF file.");
      setFile(null);
      return;
    }
    if (selected.size > MAX_SOURCE_SIZE) {
      setFileError("Source files must be 10 MB or smaller.");
      setFile(null);
      return;
    }
    setFile(selected);
  };

  return (
    <>
      <PageHeader
        eyebrow="Evidence library"
        title="Evidence sources"
        description="Only active, explicitly approved, currently valid organisational sources can support or contradict claims. Every finding remains advisory."
        action={<span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600"><FileCheck2 size={14} />Evidence traceability</span>}
      />
      {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}
      {error && <div className="mb-4"><ErrorMessage>{error}</ErrorMessage></div>}
      {canReview && (
        <FreshnessPanel resourceType="source" canRun={isAdmin} />
      )}
      {linkedSourceId && (
        <div className="mb-4 rounded-lg border border-ink-100 bg-ink-50 p-4">
          <p className="text-sm font-semibold text-ink-900">Evidence cited by a review</p>
          {relatedClaim && <p className="mt-1 text-sm text-slate-700"><strong>Related claim:</strong> {relatedClaim}</p>}
          <button
            type="button"
            className="mt-2 text-xs font-medium text-ink-700 underline"
            onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.delete("source_id");
              next.delete("claim");
              setSearchParams(next, { replace: true });
            }}
          >
            Clear source focus
          </button>
        </div>
      )}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="card overflow-hidden">
          <div className="space-y-3 border-b border-slate-100 p-4 sm:p-5">
            <div className="flex flex-col gap-3 md:flex-row">
              <div className="relative min-w-48 flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input className="field pl-9" aria-label="Search evidence" placeholder="Search title, description, or content..." value={search} onChange={(event) => setSearch(event.target.value)} />
              </div>
              <select className="field md:max-w-44" aria-label="Filter evidence approval" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">All approval states</option>
                {["draft", "pending", "approved", "rejected", "expired"].map((state) => <option key={state} value={state}>{state.replace(/^\w/, (letter) => letter.toUpperCase())}</option>)}
              </select>
              <select className="field md:max-w-44" aria-label="Filter evidence freshness" value={freshnessFilter} onChange={(event) => setFreshnessFilter(event.target.value)}>
                <option value="all">All freshness states</option>
                {["current", "expiring_soon", "review_overdue", "expired", "not_yet_valid", "inactive"].map((state) => <option key={state} value={state}>{state.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase())}</option>)}
              </select>
              <select className="field md:max-w-36" aria-label="Filter active evidence" value={activeFilter} onChange={(event) => setActiveFilter(event.target.value)}>
                <option value="all">All activity</option><option value="true">Active</option><option value="false">Inactive</option>
              </select>
            </div>
            <p className="text-xs text-slate-500">Approval and validity are separate: inactive, expired, pending, and rejected records never qualify as verification evidence.</p>
          </div>
          {loading ? <LoadingState /> : error && !sources.length ? (
            <div className="p-4"><ErrorState message={error} onRetry={load} /></div>
          ) : visible.length ? (
            <div className="divide-y divide-slate-100">
              {visible.map((source) => (
                <article id={`source-${source.id}`} key={source.id} className={`p-5 ${String(source.id) === linkedSourceId ? "bg-amber-50/60" : ""}`}>
                  <div className="flex items-start gap-3">
                    <div className="h-fit rounded-lg bg-ink-50 p-2.5 text-ink-700"><LibraryBig size={18} /></div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold text-slate-800">{source.name}</h2>
                        <Badge>{lifecycleLabel(source)}</Badge>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${source.approval_status === "approved" ? "bg-emerald-50 text-emerald-700" : source.approval_status === "rejected" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-800"}`}>
                          Approval: {(source.approval_status || "pending").replaceAll("_", " ")}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${source.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{source.is_active ? "Active" : "Inactive"}</span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{source.source_type || "document"}</span>
                        <Badge tone="status">{source.freshness_status || source.lifecycle_status}</Badge>
                      </div>
                      {source.description && <p className="mt-2 text-sm leading-5 text-slate-600">{source.description}</p>}
                      <p className="mt-2 break-all text-xs text-slate-500">
                        {source.guideline_id ? `Guideline #${source.guideline_id}` : "Available to all guidelines"}
                        {source.source_date ? ` · Published ${source.source_date}` : ""}
                        {` · Valid from ${source.valid_from || "unspecified"}`}
                        {` · Valid until ${source.valid_until || source.expiry_date || "unspecified"}`}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Last verified {source.last_verified_at ? new Date(source.last_verified_at).toLocaleString() : "never"}
                        {source.reviewed_by ? ` by ${source.reviewed_by}` : ""}
                        {` · Review every ${source.review_interval_days || 90} days`}
                      </p>
                      {source.url && <a className="mt-1 inline-block break-all text-xs font-medium text-ink-700 underline" href={source.url} target="_blank" rel="noreferrer">Open original source</a>}
                      <details className="mt-3 rounded-lg bg-slate-50 p-3">
                        <summary className="cursor-pointer text-xs font-semibold text-slate-700">Preview evidence content</summary>
                        <p className="mt-2 max-h-60 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{source.content}</p>
                      </details>
                      {source.review_note && <p className="mt-2 text-xs text-rose-700">Review note: {source.review_note}</p>}
                      <p className="mt-2 text-xs text-slate-400">
                        Created {source.created_at ? new Date(source.created_at).toLocaleString() : "—"}
                        {source.created_by ? ` by ${source.created_by}` : ""}
                        {" · "}Updated {source.updated_at ? new Date(source.updated_at).toLocaleString() : "—"}
                        {source.updated_by ? ` by ${source.updated_by}` : ""}
                        {source.reviewed_by ? ` · Reviewed by ${source.reviewed_by}` : ""}
                      </p>
                      {!!source.approval_history?.length && (
                        <details className="mt-2 text-xs text-slate-500">
                          <summary className="cursor-pointer">Approval history ({source.approval_history.length})</summary>
                          <ul className="mt-2 space-y-1">
                            {source.approval_history.map((event, index) => <li key={index}>{event.status} · {event.reviewer || "Former reviewer"} · {event.created_at ? new Date(event.created_at).toLocaleString() : ""}{event.note ? ` · ${event.note}` : ""}</li>)}
                          </ul>
                        </details>
                      )}
                      {isAdmin && (
                        <button type="button" className="btn-secondary mt-2 px-3 py-1.5 text-xs" onClick={() => showVersions(source)}>
                          <History size={14} /> Version history ({source.version_count || 0})
                        </button>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col gap-1">
                      {canReview && source.is_active && source.approval_status !== "approved" && !["expired", "not_yet_valid"].includes(source.lifecycle_status) && <button type="button" disabled={reviewing === source.id} aria-label={`Approve ${source.name}`} title="Approve source" className="rounded-lg p-2 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50" onClick={() => decide(source, "approved")}><CheckCircle2 size={17} /></button>}
                      {canReview && source.is_active && source.approval_status === "approved" && source.freshness_status === "review_overdue" && <button type="button" disabled={reviewing === source.id} aria-label={`Re-verify ${source.name}`} title="Re-verify evidence freshness" className="rounded-lg p-2 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50" onClick={() => reverify(source)}><CheckCircle2 size={17} /></button>}
                      {canReview && source.is_active && source.approval_status !== "rejected" && <button type="button" disabled={reviewing === source.id} aria-label={`Reject ${source.name}`} title="Reject source" className="rounded-lg p-2 text-rose-600 hover:bg-rose-50 disabled:opacity-50" onClick={() => decide(source, "rejected")}><XCircle size={17} /></button>}
                      {isAdmin && <button type="button" aria-label={`Edit ${source.name}`} title="Edit source" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" onClick={() => startEdit(source)}><Pencil size={16} /></button>}
                      {isAdmin && <button type="button" aria-label={`${source.is_active ? "Deactivate" : "Reactivate"} ${source.name}`} title={source.is_active ? "Deactivate source" : "Reactivate source"} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" onClick={() => deactivate(source)}>{source.is_active ? <ToggleLeft size={17} /> : <ToggleRight size={17} />}</button>}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState icon={LibraryBig} title="No evidence sources match these filters" description="Adjust your search or add a source such as an approved fact sheet, policy excerpt, or disclosure." />
          )}
        </section>

        {isAdmin ? (
          <form className="card p-5" onSubmit={save}>
            <div className="mb-2 flex items-center gap-2">
              {editing ? <Pencil size={18} className="text-ink-600" /> : <Plus size={18} className="text-ink-600" />}
              <h2 className="font-semibold text-ink-900">{editing ? "Edit evidence source" : "Add evidence source"}</h2>
            </div>
            <p className="mb-5 text-xs leading-5 text-slate-500">{editing ? "Changes to approved source content or validity reset approval to pending." : "Sources are pending review by an authorised Admin or Reviewer unless saved as a draft."}</p>
            <label className="mb-1.5 block text-sm font-medium" htmlFor="source-name">Title</label>
            <input id="source-name" className="field mb-4" maxLength={160} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Approved product fact sheet" />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="source-description">Description</label>
            <textarea id="source-description" className="field mb-4 resize-y" rows={2} maxLength={4000} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="source-type">Source type</label>
            <input id="source-type" className="field mb-4" maxLength={48} value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })} placeholder="Product facts, study, policy..." />
            {!editing && <>
              <label className="mb-1.5 block text-sm font-medium" htmlFor="source-file">Upload reference file <span className="font-normal text-slate-400">(optional)</span></label>
              <input id="source-file" type="file" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" className="field mb-2" onChange={(event) => chooseFile(event.target.files?.[0])} />
              <p className="mb-4 text-xs text-slate-400">{file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB` : "UTF-8 TXT, Markdown or PDF · up to 10 MB."}</p>
              {fileError && <p role="alert" className="mb-3 text-sm text-rose-700">{fileError}</p>}
            </>}
            {(!file || editing) && <>
              <label className="mb-1.5 block text-sm font-medium" htmlFor="source-content">Evidence content</label>
              <textarea id="source-content" className="field mb-4 resize-y" rows={7} maxLength={200000} value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} placeholder="Enter source text. Similarity alone is never proof." />
            </>}
            <label className="mb-1.5 block text-sm font-medium" htmlFor="source-guideline">Related guideline</label>
            <select id="source-guideline" className="field mb-4" value={form.guideline_id} onChange={(event) => setForm({ ...form, guideline_id: event.target.value })}><option value="">Available to all guidelines</option>{guidelines.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
            <label className="mb-1.5 block text-sm font-medium" htmlFor="source-url">Original URL <span className="font-normal text-slate-400">(optional)</span></label>
            <input id="source-url" type="url" className="field mb-4" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} placeholder="https://…" />
            <div className="grid grid-cols-2 gap-3">
              <div><label className="mb-1.5 block text-sm font-medium" htmlFor="source-date">Publication date</label><input id="source-date" type="date" className="field" value={form.source_date} onChange={(event) => setForm({ ...form, source_date: event.target.value })} /></div>
              <div><label className="mb-1.5 block text-sm font-medium" htmlFor="source-valid-from">Valid from</label><input id="source-valid-from" type="date" className="field" value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} /></div>
              <div><label className="mb-1.5 block text-sm font-medium" htmlFor="source-valid-until">Valid until</label><input id="source-valid-until" type="date" className="field" value={form.valid_until} onChange={(event) => setForm({ ...form, valid_until: event.target.value })} /></div>
              <div><label className="mb-1.5 block text-sm font-medium" htmlFor="source-review-interval">Freshness review (days)</label><input id="source-review-interval" type="number" min="1" max="3650" className="field" value={form.review_interval_days} onChange={(event) => setForm({ ...form, review_interval_days: event.target.value })} /></div>
            </div>
            {!editing && <label className="mt-4 block text-sm font-medium" htmlFor="source-approval">Initial state</label>}
            {!editing && <select id="source-approval" className="field mt-1" value={form.approval_status} onChange={(event) => setForm({ ...form, approval_status: event.target.value })}><option value="draft">Draft</option><option value="pending">Submit for approval</option></select>}
            <button className="btn-primary mt-5 w-full" type="submit" disabled={saving || Boolean(fileError)}>{saving ? "Saving…" : editing ? "Save changes" : "Save source"}</button>
            {editing && <button className="btn-secondary mt-2 w-full" type="button" onClick={resetForm}>Cancel editing</button>}
          </form>
        ) : (
          <section className="card p-5">
            <h2 className="font-semibold text-ink-900">Evidence permissions</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">{canReview ? "Reviewers may inspect evidence and approve or reject it under the existing reviewer permissions. Only Admins can create, edit, or deactivate evidence." : "Contributors can inspect evidence records but cannot create, edit, deactivate, or approve them."}</p>
          </section>
        )}
      </div>
      {versionsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setVersionsFor(null); }}>
          <section className="card max-h-[85vh] w-full max-w-3xl overflow-y-auto p-5" role="dialog" aria-modal="true" aria-labelledby="source-versions-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="source-versions-title" className="text-lg font-semibold text-ink-900">Evidence history</h2>
                <p className="mt-1 text-sm text-slate-500">{versionsFor.name}</p>
              </div>
              <button className="btn-secondary" onClick={() => setVersionsFor(null)}>Close</button>
            </div>
            {versionsError ? <p role="alert" className="mt-4 text-sm text-rose-700">{versionsError}</p> : versions.length ? (
              <div className="mt-4 space-y-3">
                {versions.map((version) => (
                  <article key={version.id} className="rounded-lg border border-slate-200 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-semibold text-slate-800">Version {version.version_number}</h3>
                      <div className="flex gap-2">
                        <Badge>{version.snapshot?.approval_status || "status unknown"}</Badge>
                        <Badge>{version.snapshot?.is_active ? "Active" : "Inactive"}</Badge>
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-slate-400">{version.editor || "Former editor"} · {version.created_at ? new Date(version.created_at).toLocaleString() : "date unavailable"}</p>
                    <p className="mt-3 text-xs text-slate-500">
                      {version.snapshot?.source_type || "document"}
                      {` · Valid from ${version.snapshot?.source_date || "unspecified"}`}
                      {` · Expires ${version.snapshot?.expiry_date || "unspecified"}`}
                    </p>
                    {version.snapshot?.url && <a className="mt-2 inline-block break-all text-xs text-ink-700 underline" href={version.snapshot.url} target="_blank" rel="noreferrer">Open original source</a>}
                    {version.snapshot?.description && <p className="mt-2 text-sm text-slate-600">{version.snapshot.description}</p>}
                    <details className="mt-3 rounded bg-slate-50 p-3">
                      <summary className="cursor-pointer text-xs font-semibold text-slate-700">Evidence content snapshot</summary>
                      <p className="mt-2 max-h-60 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{version.snapshot?.content}</p>
                    </details>
                  </article>
                ))}
              </div>
            ) : <p className="mt-4 text-sm text-slate-500">No evidence versions have been saved.</p>}
          </section>
        </div>
      )}
    </>
  );
}
