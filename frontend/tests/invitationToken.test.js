import test from "node:test";
import assert from "node:assert/strict";
import {
  getInvitationToken,
  removeInvitationTokenFromUrl,
} from "../src/utils/invitationToken.js";

const inviteToken = "url-safe-invitation-token-value-123456";

test("reads invitation token from query after email redirects remove fragments", () => {
  const search = `?campaign=mail&token=${encodeURIComponent(inviteToken)}`;
  assert.equal(getInvitationToken(search, ""), inviteToken);
});

test("accepts existing fragment invitation links during the transition", () => {
  assert.equal(getInvitationToken("", `#token=${inviteToken}`), inviteToken);
});

test("rejects absent or ambiguous invitation token parameters", () => {
  assert.equal(getInvitationToken("?source=email", ""), "");
  assert.equal(
    getInvitationToken(`?token=${inviteToken}&token=another-token`, ""),
    "",
  );
  assert.equal(getInvitationToken("", `#token=${inviteToken}&token=other`), "");
});

test("removes invitation tokens from the address while preserving other URL state", () => {
  const clean = removeInvitationTokenFromUrl(
    `http://localhost:5173/accept-invitation?source=email&token=${inviteToken}`,
  );
  assert.equal(clean, "/accept-invitation?source=email");
  assert.equal(clean.includes(inviteToken), false);
});

test("also removes legacy fragment tokens from the address", () => {
  const clean = removeInvitationTokenFromUrl(
    `http://localhost:5173/accept-invitation#token=${inviteToken}`,
  );
  assert.equal(clean, "/accept-invitation");
  assert.equal(clean.includes(inviteToken), false);
});
