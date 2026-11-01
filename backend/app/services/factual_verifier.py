import re
from datetime import date, datetime, timezone
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlsplit

import httpx

from app.config import FACT_CHECK_API_KEY, FACT_CHECK_ENABLED, TRUSTED_SOURCE_DOMAINS

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_EXTERNAL_CLAIMS = 5
MAX_EXTERNAL_RESULTS = 5
MAX_EXTERNAL_QUERY_LENGTH = 500
WORD_PATTERN = re.compile(r"[a-z][a-z'-]{2,}", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"(?<!\w)(?:[$€£]\s?[\d,]+|\d+(?:\.\d+)?\s*%?)(?!\w)")
SCOPE_MARKER_PATTERN = re.compile(
    r"\b(?:about|approximately|around|roughly|nearly|only|up\s+to|at\s+least|"
    r"at\s+most|no\s+more\s+than|no\s+less\s+than|more\s+than|less\s+than|"
    r"fewer\s+than|over|under|minimum|maximum)\b",
    re.IGNORECASE,
)
STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been",
    "before", "being", "both", "but", "can", "could", "does", "during",
    "each", "for", "from", "has", "have", "into", "its", "more", "most",
    "our", "over", "same", "than", "that", "the", "their", "this", "those",
    "was", "were", "which", "with", "you", "your",
}
NEGATION_WORDS = {
    "cannot", "cant", "hardly", "never", "neither", "no", "nor", "not",
    "rarely", "seldom", "without",
}
NEGATION_CONTRACTION_PATTERN = re.compile(
    r"\b(?:aren't|can't|couldn't|didn't|doesn't|don't|hadn't|hasn't|"
    r"haven't|isn't|mustn't|needn't|shan't|shouldn't|wasn't|weren't|"
    r"won't|wouldn't)\b",
    re.IGNORECASE,
)
EXTERNAL_SOURCE_TYPE = "external_trusted_source"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


class ExternalSearchError(RuntimeError):
    pass


def _trusted_host(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            return False
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in TRUSTED_SOURCE_DOMAINS
    )


