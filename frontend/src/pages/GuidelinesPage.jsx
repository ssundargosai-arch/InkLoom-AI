import { useEffect, useMemo, useState } from "react";
import { BookOpenText, History, Pencil, Plus, ToggleLeft, ToggleRight } from "lucide-react";
import { api, errorMessage, unwrapList } from "../services/api";
import FreshnessPanel from "../components/FreshnessPanel";
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

const suggestedCategories = [
  "Tone of Voice",
  "Brand Messaging",
  "Approved Terminology",
  "Prohibited Terminology",
  "Promotional Claims",
  "Accessibility",
  "Visual Identity",
  "Content Formatting",
];
const toneOptions = [
  "professional",
  "friendly",
  "conversational",
  "formal",
  "authoritative",
  "informative",
];
const voiceAttributeOptions = [
  "clear",
  "trustworthy",
  "concise",
  "approachable",
];
const emptyBrandVoiceForm = {
  desired_tones: [],
  voice_attributes: [],
  preferred_expressions: "",
  prohibited_expressions: "",
  target_audiences: "",
  supported_channels: "",
  messaging_principles: "",
};
const emptyForm = {
  name: "",
  category: "",
  severity: "medium",
  review_interval_days: "180",
  description: "",
  examples: "",
  prohibited_terms: "",
  preferred_terms: "",
};

const toLines = (value) =>
  Array.isArray(value) ? value.join("\n") : value || "";

