
import { mockApi } from "./mockApi";

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

export const MOCK_MODE = import.meta.env.VITE_MOCK_API === "true";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...options,
  });

  const raw = await response.text();
  let data;

  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = raw;
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object"
        ? data.detail || data.message
        : data;

    if (response.status === 401 && path !== "/api/auth/login") {
      window.dispatchEvent(new Event("inkloom:unauthorized"));
    }

    const error = new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || `Request failed (${response.status})`
    );

    error.status = response.status;
    error.detail = detail;
    throw error;
  }

  return data;
}

const json = (method, body) => ({
  method,
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify(body),
});

const realApi = {
  authMe: () => request("/api/auth/me"),

  login: (credentials) =>
    request("/api/auth/login", json("POST", credentials)),

  logout: () =>
    request("/api/auth/logout", { method: "POST" }),

  changePassword: (passwords) =>
    request("/api/auth/password", json("POST", passwords)),

  requestPasswordRecovery: (email) =>
    request(
      "/api/auth/password/forgot",
      json("POST", { email })
    ),

  freshnessOverview: () => request("/api/freshness"),

  runFreshnessCheck: () =>
    request("/api/freshness/check", { method: "POST" }),

  resetPassword: (token, newPassword) =>
    request(
      "/api/auth/password/reset",
      json("POST", {
        token,
        new_password: newPassword,
      })
    ),

  acceptInvitation: (token, newPassword) =>
    request(
      "/api/auth/invitations/accept",
      json("POST", {
        token,
        new_password: newPassword,
      })
    ),

  users: () => request("/api/auth/users"),

  createUser: (data) =>
    request("/api/auth/users", json("POST", data)),

  resendInvitation: (id) =>
    request(
      `/api/auth/users/${encodeURIComponent(id)}/invitation`,
      { method: "POST" }
    ),

  updateUser: (id, data) =>
    request(
      `/api/auth/users/${encodeURIComponent(id)}`,
      json("PATCH", data)
    ),

  health: () => request("/api/health"),

  guidelines: () => request("/api/guidelines"),

  guidelineDiagnostics: () => request("/api/guidelines/diagnostics"),

  brandVoiceConfiguration: () => request("/api/guidelines/brand-voice"),

  updateBrandVoiceConfiguration: (data) =>
    request("/api/guidelines/brand-voice", json("PUT", data)),

  brandVoiceVersions: () =>
    request("/api/guidelines/brand-voice/versions"),

  createGuideline: (data) =>
    request("/api/guidelines", json("POST", data)),

  updateGuideline: (id, data) =>
    request(
      `/api/guidelines/${encodeURIComponent(id)}`,
      json("PATCH", data),
    ),

  guidelineVersions: (id) =>
    request(`/api/guidelines/${encodeURIComponent(id)}/versions`),

  guidelineCategories: () => request("/api/guidelines/categories"),

  reviewGuideline: (id, note) =>
    request(
      `/api/guidelines/${encodeURIComponent(id)}/review`,
      json("POST", { note }),
    ),

  deleteGuideline: (id) =>
    request(
      `/api/guidelines/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),

  sources: () => request("/api/sources"),

  source: (id) => request(`/api/sources/${encodeURIComponent(id)}`),

  createSource: (data) =>
    request("/api/sources", json("POST", data)),

  updateSource: (id, data) =>
    request(`/api/sources/${encodeURIComponent(id)}`, json("PATCH", data)),

  sourceVersions: (id) =>
    request(`/api/sources/${encodeURIComponent(id)}/versions`),

  reviewSource: (id, status, note) =>
    request(
      `/api/sources/${encodeURIComponent(id)}/approval`,
      json("PATCH", { status, note })
    ),

  verifySourceFreshness: (id, note) =>
    request(
      `/api/sources/${encodeURIComponent(id)}/verify`,
      json("POST", { note }),
    ),

  uploadSource: (data) => {
    const form = new FormData();

    form.append("file", data.file);

    if (data.name) form.append("name", data.name);
    if (data.description) form.append("description", data.description);
    if (data.source_type) form.append("source_type", data.source_type);
    if (data.approval_status) {
      form.append("approval_status", data.approval_status);
    }
    if (data.guideline_id) {
      form.append("guideline_id", data.guideline_id);
    }
    if (data.url) form.append("url", data.url);
    ["source_date", "valid_from", "valid_until", "expiry_date", "review_interval_days"].forEach((key) => {
      if (data[key] != null && data[key] !== "") form.append(key, data[key]);
    });

    return request("/api/sources/upload", {
      method: "POST",
      body: form,
    });
  },

  deleteSource: (id) =>
    request(
      `/api/sources/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),

  visualAssets: (filters = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== "" && value != null) params.set(key, String(value));
    });
    const query = params.toString();
    return request(`/api/visual-assets${query ? `?${query}` : ""}`);
  },

  uploadVisualAsset: (data) => {
    const form = new FormData();
    form.append("file", data.file);
    ["name", "asset_type", "description", "usage_restrictions", "valid_from", "expiry_date"].forEach((key) => {
      if (data[key]) form.append(key, data[key]);
    });
    return request("/api/visual-assets", { method: "POST", body: form });
  },

  updateVisualAsset: (id, data) =>
    request(`/api/visual-assets/${encodeURIComponent(id)}`, json("PATCH", data)),

  replaceVisualAssetFile: (id, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/visual-assets/${encodeURIComponent(id)}/file`, {
      method: "PUT",
      body: form,
    });
  },

  reviewVisualAsset: (id, status, note) =>
    request(
      `/api/visual-assets/${encodeURIComponent(id)}/approval`,
      json("PATCH", { status, note }),
    ),

  analyze: (data) =>
    data.file
      ? (() => {
        const form = new FormData();

        form.append("title", data.title);
        form.append("content", data.content);
        form.append("content_type", data.content_type);
        form.append("alt_text", data.alt_text || "");

        form.append(
          "allow_external_verification",
          String(Boolean(data.allow_external_verification))
        );

        form.append("file", data.file);

        if (data.guideline_ids?.length) {
          form.append(
            "guideline_ids",
            JSON.stringify(data.guideline_ids)
          );
        }

        if (data.source_ids?.length) {
          form.append(
            "source_ids",
            JSON.stringify(data.source_ids)
          );
        }

        return request("/api/analyze", {
          method: "POST",
          body: form,
        });
      })()
      : request(
        "/api/analyze",
        json("POST", {
          title: data.title,
          content: data.content,
          content_type: data.content_type,
          guideline_ids: data.guideline_ids || [],
          source_ids: data.source_ids || [],
          alt_text: data.alt_text || "",
          allow_external_verification: Boolean(
            data.allow_external_verification
          ),
        })
      ),

  reviewActivity: (id) =>
    request(`/api/reviews/${encodeURIComponent(id)}/activity`),

  publishReadiness: (id) =>
    request(`/api/reviews/${encodeURIComponent(id)}/publish-readiness`),

  publishHistory: (id) =>
    request(`/api/reviews/${encodeURIComponent(id)}/publish-history`),

  publishReview: (id) =>
    request(`/api/reviews/${encodeURIComponent(id)}/publish`, {
      method: "POST",
    }),

  overridePublish: (id, reason) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/publish/override`,
      json("POST", { reason }),
    ),

  reviews: ({ offset = 0, limit = 20, status } = {}) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    if (status && status !== "all") params.set("status", status);
    return request(`/api/reviews?${params}`);
  },

  reviewers: () => request("/api/reviews/reviewers"),

  assignReviewer: (id, reviewerId) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/assignment`,
      json("PATCH", { reviewer_id: reviewerId }),
    ),

  assignReviewers: (id, reviewers) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/assignments`,
      json("PUT", { reviewers }),
    ),

  submitApprovalDecision: (id, decision) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/approval-decisions`,
      json("POST", decision),
    ),

  bypassApprovalStages: (id, data) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/approval-bypass`,
      json("POST", data),
    ),

  compareReviewVersions: (id, fromVersionId, toVersionId) => {
    const params = new URLSearchParams({
      from_version_id: String(fromVersionId),
      to_version_id: String(toVersionId),
    });
    return request(
      `/api/reviews/${encodeURIComponent(id)}/revisions/compare?${params}`,
    );
  },

  review: (id) =>
    request(`/api/reviews/${encodeURIComponent(id)}`),

  // The backend accepts the earlier conflict-specific key for compatibility.
  updateStatus: (id, status, acknowledgeWarnings = false, reason = "") =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/status`,
      json("PATCH", {
        status,
        acknowledge_warnings: acknowledgeWarnings,
        reason: reason || undefined,
      })
    ),

  addComment: (id, comment, options = {}) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/comments`,
      json("POST", {
        comment,
        is_internal: Boolean(options.is_internal),
        parent_id: options.parent_id || undefined,
      })
    ),

  addRevision: (id, revision) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/revisions`,
      json("POST", revision)
    ),

  reanalyze: (id, revision) =>
    request(
      `/api/reviews/${encodeURIComponent(id)}/reanalyze`,
      json("POST", revision)
    ),

  analytics: (startDate, endDate) => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const query = params.toString();
    return request(`/api/analytics/summary${query ? `?${query}` : ""}`);
  },

  blindSpots: (startDate, endDate) => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const query = params.toString();
    return request(
      `/api/analytics/guideline-blind-spots${query ? `?${query}` : ""}`,
    );
  },
};

export const api = MOCK_MODE ? mockApi : realApi;

export function unwrapList(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.results)) return value.results;
  if (Array.isArray(value?.data)) return value.data;

  for (const key of [
    "guidelines",
    "reviews",
    "findings",
    "issues",
    "comments",
    "revisions",
  ]) {
    if (Array.isArray(value?.[key])) {
      return value[key];
    }
  }

  return [];
}

export function errorMessage(error) {
  if (!(error instanceof Error)) return "Something went wrong. Please try again.";
  const detail = error.detail;
  if (detail && typeof detail === "object") {
    const blockerMessages = Array.isArray(detail.blockers)
      ? detail.blockers.map((blocker) => blocker.message).filter(Boolean)
      : [];
    return [detail.message || error.message, ...blockerMessages]
      .filter(Boolean)
      .join(" ");
  }
  return error.message;
}