async def search_trusted_sources(claim: str) -> List[Dict[str, object]]:
    if not FACT_CHECK_ENABLED or not FACT_CHECK_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                BRAVE_SEARCH_URL,
                headers={"X-Subscription-Token": FACT_CHECK_API_KEY},
                params={
                    "q": claim[:MAX_EXTERNAL_QUERY_LENGTH],
                    "count": MAX_EXTERNAL_RESULTS,
                },
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        reason = "HTTP {}".format(status_code) if status_code else type(exc).__name__
        raise ExternalSearchError(
            "Configured external search provider failed ({}).".format(reason)
        ) from exc

    web = body.get("web") if isinstance(body, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        raise ExternalSearchError(
            "Configured external search provider returned an invalid response."
        )

    trusted = []
    for result in results[:MAX_EXTERNAL_RESULTS]:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        title = result.get("title")
        excerpt = result.get("description")
        if (
            not isinstance(url, str)
            or not _trusted_host(url)
            or not isinstance(title, str)
            or not isinstance(excerpt, str)
            or not title.strip()
            or not excerpt.strip()
        ):
            continue
        trusted.append(
            {
                "name": title.strip()[:240],
                "url": url,
                "excerpt": excerpt.strip()[:1200],
                "freshness": "unknown",
                "valid_from": None,
                "valid_until": None,
                "approval_status": None,
                "is_active": None,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source_type": EXTERNAL_SOURCE_TYPE,
                "verification": "candidate_evidence_requires_human_review",
            }
        )
    return trusted


def _normalize_token(token: str) -> str:
    token = token.lower().replace("’", "'")
    def restore_silent_e(value: str) -> str:
        return value + "e" if value.endswith(("v", "as", "uc", "at", "us")) else value

    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        token = restore_silent_e(token[:-3])
        if len(token) > 3 and token[-1] == token[-2]:
            token = token[:-1]
    elif len(token) > 4 and token.endswith("ed"):
        token = restore_silent_e(token[:-2])
    elif len(token) > 4 and token.endswith(("ches", "shes", "xes", "zes")):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    return token


def _meaningful_words(value: str) -> set:
    tokens = {
        _normalize_token(word)
        for word in WORD_PATTERN.findall(value)
    }
    return {
        token
        for token in tokens
        if token not in STOP_WORDS and len(token) > 2
    }


def _numbers(value: str) -> Tuple[str, ...]:
    return tuple(
        re.sub(r"\s+", "", match.group(0)).replace(",", "").lower()
        for match in NUMBER_PATTERN.finditer(value)
    )


def _sentences(value: str) -> List[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", value)
        if sentence.strip()
    ]


def _source_is_eligible(source: Dict[str, object]) -> bool:
    if source.get("source_type") == EXTERNAL_SOURCE_TYPE:
        return False
    if source.get("is_active") is False:
        return False
    if source.get("approval_status") != "approved":
        return False
    freshness = str(source.get("freshness") or "").lower()
    if freshness in {"expired", "not_yet_valid"}:
        return False

    valid_from = source.get("valid_from") or source.get("source_date")
    valid_until = source.get("valid_until") or source.get("expiry_date")
    try:
        if valid_from and date.fromisoformat(str(valid_from)[:10]) > _utc_today():
            return False
        if valid_until and date.fromisoformat(str(valid_until)[:10]) < _utc_today():
            return False
    except ValueError:
        return False
    return True


def _source_freshness(source: Dict[str, object]) -> str:
    freshness = str(source.get("freshness") or "").lower()
    try:
        valid_until = source.get("valid_until") or source.get("expiry_date")
        valid_from = source.get("valid_from") or source.get("source_date")
        if valid_until and date.fromisoformat(
            str(valid_until)[:10]
        ) < _utc_today():
            return "expired"
        if valid_from and date.fromisoformat(
            str(valid_from)[:10]
        ) > _utc_today():
            return "not_yet_valid"
    except ValueError:
        return "invalid_date"
    return freshness or "current"


def _negated(value: str) -> bool:
    normalized = value.lower().replace("’", "'")
    words = {
        _normalize_token(word)
        for word in re.findall(r"[a-z']+", normalized)
    }
    return bool(
        words.intersection(NEGATION_WORDS)
        or NEGATION_CONTRACTION_PATTERN.search(normalized)
    )


def _scope_markers(value: str) -> set:
    return {
        " ".join(match.group(0).lower().split())
        for match in SCOPE_MARKER_PATTERN.finditer(value)
    }


def _compare_sentence(claim: str, evidence_sentence: str) -> Tuple[str, float]:
    claim_words = _meaningful_words(claim)
    evidence_words = _meaningful_words(evidence_sentence)
    if not claim_words or not evidence_words:
        return "irrelevant", 0.0

    overlap = len(claim_words & evidence_words) / len(claim_words)
    predicate_words = claim_words - {
        "product", "service", "platform", "company", "customer", "client",
        "team", "user", "solution", "brand", "our", "their",
    }
    predicate_overlap = len(predicate_words & evidence_words)
    claim_numbers = _numbers(claim)
    evidence_numbers = _numbers(evidence_sentence)
    if not _scope_markers(evidence_sentence).issubset(_scope_markers(claim)):
        return "relevant", min(0.6, overlap)
    if _negated(claim) or _negated(evidence_sentence):
        if overlap >= 0.35 and predicate_overlap >= 1:
            return "relevant", min(0.6, overlap)
        return "irrelevant", overlap

    # Exact claim vocabulary and values are still only a heuristic match.
    if claim_words == evidence_words:
        if claim_numbers:
            if claim_numbers == evidence_numbers:
                return "supports", min(0.98, 0.72 + overlap * 0.26)
            if (
                evidence_numbers
                and len(claim_numbers) == len(evidence_numbers)
                and claim_words == evidence_words
                and predicate_overlap >= 2
            ):
                return "contradicts", min(0.9, 0.55 + overlap * 0.3)
            return "relevant", min(0.65, overlap)
        return "supports", min(0.9, 0.65 + overlap * 0.25)

    if overlap >= 0.45 and predicate_overlap >= 1:
        return "relevant", min(0.6, overlap)
    return "irrelevant", overlap


def _candidate_sources(evidence: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    candidates = []
    seen = set()
    for source in evidence:
        if not isinstance(source, dict):
            continue
        if source.get("source_type") == EXTERNAL_SOURCE_TYPE:
            continue
        key = (
            source.get("source_id", source.get("id")),
            source.get("name"),
            source.get("excerpt"),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(source)
    return candidates


def classify_claim(
    claim: str, evidence: Sequence[Dict[str, object]]
) -> Tuple[str, float, List[Dict[str, object]]]:
    """Return the legacy status, classifier confidence, and evidence citations."""
    if not isinstance(claim, str) or not claim.strip():
        return "unverified", 0.0, []
    if not isinstance(evidence, (list, tuple)):
        return "unverified", 0.0, []

    current_support = []
    current_conflicts = []
    relevant_current = []
    expired_matches = []
    future_matches = []

    for source in _candidate_sources(evidence):
        excerpt = source.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            continue
        if source.get("is_active") is False:
            continue
        if (
            source.get("source_type") == EXTERNAL_SOURCE_TYPE
            or source.get("approval_status") != "approved"
        ):
            continue
        freshness = _source_freshness(source)
        sentence_results = [
            _compare_sentence(claim, sentence)
            for sentence in _sentences(excerpt)
        ]
        relevant_results = [
            item
            for item in sentence_results
            if item[0] in {"supports", "contradicts", "relevant"}
        ]
        if not relevant_results:
            continue
        if freshness == "expired":
            expired_matches.append(source)
            continue
        if freshness in {"not_yet_valid", "invalid_date"}:
            future_matches.append(source)
            continue
        if not _source_is_eligible(source):
            continue
        supporting_scores = [
            score for relation, score in relevant_results if relation == "supports"
        ]
        conflicting_scores = [
            score for relation, score in relevant_results if relation == "contradicts"
        ]
        relevant_scores = [
            score for relation, score in relevant_results if relation == "relevant"
        ]
        if supporting_scores:
            current_support.append((source, max(supporting_scores)))
        if conflicting_scores:
            current_conflicts.append((source, max(conflicting_scores)))
        if relevant_scores:
            relevant_current.append((source, max(relevant_scores)))

    if current_support and current_conflicts:
        citations = []
        seen_citations = set()
        for source, _score in current_support[:2] + current_conflicts[:2]:
            key = (
                source.get("source_id", source.get("id")),
                source.get("name"),
                source.get("excerpt"),
            )
            if key not in seen_citations:
                seen_citations.add(key)
                citations.append(source)
        return "conflicting_evidence", 0.55, citations
    if current_support:
        return "verified", 0.9, [
            source for source, _ in current_support[:3]
        ]
    if current_conflicts:
        return "contradicted", 0.8, [
            source for source, _ in current_conflicts[:3]
        ]
    if expired_matches:
        return "expired_evidence", 0.95, expired_matches[:3]
    if relevant_current:
        return "unverified", 0.8, [source for source, _ in relevant_current[:3]]
    if future_matches:
        return "unverified", 0.9, future_matches[:3]
    return "unverified", 0.95 if not evidence else 0.75, []


CANONICAL_STATUS = {
    "verified": "supported",
    "contradicted": "unsupported",
    "conflicting_evidence": "conflicting",
    "unverified": "unverified",
    "expired_evidence": "expired_evidence",
}


def verification_fields(
    claim: str,
    evidence: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    if not isinstance(claim, str) or not claim.strip():
        legacy_status, confidence, citations = "unverified", 0.0, []
    else:
        legacy_status, confidence, citations = classify_claim(claim, evidence)
    evidence_status = CANONICAL_STATUS[legacy_status]
    explanations = {
        "supported": (
            "A heuristic vocabulary and value match was found in current approved evidence. "
            "This is not proof of truth; confirm source scope, context, units, and baseline "
            "before use."
        ),
        "unsupported": (
            "A close heuristic match with different values was found in current approved "
            "evidence. The claim is not supported as written; confirm source scope, units, "
            "and baseline before treating it as a contradiction."
        ),
        "conflicting": (
            "Current approved sources produced heuristic matches with different values. "
            "A reviewer must resolve source scope, units, dates, and authority."
        ),
        "unverified": (
            "No current approved evidence substantiates the complete claim. "
            "Similarity or partial matches are not proof; human verification is required. "
            "Lack of evidence does not establish that the claim is false."
        ),
        "expired_evidence": (
            "Relevant evidence was found, but all matching approved evidence has expired. "
            "It cannot verify this claim; obtain current approval or evidence."
        ),
    }
    evidence_strength = {
        "supported": 0.9,
        "unsupported": 0.75,
        "conflicting": 0.5,
        "unverified": 0.0,
        "expired_evidence": 0.0,
    }[evidence_status]
    return {
        "claim": claim.strip() if isinstance(claim, str) else "",
        "verification_status": legacy_status,
        "evidence_status": evidence_status,
        "citations": citations,
        "verification_explanation": explanations[evidence_status],
        "evidence_reason": explanations[evidence_status],
        "verification_confidence": confidence,
        "evidence_strength": evidence_strength,
    }
