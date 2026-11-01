import re
from typing import Dict, Iterable, List, Optional, Sequence


_INFORMAL_SIGNALS = (
    re.compile(r"\b(?:gonna|wanna|gotta|kinda|sorta|lol|btw)\b", re.IGNORECASE),
)


def _phrase_pattern(phrase: str) -> re.Pattern:
    phrase = phrase.strip()
    escaped = re.escape(phrase)
    if not escaped:
        return re.compile(r"(?!x)x")
    if phrase[0].isalnum() or phrase[0] == "_":
        escaped = r"\b" + escaped
    if phrase[-1].isalnum() or phrase[-1] == "_":
        escaped += r"\b"
    return re.compile(escaped, re.IGNORECASE)


def _values(configuration: Dict[str, object], key: str) -> Iterable[str]:
    value = configuration.get(key, [])
    if not isinstance(value, (list, tuple)):
        return ()
    return (
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )


def _attach_voice_finding(
    finding: Dict[str, object], voice_finding: Dict[str, object]
) -> None:
    current = finding.setdefault("brand_voice_findings", [])
    if isinstance(current, list):
        key = (
            voice_finding.get("finding_type"),
            str(voice_finding.get("matched_text") or "").casefold(),
            str(voice_finding.get("configuration_rule") or "").casefold(),
        )
        if not any(
            (
                item.get("finding_type"),
                str(item.get("matched_text") or "").casefold(),
                str(item.get("configuration_rule") or "").casefold(),
            )
            == key
            for item in current
            if isinstance(item, dict)
        ):
            current.append(voice_finding)


def _overlapping_finding(
    findings: Sequence[Dict[str, object]], matched_text: str
) -> Optional[Dict[str, object]]:
    matched = matched_text.casefold()
    for finding in findings:
        existing = finding.get("matched_text")
        if not isinstance(existing, str) or not existing:
            continue
        category = str(finding.get("category") or "").casefold()
        if category in {
            "terminology",
            "unsupported_claim",
            "factual_claim",
        } and matched in existing.casefold():
            return finding
    return None


def _voice_finding(
    *,
    finding_type: str,
    matched_text: str,
    rule: str,
    explanation: str,
    suggestion: Optional[str] = None,
) -> Dict[str, object]:
    is_violation = finding_type == "prohibited_expression"
    return {
        "category": "brand_voice",
        "brand_voice_category": (
            "Prohibited expression" if is_violation else "Tone suggestion"
        ),
        "finding_type": finding_type,
        "assessment": "configured_rule_violation" if is_violation else "advisory",
        "severity": "medium" if is_violation else "low",
        "title": (
            "Prohibited brand expression"
            if is_violation
            else "Review tone against configured voice"
        ),
        "matched_text": matched_text,
        "configuration_rule": rule,
        "explanation": explanation,
        "suggestion": suggestion,
        "suggestion_status": (
            None
            if suggestion
            else "No directly associated preferred replacement is configured."
            if is_violation
            else "Review manually; no replacement text is generated."
        ),
        "source": "Organization brand voice configuration",
        "guideline": "Organization brand voice configuration",
        "guideline_id": None,
        "confidence": 0.96 if is_violation else 0.62,
    }


def check_brand_voice(
    text: str,
    configuration: Optional[Dict[str, object]],
    existing_findings: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """Check only explicit prohibited expressions and a narrow tone advisory."""
    if not isinstance(text, str) or not text or not isinstance(configuration, dict):
        return []

    findings = existing_findings if existing_findings is not None else []
    added: List[Dict[str, object]] = []
    prohibited_matches = set()

    for expression in _values(configuration, "prohibited_expressions"):
        for match in _phrase_pattern(expression).finditer(text):
            prohibited_matches.add(match.group(0).casefold())
            voice_finding = _voice_finding(
                finding_type="prohibited_expression",
                matched_text=match.group(0),
                rule=expression,
                explanation=(
                    "This exact expression is listed as prohibited in the "
                    "organization's Brand Voice Configuration."
                ),
            )
            overlap = _overlapping_finding(findings, match.group(0))
            if overlap is not None:
                _attach_voice_finding(overlap, voice_finding)
                continue
            added.append(voice_finding)

    tones = {tone.casefold() for tone in _values(configuration, "desired_tones")}
    if tones.intersection({"formal", "professional"}):
        configured_tone = ", ".join(sorted(tones.intersection({"formal", "professional"})))
        for pattern in _INFORMAL_SIGNALS:
            for match in pattern.finditer(text):
                if match.group(0).casefold() in prohibited_matches:
                    continue
                voice_finding = _voice_finding(
                    finding_type="tone_signal",
                    matched_text=match.group(0),
                    rule="Desired tone: {}".format(configured_tone),
                    explanation=(
                        "This colloquial expression may not fit the configured "
                        "{} tone. This is a limited heuristic signal, not proof "
                        "of an objective tone mismatch."
                    ).format(configured_tone),
                    suggestion=(
                        "Review this wording manually against the intended voice "
                        "and preserve the original meaning."
                    ),
                )
                overlap = _overlapping_finding(findings, match.group(0))
                if overlap is not None:
                    _attach_voice_finding(overlap, voice_finding)
                    continue
                added.append(voice_finding)

    findings.extend(added)
    return added
