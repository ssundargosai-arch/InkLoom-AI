import test from "node:test";
import assert from "node:assert/strict";
import {
  canInitiatePublish,
  canOverridePublish,
} from "../src/utils/publishPermissions.js";

test("publishing is limited to admins", () => {
  assert.equal(canInitiatePublish("admin"), true);
  assert.equal(canInitiatePublish("reviewer"), false);
  assert.equal(canInitiatePublish("contributor"), false);
});

test("reviewers cannot initiate Admin risk overrides", () => {
  const readiness = { can_override: true };
  assert.equal(canOverridePublish("admin", readiness), true);
  assert.equal(canOverridePublish("reviewer", readiness), false);
  assert.equal(canOverridePublish("admin", { can_override: false }), false);
});
