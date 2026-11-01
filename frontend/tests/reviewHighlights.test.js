import assert from "node:assert/strict";
import test from "node:test";

import {
  findExactPhraseRanges,
  getReviewContentSegments,
} from "../src/utils/reviewHighlights.js";

test("highlights every exact duplicate occurrence", () => {
  const segments = findExactPhraseRanges("bad phrase, then bad phrase", [
    { matched_text: "bad phrase" },
  ]);
  const marked = segments.filter((segment) => segment.findingIndices.length);

  assert.deepEqual(marked.map((segment) => segment.text).join(""), "bad phrasebad phrase");
  assert.equal(marked.length, 2);
});

test("splits overlapping phrases without losing either finding", () => {
  const segments = findExactPhraseRanges("abcdef", [
    { matched_text: "abcd" },
    { matched_text: "cdef" },
  ]);

  assert.deepEqual(segments, [
    { text: "ab", findingIndices: [0] },
    { text: "cd", findingIndices: [0, 1] },
    { text: "ef", findingIndices: [1] },
  ]);
});

test("does not highlight missing, empty, or case-mismatched phrases", () => {
  assert.deepEqual(
    findExactPhraseRanges("Draft text", [
      { matched_text: "draft" },
      { matched_text: "" },
      { matched_text: "not present" },
    ]),
    [],
  );
});

test("keeps current revision text visible when there are no findings", () => {
  assert.deepEqual(
    getReviewContentSegments("Current draft content.", []),
    [{ text: "Current draft content.", findingIndices: [] }],
  );
});

test("preserves finding highlights when findings are present", () => {
  assert.deepEqual(
    getReviewContentSegments("Keep the claim specific.", [
      { matched_text: "claim" },
    ]),
    [
      { text: "Keep the ", findingIndices: [] },
      { text: "claim", findingIndices: [0] },
      { text: " specific.", findingIndices: [] },
    ],
  );
});

test("returns no text segments for empty current content", () => {
  assert.deepEqual(getReviewContentSegments("", []), []);
});
