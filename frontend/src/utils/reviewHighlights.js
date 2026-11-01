export function findExactPhraseRanges(content, findings) {
  if (typeof content !== "string" || !Array.isArray(findings)) return [];

  const ranges = [];
  findings.forEach((finding, findingIndex) => {
    const phrase = finding?.matched_text;
    if (typeof phrase !== "string" || !phrase.length) return;

    let fromIndex = 0;
    while (fromIndex <= content.length - phrase.length) {
      const start = content.indexOf(phrase, fromIndex);
      if (start === -1) break;
      ranges.push({
        start,
        end: start + phrase.length,
        findingIndex,
      });
      fromIndex = start + 1;
    }
  });

  if (!ranges.length) return [];

  const boundaries = [
    ...new Set([0, content.length, ...ranges.flatMap(({ start, end }) => [start, end])]),
  ].sort((a, b) => a - b);

  return boundaries.slice(0, -1).flatMap((start, index) => {
    const end = boundaries[index + 1];
    if (start === end) return [];

    const findingIndices = ranges
      .filter((range) => range.start < end && range.end > start)
      .map((range) => range.findingIndex);

    return [{
      text: content.slice(start, end),
      findingIndices,
    }];
  });
}

export function getReviewContentSegments(content, findings) {
  if (typeof content !== "string" || content.length === 0) return [];

  const highlightedSegments = findExactPhraseRanges(content, findings);
  return highlightedSegments.length
    ? highlightedSegments
    : [{ text: content, findingIndices: [] }];
}
