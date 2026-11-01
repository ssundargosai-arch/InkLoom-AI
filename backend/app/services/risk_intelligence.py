import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.config import PUBLISH_RISK_THRESHOLDS, RISK_SEVERITY_WEIGHTS

RESOLVED_FINDING_STATUSES = {
    "accepted",
    "closed",
    "dismissed",
    "fixed",
    "resolved",
}
CLAIM_CATEGORIES = {
    "promotional_claim",
    "unsupported_claim",
    "unsupported_promotional_claim",
    "factual_claim",
}
EVIDENCE_MULTIPLIERS = {
    "supported": 0.25,
    "verified": 0.25,
    "unsupported": 1.4,
    "conflicting": 1.5,
    "conflicting_evidence": 1.5,
    "unverified": 1.1,
    "expired_evidence": 1.2,
    "contradicted": 1.5,
}
FRESHNESS_PENALTIES = {
    "expired": 12,
    "inactive": 12,
    "rejected": 10,
    "pending": 8,
    "not_yet_valid": 8,
    "review_overdue": 6,
    "expiring_soon": 3,
}


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _finding_status(finding: Dict[str, Any]) -> str:
    return str(
        finding.get("review_status") or finding.get("status") or "pending"
    ).strip().lower()


def _evidence_status(finding: Dict[str, Any]) -> str:
    return str(
        finding.get("evidence_status")
        or finding.get("verification_status")
        or ""
    ).strip().lower()


def _finding_contribution(finding: Dict[str, Any]) -> Dict[str, Any]:
    severity = str(finding.get("severity") or "low").strip().lower()
    severity_points = RISK_SEVERITY_WEIGHTS.get(severity, RISK_SEVERITY_WEIGHTS["low"])
    evidence_status = _evidence_status(finding)
    evidence_multiplier = EVIDENCE_MULTIPLIERS.get(evidence_status, 1.0)
    confidence = finding.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = finding.get("verification_confidence", 0.5)
    try:
        confidence_value = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_value = 0.5
    confidence_factor = 0.5 + (0.5 * confidence_value)
    severity_risk = round(
        severity_points * evidence_multiplier * confidence_factor
    )
    category = str(finding.get("category") or "").lower()
    guideline_points = (
        5
        if finding.get("guideline_id") is not None
        or "guideline" in category
        or "brand" in category
        else 0
    )
    visual_points = (
        5
        if isinstance(finding.get("visual_data"), dict)
        or "visual" in category
        else 0
    )
    severity_risk = max(0, severity_risk)
    points = severity_risk + guideline_points + visual_points
    return {
        "points": points,
        "severity_points": severity_risk,
        "guideline_points": guideline_points,
        "visual_points": visual_points,
        "evidence_status": evidence_status or "not_applicable",
        "severity": severity,
        "confidence_factor": round(confidence_factor, 3),
    }


