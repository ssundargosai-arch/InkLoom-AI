import re
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Sequence

from app.models.brand_guideline import BrandGuideline
from app.services.claim_checker import (
    check_promotional_claims,
    factual_claim_spans,
)
from app.services.brand_voice_checker import check_brand_voice
from app.services.suggestion_engine import (
    claim_suggestion,
    factual_suggestion,
    terminology_suggestion,
)


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip())
    if not escaped:
        return re.compile(r"(?!x)x")
    if term[0].isalnum() or term[0] == "_":
        escaped = r"\b" + escaped
    if term[-1].isalnum() or term[-1] == "_":
        escaped += r"\b"
    return re.compile(escaped, re.IGNORECASE)


def _source_is_expired(source: dict) -> bool:
    expiry = source.get("valid_until") or source.get("expiry_date")
    if not expiry:
        return False
    try:
        return date.fromisoformat(str(expiry)[:10]) < datetime.now(timezone.utc).date()
    except ValueError:
        return False


def _source_is_future(source: dict) -> bool:
    valid_from = source.get("valid_from") or source.get("source_date")
    if not valid_from:
        return False
    try:
        return date.fromisoformat(str(valid_from)[:10]) > datetime.now(timezone.utc).date()
    except ValueError:
        return False




def _factual_guideline(
    text: str,
    guidelines: Sequence[BrandGuideline],
    evidence_matches: Optional[Sequence[dict]] = None,
    excerpt_override: Optional[str] = None,
) -> Optional[tuple]:
    excerpt = excerpt_override
    if not excerpt:
        return None

    relevant = [
        item
        for item in guidelines
        if any(
            word in item.category.lower()
            for word in ("fact", "evidence", "source")
        )
    ]

    if not relevant:
        relevant = [
            item
            for item in guidelines
            if "claim" in item.category.lower()
        ]

    guideline_id = relevant[0].id if relevant else None
    source_label = relevant[0].name if relevant else "Factual claim review"

    # Retrieved evidence is a candidate, not automatic proof.
    # Claim-level verification is performed separately.
    if evidence_matches:
        freshness_values = [
            str(item.get("freshness", "unknown")).lower()
            for item in evidence_matches
        ]

        if all(value == "expired" for value in freshness_values):
            return (
                excerpt,
                (
                    "Only expired approved source material matched. "
                    "It cannot verify this claim. Check a current "
                    "approved source before publication."
                ),
                guideline_id,
                source_label,
            )

        return (
            excerpt,
            (
                "Retrieved source candidates were found, but none has "
                "established support through retrieval alone. "
                "Claim-level verification is evaluated separately "
                "against approved source content."
            ),
            guideline_id,
            source_label,
        )

    if not relevant:
        return (
            excerpt,
            (
                "This potentially factual statement requires review. "
                "No configured factual guideline or retrieved evidence "
                "is available to establish support."
            ),
            None,
            "Factual claim review",
        )

    for item in relevant:
        approved_sources = item.approved_sources or []

        expired = [
            source
            for source in approved_sources
            if _source_is_expired(source)
        ]

        active = [
            source
            for source in approved_sources
            if source.get("name")
            and not _source_is_expired(source)
            and not _source_is_future(source)
        ]

        if expired and not active:
            source_names = ", ".join(
                source.get("name", "source")
                for source in expired
            )
            return (
                excerpt,
                (
                    "Configured evidence sources may have expired "
                    "({}). Verify this statement against a current "
                    "approved source."
                ).format(source_names),
                item.id,
                item.name,
            )

        if not active:
            return (
                excerpt,
                (
                    "No current approved evidence source is configured "
                    "for this guideline."
                ),
                item.id,
                item.name,
            )

    names = ", ".join(item.name for item in relevant)

    return (
        excerpt,
        (
            "Approved evidence sources are configured ({}), but "
            "retrieval has not established support for this claim. "
            "Review exact source scope and context."
        ).format(names),
        relevant[0].id,
        relevant[0].name,
    )


