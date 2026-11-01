import assert from "node:assert/strict";
import test from "node:test";

import { mockApi } from "../src/services/mockApi.js";

test("review details keep empty history unavailable instead of inventing a baseline", async () => {
  const review = await mockApi.review("rv-1047");

  assert.equal(review.content, "A warmer welcome to your new routine.");
  assert.deepEqual(review.revisions, []);
  assert.deepEqual(review.versions, []);
  assert.equal(review.current_version_id, null);
});

test("addRevision captures the original content and retains its existing return shape", async () => {
  const originalContent = (
    await mockApi.review("rv-1048")
  ).content;
  const result = await mockApi.addRevision("rv-1048", {
    content: "A first safe revision.",
    title: "First revision",
  });
  const review = await mockApi.review("rv-1048");

  assert.match(result.id, /^rev-/);
  assert.equal(result.content, "A first safe revision.");
  assert.equal(review.content, "A first safe revision.");
  assert.equal(review.analysis_runs[0].content, originalContent);
  assert.equal(review.versions[0].content, originalContent);
  assert.equal(review.versions[0].is_original, true);
  assert.equal(review.versions[1].content, "A first safe revision.");
  assert.equal(review.versions[1].is_original, false);
  assert.equal(review.current_version_id, review.versions[1].id);
});

test("reanalyze captures the original content and returns the latest version", async () => {
  const originalContent = (
    await mockApi.review("rv-1047")
  ).content;
  const response = await mockApi.reanalyze("rv-1047", {
    content: "A revised welcome with guaranteed delight.",
    title: "Reviewed welcome revision",
  });
  const review = await mockApi.review("rv-1047");

  assert.equal(response.content, "A revised welcome with guaranteed delight.");
  assert.equal(review.analysis_runs[0].content, originalContent);
  assert.equal(review.versions[0].content, originalContent);
  assert.equal(review.versions[0].is_original, true);
  assert.equal(review.versions.at(-1).content, review.content);
  assert.equal(review.versions.at(-1).is_original, false);
  assert.equal(review.current_version_id, review.versions.at(-1).id);
});

test("multiple revisions retain one original and point to the latest version", async () => {
  const created = await mockApi.analyze({
    title: "Multiple revision test",
    content: "An original illustrative submission.",
    content_type: "Email",
  });
  const originalContent = created.content;

  await mockApi.reanalyze(created.id, {
    content: "A first revision with guaranteed clarity.",
  });
  await mockApi.reanalyze(created.id, {
    content: "A latest revision with ultimate clarity.",
  });

  const review = await mockApi.review(created.id);
  const originalVersions = review.versions.filter(
    (version) => version.is_original,
  );

  assert.equal(originalVersions.length, 1);
  assert.equal(originalVersions[0].id, 0);
  assert.equal(originalVersions[0].content, originalContent);
  assert.equal(review.versions.length, 3);
  assert.equal(review.versions.at(-1).content, review.content);
  assert.equal(review.current_version_id, review.versions.at(-1).id);
});

test("review detail and list retain existing mock API fields and pagination shape", async () => {
  const created = await mockApi.analyze({
    title: "Compatibility test",
    content: "A harmless mock review.",
    content_type: "Email",
  });
  const detail = await mockApi.review(created.id);
  const listing = await mockApi.reviews({ offset: 0, limit: 1 });

  for (const field of [
    "content",
    "findings",
    "revisions",
    "analysis_runs",
    "versions",
    "current_version_id",
  ]) {
    assert.ok(Object.hasOwn(detail, field), `expected detail field ${field}`);
  }
  assert.equal(listing.items.length, 1);
  assert.equal(typeof listing.total, "number");
  assert.equal(listing.offset, 0);
  assert.equal(listing.limit, 1);
});

test("mock brand voice configuration persists and records changed versions", async () => {
  const initial = await mockApi.brandVoiceConfiguration();
  assert.equal(initial.version_number, 0);
  assert.deepEqual(initial.desired_tones, []);

  const saved = await mockApi.updateBrandVoiceConfiguration({
    desired_tones: ["professional"],
    voice_attributes: ["clear"],
    preferred_expressions: ["Made with care"],
    prohibited_expressions: ["world-class"],
    target_audiences: ["Readers"],
    supported_channels: ["Website"],
    messaging_principles: ["Be specific"],
  });
  assert.equal(saved.version_number, 1);

  const reloaded = await mockApi.brandVoiceConfiguration();
  assert.deepEqual(reloaded.preferred_expressions, ["Made with care"]);
  const history = await mockApi.brandVoiceVersions();
  assert.equal(history[0].version_number, 1);
  assert.deepEqual(history[0].snapshot.desired_tones, ["professional"]);
});
