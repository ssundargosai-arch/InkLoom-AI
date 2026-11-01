const RESOLVED_STATUSES = new Set([
  "accepted",
  "closed",
  "dismissed",
  "fixed",
  "resolved",
]);
const CLAIM_CATEGORIES = new Set([
  "promotional_claim",
  "unsupported_claim",
  "unsupported_promotional_claim",
]);
const CLAIM_VERIFICATION_STATUSES = new Set([
  "contradicted",
  "conflicting_evidence",
  "expired_evidence",
  "unverified",
  "unsupported",
  "conflicting",
]);

export function getApprovalWarnings(findings) {
  if (!Array.isArray(findings)) return [];

  return findings.filter((finding) => {
    const reviewStatus = String(
      finding?.review_status || finding?.status || "pending",
    ).toLowerCase();
    if (RESOLVED_STATUSES.has(reviewStatus)) return false;

    const category = String(finding?.category || "").toLowerCase();
    const evidenceStatus = String(
      finding?.evidence_status || finding?.verification_status || "",
    ).toLowerCase();
    const unsupportedClaim =
      CLAIM_CATEGORIES.has(category) &&
      !["supported", "verified"].includes(evidenceStatus);

    return (
      String(finding?.severity || "").toLowerCase() === "critical" ||
      unsupportedClaim ||
      CLAIM_VERIFICATION_STATUSES.has(evidenceStatus)
    );
  });
}
