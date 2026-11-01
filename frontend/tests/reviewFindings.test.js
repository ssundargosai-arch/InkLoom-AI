import assert from "node:assert/strict";
import test from "node:test";

import {
  filterReviewFindings,
  getConfidenceBand,
  getEvidenceStatus,
  getReviewContentVersions,
  summarizeEvidenceStatuses,
} from "../src/utils/reviewFindings.js";

test("classifies confidence and evidence without inventing evidence status", () => {
  assert.equal(getConfidenceBand({ confidence: 0.8 }), "high");
  assert.equal(getConfidenceBand({ confidence: 0.79 }), "medium");
  assert.equal(getConfidenceBand({ confidence: 0.2 }), "low");
  assert.equal(getConfidenceBand({}), "unknown");
  assert.equal(getConfidenceBand({ confidence: null }), "unknown");
  assert.equal(
    getEvidenceStatus({
      verification_status: "verified",
      evidence_status: "supported",
    }),
    "supported",
  );
  assert.equal(getEvidenceStatus({ verification_status: "verified" }), "supported");
  assert.equal(
    getEvidenceStatus({ verification_status: "contradicted" }),
    "unsupported",
  );
  assert.equal(
    getEvidenceStatus({ verification_status: "conflicting_evidence" }),
    "conflicting",
  );
  assert.equal(
    getEvidenceStatus({ evidence_status: "expired_evidence" }),
    "expired_evidence",
  );
  assert.equal(getEvidenceStatus({ evidence_status: "unverified" }), "unverified");
  assert.equal(getEvidenceStatus({}), "not_assessed");
  assert.equal(getEvidenceStatus({ evidence_status: "unknown" }), "not_assessed");
  assert.equal(
    getEvidenceStatus({
      evidence_status: "unknown",
      verification_status: "verified",
    }),
    "supported",
  );
});

test("summarizes canonical and legacy evidence statuses exactly once", () => {
  assert.deepEqual(
    summarizeEvidenceStatuses([
      { evidence_status: "supported", verification_status: "verified" },
      { verification_status: "verified" },
      { evidence_status: "unsupported", verification_status: "contradicted" },
      { verification_status: "conflicting_evidence" },
      { evidence_status: "expired_evidence" },
      { verification_status: "unverified" },
      {},
      { evidence_status: "unknown" },
    ]),
    {
      supported: 2,
      unsupported: 1,
      conflicting: 1,
      expired_evidence: 1,
      unverified: 1,
      not_assessed: 2,
    },
  );
});

test("selects original and current versions after reanalysis", () => {
  assert.deepEqual(
    getReviewContentVersions(
      [
        { id: 0, is_original: true, content: "Original copy." },
        { id: 1, is_original: false, content: "First revision." },
        { id: 2, is_original: false, content: "Latest revision." },
      ],
      2,
      "Latest revision.",
    ),
    {
      originalContent: "Original copy.",
      currentContent: "Latest revision.",
    },
  );
});

test("handles missing version history without mislabeling current content", () => {
  assert.deepEqual(
    getReviewContentVersions([], 0, "Current review content."),
    {
      originalContent: null,
      currentContent: "Current review content.",
    },
  );
  assert.deepEqual(getReviewContentVersions(null, null, null), {
    originalContent: null,
    currentContent: null,
  });
});

test("missing original history keeps current revision available without an original", () => {
  const versions = getReviewContentVersions(
    [{ id: 1, is_original: false, content: "Current revision content." }],
    1,
    "Current revision content.",
  );

  assert.deepEqual(versions, {
    originalContent: null,
    currentContent: "Current revision content.",
  });
});

test("combines finding filters and preserves original indexes", () => {
  const findings = [
    {
      severity: "HIGH",
      category: "claims",
      status: "pending",
      confidence: 0.9,
    },
    {
      severity: "low",
      category: "tone",
      verification_status: "verified",
      evidence_status: "supported",
    },
    {
      severity: "high",
      category: "claims",
      verification_status: "unverified",
      evidence_status: "unverified",
      confidence: 0.6,
    },
  ];

  assert.deepEqual(
    filterReviewFindings(findings, {
      severity: "high",
      category: "claims",
      evidence: "unverified",
      confidence: "medium",
    }).map(({ index }) => index),
    [2],
  );
});

test("searches findings case-insensitively across supported text and evidence fields", () => {
  const findings = [
    { title: "Pricing mismatch", explanation: "Check the plan.", matched_text: "Annual plan" },
    { title: "Other finding", explanation: "Evidence supports an annual subscription." },
    {
      title: "Citation finding",
      citations: [{ excerpt: "Current price is $240 per year." }],
    },
  ];

  assert.deepEqual(
    filterReviewFindings(findings, { search: "PRICING" }).map(({ index }) => index),
    [0],
  );
  assert.deepEqual(
    filterReviewFindings(findings, { search: "annual subscription" }).map(
      ({ index }) => index,
    ),
    [1],
  );
  assert.deepEqual(
    filterReviewFindings(findings, { search: "$240 per year" }).map(
      ({ index }) => index,
    ),
    [2],
  );
});

test("combines finding search with existing filters and critical/high quick filter", () => {
  const findings = [
    {
      severity: "critical",
      category: "claims",
      title: "Unsupported offer",
      matched_text: "free forever",
      evidence_status: "unverified",
    },
    {
      severity: "high",
      category: "claims",
      title: "Unsupported fee",
      explanation: "Free setup lacks substantiation.",
      evidence_status: "unverified",
    },
    {
      severity: "medium",
      category: "claims",
      title: "Free trial",
      evidence_status: "unverified",
    },
    {
      severity: "high",
      category: "tone",
      title: "Free language",
      evidence_status: "supported",
    },
  ];

  assert.deepEqual(
    filterReviewFindings(findings, {
      severity: "critical_high",
      category: "claims",
      evidence: "unverified",
      search: "free",
    }).map(({ index }) => index),
    [0, 1],
  );
  assert.deepEqual(
    filterReviewFindings(findings, {
      severity: "critical_high",
      search: "missing phrase",
    }),
    [],
  );
});

test("returns no findings when the search has no matches", () => {
  assert.deepEqual(
    filterReviewFindings(
      [{ title: "Pricing guidance", explanation: "Use current approved facts." }],
      { search: "visual contrast" },
    ),
    [],
  );
});
