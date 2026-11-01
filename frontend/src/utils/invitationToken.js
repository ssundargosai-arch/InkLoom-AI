export function getInvitationToken(search = "", hash = "") {
  const queryTokens = new URLSearchParams(search).getAll("token");
  if (queryTokens.length === 1 && queryTokens[0]) {
    return queryTokens[0];
  }
  if (queryTokens.length > 1) {
    return "";
  }

  const fragmentTokens = new URLSearchParams(hash.replace(/^#/, "")).getAll("token");
  return fragmentTokens.length === 1 ? fragmentTokens[0] || "" : "";
}

export function removeInvitationTokenFromUrl(href) {
  const url = new URL(href);
  url.searchParams.delete("token");

  if (url.hash) {
    const fragment = new URLSearchParams(url.hash.slice(1));
    if (fragment.has("token")) {
      fragment.delete("token");
      url.hash = fragment.toString() ? `#${fragment}` : "";
    }
  }

  return `${url.pathname}${url.search}${url.hash}`;
}
