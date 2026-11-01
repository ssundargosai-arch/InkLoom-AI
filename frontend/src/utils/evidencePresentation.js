const STATUS_LABELS = {
  supported: "Matched excerpt — reported as supported; verify scope",
  verified: "Matched excerpt — reported as supported; verify scope",
  unsupported: "Matched excerpt — does not support the claim; verify scope",
  contradicted: "Matched excerpt — does not support the claim; verify scope",
  conflicting: "Matched excerpt — sources conflict; reviewer resolution needed",
  conflicting_evidence:
    "Matched excerpt — sources conflict; reviewer resolution needed",
  expired_evidence: "Historical excerpt — expired; not current support",
  unverified: "Related excerpt — not verification",
};

export function getEvidenceExcerptLabel(status) {
  const normalized = String(status || "").trim().toLowerCase();
  return STATUS_LABELS[normalized] || "Related excerpt — not independently verified";
}

export function getCitationSourceLabel(source) {
  if (source?.source_type === "external_trusted_source") {
    return "External candidate — not approved or verified";
  }
  const approvalStatus = String(source?.approval_status || "").trim();
  return approvalStatus
    ? `Internal source · ${approvalStatus}`
    : "Internal source · status unavailable";
}

export function formatVerificationMatchScore(value) {
  if (value === null || value === undefined || value === "") return null;
  const score = Number(value);
  if (!Number.isFinite(score) || score < 0 || score > 1) return null;
  return `${Math.round(score * 100)}% heuristic match score (not probability)`;
}
