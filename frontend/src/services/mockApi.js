const wait = (value) => new Promise((resolve) => setTimeout(() => resolve(value), 350));

let mockRevisionSequence = 0;

function createMockRevisionId() {
  mockRevisionSequence += 1;
  return `rev-${Date.now()}-${mockRevisionSequence}`;
}

function ensureOriginalAnalysisRun(review) {
  if (
    review.analysis_runs?.length ||
    review.revisions?.length ||
    typeof review.content !== "string"
  ) {
    return;
  }

  const createdAt = review.submitted_at || new Date().toISOString();
  review.analysis_runs = [{
    id: `run-${Date.now()}`,
    content: review.content,
    findings: review.findings || [],
    analysis_engine: "mock",
    warnings: [],
    created_at: createdAt,
    is_original: true,
  }];
}

function withReviewVersionHistory(review) {
  const analysisRuns = Array.isArray(review.analysis_runs)
    ? review.analysis_runs
    : [];
  const revisions = Array.isArray(review.revisions) ? review.revisions : [];
  const versions = [];

  const originalRun =
    analysisRuns.find((run) => run.is_original === true) ||
    (revisions.length === 0 ? analysisRuns[0] : null);
  if (originalRun) {
    versions.push({
      id: 0,
      content: originalRun.content,
      title: "Original submission",
      author: originalRun.created_by || null,
      author_id: originalRun.created_by_id ?? null,
      created_at: originalRun.created_at,
      is_original: true,
    });
  }

  versions.push(
    ...revisions.map((revision) => ({
      id: revision.id,
      content: revision.content,
      title: revision.title || "Revision",
      author: revision.author || null,
      author_id: revision.author_id ?? null,
      created_at: revision.created_at,
      is_original: false,
    })),
  );

  return {
    ...review,
    versions,
    current_version_id: versions.length
      ? versions[versions.length - 1].id
      : null,
  };
}

const reviews = [
  {
    id: "rv-1048",
    title: "Autumn collection launch",
    content_type: "Campaign",
    status: "in_review",
    submitted_at: "2026-10-25T10:30:00Z",
    issue_count: 3,
    reviewer: "Maya Chen",
    content: "Meet the ultimate autumn collection. Our new pieces are guaranteed to transform your everyday wardrobe.",
    findings: [
      { id: "f1", category: "Claims", severity: "high", explanation: "Absolute performance language needs substantiation.", matched_text: "guaranteed to transform", suggestion: "designed to refresh", guideline: "Substantiated claims", confidence: 0.94, status: "open" },
      { id: "f2", category: "Tone of voice", severity: "medium", explanation: "“Ultimate” is more superlative than the approved brand voice.", matched_text: "ultimate", suggestion: "considered", guideline: "Confident, never boastful", confidence: 0.89, status: "open" },
      { id: "f3", category: "Terminology", severity: "low", explanation: "Use the preferred product term in campaign copy.", matched_text: "pieces", suggestion: "essentials", guideline: "Product vocabulary", confidence: 0.83, status: "open" },
    ],
    revisions: [],
    comments: [],
  },
  { id: "rv-1047", title: "Welcome email refresh", content_type: "Email", status: "approved", submitted_at: "2026-10-24T14:05:00Z", issue_count: 1, reviewer: "Eli Morgan", content: "A warmer welcome to your new routine.", findings: [], revisions: [], comments: [] },
  { id: "rv-1046", title: "Product page: Cloud Knit", content_type: "Product page", status: "changes_requested", submitted_at: "2026-10-23T09:20:00Z", issue_count: 4, reviewer: "Jordan Lee", content: "Soft, sustainable comfort for every day.", findings: [], revisions: [], comments: [] },
];

const guidelines = [
  { id: "g1", name: "Confident, never boastful", category: "Tone of voice", severity: "medium", description: "Use clear, assured language. Avoid superlatives and absolute promises.", status: "approved" },
  { id: "g2", name: "Substantiated claims", category: "Claims", severity: "high", description: "Promotional or performance claims must have current supporting evidence.", status: "approved" },
  { id: "g3", name: "Product vocabulary", category: "Terminology", severity: "low", description: "Use approved product names and preferred customer-facing terms.", status: "approved" },
];
const sources = [];
const visualAssets = [];
const emptyBrandVoiceConfiguration = {
  desired_tones: [],
  voice_attributes: [],
  preferred_expressions: [],
  prohibited_expressions: [],
  target_audiences: [],
  supported_channels: [],
  messaging_principles: [],
};
let brandVoiceConfiguration = { ...emptyBrandVoiceConfiguration };
let brandVoiceVersion = 0;
const brandVoiceHistory = [];

