import assert from "node:assert/strict";
import test from "node:test";

import { getApprovalWarnings } from "../src/utils/reviewApproval.js";

test("requires acknowledgement for unresolved critical findings and claims", () => {
  const findings = [
    { id: 1, severity: "critical", category: "tone" },
    { id: 2, category: "unsupported_claim" },
    { id: 3, verification_status: "conflicting_evidence" },
    { id: 4, severity: "low", category: "terminology" },
    { id: 5, evidence_status: "expired_evidence" },
    {
      id: 6,
      category: "unsupported_claim",
      verification_status: "verified",
      evidence_status: "supported",
    },
  ];

  assert.deepEqual(
    getApprovalWarnings(findings).map((finding) => finding.id),
    [1, 2, 3, 5],
  );
});

test("does not require acknowledgement for resolved findings", () => {
  const findings = [
    { id: 1, severity: "critical", status: "resolved" },
    { id: 2, category: "unsupported_claim", review_status: "dismissed" },
    { id: 3, verification_status: "unverified", status: "closed" },
  ];

  assert.deepEqual(getApprovalWarnings(findings), []);
});
