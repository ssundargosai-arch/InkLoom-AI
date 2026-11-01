export function getBrandVoiceFindings(finding) {
  if (!finding || typeof finding !== "object") return [];

  const attached = Array.isArray(finding.brand_voice_findings)
    ? finding.brand_voice_findings.filter(
        (item) => item && typeof item === "object",
      )
    : [];
  if (String(finding.category || "").toLowerCase() === "brand_voice") {
    return [finding, ...attached];
  }
  return attached;
}

export function getBrandVoiceFindingLabel(finding) {
  if (finding?.assessment === "configured_rule_violation") {
    return "Configured rule violation";
  }
  return "Advisory suggestion";
}
