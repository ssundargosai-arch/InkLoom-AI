import re
from typing import Dict, List, Optional, Tuple

CLAIM_TRIGGERS = (
    (
        re.compile(
            r"\b(?:guarantee(?:s|d)?|promise(?:s|d)?)\b|"
            r"\b100\s*%\s+guaranteed\b|\brisk[- ]free\b",
            re.IGNORECASE,
        ),
        "Unverified guarantee",
        "A guarantee or absolute promise needs evidence for its exact scope and outcome.",
        0.96,
    ),
    (
        re.compile(
            r"\b(?:best|number one|no\.?\s*1|#1|world['’]s best|"
            r"market[- ]leading|industry[- ]leading|top[- ]rated)\b",
            re.IGNORECASE,
        ),
        "Unsubstantiated superiority claim",
        "A superiority or ranking claim needs current, objective evidence and a defined comparison set.",
        0.94,
    ),
    (
        re.compile(
            r"\b(?:save|saves|saved|saving|savings|reduce[sd]?|"
            r"cut[sd]?|lower(?:s|ed)?|cheaper)\b"
            r"[^.!?;]{0,50}\b(?:costs?|spend(?:ing)?|price|fees?|"
            r"expenses?|budget|money|dollars?|revenue|roi|percent)\b|"
            r"\b(?:\$|€|£)\s?\d",
            re.IGNORECASE,
        ),
        "Promotional savings claim",
        "A savings or cost-reduction claim needs evidence for the amount, baseline, and conditions.",
        0.9,
    ),
    (
        re.compile(
            r"\b(?:increase[sd]?|boost[sd]?|improv(?:e|es|ed|ing)|"
            r"grow(?:s|n|ing)?|accelerat(?:e|es|ed|ing)|"
            r"outperform(?:s|ed|ing)?)\b",
            re.IGNORECASE,
        ),
        "Promotional performance claim",
        "A performance claim needs evidence for the measured outcome, baseline, and population.",
        0.9,
    ),
    (
        re.compile(
            r"\b(?:more|less|faster|slower|better|higher|lower|"
            r"greater|cheaper|safer|easier)\b.{0,45}\bthan\b|"
            r"\b(?:outperform|surpass|exceed)(?:s|ed)?\b",
            re.IGNORECASE,
        ),
        "Comparative claim",
        "A comparison needs evidence that covers the comparator, method, and relevant conditions.",
        0.9,
    ),
    (
        re.compile(
            r"(?:\b\d+(?:\.\d+)?\s*(?:%|percent|x|times|hours?|days?|"
            r"weeks?|months?|years?|users?|customers?|teams?|"
            r"minutes?|seconds?)\b|\b(?:\d{1,3}(?:,\d{3})+)\b)",
            re.IGNORECASE,
        ),
        "Quantified promotional claim",
        "A quantitative claim needs a source that substantiates the full figure, unit, and scope.",
        0.84,
    ),
    (
        re.compile(
            r"\b(?:our|the|this)?\s*"
            r"(?:product|platform|app|software|service|tool|solution|"
            r"system|assistant|device|feature|workflow|AI)\b"
            r"[^.!?;]{0,80}\b(?:helps?|enables?|allows?|lets?|"
            r"automates?|detects?|prevents?|integrates?|"
            r"analy[sz]es?|personaliz(?:e|es|ed)|streamlines?)\b",
            re.IGNORECASE,
        ),
        "Product capability claim",
        "Confirm that the described product capability is currently available and supported by evidence.",
        0.82,
    ),
    (
        re.compile(
            r"\b(?:product|platform|app|software|service|tool|solution|"
            r"system|assistant|device|feature|workflow)\b"
            r"[^.!?;]{0,80}\bsupports?\s+"
            r"(?:sso|single sign-on|api|offline mode|integrations?|"
            r"automation|workflows?|webhooks?|saml|oauth|data exports?|"
            r"two-factor authentication|audit logs?)\b",
            re.IGNORECASE,
        ),
        "Product capability claim",
        "Confirm that the described product capability is currently available and supported by evidence.",
        0.82,
    ),
    (
        re.compile(
            r"\b(?:customers?|clients?|teams?|users?)\b.{0,70}"
            r"\b(?:achieve|save|earn|gain|increase|reduce|improve|"
            r"grow|reach|deliver|get|experience)\b|"
            r"\b(?:achieve|save|earn|gain|increase|reduce|improve|"
            r"grow|reach|deliver)\b.{0,70}"
            r"\b(?:customers?|clients?|teams?|users?)\b",
            re.IGNORECASE,
        ),
        "Customer outcome claim",
        "A customer outcome claim needs evidence for the measured result and the customers or conditions it describes.",
        0.86,
    ),
)