def analyze_text(
    text: str,
    guidelines: Sequence[BrandGuideline],
    image_attached: bool = False,
    alt_text: Optional[str] = None,
    evidence_matches: Optional[Sequence[dict]] = None,
    evidence_by_claim: Optional[Dict[str, Sequence[dict]]] = None,
    brand_voice_configuration: Optional[Dict[str, object]] = None,
) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []

    for guideline in guidelines:
        prohibited = guideline.prohibited_terms or []
        preferred = guideline.preferred_terms or []
        for index, term in enumerate(prohibited):
            if not isinstance(term, str) or not term.strip():
                continue
            preferred_term = preferred[index] if index < len(preferred) else None
            for match in _term_pattern(term).finditer(text):
                findings.append(
                    {
                        "category": "terminology",
                        "severity": guideline.severity,
                        "title": "Prohibited or non-preferred terminology",
                        "explanation": (
                            "This wording matches a term prohibited by the configured guideline: {}."
                        ).format(guideline.name),
                        "matched_text": match.group(0),
                        "suggestion": terminology_suggestion(match.group(0), preferred_term),
                        "source": guideline.name,
                        "guideline": guideline.name,
                        "guideline_id": guideline.id,
                        "confidence": 0.96,
                    }
                )

    claim_guidelines = [
        item for item in guidelines if "claim" in item.category.lower()
    ]
    claim_guideline = claim_guidelines[0] if claim_guidelines else None
    findings.extend(check_promotional_claims(text))
    for finding in findings:
        if finding["category"] == "unsupported_claim":
            finding["suggestion"] = claim_suggestion(str(finding["matched_text"]))
            if claim_guideline:
                finding["source"] = claim_guideline.name
                finding["guideline"] = claim_guideline.name
                finding["guideline_id"] = claim_guideline.id

    for factual_claim in factual_claim_spans(text):
        excerpt = str(factual_claim["matched_text"])
        if any(
            finding["category"] == "unsupported_claim"
            and finding["matched_text"]
            and excerpt.casefold() == str(finding["matched_text"]).casefold()
            for finding in findings
        ):
            continue
        if evidence_by_claim is not None:
            claim_evidence = evidence_by_claim.get(excerpt.casefold(), [])
        else:
            claim_evidence = evidence_matches
        factual = _factual_guideline(
            text,
            guidelines,
            claim_evidence,
            excerpt_override=excerpt,
        )
        if factual:
            _excerpt, explanation, guideline_id, source = factual
            start = int(factual_claim["claim_start"])
            findings.append(
                {
                    "category": "factual_claim",
                    "severity": "medium",
                    "title": "Verify factual statement",
                    "explanation": explanation,
                    "matched_text": excerpt,
                    "claim": excerpt,
                    "claim_start": start if start >= 0 else None,
                    "claim_end": int(factual_claim["claim_end"]),
                    "suggestion": factual_suggestion(),
                    "source": source,
                    "guideline": source,
                    "guideline_id": guideline_id,
                    "confidence": 0.62,
                }
            )

    click_here = re.search(r"\bclick here\b", text, re.IGNORECASE)
    if click_here:
        findings.append(
            {
                "category": "accessibility",
                "severity": "low",
                "title": "Non-descriptive link wording",
                "explanation": "“Click here” does not describe the destination and can be less useful to assistive-technology users.",
                "matched_text": click_here.group(0),
                "suggestion": "Replace it with a concise link label that describes the destination or action.",
                "source": "Basic accessibility heuristic (not a WCAG audit)",
                "guideline": None,
                "guideline_id": None,
                "confidence": 0.82,
            }
        )

    if image_attached and not (alt_text or "").strip():
        findings.append(
            {
                "category": "accessibility",
                "severity": "medium",
                "title": "Image alternative text not provided",
                "explanation": "No alternative text was supplied for the uploaded image, so its meaning may not be available to screen-reader users.",
                "matched_text": None,
                "suggestion": "Add concise alternative text describing the image's relevant content or purpose.",
                "source": "Basic image accessibility check (not a WCAG audit)",
                "guideline": None,
                "guideline_id": None,
                "confidence": 0.9,
            }
        )

    check_brand_voice(text, brand_voice_configuration, findings)

    return findings
