import { useEffect, useMemo, useState } from "react";
import { Check, FileImage, LoaderCircle, Search, ShieldCheck, Upload, X } from "lucide-react";
import { API_BASE_URL, api, errorMessage, MOCK_MODE } from "../services/api";
import { Badge, EmptyState, ErrorMessage, PageHeader, SuccessMessage } from "../components/common/UI";
import { useAuth } from "../contexts/AuthContext";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const allowedTypes = new Set(["image/png", "image/jpeg", "image/webp", "application/pdf"]);

function isImage(asset) {
  return asset.media_type?.startsWith("image/");
}

export default function VisualAssetsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || MOCK_MODE;
  const canSubmit = isAdmin || user?.role === "contributor";
  const [assets, setAssets] = useState([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [assetType, setAssetType] = useState("logo");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [restrictions, setRestrictions] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [rejectionNotes, setRejectionNotes] = useState({});
  const [editing, setEditing] = useState(null);
  const [editFields, setEditFields] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = async () => {
    const result = await api.visualAssets();
    setAssets(Array.isArray(result) ? result : []);
  };

  useEffect(() => {
    refresh().catch((err) => setError(errorMessage(err)));
  }, []);

  const visibleAssets = useMemo(() => assets.filter((asset) => {
    const matchesText = `${asset.name} ${asset.description || ""} ${asset.asset_type}`.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = statusFilter === "all" || asset.lifecycle_status === statusFilter;
    const matchesType = typeFilter === "all" || asset.asset_type === typeFilter;
    return matchesText && matchesStatus && matchesType;
  }), [assets, search, statusFilter, typeFilter]);

  const chooseFile = (selected) => {
    setFileError("");
    if (!selected) return;
    const extension = selected.name.split(".").pop()?.toLowerCase();
    if (!["png", "jpg", "jpeg", "webp", "pdf"].includes(extension) ||
      (selected.type && !allowedTypes.has(selected.type))) {
      setFileError("Choose a valid PNG, JPG, WEBP, or PDF file.");
      return;
    }
    if (selected.size > MAX_FILE_SIZE) {
      setFileError("File must be 10 MB or smaller.");
      return;
    }
    setFile(selected);
  };

  const upload = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    if (!file) {
      setFileError("Choose a file to submit.");
      return;
    }
    setBusy(true);
    try {
      await api.uploadVisualAsset({
        file,
        name: name.trim(),
        asset_type: assetType,
        description: description.trim(),
        usage_restrictions: restrictions.trim(),
        valid_from: validFrom,
        expiry_date: expiryDate,
      });
      setFile(null);
      setName("");
      setDescription("");
      setRestrictions("");
      setValidFrom("");
      setExpiryDate("");
      setNotice("Asset submitted for Admin approval. It will not be used by analysis until approved and active.");
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const updateAsset = async (id, patch) => {
    setError("");
    setBusy(true);
    try {
      await api.updateVisualAsset(id, patch);
      setEditing(null);
      setNotice("Asset updated. Approval is required before it can be used again.");
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const replaceFile = async (asset, replacement) => {
    if (!replacement) return;
    if (replacement.size > MAX_FILE_SIZE) {
      setError("Replacement file must be 10 MB or smaller.");
      return;
    }
    const extension = replacement.name.split(".").pop()?.toLowerCase();
    if (!["png", "jpg", "jpeg", "webp", "pdf"].includes(extension) ||
      (replacement.type && !allowedTypes.has(replacement.type))) {
      setError("Choose a valid PNG, JPG, WEBP, or PDF replacement.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.replaceVisualAssetFile(asset.id, replacement);
      setNotice("File replaced. The new revision requires Admin approval before use.");
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reviewAsset = async (asset, status) => {
    const note = rejectionNotes[asset.id]?.trim() || "";
    if (status === "rejected" && !note) {
      setError("Enter a rejection reason before rejecting an asset.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      await api.reviewVisualAsset(asset.id, status, note);
      setNotice(`Asset ${status}.`);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Brand resources"
        title="Visual asset library"
        description="Manage approved logos and visual resources. Uploaded files remain private and are only available to analysis after Admin approval."
      />
      {MOCK_MODE && (
        <p className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Demo mode: uploads and approval changes stay in this browser session only. They are not sent to or saved by the backend.
        </p>
      )}
      {error && <div className="mb-4"><ErrorMessage>{error}</ErrorMessage></div>}
      {notice && <div className="mb-4"><SuccessMessage>{notice}</SuccessMessage></div>}

      {canSubmit && (
        <form onSubmit={upload} className="card mb-6 p-5 sm:p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="rounded-lg bg-ink-50 p-2 text-ink-700"><Upload size={18} /></div>
            <div>
              <h2 className="font-semibold text-ink-900">Submit a visual asset</h2>
              <p className="mt-1 text-xs text-slate-500">PNG, JPG, WEBP, or PDF · maximum 10 MB</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-700">
              Asset name
              <input className="field mt-1" value={name} onChange={(event) => setName(event.target.value)} maxLength={160} placeholder="Primary logo" />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Asset category
              <select className="field mt-1" value={assetType} onChange={(event) => setAssetType(event.target.value)}>
                {["logo", "brand_icon", "illustration", "product_image", "template", "background", "other"].map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}
              </select>
            </label>
            <label className="text-sm font-medium text-slate-700 md:col-span-2">
              Description
              <textarea className="field mt-1 min-h-20" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={4000} />
            </label>
            <label className="text-sm font-medium text-slate-700 md:col-span-2">
              Usage restrictions
              <input className="field mt-1" value={restrictions} onChange={(event) => setRestrictions(event.target.value)} maxLength={4000} placeholder="e.g. Use on light backgrounds only" />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Valid from (optional)
              <input className="field mt-1" type="date" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Expires (optional)
              <input className="field mt-1" type="date" value={expiryDate} onChange={(event) => setExpiryDate(event.target.value)} min={validFrom || undefined} />
            </label>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <input type="file" accept=".png,.jpg,.jpeg,.webp,.pdf,image/png,image/jpeg,image/webp,application/pdf" onChange={(event) => chooseFile(event.target.files?.[0])} aria-label="Select visual asset" />
            {file && <span className="text-sm text-slate-600">{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB</span>}
            <button type="submit" className="btn-primary ml-auto" disabled={busy || Boolean(fileError) || MOCK_MODE}>
              {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Upload size={16} />}
              Submit for approval
            </button>
          </div>
          {fileError && <p role="alert" className="mt-2 text-sm text-rose-700">{fileError}</p>}
        </form>
      )}

      <section className="card overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-end">
          <label className="flex-1 text-xs font-medium text-slate-500">
            Search assets
            <span className="relative mt-1 block">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input className="field pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, description, category" />
            </span>
          </label>
          <label className="text-xs font-medium text-slate-500">
            Lifecycle
            <select className="field mt-1 min-w-44" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">All statuses</option>
              {["pending", "approved", "rejected", "expired", "inactive", "not_yet_valid"].map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-500">
            Category
            <select className="field mt-1 min-w-40" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="all">All categories</option>
              {["logo", "brand_icon", "illustration", "product_image", "template", "background", "other"].map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}
            </select>
          </label>
        </div>
        {!visibleAssets.length ? (
          <EmptyState icon={FileImage} title="No visual assets found" description="Approved visual assets will appear here with their lifecycle, preview, and usage restrictions." />
        ) : (
          <div className="divide-y divide-slate-100">
            {visibleAssets.map((asset) => (
              <article key={asset.id} className="grid gap-4 p-4 sm:grid-cols-[minmax(160px,260px)_1fr] sm:p-5">
                <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                  {isImage(asset) ? (
                    <img src={asset.preview_url || `${API_BASE_URL}${asset.file_url}`} alt={asset.name} className="max-h-56 w-full object-contain" />
                  ) : asset.media_type === "application/pdf" ? (
                    <iframe title={`${asset.name} PDF preview`} src={asset.preview_url || `${API_BASE_URL}${asset.file_url}`} className="h-56 w-full" />
                  ) : (
                    <div className="flex h-40 items-center justify-center text-sm text-slate-500">Preview unavailable</div>
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold text-ink-900">{asset.name}</h3>
                    <Badge>{asset.asset_type?.replaceAll("_", " ")}</Badge>
                    <Badge tone={asset.lifecycle_status === "approved" ? "approved" : "status"}>{asset.lifecycle_status?.replaceAll("_", " ")}</Badge>
                    <span className="text-xs text-slate-400">v{asset.version}</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{asset.description || "No description provided."}</p>
                  {asset.usage_restrictions && <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">Usage: {asset.usage_restrictions}</p>}
                  <p className="mt-2 text-xs text-slate-400">
                    Uploaded by {asset.uploaded_by || "Workspace member"} · {asset.valid_from ? `valid from ${asset.valid_from}` : "no start date"} · {asset.expiry_date ? `expires ${asset.expiry_date}` : "no expiry"}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    Created {asset.created_at ? new Date(asset.created_at).toLocaleString() : "date unavailable"} · Modified {asset.updated_at ? new Date(asset.updated_at).toLocaleString() : "date unavailable"}{asset.updated_by ? ` by ${asset.updated_by}` : ""}
                  </p>
                  {asset.reviewed_at && <p className="mt-1 text-xs text-slate-400">Reviewed {new Date(asset.reviewed_at).toLocaleString()}{asset.reviewed_by ? ` by ${asset.reviewed_by}` : ""}</p>}
                  {asset.review_note && <p className="mt-2 text-xs text-slate-500">Review note: {asset.review_note}</p>}

                  {isAdmin && editing === asset.id ? (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <input className="field" aria-label="Edit asset name" value={editFields.name || ""} onChange={(event) => setEditFields((current) => ({ ...current, name: event.target.value }))} />
                      <input className="field" aria-label="Edit usage restrictions" value={editFields.usage_restrictions || ""} onChange={(event) => setEditFields((current) => ({ ...current, usage_restrictions: event.target.value }))} placeholder="Usage restrictions" />
                      <select className="field" aria-label="Edit asset category" value={editFields.asset_type || asset.asset_type} onChange={(event) => setEditFields((current) => ({ ...current, asset_type: event.target.value }))}>
                        {["logo", "brand_icon", "illustration", "product_image", "template", "background", "other"].map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}
                      </select>
                      <input className="field" aria-label="Edit valid from date" type="date" value={editFields.valid_from || ""} onChange={(event) => setEditFields((current) => ({ ...current, valid_from: event.target.value }))} />
                      <input className="field" aria-label="Edit expiry date" type="date" value={editFields.expiry_date || ""} onChange={(event) => setEditFields((current) => ({ ...current, expiry_date: event.target.value }))} />
                      <textarea className="field min-h-16 sm:col-span-2" aria-label="Edit asset description" value={editFields.description || ""} onChange={(event) => setEditFields((current) => ({ ...current, description: event.target.value }))} />
                      <button type="button" className="btn-primary" disabled={busy} onClick={() => updateAsset(asset.id, { ...editFields, valid_from: editFields.valid_from || null, expiry_date: editFields.expiry_date || null })}><Check size={15} /> Save changes</button>
                      <button type="button" className="btn-secondary" onClick={() => setEditing(null)}><X size={15} /> Cancel</button>
                    </div>
                  ) : (
                    isAdmin && (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <button type="button" className="btn-secondary !py-1.5 !text-xs" onClick={() => {
                          setEditing(asset.id);
                          setEditFields({ name: asset.name, description: asset.description || "", usage_restrictions: asset.usage_restrictions || "", asset_type: asset.asset_type, valid_from: asset.valid_from || "", expiry_date: asset.expiry_date || "" });
                        }}>Edit details</button>
                        <button type="button" className="btn-secondary !py-1.5 !text-xs" disabled={busy} onClick={() => updateAsset(asset.id, { is_active: !asset.is_active })}>
                          {asset.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                        <label className="btn-secondary !py-1.5 !text-xs">
                          Replace file
                          <input
                            type="file"
                            className="sr-only"
                            accept=".png,.jpg,.jpeg,.webp,.pdf,image/png,image/jpeg,image/webp,application/pdf"
                            disabled={busy}
                            aria-label={`Replace file for ${asset.name}`}
                            onChange={(event) => {
                              replaceFile(asset, event.target.files?.[0]);
                              event.target.value = "";
                            }}
                          />
                        </label>
                        {["pending", "draft"].includes(asset.approval_status) && <>
                          <button type="button" className="btn-primary !py-1.5 !text-xs" disabled={busy} onClick={() => reviewAsset(asset, "approved")}><Check size={14} /> Approve</button>
                          <input className="field max-w-56 !py-1.5 text-xs" aria-label={`Rejection reason for ${asset.name}`} placeholder="Reason required to reject" value={rejectionNotes[asset.id] || ""} onChange={(event) => setRejectionNotes((current) => ({ ...current, [asset.id]: event.target.value }))} />
                          <button type="button" className="btn-secondary !py-1.5 !text-xs" disabled={busy} onClick={() => reviewAsset(asset, "rejected")}>Reject</button>
                        </>}
                      </div>
                    )
                  )}
                  {asset.expiry_date && new Date(`${asset.expiry_date}T00:00:00`) < new Date(new Date().toDateString()) && (
                    <p className="mt-2 text-xs font-medium text-rose-700">Expired assets are excluded from visual comparison.</p>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
        {isAdmin && <p className="border-t border-slate-100 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500"><ShieldCheck size={14} className="mr-1 inline" />Only active, approved, currently valid logo and icon assets are used for coarse similarity comparison. Uploading or editing does not approve an asset.</p>}
      </section>
    </>
  );
}
