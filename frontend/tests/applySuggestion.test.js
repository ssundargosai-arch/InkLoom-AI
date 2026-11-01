import test from "node:test";
import assert from "node:assert/strict";
import { applySuggestionToContent, getSafeReplacement } from "../src/utils/applySuggestion.js";

test("replaces a unique exact match without changing surrounding text", () => {
  assert.deepEqual(
    applySuggestionToContent("Our ultimate product is here.", "ultimate", "thoughtful"),
    { ok: true, content: "Our thoughtful product is here." },
  );
});

test("refuses to guess when a phrase appears more than once", () => {
  assert.deepEqual(
    applySuggestionToContent("ultimate value, ultimate quality", "ultimate", "considered"),
    { ok: false, reason: "ambiguous" },
  );
});

test("detects overlapping matches", () => {
  assert.deepEqual(
    applySuggestionToContent("aaa", "aa", "b"),
    { ok: false, reason: "ambiguous" },
  );
});

test("reports when the original phrase is no longer in the draft", () => {
  assert.deepEqual(
    applySuggestionToContent("Draft changed", "old phrase", "new phrase"),
    { ok: false, reason: "not-found" },
  );
});

test("rejects missing or invalid inputs", () => {
  assert.deepEqual(applySuggestionToContent("draft", "", "replacement"), { ok: false, reason: "missing-text" });
  assert.deepEqual(applySuggestionToContent(null, "draft", "replacement"), { ok: false, reason: "invalid-input" });
});

test("extracts only the explicit approved terminology replacement", () => {
  assert.deepEqual(
    getSafeReplacement(
      "amazing",
      "Replace “amazing” with “considered” to use the approved terminology.",
      "terminology",
    ),
    { ok: true, replacement: "considered" },
  );
});

test("refuses to insert promotional claim instructions into draft text", () => {
  assert.deepEqual(
    getSafeReplacement(
      "100% guaranteed to double productivity",
      "Revise this claim to a specific, supportable statement and include evidence.",
      "unsupported_claim",
    ),
    { ok: false, reason: "manual-edit-required" },
  );
});

test("refuses automatic replacement for brand voice suggestions", () => {
  assert.deepEqual(
    getSafeReplacement(
      "gonna",
      "Review this wording manually against the intended voice.",
      "brand_voice",
    ),
    { ok: false, reason: "manual-edit-required" },
  );
});

test("refuses terminology guidance without an explicit replacement", () => {
  assert.deepEqual(
    getSafeReplacement(
      "amazing",
      "Review “amazing” and replace it with the preferred wording in your brand guidelines.",
      "terminology",
    ),
    { ok: false, reason: "manual-edit-required" },
  );
});
