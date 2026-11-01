from typing import Any, Dict

from app.models.content_review import ContentReview


def finding_payload(finding: Any) -> Dict[str, Any]:
    payload = {
        "id": finding.id,
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "message": finding.explanation,
        "matched_text": finding.matched_text,
        "suggestion": finding.suggestion,
        "source": finding.source,
        "guideline": finding.source,
        "guideline_id": finding.guideline_id,
        "confidence": finding.confidence,
        "status": finding.review_status,
        "review_status": finding.review_status,
    }
    payload.update(finding.metadata_json or {})
    return payload


def review_payload(review: ContentReview, viewer=None) -> Dict[str, Any]:
    may_view_internal = viewer is None or viewer.role in {"admin", "reviewer"}
    comments = [
        comment
        for comment in review.comments
        if may_view_internal or not comment.is_internal
    ]
    assignments = list(getattr(review, "reviewer_assignments", []) or [])
    decisions = list(getattr(review, "approval_decisions", []) or [])
    bypasses = list(getattr(review, "approval_bypasses", []) or [])
    current_version_id = max(
        (revision.id for revision in review.revisions),
        default=0,
    )
    stage_numbers = sorted(
        {assignment.stage_number for assignment in assignments}
    )
    active_stage = next(
        (
            stage
            for stage in stage_numbers
            if not all(
                any(
                    decision.reviewer_id == assignment.reviewer_id
                    and decision.version_id == current_version_id
                    and decision.decision == "approved"
                    for decision in decisions
                )
                for assignment in assignments
                if assignment.stage_number == stage
            )
        ),
        stage_numbers[-1] if stage_numbers else None,
    )
    stage_summaries = []
    for stage in stage_numbers:
        stage_assignments = [
            item for item in assignments if item.stage_number == stage
        ]
        stage_decisions = [
            decision
            for decision in decisions
            if decision.version_id == current_version_id
            if decision.reviewer_id
            in {assignment.reviewer_id for assignment in stage_assignments}
        ]
        approved_count = sum(
            decision.decision == "approved" for decision in stage_decisions
        )
        stage_summaries.append(
            {
                "stage_number": stage,
                "required": len(stage_assignments),
                "approved": approved_count,
                "completed": len(stage_decisions),
                "status": (
                    "completed"
                    if approved_count == len(stage_assignments)
                    else "rejected"
                    if any(decision.decision == "rejected" for decision in stage_decisions)
                    else "changes_requested"
                    if any(decision.decision == "changes_requested" for decision in stage_decisions)
                    else "pending"
                ),
                "reviewers": [
                    {
                        "id": assignment.reviewer_id,
                        "display_name": (
                            assignment.reviewer.display_name
                            if assignment.reviewer
                            else None
                        ),
                        "decision": next(
                            (
                                decision.decision
                                for decision in stage_decisions
                                if decision.reviewer_id == assignment.reviewer_id
                            ),
                            "pending",
                        ),
                    }
                    for assignment in stage_assignments
                ],
            }
        )
    analysis_runs = list(review.analysis_runs or [])
    version_history = []
    if analysis_runs:
        original_run = analysis_runs[0]
        version_history.append(
            {
                "id": 0,
                "content": original_run.content,
                "title": "Original submission",
                "author": (
                    original_run.created_by.display_name
                    if original_run.created_by
                    else None
                ),
                "author_id": original_run.created_by_id,
                "created_at": original_run.created_at,
                "is_original": True,
            }
        )
    elif not review.revisions:
        version_history.append(
            {
                "id": 0,
                "content": review.content,
                "title": "Original submission (legacy baseline)",
                "author": (
                    review.submitted_by.display_name
                    if review.submitted_by
                    else None
                ),
                "author_id": review.submitted_by_id,
                "created_at": review.created_at,
                "is_original": True,
            }
        )
    version_history.extend(
        {
            "id": revision.id,
            "content": revision.content,
            "title": revision.title or "Revision",
            "author": revision.author.display_name if revision.author else None,
            "author_id": revision.author_id,
            "created_at": revision.created_at,
            "is_original": False,
        }
        for revision in review.revisions
    )

    return {
        "id": review.id,
        "title": review.title,
        "content": review.content,
        "content_type": review.content_type,
        "status": review.status,
        "reviewer": review.reviewer,
        "reviewer_name": review.reviewer,
        "assigned_reviewer_id": review.assigned_reviewer_id,
        "assigned_reviewer": (
            {
                "id": review.assigned_reviewer.id,
                "display_name": review.assigned_reviewer.display_name,
            }
            if review.assigned_reviewer
            else None
        ),
        "assigned_reviewers": [
            {
                "id": assignment.reviewer_id,
                "display_name": (
                    assignment.reviewer.display_name
                    if assignment.reviewer
                    else None
                ),
                "stage_number": assignment.stage_number,
            }
            for assignment in assignments
        ],
        "approval_stages": stage_summaries,
        "active_approval_stage": active_stage,
        "current_version_id": current_version_id,
        "approval_decisions": [
            {
                "reviewer_id": decision.reviewer_id,
                "reviewer": (
                    decision.reviewer.display_name if decision.reviewer else None
                ),
                "decision": decision.decision,
                "reason": decision.reason,
                "version_id": decision.version_id,
                "acknowledged_warning_ids": decision.acknowledged_warning_ids or [],
                "created_at": decision.created_at,
            }
            for decision in decisions
        ],
        "approval_bypasses": [
            {
                "id": bypass.id,
                "initiated_by": (
                    bypass.initiated_by.display_name
                    if bypass.initiated_by
                    else None
                ),
                "reason": bypass.reason,
                "version_id": bypass.version_id,
                "created_at": bypass.created_at,
                "acknowledged_warning_ids": bypass.acknowledged_warning_ids or [],
            }
            for bypass in bypasses
        ],
        "submitted_at": review.created_at,
        "analysis_timestamp": review.analysis_timestamp,
        "issue_count": len(review.findings),
        "findings": [finding_payload(item) for item in review.findings],
        "visual_attachment": (
            {
                "filename": review.visual_attachment.filename,
                "media_type": review.visual_attachment.media_type,
                "url": "/api/reviews/{}/visual-attachment".format(review.id),
                "analysis": review.visual_attachment.analysis_metadata or {},
            }
            if review.visual_attachment
            else None
        ),
        "comments": [
            {
                "id": comment.id,
                "comment": comment.comment,
                "author": comment.author,
                "created_at": comment.created_at,
                "is_internal": comment.is_internal,
                "parent_id": comment.parent_id,
            }
            for comment in comments
        ],
        "revisions": [
            {
                "id": revision.id,
                "content": revision.content,
                "title": revision.title,
                "summary": revision.title or "Revision",
                "created_at": revision.created_at,
                "author_id": revision.author_id,
                "author": revision.author.display_name if revision.author else None,
            }
            for revision in review.revisions
        ],
        "versions": version_history,
        "analysis_runs": [
            {
                "id": run.id,
                "content": run.content,
                "findings": run.findings or [],
                "analysis_engine": run.analysis_engine,
                "evidence_retrieval_method": run.evidence_retrieval_method,
                "warnings": run.warnings or [],
                "created_by": (
                    run.created_by.display_name if run.created_by else None
                ),
                "created_at": run.created_at,
            }
            for run in review.analysis_runs
        ],
    }
