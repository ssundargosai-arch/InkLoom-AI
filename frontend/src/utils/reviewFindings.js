const EVIDENCE_STATUS_ALIASES = {
  supported: "supported",
  verified: "supported",
  unsupported: "unsupported",
  contradicted: "unsupported",
  conflicting: "conflicting",
  conflicting_evidence: "conflicting",
  expired_evidence: "expired_evidence",
  unverified: "unverified",
};

function normalizeEvidenceStatus(status) {
  if (typeof status !== "string") return null;
  return EVIDENCE_STATUS_ALIASES[status.trim().toLowerCase()] || null;
}

export function getEvidenceStatus(finding) {
  return (
    normalizeEvidenceStatus(finding?.evidence_status) ||
    normalizeEvidenceStatus(finding?.verification_status) ||
    "not_assessed"
  );
}

export function summarizeEvidenceStatuses(findings) {
  const summary = {
    supported: 0,
    unsupported: 0,
    conflicting: 0,
    expired_evidence: 0,
    unverified: 0,
    not_assessed: 0,
  };
  if (!Array.isArray(findings)) return summary;

  for (const finding of findings) {
    summary[getEvidenceStatus(finding)] += 1;
  }
  return summary;
}

export function getReviewContentVersions(
  versions,
  currentVersionId,
  fallbackContent,
) {
  const history = Array.isArray(versions) ? versions : [];
  const originalVersion =
    history.find((version) => version?.is_original === true) ||
    history.find((version) => String(version?.id) === "0");
  const currentVersion =
    history.find(
      (version) =>
        currentVersionId != null &&
        String(version?.id) === String(currentVersionId),
    ) ||
    [...history].reverse().find((version) => version?.is_original !== true);

  const content = (version) =>
    typeof version?.content === "string" ? version.content : null;
  const fallback =
    typeof fallbackContent === "string" ? fallbackContent : null;

  return {
    originalContent: content(originalVersion),
    currentContent: content(currentVersion) ?? fallback,
  };
}

export function getConfidenceBand(finding) {
  const rawConfidence = finding?.confidence;
  if (rawConfidence == null || rawConfidence === "") return "unknown";
  const confidence = Number(rawConfidence);
  if (!Number.isFinite(confidence)) return "unknown";
  if (confidence >= 0.8) return "high";
  if (confidence >= 0.5) return "medium";
  return "low";
}

export function filterReviewFindings(findings, filters = {}) {
  if (!Array.isArray(findings)) return [];

  const {
    severity = "all",
    category = "all",
    evidence = "all",
    reviewStatus = "all",
    confidence = "all",
    search = "",
  } = filters;
  const normalizedSearch = String(search).trim().toLowerCase();

  return findings
    .map((finding, index) => ({ finding, index }))
    .filter(({ finding }) => {
      const findingSeverity = String(
        finding?.severity || "medium",
      ).toLowerCase();
      const findingCategory = String(
        finding?.category || finding?.type || "other",
      ).toLowerCase();
      const findingReviewStatus = String(
        finding?.review_status || finding?.status || "pending",
      ).toLowerCase();
      const evidenceExcerpts = [
        ...(Array.isArray(finding?.citations) ? finding.citations : []),
        ...(Array.isArray(finding?.evidence) ? finding.evidence : []),
        ...(finding?.evidence && !Array.isArray(finding.evidence)
          ? [finding.evidence]
          : []),
      ]
        .map((source) =>
          typeof source === "string" ? source : source?.excerpt,
        )
        .filter((excerpt) => typeof excerpt === "string");
      const searchText = [
        finding?.title,
        finding?.explanation,
        finding?.matched_text,
        finding?.evidence_excerpt,
        finding?.citation_excerpt,
        ...evidenceExcerpts,
      ]
        .filter((value) => typeof value === "string")
        .join("\n")
        .toLowerCase();

      return (
        (severity === "all" ||
          (severity === "critical_high"
            ? ["critical", "high"].includes(findingSeverity)
            : findingSeverity === severity)) &&
        (category === "all" || findingCategory === category) &&
        (evidence === "all" || getEvidenceStatus(finding) === evidence) &&
        (reviewStatus === "all" || findingReviewStatus === reviewStatus) &&
        (confidence === "all" || getConfidenceBand(finding) === confidence) &&
        (!normalizedSearch || searchText.includes(normalizedSearch))
      );
    });
}
