import test from "node:test";
import assert from "node:assert/strict";

import {
  canStartReviewCollaboration,
  isReviewerAssignedToStage,
} from "../src/utils/reviewCollaboration.js";

const authorizedLoad = {
  loading: false,
  error: "",
  loadedReviewId: "32",
  reviewId: "32",
  review: { id: 32 },
  user: { id: 7, role: "contributor" },
};

test("starts collaboration only after an authorized detail request succeeds", () => {
  assert.equal(canStartReviewCollaboration(authorizedLoad), true);
});

test("does not start collaboration while loading or after a failed review request", () => {
  assert.equal(
    canStartReviewCollaboration({
      ...authorizedLoad,
      loading: true,
      loadedReviewId: null,
      review: null,
    }),
    false,
  );
  assert.equal(
    canStartReviewCollaboration({
      ...authorizedLoad,
      error: "Review not found.",
      loadedReviewId: null,
      review: null,
    }),
    false,
  );
});

test("does not use a previously loaded review to authorize a different route", () => {
  assert.equal(
    canStartReviewCollaboration({
      ...authorizedLoad,
      reviewId: "33",
    }),
    false,
  );
});

test("does not start collaboration for a role outside the backend access policy", () => {
  assert.equal(
    canStartReviewCollaboration({
      ...authorizedLoad,
      user: { id: 7, role: "demo" },
    }),
    false,
  );
});

test("allows a reviewer to act only in their configured stage", () => {
  const assignments = [
    { id: 12, display_name: "First", stage_number: 1 },
    { id: 24, display_name: "Second", stage_number: 2 },
  ];

  assert.equal(isReviewerAssignedToStage(assignments, "12", 1), true);
  assert.equal(isReviewerAssignedToStage(assignments, 12, 2), false);
  assert.equal(isReviewerAssignedToStage(assignments, 99, 1), false);
});

test("denies incomplete or malformed assignment data", () => {
  assert.equal(isReviewerAssignedToStage(null, 12, 1), false);
  assert.equal(isReviewerAssignedToStage([], 12, 1), false);
  assert.equal(isReviewerAssignedToStage([{ reviewer_id: 12 }], 12, 1), false);
  assert.equal(isReviewerAssignedToStage([{ id: 12, stage_number: 1 }], null, 1), false);
});