export const mockApi = {
  health: () => wait({ status: "ok", mode: "mock", password_recovery_enabled: false }),
  requestPasswordRecovery: async () => {
    throw new Error("Password recovery is unavailable in mock mode.");
  },
  resetPassword: async () => {
    throw new Error("Password recovery is unavailable in mock mode.");
  },
  acceptInvitation: async () => {
    throw new Error("Invitations are unavailable in mock mode.");
  },
  users: async () => {
    throw new Error("Workspace member management is unavailable in mock mode.");
  },
  createUser: async () => {
    throw new Error("Workspace member management is unavailable in mock mode.");
  },
  resendInvitation: async () => {
    throw new Error("Workspace member management is unavailable in mock mode.");
  },
  updateUser: async () => {
    throw new Error("Workspace member management is unavailable in mock mode.");
  },
  guidelines: () => wait(guidelines),
  guidelineDiagnostics: async () => {
    throw new Error("Guideline diagnostics are unavailable in mock mode.");
  },
  brandVoiceConfiguration: () =>
    wait({
      ...brandVoiceConfiguration,
      version_number: brandVoiceVersion,
      updated_by: brandVoiceVersion ? "Mock workspace" : null,
      updated_at: brandVoiceHistory[0]?.created_at || null,
    }),
  updateBrandVoiceConfiguration: async (data) => {
    const configuration = Object.fromEntries(
      Object.entries(emptyBrandVoiceConfiguration).map(([key]) => [
        key,
        [...(data[key] || [])],
      ]),
    );
    if (JSON.stringify(configuration) !== JSON.stringify(brandVoiceConfiguration)) {
      brandVoiceVersion += 1;
      brandVoiceConfiguration = configuration;
      brandVoiceHistory.unshift({
        version_number: brandVoiceVersion,
        snapshot: { ...configuration },
        editor: "Mock workspace",
        created_at: new Date().toISOString(),
      });
    }
    return wait({
      ...brandVoiceConfiguration,
      version_number: brandVoiceVersion,
      updated_by: brandVoiceVersion ? "Mock workspace" : null,
      updated_at: brandVoiceHistory[0]?.created_at || null,
    });
  },
  brandVoiceVersions: () => wait([...brandVoiceHistory]),
  createGuideline: async (data) => {
    const now = new Date().toISOString();
    const item = { ...data, id: `g${Date.now()}`, status: "approved", created_at: now, updated_at: now, version: 1 };
    guidelines.unshift(item);
    return wait(item);
  },
  updateGuideline: async (id, data) => {
    const item = guidelines.find((guideline) => String(guideline.id) === String(id));
    if (!item) throw new Error("Guideline not found");
    Object.assign(item, data, { updated_at: new Date().toISOString(), version: (item.version || 1) + 1 });
    return wait(item);
  },
  guidelineVersions: async (id) => {
    const item = guidelines.find((guideline) => String(guideline.id) === String(id));
    return wait(item ? [{ version_number: item.version || 1, snapshot: { ...item }, editor: "Mock workspace", created_at: item.updated_at }] : []);
  },
  guidelineCategories: () => wait([...new Set(guidelines.map((item) => item.category).filter(Boolean))]),
  deleteGuideline: async (id) => {
    const index = guidelines.findIndex((item) => String(item.id) === String(id));
    if (index >= 0) guidelines.splice(index, 1);
    return wait({ success: true });
  },
  sources: () => wait(sources),
  createSource: async (data) => {
    const now = new Date().toISOString();
    const source = { ...data, id: `source-${Date.now()}`, approval_status: data.approval_status || "pending", lifecycle_status: data.approval_status || "pending", is_active: true, created_at: now, updated_at: now };
    sources.unshift(source);
    return wait(source);
  },
  updateSource: async (id, data) => {
    const source = sources.find((item) => String(item.id) === String(id));
    if (!source) throw new Error("Evidence source not found.");
    Object.assign(source, data, { updated_at: new Date().toISOString() });
    if (data.content || data.name || data.source_date || data.expiry_date) source.approval_status = "pending";
    source.lifecycle_status = !source.is_active ? "inactive" : source.approval_status;
    return wait(source);
  },
  reviewSource: async (id, status, note) => {
    const source = sources.find((item) => String(item.id) === String(id));
    if (!source) throw new Error("Evidence source not found.");
    Object.assign(source, {
      approval_status: status,
      lifecycle_status: status,
      reviewed_by: "Mock workspace",
      reviewed_at: new Date().toISOString(),
      review_note: note || null,
    });
    return wait(source);
  },
  uploadSource: async ({ file, ...data }) => {
    if (!file || !/\.(txt|md)$/i.test(file.name)) {
      throw new Error("Mock mode supports TXT and Markdown source uploads only.");
    }
    const source = { ...data, name: data.name || file.name, content: await file.text(), id: `source-${Date.now()}`, approval_status: "pending", created_at: new Date().toISOString() };
    sources.unshift(source);
    return wait(source);
  },
  deleteSource: async (id) => {
    const source = sources.find((item) => String(item.id) === String(id));
    if (source) Object.assign(source, { is_active: false, lifecycle_status: "inactive" });
    return wait({ success: true });
  },
  visualAssets: () => wait(visualAssets),
  uploadVisualAsset: async ({ file, ...data }) => {
    if (!file) throw new Error("Choose a visual asset to submit.");
    const now = new Date().toISOString();
    const item = {
      ...data,
      id: `visual-${Date.now()}`,
      name: data.name || file.name,
      filename: file.name,
      media_type: file.type || "application/octet-stream",
      preview_url: URL.createObjectURL(file),
      version: 1,
      approval_status: "pending",
      lifecycle_status: "pending",
      is_active: true,
      uploaded_by: "Mock workspace",
      uploaded_by_id: "mock",
      created_at: now,
      updated_at: now,
      valid_from: data.valid_from || null,
      expiry_date: data.expiry_date || null,
    };
    visualAssets.unshift(item);
    return wait(item);
  },
  updateVisualAsset: async (id, data) => {
    const item = visualAssets.find((asset) => String(asset.id) === String(id));
    if (!item) throw new Error("Visual asset not found.");
    Object.assign(item, data, {
      version: item.version + 1,
      updated_at: new Date().toISOString(),
    });
    if (item.approval_status === "approved" || data.is_active === true ||
      ["name", "description", "asset_type", "usage_restrictions", "valid_from", "expiry_date"].some((key) => key in data)) {
      item.approval_status = "pending";
    }
    item.lifecycle_status = item.is_active ? item.approval_status : "inactive";
    return wait(item);
  },
  replaceVisualAssetFile: async (id, file) => {
    const item = visualAssets.find((asset) => String(asset.id) === String(id));
    if (!item) throw new Error("Visual asset not found.");
    if (item.preview_url) URL.revokeObjectURL(item.preview_url);
    Object.assign(item, {
      filename: file.name,
      media_type: file.type || "application/octet-stream",
      preview_url: URL.createObjectURL(file),
      version: item.version + 1,
      approval_status: "pending",
      lifecycle_status: "pending",
      updated_at: new Date().toISOString(),
    });
    return wait(item);
  },
  reviewVisualAsset: async (id, status, note) => {
    const item = visualAssets.find((asset) => String(asset.id) === String(id));
    if (!item) throw new Error("Visual asset not found.");
    if (status === "rejected" && !note?.trim()) {
      throw new Error("A rejection reason is required.");
    }
    Object.assign(item, {
      approval_status: status,
      lifecycle_status: !item.is_active ? "inactive" : status,
      reviewed_by: "Mock workspace",
      reviewed_at: new Date().toISOString(),
      review_note: note || null,
      updated_at: new Date().toISOString(),
    });
    return wait(item);
  },
  analyze: async ({ title, content, content_type }) => {
    const review = {
      id: `rv-${Date.now()}`,
      title,
      content,
      content_type,
      status: "pending",
      submitted_at: new Date().toISOString(),
      issue_count: 1,
      findings: [{
        id: `finding-${Date.now()}`,
        category: "Tone of voice",
        severity: "medium",
        explanation: "This illustrative mock finding flags a phrase for review. It is not an AI analysis.",
        matched_text: content.match(/\b(ultimate|guaranteed|best)\b/i)?.[0] || content.split(/\s+/).slice(0, 3).join(" "),
        suggestion: "Review this phrase against your approved brand voice.",
        guideline: "Confident, never boastful",
        confidence: 0.78,
        status: "open",
      }],
      revisions: [],
      comments: [],
      _source: "mock",
    };
    review.analysis_runs = [{
      id: `run-${Date.now()}`,
      content,
      findings: review.findings,
      analysis_engine: "mock",
      warnings: [],
      created_at: review.submitted_at,
      is_original: true,
    }];
    reviews.unshift(review);
    return wait(withReviewVersionHistory(review));
  },
  reviews: ({ offset = 0, limit = 20, status } = {}) => {
    const filtered = status && status !== "all"
      ? reviews.filter((review) => review.status === status)
      : reviews;
    return wait({
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      offset,
      limit,
    });
  },
  reviewers: () => wait([]),
  assignReviewer: async (id, reviewerId) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (!item) throw new Error("Review not found");
    item.assigned_reviewer_id = reviewerId || null;
    item.assigned_reviewer = null;
    return wait(item);
  },
  review: (id) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    return wait(item ? withReviewVersionHistory(item) : null);
  },
  publishReadiness: async () => {
    throw new Error("Publish readiness requires the live backend and is unavailable in mock mode.");
  },
  publishHistory: async () => {
    throw new Error("Publish history requires the live backend and is unavailable in mock mode.");
  },
  publishReview: async () => {
    throw new Error("Publishing requires the live backend and is unavailable in mock mode.");
  },
  overridePublish: async () => {
    throw new Error("Publish overrides require the live backend and are unavailable in mock mode.");
  },
  updateStatus: async (id, status) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (item) item.status = status;
    return wait(item);
  },
  addComment: async (id, comment, options = {}) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (!item) throw new Error("Review not found");
    const entry = { id: `c-${Date.now()}`, comment, is_internal: Boolean(options.is_internal), parent_id: options.parent_id || null, created_at: new Date().toISOString(), author: "You" };
    item.comments = [...(item.comments || []), entry];
    return wait(entry);
  },
  addRevision: async (id, revision) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (!item) throw new Error("Review not found");
    ensureOriginalAnalysisRun(item);
    const entry = {
      id: createMockRevisionId(),
      ...revision,
      created_at: new Date().toISOString(),
    };
    item.revisions = [...(item.revisions || []), entry];
    if (revision.content) item.content = revision.content;
    return wait(entry);
  },
  reanalyze: async (id, revision) => {
    const item = reviews.find((review) => String(review.id) === String(id));
    if (!item) throw new Error("Review not found");
    if (revision.content === item.content) throw new Error("The revision must differ from the current review content.");
    ensureOriginalAnalysisRun(item);
    item.analysis_runs = item.analysis_runs || [];
    const matched = revision.content.match(/\b(ultimate|guaranteed|best)\b/i)?.[0];
    const findings = matched ? [{
      id: `finding-${Date.now()}`,
      category: "Claims",
      severity: "medium",
      title: "Illustrative mock finding",
      explanation: "This mock result is for interface development only.",
      matched_text: matched,
      suggestion: "Review this wording against your approved brand voice.",
      status: "pending",
    }] : [];
    item.revisions = item.revisions || [];
    item.revisions.push({
      id: createMockRevisionId(),
      content: revision.content,
      title: revision.title || "Revision with re-analysis",
      created_at: new Date().toISOString(),
    });
    item.content = revision.content;
    item.findings = findings;
    item.issue_count = findings.length;
    item.status = "pending";
    item.reviewer = null;
    item.analysis_runs.push({
      id: `run-${Date.now()}`,
      content: revision.content,
      findings,
      analysis_engine: "mock",
      warnings: [],
      created_at: new Date().toISOString(),
    });
    return wait(withReviewVersionHistory(item));
  },
  reviewActivity: () => wait([]),
  analytics: () => wait({
    total_reviews: 24,
    total_issues: 63,
    pending_approvals: 5,
    issues_by_severity: { high: 12, medium: 31, low: 20 },
    issues_by_category: [{ category: "Tone of voice", count: 24 }, { category: "Claims", count: 18 }, { category: "Terminology", count: 13 }, { category: "Accessibility", count: 8 }],
    status_distribution: [{ status: "approved", count: 15 }, { status: "in_review", count: 5 }, { status: "changes_requested", count: 4 }],
    frequent_guidelines: [{ name: "Confident, never boastful", count: 16 }, { name: "Substantiated claims", count: 12 }, { name: "Product vocabulary", count: 9 }],
  }),
  blindSpots: () => wait([{ guideline: "Inclusive language", ambiguity_score: 0.72, mentions: 8 }, { guideline: "Sustainability claims", ambiguity_score: 0.58, mentions: 5 }]),
};