export default function GuidelinesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const canRunDiagnostics = isAdmin || user?.role === "reviewer";
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [activeFilter, setActiveFilter] = useState("all");
  const [freshnessFilter, setFreshnessFilter] = useState("all");
  const [versionsFor, setVersionsFor] = useState(null);
  const [versions, setVersions] = useState([]);
  const [versionsError, setVersionsError] = useState("");
  const [diagnostics, setDiagnostics] = useState(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState("");
  const [brandVoice, setBrandVoice] = useState(null);
  const [brandVoiceForm, setBrandVoiceForm] = useState(emptyBrandVoiceForm);
  const [brandVoiceSaving, setBrandVoiceSaving] = useState(false);
  const [brandVoiceError, setBrandVoiceError] = useState("");
  const [brandVoiceVersions, setBrandVoiceVersions] = useState([]);
  const [brandVoiceVersionsError, setBrandVoiceVersionsError] = useState("");
  const [form, setForm] = useState(emptyForm);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const canInspectBrandVoice =
        user?.role === "admin" || user?.role === "reviewer";
      const [guidelineResponse, categoryResponse, voiceResponse] =
        await Promise.all([
          api.guidelines(),
          api.guidelineCategories(),
          canInspectBrandVoice ? api.brandVoiceConfiguration() : null,
        ]);
      const loaded = unwrapList(guidelineResponse);
      if (voiceResponse) {
        setBrandVoice(voiceResponse);
        setBrandVoiceForm({
          desired_tones: voiceResponse.desired_tones || [],
          voice_attributes: voiceResponse.voice_attributes || [],
          preferred_expressions: toLines(voiceResponse.preferred_expressions),
          prohibited_expressions: toLines(voiceResponse.prohibited_expressions),
          target_audiences: toLines(voiceResponse.target_audiences),
          supported_channels: toLines(voiceResponse.supported_channels),
          messaging_principles: toLines(voiceResponse.messaging_principles),
        });
      }
      setItems(loaded);
      setCategories([
        ...new Set([
          ...suggestedCategories,
          ...unwrapList(categoryResponse),
          ...loaded.map((item) => item.category).filter(Boolean),
        ]),
      ]);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [user?.role]);

  const visible = useMemo(
    () =>
      items.filter((item) => {
        const matchesSearch = [
          item.name,
          item.category,
          item.description,
          ...(item.examples || []),
        ]
          .join(" ")
          .toLowerCase()
          .includes(search.toLowerCase());
        return (
          matchesSearch &&
          (categoryFilter === "all" || item.category === categoryFilter) &&
          (freshnessFilter === "all" ||
            item.freshness_status === freshnessFilter) &&
          (activeFilter === "all" ||
            String(Boolean(item.is_active)) === activeFilter)
        );
      }),
    [items, search, categoryFilter, activeFilter, freshnessFilter],
  );

  const startEdit = (item) => {
    setEditing(item.id);
    setForm({
      name: item.name || "",
      category: item.category || "",
      severity: item.severity || "medium",
      review_interval_days: String(item.review_interval_days || 180),
      description: item.description || "",
      examples: toLines(item.examples),
      prohibited_terms: toLines(item.prohibited_terms),
      preferred_terms: toLines(item.preferred_terms),
    });
    setFormError("");
    setNotice("");
  };

  const resetForm = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError("");
  };

  const save = async (event) => {
    event.preventDefault();
    setFormError("");
    setNotice("");
    if (!form.name.trim() || !form.category.trim() || !form.description.trim()) {
      setFormError("Name, category, and description are required.");
      return;
    }
    const body = {
      name: form.name,
      category: form.category,
      severity: form.severity,
      review_interval_days: Number(form.review_interval_days),
      description: form.description,
      examples: form.examples.split("\n").map((line) => line.trim()).filter(Boolean),
      prohibited_terms: form.prohibited_terms.split("\n").map((line) => line.trim()).filter(Boolean),
      preferred_terms: form.preferred_terms.split("\n").map((line) => line.trim()).filter(Boolean),
    };
    setSaving(true);
    try {
      if (editing) {
        await api.updateGuideline(editing, body);
        setNotice("Guideline updated. Previous review findings remain unchanged.");
      } else {
        await api.createGuideline(body);
        setNotice("Guideline created.");
      }
      resetForm();
      await load();
    } catch (e) {
      setFormError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (item) => {
    const action = item.is_active ? "deactivate" : "activate";
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} “${item.name}”?`)) return;
    try {
      const updated = await api.updateGuideline(item.id, {
        is_active: !item.is_active,
      });
      setItems((current) =>
        current.map((entry) => (entry.id === item.id ? updated : entry)),
      );
      setNotice(`Guideline ${action}d.`);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const markReviewed = async (item) => {
    try {
      const updated = await api.reviewGuideline(item.id);
      setItems((current) =>
        current.map((entry) => (entry.id === item.id ? updated : entry)),
      );
      setNotice("Guideline freshness review recorded.");
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const showVersions = async (item) => {
    setVersionsFor(item);
    setVersionsError("");
    setVersions([]);
    try {
      setVersions(unwrapList(await api.guidelineVersions(item.id)));
    } catch (e) {
      setVersionsError(errorMessage(e));
    }
  };

  const runDiagnostics = async () => {
    setDiagnosticsLoading(true);
    setDiagnosticsError("");
    try {
      setDiagnostics(await api.guidelineDiagnostics());
    } catch (e) {
      setDiagnosticsError(errorMessage(e));
      setDiagnostics(null);
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  const updateVoiceSelection = (field, event) => {
    setBrandVoiceForm((current) => ({
      ...current,
      [field]: Array.from(event.target.selectedOptions, (option) => option.value),
    }));
  };

  const saveBrandVoice = async (event) => {
    event.preventDefault();
    setBrandVoiceSaving(true);
    setBrandVoiceError("");
    const body = {
      desired_tones: brandVoiceForm.desired_tones,
      voice_attributes: brandVoiceForm.voice_attributes,
      preferred_expressions: brandVoiceForm.preferred_expressions
        .split("\n").map((line) => line.trim()).filter(Boolean),
      prohibited_expressions: brandVoiceForm.prohibited_expressions
        .split("\n").map((line) => line.trim()).filter(Boolean),
      target_audiences: brandVoiceForm.target_audiences
        .split("\n").map((line) => line.trim()).filter(Boolean),
      supported_channels: brandVoiceForm.supported_channels
        .split("\n").map((line) => line.trim()).filter(Boolean),
      messaging_principles: brandVoiceForm.messaging_principles
        .split("\n").map((line) => line.trim()).filter(Boolean),
    };
    try {
      const saved = await api.updateBrandVoiceConfiguration(body);
      setBrandVoice(saved);
      setNotice("Brand voice configuration saved. Existing reviews are unchanged.");
    } catch (e) {
      setBrandVoiceError(errorMessage(e));
    } finally {
      setBrandVoiceSaving(false);
    }
  };

  const loadBrandVoiceVersions = async () => {
    setBrandVoiceVersionsError("");
    try {
      setBrandVoiceVersions(unwrapList(await api.brandVoiceVersions()));
    } catch (e) {
      setBrandVoiceVersionsError(errorMessage(e));
    }
  };

  const renderVoiceValues = (label, values) => (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </h3>
      {values?.length ? (
        <ul className="mt-1 flex flex-wrap gap-2">
          {values.map((value) => (
            <li
              key={value}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700"
            >
              {value}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-slate-400">Not configured</p>
      )}
    </div>
  );

  const renderDiagnostic = (diagnostic, index) => (
    <article
      key={`${diagnostic.diagnostic_type}-${diagnostic.guideline_ids?.join("-")}-${index}`}
      className="rounded-lg border border-slate-200 bg-white p-4"
    >
      <h3 className="font-medium text-slate-800">
        {diagnostic.guideline_names?.join(" and ") || "Guideline"}
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        Guideline IDs: {diagnostic.guideline_ids?.join(", ") || "unavailable"}
        {diagnostic.category ? ` · Category: ${diagnostic.category}` : ""}
        {" · Scope: unclear"}
      </p>
      {!!diagnostic.matched_text?.length && (
        <div className="mt-2 space-y-1">
          {diagnostic.matched_text.map((text, textIndex) => (
            <p key={`${text}-${textIndex}`} className="text-sm text-slate-700">
              Matched text: <q>{text}</q>
            </p>
          ))}
        </div>
      )}
      <p className="mt-2 text-sm leading-5 text-slate-600">{diagnostic.explanation}</p>
      <p className="mt-2 text-xs leading-5 text-ink-700">
        Human review: {diagnostic.human_review_recommendation}
      </p>
    </article>
  );

  return (
    <>
      <PageHeader
        eyebrow="Brand system"
        title="Brand guidelines"
        description="Manage standards for consistent, evidence-aware reviews. Changes apply to future analysis and do not rewrite historical findings."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600">
              {items.filter((item) => item.is_active).length} active
            </span>
            {canRunDiagnostics && (
              <button
                className="btn-secondary px-3 py-1.5 text-xs"
                type="button"
                onClick={runDiagnostics}
                disabled={diagnosticsLoading}
              >
                {diagnosticsLoading ? "Checking…" : "Check for conflicts and clarity"}
              </button>
            )}
          </div>
        }
      />
      {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}
      {error && <div className="mb-4"><ErrorMessage>{error}</ErrorMessage></div>}
      {(isAdmin || user?.role === "reviewer") && (
        <FreshnessPanel resourceType="guideline" canRun={isAdmin} />
      )}
      {(isAdmin || user?.role === "reviewer") && (
        <section className="card mb-6 p-5 sm:p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-ink-900">
              Brand voice configuration
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-5 text-slate-500">
              Define only the voice guidance your organization chooses to use.
              Empty settings are intentional; this configuration does not
              automatically analyze or change existing reviews.
            </p>
          </div>
          {isAdmin ? (
            <form onSubmit={saveBrandVoice} className="space-y-4">
              <p className="text-xs text-slate-400">
                Saved configuration version {brandVoice?.version_number || 0}
                {brandVoice?.updated_at
                  ? ` · Updated ${new Date(brandVoice.updated_at).toLocaleString()}`
                  : " · No configuration saved yet"}
              </p>
              {brandVoiceError && (
                <div role="alert"><ErrorMessage>{brandVoiceError}</ErrorMessage></div>
              )}
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-sm font-medium" htmlFor="brand-voice-tones">
                    Desired tone
                  </label>
                  <p className="mb-2 text-xs text-slate-500">
                    Optional; select only tones your organization has approved.
                  </p>
                  <select
                    id="brand-voice-tones"
                    className="field min-h-32"
                    multiple
                    value={brandVoiceForm.desired_tones}
                    onChange={(event) => updateVoiceSelection("desired_tones", event)}
                  >
                    {toneOptions.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium" htmlFor="brand-voice-attributes">
                    Brand voice attributes
                  </label>
                  <p className="mb-2 text-xs text-slate-500">
                    Optional attributes; these are saved as guidance, not automatic judgments.
                  </p>
                  <select
                    id="brand-voice-attributes"
                    className="field min-h-32"
                    multiple
                    value={brandVoiceForm.voice_attributes}
                    onChange={(event) => updateVoiceSelection("voice_attributes", event)}
                  >
                    {voiceAttributeOptions.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                </div>
              </div>
              <p className="-mt-2 text-xs text-slate-400">
                Use Ctrl (Windows/Linux) or Command (macOS) to select multiple options.
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                {[
                  ["preferred_expressions", "Preferred expressions", "Approved phrases the organization likes to use; these are independent from preferred terminology replacements."],
                  ["prohibited_expressions", "Prohibited expressions", "Phrases the organization does not want used."],
                  ["target_audiences", "Target audiences", "Audience labels applicable to this organization; add only relevant audiences."],
                  ["supported_channels", "Supported channels", "Optional labels such as Website, Email or Social media. No channels are selected by default."],
                  ["messaging_principles", "Messaging principles", "Organization-defined principles. Enter one principle per line."],
                ].map(([field, label, description]) => (
                  <div key={field}>
                    <label className="mb-1.5 block text-sm font-medium" htmlFor={`brand-voice-${field}`}>
                      {label}
                    </label>
                    <p className="mb-2 text-xs text-slate-500">{description}</p>
                    <textarea
                      id={`brand-voice-${field}`}
                      className="field resize-y"
                      rows={field === "messaging_principles" ? 4 : 3}
                      maxLength={10000}
                      value={brandVoiceForm[field]}
                      onChange={(event) => setBrandVoiceForm((current) => ({
                        ...current,
                        [field]: event.target.value,
                      }))}
                      placeholder="One entry per line"
                    />
                  </div>
                ))}
              </div>
              <button className="btn-primary" type="submit" disabled={brandVoiceSaving}>
                {brandVoiceSaving ? "Saving…" : "Save brand voice configuration"}
              </button>
            </form>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {renderVoiceValues("Desired tone", brandVoice?.desired_tones)}
              {renderVoiceValues("Brand voice attributes", brandVoice?.voice_attributes)}
              {renderVoiceValues("Preferred expressions", brandVoice?.preferred_expressions)}
              {renderVoiceValues("Prohibited expressions", brandVoice?.prohibited_expressions)}
              {renderVoiceValues("Target audiences", brandVoice?.target_audiences)}
              {renderVoiceValues("Supported channels", brandVoice?.supported_channels)}
              {renderVoiceValues("Messaging principles", brandVoice?.messaging_principles)}
            </div>
          )}
          {isAdmin && (
            <details className="mt-5 border-t border-slate-100 pt-4">
              <summary
                className="cursor-pointer text-sm font-medium text-ink-700"
                onClick={(event) => {
                  if (!event.currentTarget.parentElement.open) {
                    loadBrandVoiceVersions();
                  }
                }}
              >
                Configuration version history
              </summary>
              {brandVoiceVersionsError ? (
                <div className="mt-3" role="alert">
                  <ErrorMessage>{brandVoiceVersionsError}</ErrorMessage>
                </div>
              ) : brandVoiceVersions.length ? (
                <ul className="mt-3 space-y-2">
                  {brandVoiceVersions.map((version) => (
                    <li key={version.id} className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
                      Version {version.version_number} · {version.editor || "Former Admin"}
                      {" · "}{version.created_at ? new Date(version.created_at).toLocaleString() : "date unavailable"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  No saved configuration versions yet.
                </p>
              )}
            </details>
          )}
        </section>
      )}
      {canRunDiagnostics && diagnosticsError && (
        <div className="mb-4" role="alert"><ErrorMessage>{diagnosticsError}</ErrorMessage></div>
      )}
      {canRunDiagnostics && diagnostics && (
        <section className="card mb-6 space-y-5 p-5" aria-live="polite">
          <p className="text-sm leading-5 text-slate-500">
            Deterministic suggestions only. Category is a grouping hint, scope is unknown, and no guideline is changed automatically.
          </p>
          <div>
            <h2 className="font-semibold text-ink-900">Potential Conflicts</h2>
            <p className="mb-3 mt-1 text-xs text-slate-500">
              Possible opposing directives requiring human confirmation; these are not confirmed conflicts.
            </p>
            {diagnostics.potential_conflicts?.length ? (
              <div className="space-y-3">
                {diagnostics.potential_conflicts.map(renderDiagnostic)}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No potential conflicts detected.</p>
            )}
          </div>
          <div>
            <h2 className="font-semibold text-ink-900">Needs Clarification</h2>
            <p className="mb-3 mt-1 text-xs text-slate-500">
              Subjective wording suggestions are separate from conflict detection.
            </p>
            {diagnostics.needs_clarification?.length ? (
              <div className="space-y-3">
                {diagnostics.needs_clarification.map(renderDiagnostic)}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No clarification suggestions detected.</p>
            )}
          </div>
        </section>
      )}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="card overflow-hidden">
          <div className="space-y-3 border-b border-slate-100 p-4 sm:p-5">
            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                className="field"
                aria-label="Search guidelines"
                placeholder="Search guidelines..."
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <select
                className="field sm:max-w-56"
                aria-label="Filter by category"
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
              >
                <option value="all">All categories</option>
                {categories.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </select>
              <select
                className="field sm:max-w-40"
                aria-label="Filter by active status"
                value={activeFilter}
                onChange={(event) => setActiveFilter(event.target.value)}
              >
                <option value="all">All states</option>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
              <select
                className="field sm:max-w-48"
                aria-label="Filter by freshness"
                value={freshnessFilter}
                onChange={(event) => setFreshnessFilter(event.target.value)}
              >
                <option value="all">All freshness states</option>
                <option value="current">Current</option>
                <option value="review_overdue">Review overdue</option>
              </select>
            </div>
          </div>
          {loading ? <LoadingState /> : error && !items.length ? (
            <div className="p-4"><ErrorState message={error} onRetry={load} /></div>
          ) : visible.length ? (
            <div className="divide-y divide-slate-100">
              {visible.map((item) => (
                <article id={`guideline-${item.id}`} key={item.id} className="flex gap-3 p-5">
                  <div className="h-fit rounded-lg bg-ink-50 p-2.5 text-ink-700">
                    <BookOpenText size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold text-slate-800">{item.name}</h2>
                      <Badge>{item.is_active ? "Active" : "Inactive"}</Badge>
                      <Badge tone="severity">{item.severity}</Badge>
                      <Badge tone="status">{item.freshness_status || "unknown"}</Badge>
                    </div>
                    <p className="mt-1 text-xs font-medium text-ink-600">{item.category}</p>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{item.description}</p>
                    {!!item.examples?.length && (
                      <div className="mt-3 rounded-lg bg-slate-50 p-3">
                        <p className="text-xs font-semibold text-slate-600">Examples</p>
                        <ul className="mt-1 list-inside list-disc space-y-1 text-xs text-slate-500">
                          {item.examples.map((example, index) => <li key={index}>{example}</li>)}
                        </ul>
                      </div>
                    )}
                    <p className="mt-3 text-xs text-slate-400">
                      Created {item.created_at ? new Date(item.created_at).toLocaleString() : "—"}
                      {item.created_by ? ` by ${item.created_by}` : ""}
                      {" · "}Updated {item.updated_at ? new Date(item.updated_at).toLocaleString() : "—"}
                      {item.updated_by ? ` by ${item.updated_by}` : ""}
                      {" · "}Last reviewed {item.last_reviewed_at ? new Date(item.last_reviewed_at).toLocaleString() : "Never"}
                      {item.last_reviewed_by ? ` by ${item.last_reviewed_by}` : ""}
                    </p>
                    {!!item.review_history?.length && (
                      <details className="mt-2 text-xs text-slate-500">
                        <summary className="cursor-pointer">Freshness review history ({item.review_history.length})</summary>
                        <ul className="mt-2 space-y-1">
                          {item.review_history.map((event, index) => (
                            <li key={`${event.created_at}-${index}`}>
                              {event.reviewer || "Former Admin"} · {event.created_at ? new Date(event.created_at).toLocaleString() : ""}
                              {event.note ? ` · ${event.note}` : ""}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {isAdmin && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button className="btn-secondary px-3 py-1.5 text-xs" onClick={() => startEdit(item)}>
                          <Pencil size={14} /> Edit
                        </button>
                        <button className="btn-secondary px-3 py-1.5 text-xs" onClick={() => toggleActive(item)}>
                          {item.is_active ? <ToggleLeft size={14} /> : <ToggleRight size={14} />}
                          {item.is_active ? "Deactivate" : "Activate"}
                        </button>
                        {item.is_active && (
                          <button className="btn-secondary px-3 py-1.5 text-xs" onClick={() => markReviewed(item)}>
                            <BookOpenText size={14} /> Mark reviewed
                          </button>
                        )}
                        <button className="btn-secondary px-3 py-1.5 text-xs" onClick={() => showVersions(item)}>
                          <History size={14} /> Version history
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="No guidelines match these filters" description="Change your search or filters, or add a new guideline." />
          )}
        </section>

        {isAdmin ? (
          <form className="card p-5" onSubmit={save}>
            <div className="mb-4 flex items-center gap-2">
              {editing ? <Pencil size={18} className="text-ink-600" /> : <Plus size={18} className="text-ink-600" />}
              <h2 className="font-semibold text-ink-900">{editing ? "Edit guideline" : "Add a guideline"}</h2>
            </div>
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-name">Guideline name</label>
            <input id="rule-name" className="field mb-4" maxLength={160} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-category">Category</label>
            <input id="rule-category" className="field mb-4" list="guideline-categories" maxLength={80} value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} placeholder="Choose or enter a category" />
            <datalist id="guideline-categories">{categories.map((category) => <option key={category} value={category} />)}</datalist>
            <p className="-mt-3 mb-4 text-xs leading-5 text-slate-400">
              For heuristic visual palette checks, use a visual identity, brand colour, logo, or accessibility category and include approved HEX colours in the description or examples. Other visual rules remain reviewer guidance.
            </p>
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-severity">Severity</label>
            <select id="rule-severity" className="field mb-4" value={form.severity} onChange={(event) => setForm({ ...form, severity: event.target.value })}>
              {["low", "medium", "high", "critical"].map((value) => <option key={value}>{value}</option>)}
            </select>
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-review-interval">Freshness review interval (days)</label>
            <input id="rule-review-interval" className="field mb-4" type="number" min="1" max="3650" value={form.review_interval_days} onChange={(event) => setForm({ ...form, review_interval_days: event.target.value })} />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-description">Description</label>
            <textarea id="rule-description" rows={4} maxLength={4000} className="field mb-4 resize-y" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-examples">Examples <span className="font-normal text-slate-400">(one per line)</span></label>
            <textarea id="rule-examples" rows={3} className="field mb-4 resize-y" value={form.examples} onChange={(event) => setForm({ ...form, examples: event.target.value })} />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-prohibited">Prohibited terms <span className="font-normal text-slate-400">(one per line)</span></label>
            <textarea id="rule-prohibited" rows={2} className="field mb-4 resize-y" value={form.prohibited_terms} onChange={(event) => setForm({ ...form, prohibited_terms: event.target.value })} />
            <label className="mb-1.5 block text-sm font-medium" htmlFor="rule-preferred">Preferred replacements <span className="font-normal text-slate-400">(one per line)</span></label>
            <textarea id="rule-preferred" rows={2} className="field mb-4 resize-y" value={form.preferred_terms} onChange={(event) => setForm({ ...form, preferred_terms: event.target.value })} />
            {formError && <div className="mb-3"><ErrorMessage>{formError}</ErrorMessage></div>}
            <button className="btn-primary w-full" type="submit" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Create guideline"}</button>
            {editing && <button className="btn-secondary mt-2 w-full" type="button" onClick={resetForm}>Cancel editing</button>}
          </form>
        ) : (
          <section className="card p-5">
            <h2 className="font-semibold text-ink-900">Guideline management</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">Guideline editing and version history are available to Admins. Reviewers and Contributors can inspect active standards.</p>
          </section>
        )}
      </div>

      {versionsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setVersionsFor(null); }}>
          <section className="card max-h-[85vh] w-full max-w-2xl overflow-y-auto p-5" role="dialog" aria-modal="true" aria-labelledby="guideline-versions-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="guideline-versions-title" className="text-lg font-semibold text-ink-900">Version history</h2>
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
                      <Badge>{version.snapshot?.is_active ? "Active at save" : "Inactive at save"}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-400">{version.editor || "Former editor"} · {version.created_at ? new Date(version.created_at).toLocaleString() : "date unavailable"}</p>
                    <p className="mt-3 text-sm font-medium">{version.snapshot?.name}</p>
                    <p className="mt-1 text-xs text-ink-600">{version.snapshot?.category} · {version.snapshot?.severity}</p>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-5 text-slate-600">{version.snapshot?.description}</p>
                    {!!version.snapshot?.examples?.length && <ul className="mt-2 list-inside list-disc text-xs text-slate-500">{version.snapshot.examples.map((example, index) => <li key={index}>{example}</li>)}</ul>}
                  </article>
                ))}
              </div>
            ) : <p className="mt-4 text-sm text-slate-500">No saved versions are available.</p>}
          </section>
        </div>
      )}
    </>
  );
}
