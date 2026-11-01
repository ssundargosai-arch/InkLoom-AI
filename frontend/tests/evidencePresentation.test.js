import assert from "node:assert/strict";
import test from "node:test";

import {
  formatVerificationMatchScore,
  getCitationSourceLabel,
  getEvidenceExcerptLabel,
} from "../src/utils/evidencePresentation.js";

test("unsupported excerpts are distinct from conflicting evidence", () => {
  for (const status of ["unsupported", "contradicted"]) {
    const label = getEvidenceExcerptLabel(status);
    assert.match(label, /does not support the claim/);
    assert.doesNotMatch(label, /conflict/i);
  }

  for (const status of ["conflicting", "conflicting_evidence"]) {
    const label = getEvidenceExcerptLabel(status);
    assert.match(label, /sources conflict/);
    assert.doesNotMatch(label, /does not support the claim/);
  }
});

test("supported, expired, unverified, and unknown labels remain clear", () => {
  assert.match(getEvidenceExcerptLabel("supported"), /reported as supported/);
  assert.match(getEvidenceExcerptLabel("verified"), /reported as supported/);
  assert.match(getEvidenceExcerptLabel("expired_evidence"), /Historical excerpt/);
  assert.match(getEvidenceExcerptLabel("unverified"), /not verification/);
  assert.match(getEvidenceExcerptLabel("unknown"), /not independently verified/);
  assert.match(getEvidenceExcerptLabel(), /not independently verified/);
});

test("external citations are clearly presented as candidates", () => {
  assert.equal(
    getCitationSourceLabel({ source_type: "external_trusted_source" }),
    "External candidate — not approved or verified",
  );
  assert.equal(
    getCitationSourceLabel({ approval_status: "approved" }),
    "Internal source · approved",
  );
});

test("verification match score is explicitly heuristic and bounded", () => {
  assert.equal(
    formatVerificationMatchScore(0.8),
    "80% heuristic match score (not probability)",
  );
  assert.equal(formatVerificationMatchScore(null), null);
  assert.equal(formatVerificationMatchScore(1.1), null);
});
