import re
from typing import Dict, Iterable, List


_CONFLICT_DIRECTIVES = {
    "formal": re.compile(
        r"\b(?:always\s+)?use\s+(?:a\s+)?formal\s+(?:tone|language)\b|"
        r"\bmaintain\s+(?:a\s+)?formal\s+(?:tone|language)\b",
        re.IGNORECASE,
    ),
    "casual": re.compile(
        r"\b(?:always\s+)?use\s+(?:a\s+)?casual\s+(?:tone|language)\b|"
        r"\bmaintain\s+(?:a\s+)?casual\s+(?:tone|language)\b",
        re.IGNORECASE,
    ),
}

_VAGUE_TERMS = (
    "modern",
    "engaging",
    "professional",
    "compelling",
    "innovative",
)


def _guideline_value(guideline, key, default=None):
    if isinstance(guideline, dict):
        return guideline.get(key, default)
    return getattr(guideline, key, default)


def _guideline_text(guideline) -> str:
    parts = [
        _guideline_value(guideline, "name", ""),
        _guideline_value(guideline, "description", ""),
    ]
    examples = _guideline_value(guideline, "examples", [])
    if isinstance(examples, (list, tuple)):
        parts.extend(example for example in examples if isinstance(example, str))
    return "\n".join(part for part in parts if isinstance(part, str))


def _matched_directive(guideline, pattern: re.Pattern) -> str:
    text = _guideline_text(guideline)
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 24) : match.start()]
        if re.search(
            r"\b(?:do\s+not|don['’]t|never|not|avoid|without)\s+(?:always\s+)?$",
            prefix,
            re.IGNORECASE,
        ):
            continue
        return match.group(0)
    return ""


def _vague_matches(text: str) -> Iterable[str]:
    seen = set()
    for term in _VAGUE_TERMS:
        match = re.search(r"\b{}\b".format(re.escape(term)), text, re.IGNORECASE)
        if match and term not in seen:
            seen.add(term)
            yield match.group(0)


def _mentions_both_tone_options(guideline) -> bool:
    text = _guideline_text(guideline)
    return all(
        re.search(r"\b{}\s+(?:tone|language)\b".format(kind), text, re.IGNORECASE)
        for kind in ("formal", "casual")
    )


def diagnose_guidelines(guidelines) -> Dict[str, List[dict]]:
    active = [
        guideline
        for guideline in guidelines
        if _guideline_value(guideline, "is_active", True) is True
    ]
    active.sort(
        key=lambda guideline: (
            str(_guideline_value(guideline, "category", "")).casefold(),
            str(_guideline_value(guideline, "id", "")),
            str(_guideline_value(guideline, "name", "")).casefold(),
        )
    )

    potential_conflicts: List[dict] = []
    for index, first in enumerate(active):
        first_category = str(
            _guideline_value(first, "category", "")
        ).strip().casefold()
        if not first_category:
            continue
        for second in active[index + 1 :]:
            second_category = str(
                _guideline_value(second, "category", "")
            ).strip().casefold()
            if first_category != second_category:
                continue
            if _mentions_both_tone_options(first) or _mentions_both_tone_options(
                second
            ):
                continue

            first_matches = {
                kind: _matched_directive(first, pattern)
                for kind, pattern in _CONFLICT_DIRECTIVES.items()
            }
            second_matches = {
                kind: _matched_directive(second, pattern)
                for kind, pattern in _CONFLICT_DIRECTIVES.items()
            }
            if (
                bool(first_matches["formal"]) == bool(first_matches["casual"])
                or bool(second_matches["formal"]) == bool(second_matches["casual"])
            ):
                continue
            if bool(first_matches["formal"]) == bool(second_matches["formal"]):
                continue

            first_kind = "formal" if first_matches["formal"] else "casual"
            second_kind = "formal" if second_matches["formal"] else "casual"
            potential_conflicts.append(
                {
                    "diagnostic_type": "potential_conflict",
                    "guideline_ids": [
                        _guideline_value(first, "id"),
                        _guideline_value(second, "id"),
                    ],
                    "guideline_names": [
                        _guideline_value(first, "name", ""),
                        _guideline_value(second, "name", ""),
                    ],
                    "matched_text": [
                        first_matches[first_kind],
                        second_matches[second_kind],
                    ],
                    "category": _guideline_value(first, "category", ""),
                    "scope_status": "unclear",
                    "explanation": (
                        "These active guidelines contain opposing formal- and "
                        "casual-language directives in the same category. Category "
                        "is only a grouping hint; their applicable scope is unknown."
                    ),
                    "human_review_recommendation": (
                        "Confirm whether both rules apply to the same audience, "
                        "channel, and content type before treating this as a conflict."
                    ),
                }
            )

    needs_clarification: List[dict] = []
    for guideline in active:
        text = _guideline_text(guideline)
        for matched_text in _vague_matches(text):
            needs_clarification.append(
                {
                    "diagnostic_type": "needs_clarification",
                    "guideline_ids": [_guideline_value(guideline, "id")],
                    "guideline_names": [_guideline_value(guideline, "name", "")],
                    "matched_text": [matched_text],
                    "category": _guideline_value(guideline, "category", ""),
                    "scope_status": "unclear",
                    "explanation": (
                        "This wording may be subjective without a measurable standard "
                        "or context. This is a clarification suggestion, not a conflict."
                    ),
                    "human_review_recommendation": (
                        "Ask the guideline owner to define the intended audience, "
                        "context, or observable criteria."
                    ),
                }
            )

    return {
        "potential_conflicts": potential_conflicts,
        "needs_clarification": needs_clarification,
    }