def _overlap_groups(findings: List[Dict[str, Any]]) -> List[List[int]]:
    parents = list(range(len(findings)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    ranges: List[Optional[Tuple[int, int]]] = []
    texts = []
    for finding in findings:
        start = finding.get("claim_start")
        end = finding.get("claim_end")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and start >= 0
            and end > start
        ):
            ranges.append((start, end))
        else:
            ranges.append(None)
        texts.append(_normalized(finding.get("matched_text") or finding.get("claim")))

    for first in range(len(findings)):
        for second in range(first + 1, len(findings)):
            first_range = ranges[first]
            second_range = ranges[second]
            intervals_overlap = bool(
                first_range
                and second_range
                and first_range[0] < second_range[1]
                and second_range[0] < first_range[1]
            )
            duplicate_text = bool(texts[first] and texts[first] == texts[second])
            if intervals_overlap or duplicate_text:
                union(first, second)

    groups: Dict[int, List[int]] = {}
    for index in range(len(findings)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def calculate_risk(
    findings: Iterable[Dict[str, Any]],
    source_freshness: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    all_findings = [finding for finding in findings if isinstance(finding, dict)]
    unresolved = [
        finding
        for finding in all_findings
        if _finding_status(finding) not in RESOLVED_FINDING_STATUSES
    ]
    grouped = _overlap_groups(unresolved)
    contributions = [_finding_contribution(item) for item in unresolved]
    included = []
    deduplicated = []
    category_points = {
        "findings": 0,
        "guideline_violations": 0,
        "visual_findings": 0,
        "evidence_freshness": 0,
    }

    for group in grouped:
        winner = max(group, key=lambda index: (contributions[index]["points"], -index))
        winner_contribution = contributions[winner]
        included.append(
            {
                "finding_id": unresolved[winner].get("id"),
                "title": unresolved[winner].get("title") or "Finding",
                **winner_contribution,
                "overlap_count": len(group),
            }
        )
        category_points["findings"] += winner_contribution["severity_points"]
        category_points["guideline_violations"] += winner_contribution["guideline_points"]
        category_points["visual_findings"] += winner_contribution["visual_points"]
        for index in group:
            if index != winner:
                deduplicated.append(
                    {
                        "finding_id": unresolved[index].get("id"),
                        "merged_into_finding_id": unresolved[winner].get("id"),
                    }
                )

    freshness_items = []
    freshness_seen = set()
    for item in source_freshness or []:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        key = source_id if source_id is not None else (
            item.get("source_name"),
            item.get("status"),
        )
        if key in freshness_seen:
            continue
        freshness_seen.add(key)
        status_value = str(item.get("status") or "unknown").lower()
        points = FRESHNESS_PENALTIES.get(status_value, 0)
        if points:
            freshness_items.append(
                {
                    "source_id": source_id,
                    "source_name": item.get("source_name"),
                    "status": status_value,
                    "points": points,
                }
            )
            category_points["evidence_freshness"] += points

    raw_score = sum(item["points"] for item in included) + sum(
        item["points"] for item in freshness_items
    )
    score = min(100, max(0, round(raw_score)))
    level = (
        "Critical"
        if score >= PUBLISH_RISK_THRESHOLDS["critical"]
        else "High"
        if score >= PUBLISH_RISK_THRESHOLDS["high"]
        else "Medium"
        if score >= PUBLISH_RISK_THRESHOLDS["medium"]
        else "Low"
    )
    return {
        "score": score,
        "level": level,
        "is_heuristic_estimate": True,
        "verified_fact_assessment": False,
        "breakdown": {
            "category_points": {
                key: round(value, 2) for key, value in category_points.items()
            },
            "finding_contributions": included,
            "deduplicated_overlaps": deduplicated,
            "evidence_freshness_contributions": freshness_items,
            "raw_score": round(raw_score, 2),
            "score_cap": 100,
            "thresholds": {
                "medium": PUBLISH_RISK_THRESHOLDS["medium"],
                "high": PUBLISH_RISK_THRESHOLDS["high"],
                "critical": PUBLISH_RISK_THRESHOLDS["critical"],
            },
            "severity_weights": dict(RISK_SEVERITY_WEIGHTS),
        },
    }


def evaluate_publish_readiness(
    *,
    review_status: str,
    risk: Dict[str, Any],
    findings: Iterable[Dict[str, Any]],
    analysis_is_current: bool,
    approvals_complete: bool,
    approval_bypassed: bool,
    invalid_guidelines: Iterable[Dict[str, Any]] = (),
    invalid_sources: Iterable[Dict[str, Any]] = (),
    publication: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    all_findings = [item for item in findings if isinstance(item, dict)]
    blockers = []
    warnings = []
    if str(review_status).lower() != "approved":
        blockers.append(
            {
                "code": "review_not_approved",
                "message": "The review must be approved before publishing.",
                "eligible_for_override": False,
            }
        )
    if not analysis_is_current:
        blockers.append(
            {
                "code": "analysis_stale",
                "message": "The latest content revision does not have a matching analysis.",
                "eligible_for_override": False,
            }
        )
    if not approvals_complete and not approval_bypassed:
        blockers.append(
            {
                "code": "approvals_incomplete",
                "message": "Every required approval stage must be completed for the current revision.",
                "eligible_for_override": False,
            }
        )
    elif approval_bypassed:
        warnings.append(
            {
                "code": "approval_stages_bypassed",
                "message": "Approval stages were explicitly bypassed by an Admin for this revision.",
            }
        )

    for guideline in invalid_guidelines:
        blockers.append(
            {
                "code": "mandatory_guideline_unavailable",
                "message": "A guideline selected for this review is no longer active and approved.",
                "guideline_id": guideline.get("guideline_id"),
                "eligible_for_override": False,
            }
        )

    for source in invalid_sources:
        blockers.append(
            {
                "code": "cited_evidence_invalid",
                "message": "Cited organisational evidence is no longer approved, active, or currently valid.",
                "source_id": source.get("source_id"),
                "source_name": source.get("source_name"),
                "freshness": source.get("status"),
                "eligible_for_override": True,
            }
        )
    freshness_warnings = [
        item
        for item in risk["breakdown"]["evidence_freshness_contributions"]
        if item["status"] in {"review_overdue", "expiring_soon"}
    ]
    for source in freshness_warnings:
        warnings.append(
            {
                "code": "evidence_freshness_warning",
                "message": "Cited evidence requires freshness attention.",
                "source_id": source.get("source_id"),
                "source_name": source.get("source_name"),
                "freshness": source["status"],
            }
        )

    for finding in all_findings:
        if _finding_status(finding) in RESOLVED_FINDING_STATUSES:
            continue
        severity = str(finding.get("severity") or "").lower()
        evidence_status = _evidence_status(finding)
        category = str(finding.get("category") or "").lower()
        is_claim = category in CLAIM_CATEGORIES
        finding_ref = {
            "finding_id": finding.get("id"),
            "title": finding.get("title") or "Finding",
            "severity": severity,
            "evidence_status": evidence_status or "not_applicable",
        }
        if severity == "critical":
            blockers.append(
                {
                    "code": "unresolved_critical_finding",
                    "message": "An unresolved critical finding must be addressed before publishing.",
                    **finding_ref,
                    "eligible_for_override": True,
                }
            )
        if is_claim and evidence_status in {
            "unsupported",
            "conflicting",
            "conflicting_evidence",
            "unverified",
            "expired_evidence",
            "contradicted",
        } and severity in {"high", "critical"}:
            blockers.append(
                {
                    "code": "unsupported_high_risk_claim",
                    "message": "A high-risk claim lacks current, supporting evidence.",
                    **finding_ref,
                    "eligible_for_override": True,
                }
            )

    if publication:
        state = "Published"
    elif blockers:
        state = "Blocked"
    elif warnings or risk["level"] != "Low":
        state = "Ready with Warnings"
    else:
        state = "Ready"
    return {
        "state": state,
        "risk": risk,
        "blockers": blockers,
        "warnings": warnings,
        "can_publish": not blockers and publication is None,
        "can_override": (
            publication is None
            and bool(blockers)
            and all(item.get("eligible_for_override") for item in blockers)
        ),
        "publication": publication,
    }
