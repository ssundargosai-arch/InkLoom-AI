import assert from "node:assert/strict";
import test from "node:test";

import {
  getBrandVoiceFindingLabel,
  getBrandVoiceFindings,
} from "../src/utils/brandVoiceFindings.js";

test("exposes a standalone prohibited-expression finding with its rule and status", () => {
  const finding = {
    category: "brand_voice",
    assessment: "configured_rule_violation",
    brand_voice_category: "Prohibited expression",
    matched_text: "world-class",
    configuration_rule: "world-class",
    explanation: "This expression is prohibited.",
  };

  assert.deepEqual(getBrandVoiceFindings(finding), [finding]);
  assert.equal(getBrandVoiceFindingLabel(finding), "Configured rule violation");
});

test("shows attached voice metadata without duplicating base findings", () => {
  const voiceFinding = {
    finding_type: "tone_signal",
    assessment: "advisory",
    brand_voice_category: "Tone suggestion",
    configuration_rule: "Desired tone: formal",
    explanation: "Review this wording manually.",
  };
  const finding = {
    category: "unsupported_claim",
    brand_voice_findings: [voiceFinding],
  };

  assert.deepEqual(getBrandVoiceFindings(finding), [voiceFinding]);
  assert.equal(getBrandVoiceFindingLabel(voiceFinding), "Advisory suggestion");
});

test("handles findings without voice metadata and missing suggestions", () => {
  assert.deepEqual(getBrandVoiceFindings({ category: "terminology" }), []);
  assert.deepEqual(getBrandVoiceFindings(null), []);

  const finding = {
    category: "brand_voice",
    assessment: "configured_rule_violation",
    suggestion: null,
    suggestion_status: "No associated replacement is configured.",
  };
  assert.equal(getBrandVoiceFindings(finding).length, 1);
  assert.equal(finding.suggestion, null);
});
