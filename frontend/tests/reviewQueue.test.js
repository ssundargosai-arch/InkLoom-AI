import assert from "node:assert/strict";
import test from "node:test";

import {
  getReviewQueuePageCount,
  getReviewQueuePageOffset,
  getReviewQueuePagination,
  updateReviewQueueState,
} from "../src/utils/reviewQueue.js";

test("calculates queue pages and disables navigation at boundaries", () => {
  assert.equal(getReviewQueuePageCount(0, 20), 1);
  assert.equal(getReviewQueuePageCount(41, 20), 3);
  assert.deepEqual(getReviewQueuePagination(41, 20, 0), {
    page: 0,
    pageCount: 3,
    canPrevious: false,
    canNext: true,
  });
  assert.deepEqual(getReviewQueuePagination(41, 20, 2), {
    page: 2,
    pageCount: 3,
    canPrevious: true,
    canNext: false,
  });
  assert.equal(getReviewQueuePageOffset(2, 20, 41), 40);
});

test("clamps requested queue pages when result count shrinks", () => {
  assert.deepEqual(getReviewQueuePagination(5, 20, 4), {
    page: 0,
    pageCount: 1,
    canPrevious: false,
    canNext: false,
  });
  assert.equal(getReviewQueuePageOffset(4, 20, 5), 0);
});

test("search and status filter changes reset queue pagination", () => {
  const current = {
    query: "draft",
    status: "pending",
    page: 3,
  };
  assert.deepEqual(
    updateReviewQueueState(current, { query: "launch" }),
    { query: "launch", status: "pending", page: 0 },
  );
  assert.deepEqual(
    updateReviewQueueState(current, { status: "approved" }),
    { query: "draft", status: "approved", page: 0 },
  );
  assert.deepEqual(
    updateReviewQueueState(current, { page: 2 }),
    { query: "draft", status: "pending", page: 2 },
  );
});