INSTRUCTION_PATTERN = re.compile(
    r"^\s*(?:(?:rule|guideline|policy)\s*#?\s*\d*\s*[:.)-]\s*|"
    r"(?:never|do not|don't|avoid|must not|should not)\s+"
    r"(?:claim|state|say|promise|advertise|assert|describe|use|write|mention)\b)",
    re.IGNORECASE,
)


def _sentence_spans(text: str):
    for match in re.finditer(r"\S(?:.*?\S)?(?:(?<=[.!?])(?=\s|$)|(?=\n)|$)", text, re.DOTALL):
        start, end = match.span()
        segment = text[start:end]
        left_trim = len(segment) - len(segment.lstrip())
        right_trimmed = segment.rstrip()
        right_trim = len(segment) - len(right_trimmed)
        candidate = right_trimmed.lstrip()
        if candidate:
            start += left_trim
            end -= right_trim
            while candidate and candidate[-1] in ".!?\"'”’)]}":
                candidate = candidate[:-1].rstrip()
                end -= 1
            if candidate:
                yield start, end, candidate


def extract_promotional_claims(text: str) -> List[Dict[str, object]]:
    """Extract whole claim-bearing sentences with offsets into the submitted draft."""
    if not isinstance(text, str) or not text:
        return []

    extracted = []
    seen = set()
    for start, end, sentence in _sentence_spans(text):
        if INSTRUCTION_PATTERN.search(sentence):
            continue
        matching = next(
            (item for item in CLAIM_TRIGGERS if item[0].search(sentence)),
            None,
        )
        if matching is None:
            continue
        pattern, title, explanation, confidence = matching
        key = (start, end, sentence.casefold())
        if key in seen:
            continue
        seen.add(key)
        extracted.append(
            {
                "category": "unsupported_claim",
                "severity": "high",
                "title": title,
                "explanation": explanation,
                "matched_text": sentence,
                "claim": sentence,
                "claim_start": start,
                "claim_end": end,
                "suggestion": (
                    "Revise this to a specific, supportable statement. Keep any "
                    "performance promise only when current evidence supports its full scope."
                ),
                "source": "Promotional claim detection heuristic",
                "guideline": "Promotional claim review",
                "guideline_id": None,
                "confidence": confidence,
                "detection_method": "rule_based_claim_trigger",
            }
        )
    return extracted


def check_promotional_claims(text: str) -> List[Dict[str, object]]:
    return extract_promotional_claims(text)


FACTUAL_CLAIM_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?\s*%|\$[\d,]+|\b\d{4}\b|\baccording to\b|"
    r"\bresearch shows\b|\bstudies show\b|\bscientifically proven\b|"
    r"\bnumber one\b|#1)",
    re.IGNORECASE,
)


def factual_claim_spans(text: str) -> List[Dict[str, object]]:
    if not isinstance(text, str) or not text:
        return []

    claims = []
    for start, end, sentence in _sentence_spans(text):
        if (
            FACTUAL_CLAIM_PATTERN.search(sentence)
            and not INSTRUCTION_PATTERN.search(sentence)
        ):
            claims.append(
                {
                    "matched_text": sentence,
                    "claim_start": start,
                    "claim_end": end,
                }
            )
    return claims


def factual_claim_excerpt(text: str) -> Optional[str]:
    claims = factual_claim_spans(text)
    return str(claims[0]["matched_text"]) if claims else None


def factual_claim_excerpts(text: str) -> List[str]:
    return [str(item["matched_text"]) for item in factual_claim_spans(text)]
