
import asyncio
import difflib
import hashlib
import json
import re
from functools import wraps
from threading import Lock

from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.brand_voice import BrandVoiceConfiguration
from app.models.content_review import (
    ContentReview,
    ReviewAnalysisRun,
    ReviewFinding,
    ReviewRevision,
)
from app.models.review_comment import (
    ReviewActivity,
    ReviewApprovalBypass,
    ReviewApprovalDecision,
    ReviewAssignment,
    ReviewComment,
)
from app.models.review_publish import (
    ReviewPublication,
    ReviewPublishAuditEvent,
)
from app.models.source_document import SourceDocument
from app.models.user import User
from app.models.visual_asset import ReviewVisualAttachment

from app.schemas.reviews import (
    AssignmentUpdate,
    ApprovalBypassCreate,
    ApprovalDecisionCreate,
    CommentCreate,
    RevisionCreate,
    ReviewerAssignmentsUpdate,
    PublishOverrideCreate,
    StatusUpdate,
)

from app.services.audit_service import record_status_change
from app.services.activity_service import record_activity
from app.services.collaboration import collaboration_hub
from app.services.review_service import review_payload, finding_payload
from app.services.risk_intelligence import (
    calculate_risk,
    evaluate_publish_readiness,
)
from app.services.freshness_service import source_freshness
from app.services.claim_checker import (
    check_promotional_claims,
    factual_claim_excerpts,
)
from app.services.factual_verifier import verification_fields
from app.services.source_retrieval import (
    EmbeddingProviderError,
    retrieve_evidence,
    retrieve_lexical_evidence,
    retrieval_method,
)
from app.services.source_access import apply_source_visibility
from app.services.text_analyzer import analyze_text
from app.services.auth_service import authenticate_token, require_roles

from app.config import MAX_CONTENT_LENGTH, CORS_ORIGINS


router = APIRouter(
    prefix="/api/reviews",
    tags=["reviews"],
)

ALLOWED_STATUS_TRANSITIONS = {
    "draft": {"submitted"},
    "submitted": {
        "draft",
        "in_review",
        "changes_requested",
        "approved",
        "rejected",
    },
    "pending": {
        "draft",
        "in_review",
        "changes_requested",
        "approved",
        "rejected",
    },
    "in_review": {"changes_requested", "approved", "rejected"},
    "changes_requested": {
        "submitted",
        "in_review",
        "approved",
        "rejected",
    },
    "approved": set(),
    "rejected": set(),
}
_PUBLISH_SERIALIZER = Lock()


def _serialize_publish_action(function):
    @wraps(function)
    def serialized(*args, **kwargs):
        with _PUBLISH_SERIALIZER:
            return function(*args, **kwargs)

    return serialized


def _get_review(
    db: Session,
    review_id: int,
    for_update: bool = False,
) -> ContentReview:
    query = (
        db.query(ContentReview)
        .options(
            selectinload(ContentReview.findings),
            selectinload(ContentReview.comments),
            selectinload(ContentReview.revisions),
            selectinload(ContentReview.analysis_runs),
            selectinload(ContentReview.assigned_reviewer),
            selectinload(ContentReview.reviewer_assignments).selectinload(
                ReviewAssignment.reviewer
            ),
            selectinload(ContentReview.approval_decisions).selectinload(
                ReviewApprovalDecision.reviewer
            ),
            selectinload(ContentReview.approval_bypasses).selectinload(
                ReviewApprovalBypass.initiated_by
            ),
        )
        .filter(ContentReview.id == review_id)
    )
    if for_update:
        query = query.with_for_update()
    review = query.first()

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Review not found.",
        )

    return review


def _authorize_review_access(review: ContentReview, user: User) -> None:
    if user.role == "contributor" and review.submitted_by_id != user.id:
        raise HTTPException(status_code=404, detail="Review not found.")


def _approval_warnings(review: ContentReview) -> list:
    terminal_finding_statuses = {
        "accepted",
        "closed",
        "dismissed",
        "fixed",
        "resolved",
    }
    unsupported_claim_categories = {
        "promotional_claim",
        "unsupported_claim",
        "unsupported_promotional_claim",
    }
    warnings = []

    for finding in review.findings:
        item = finding_payload(finding)
        finding_status = str(
            item.get("review_status") or item.get("status") or "pending"
        ).lower()
        if finding_status in terminal_finding_statuses:
            continue

        severity = str(item.get("severity") or "").lower()
        category = str(item.get("category") or "").lower()
        verification_status = str(
            item.get("evidence_status")
            or item.get("verification_status")
            or ""
        ).lower()
        claim_has_unresolved_evidence = (
            verification_status
            in {
                "contradicted",
                "conflicting_evidence",
                "unverified",
                "expired_evidence",
                "unsupported",
                "conflicting",
            }
            or (
                category in unsupported_claim_categories
                and verification_status not in {"verified", "supported"}
            )
        )
        reasons = []

        if severity == "critical":
            reasons.append("unresolved_critical_finding")
        if claim_has_unresolved_evidence:
            reasons.append("claim_requires_human_verification")

        if not reasons:
            continue

        warnings.append(
            {
                "finding_id": item["id"],
                "title": item["title"],
                "category": item["category"],
                "severity": item["severity"],
                "claim": item.get("claim") or item.get("matched_text"),
                "verification_status": item.get("verification_status"),
                "explanation": (
                    item.get("verification_explanation")
                    or item.get("explanation")
                ),
                "citations": item.get("citations") or [],
                "reasons": reasons,
            }
        )

    return warnings


def _current_version_id(review: ContentReview) -> int:
    return max((revision.id for revision in review.revisions), default=0)


def _active_approval_stage(review: ContentReview) -> Optional[int]:
    assignments = list(review.reviewer_assignments or [])
    if not assignments:
        return None
    version_id = _current_version_id(review)
    decisions = {
        decision.reviewer_id: decision.decision
        for decision in review.approval_decisions
        if decision.version_id == version_id
    }
    for stage in sorted({item.stage_number for item in assignments}):
        stage_assignments = [
            item for item in assignments if item.stage_number == stage
        ]
        if not all(
            decisions.get(item.reviewer_id) == "approved"
            for item in stage_assignments
        ):
            return stage
    return None


def _all_assigned_reviewers_approved(review: ContentReview) -> bool:
    assignments = list(review.reviewer_assignments or [])
    if not assignments:
        return True
    version_id = _current_version_id(review)
    decisions = {
        decision.reviewer_id: decision.decision
        for decision in review.approval_decisions
        if decision.version_id == version_id
    }
    return all(decisions.get(item.reviewer_id) == "approved" for item in assignments)


@router.get("")
def list_reviews(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    review_status: str = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    query = db.query(ContentReview)
    if _user.role == "contributor":
        query = query.filter(ContentReview.submitted_by_id == _user.id)

    if review_status:
        if review_status not in {
            "draft",
            "submitted",
            "pending",
            "in_review",
            "approved",
            "changes_requested",
            "rejected",
        }:
            raise HTTPException(
                status_code=422,
                detail="Unsupported review status.",
            )

        query = query.filter(
            ContentReview.status == review_status
        )

    total = query.count()

    reviews = (
        query.options(
            selectinload(ContentReview.findings),
            selectinload(ContentReview.assigned_reviewer),
            selectinload(ContentReview.reviewer_assignments).selectinload(
                ReviewAssignment.reviewer
            ),
        )
        .order_by(
            ContentReview.created_at.desc(),
            ContentReview.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []

    for review in reviews:
        items.append(
            {
                "id": review.id,
                "title": review.title,
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
                    for assignment in review.reviewer_assignments
                ],
                "submitted_at": review.created_at,
                "analysis_timestamp": review.analysis_timestamp,
                "issue_count": len(review.findings),
            }
        )

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def _publish_assessment(db: Session, review: ContentReview) -> dict:
    version_id = _current_version_id(review)
    latest_run = max(review.analysis_runs or [], key=lambda run: run.id, default=None)
    analysis_is_current = bool(
        latest_run is not None and latest_run.content == review.content
    )
    findings = [finding_payload(item) for item in review.findings]
    citations = [
        citation
        for finding in findings
        for citation in (finding.get("citations") or [])
        if isinstance(citation, dict)
    ]
    internal_source_ids = {
        citation.get("source_id")
        for citation in citations
        if citation.get("source_type") == "approved_internal_source"
        and isinstance(citation.get("source_id"), int)
        and not isinstance(citation.get("source_id"), bool)
    }
    source_rows = (
        db.query(SourceDocument)
        .filter(SourceDocument.id.in_(internal_source_ids))
        .all()
        if internal_source_ids
        else []
    )
    sources_by_id = {source.id: source for source in source_rows}
    freshness_items = []
    invalid_sources = []
    seen_sources = set()
    for citation in citations:
        if citation.get("source_type") != "approved_internal_source":
            continue
        source_id = citation.get("source_id")
        if not isinstance(source_id, int) or isinstance(source_id, bool):
            continue
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        source = sources_by_id.get(source_id)
        source_status = source_freshness(source) if source else "missing"
        source_name = (
            source.name if source else citation.get("name") or "Evidence source"
        )
        freshness_items.append(
            {
                "source_id": source_id,
                "source_name": source_name,
                "status": source_status,
            }
        )
        if source is None or source_status not in {"current", "expiring_soon"}:
            invalid_sources.append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "status": source_status,
                }
            )

    guideline_ids = {
        item for item in (review.guideline_ids or []) if isinstance(item, int)
    }
    guidelines = (
        db.query(BrandGuideline)
        .filter(BrandGuideline.id.in_(guideline_ids))
        .all()
        if guideline_ids
        else []
    )
    guidelines_by_id = {guideline.id: guideline for guideline in guidelines}
    invalid_guidelines = [
        {"guideline_id": guideline_id}
        for guideline_id in sorted(guideline_ids)
        if guideline_id not in guidelines_by_id
        or not guidelines_by_id[guideline_id].is_active
        or guidelines_by_id[guideline_id].status != "approved"
    ]
    risk = calculate_risk(findings, freshness_items)
    bypass_exists = any(
        bypass.version_id == version_id
        for bypass in (review.approval_bypasses or [])
    )
    publication_row = (
        db.query(ReviewPublication)
        .filter(
            ReviewPublication.review_id == review.id,
            ReviewPublication.version_id == version_id,
        )
        .first()
    )
    publication = (
        _publication_payload(publication_row)
        if publication_row is not None
        else None
    )
    readiness = evaluate_publish_readiness(
        review_status=review.status,
        risk=risk,
        findings=findings,
        analysis_is_current=analysis_is_current,
        approvals_complete=_all_assigned_reviewers_approved(review),
        approval_bypassed=bypass_exists,
        invalid_guidelines=invalid_guidelines,
        invalid_sources=invalid_sources,
        publication=publication,
    )
    return {
        **readiness,
        "review_id": review.id,
        "revision_id": version_id,
        "analysis": {
            "is_current": analysis_is_current,
            "analysis_run_id": latest_run.id if latest_run else None,
            "analyzed_at": latest_run.created_at if latest_run else None,
        },
        "approval_stages": review_payload(review)["approval_stages"],
    }


def _publication_payload(publication: ReviewPublication) -> dict:
    return {
        "id": publication.id,
        "review_id": publication.review_id,
        "revision_id": publication.version_id,
        "published_by_id": publication.published_by_id,
        "published_by": (
            publication.published_by.display_name
            if publication.published_by
            else None
        ),
        "risk_score": publication.risk_score,
        "risk_level": publication.risk_level,
        "snapshot": publication.snapshot or {},
        "created_at": publication.created_at,
    }


def _publish_event(
    db: Session,
    review: ContentReview,
    user: User,
    action: str,
    assessment: dict,
    details: Optional[dict] = None,
    publication: Optional[ReviewPublication] = None,
) -> None:
    event_details = {
        "state": assessment["state"],
        "blockers": assessment["blockers"],
        "warnings": assessment["warnings"],
        "risk": assessment["risk"],
        **(details or {}),
    }
    db.add(
        ReviewPublishAuditEvent(
            review_id=review.id,
            publication_id=publication.id if publication else None,
            actor_id=user.id,
            action=action,
            version_id=assessment["revision_id"],
            decision=action,
            risk_score=assessment["risk"]["score"],
            risk_level=assessment["risk"]["level"],
            details=jsonable_encoder(event_details),
        )
    )
    record_activity(
        db,
        review.id,
        action,
        actor=user.display_name,
        details={
            "revision_id": assessment["revision_id"],
            "risk_score": assessment["risk"]["score"],
            "risk_level": assessment["risk"]["level"],
            "blockers": assessment["blockers"],
            **(details or {}),
        },
    )


def _require_publish_actor(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only Admins may publish content.",
        )


@router.get("/{review_id}/publish-readiness")
def get_publish_readiness(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    review = _get_review(db, review_id, for_update=False)
    _authorize_review_access(review, user)
    return _publish_assessment(db, review)


@router.get("/{review_id}/publish-history")
def get_publish_history(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    review = _get_review(db, review_id, for_update=False)
    _authorize_review_access(review, user)
    publications = (
        db.query(ReviewPublication)
        .filter(ReviewPublication.review_id == review_id)
        .order_by(ReviewPublication.id.desc())
        .all()
    )
    events = (
        db.query(ReviewPublishAuditEvent)
        .filter(ReviewPublishAuditEvent.review_id == review_id)
        .order_by(ReviewPublishAuditEvent.id.desc())
        .all()
    )
    return {
        "publications": [_publication_payload(item) for item in publications],
        "events": [
            {
                "id": event.id,
                "action": event.action,
                "revision_id": event.version_id,
                "decision": event.decision,
                "risk_score": event.risk_score,
                "risk_level": event.risk_level,
                "actor": event.actor.display_name if event.actor else None,
                "details": event.details or {},
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


@router.post("/{review_id}/publish")
@_serialize_publish_action
def publish_review(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    review = _get_review(db, review_id, for_update=True)
    _authorize_review_access(review, user)
    _require_publish_actor(user)
    assessment = _publish_assessment(db, review)
    if assessment["publication"]:
        _publish_event(
            db,
            review,
            user,
            "publish_duplicate_request",
            assessment,
            publication=(
                db.query(ReviewPublication)
                .filter(
                    ReviewPublication.review_id == review.id,
                    ReviewPublication.version_id == assessment["revision_id"],
                )
                .first()
            ),
        )
        db.commit()
        return {
            **assessment,
            "publication": assessment["publication"],
            "idempotent": True,
        }
    if not assessment["can_publish"]:
        _publish_event(db, review, user, "publish_blocked", assessment)
        db.commit()
        raise HTTPException(
            status_code=409,
            detail=jsonable_encoder(assessment),
        )

    content_hash = hashlib.sha256(review.content.encode("utf-8")).hexdigest()
    snapshot = {
        "revision_id": assessment["revision_id"],
        "content_sha256": content_hash,
        "risk": assessment["risk"],
        "warnings": assessment["warnings"],
        "approval_stages": assessment["approval_stages"],
        "analysis": assessment["analysis"],
        "overridden_blockers": [],
    }
    publication = ReviewPublication(
        review_id=review.id,
        version_id=assessment["revision_id"],
        published_by_id=user.id,
        risk_score=assessment["risk"]["score"],
        risk_level=assessment["risk"]["level"],
        snapshot=jsonable_encoder(snapshot),
    )
    db.add(publication)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(ReviewPublication)
            .filter(
                ReviewPublication.review_id == review_id,
                ReviewPublication.version_id == assessment["revision_id"],
            )
            .first()
        )
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail="A concurrent publish decision could not be completed.",
            )
        duplicate_assessment = _publish_assessment(
            db, _get_review(db, review_id)
        )
        _publish_event(
            db,
            _get_review(db, review_id),
            user,
            "publish_duplicate_request",
            duplicate_assessment,
            publication=existing,
        )
        db.commit()
        return {
            **duplicate_assessment,
            "publication": _publication_payload(existing),
            "idempotent": True,
        }
    assessment["state"] = "Published"
    assessment["can_publish"] = False
    assessment["publication"] = _publication_payload(publication)
    _publish_event(
        db,
        review,
        user,
        "published",
        assessment,
        publication=publication,
    )
    db.commit()
    db.refresh(publication)
    return {
        **assessment,
        "publication": _publication_payload(publication),
        "idempotent": False,
    }


@router.post("/{review_id}/publish/override")
@_serialize_publish_action
def override_publish_blockers(
    review_id: int,
    payload: PublishOverrideCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    review = _get_review(db, review_id, for_update=True)
    _authorize_review_access(review, admin)
    assessment = _publish_assessment(db, review)
    if assessment["publication"]:
        raise HTTPException(
            status_code=409,
            detail="This revision has already been published.",
        )
    if not assessment["can_override"]:
        raise HTTPException(
            status_code=409,
            detail=jsonable_encoder({
                **assessment,
                "message": (
                    "Only eligible content-risk or evidence-freshness blockers can be overridden. "
                    "Review approval, required stages, current analysis, and active guidelines remain mandatory."
                ),
            }),
        )

    overridden = assessment["blockers"]
    snapshot = {
        "revision_id": assessment["revision_id"],
        "content_sha256": hashlib.sha256(review.content.encode("utf-8")).hexdigest(),
        "risk": assessment["risk"],
        "warnings": assessment["warnings"],
        "approval_stages": assessment["approval_stages"],
        "analysis": assessment["analysis"],
        "overridden_blockers": overridden,
        "override_reason": payload.reason,
        "override_actor_id": admin.id,
    }
    publication = ReviewPublication(
        review_id=review.id,
        version_id=assessment["revision_id"],
        published_by_id=admin.id,
        risk_score=assessment["risk"]["score"],
        risk_level=assessment["risk"]["level"],
        snapshot=jsonable_encoder(snapshot),
    )
    db.add(publication)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This revision has already been published.",
        ) from exc

    assessment["state"] = "Published"
    assessment["can_publish"] = False
    assessment["can_override"] = False
    assessment["overridden_blockers"] = overridden
    assessment["override_reason"] = payload.reason
    assessment["publication"] = _publication_payload(publication)
    _publish_event(
        db,
        review,
        admin,
        "publish_override",
        assessment,
        details={
            "reason": payload.reason,
            "overridden_blockers": overridden,
        },
        publication=publication,
    )
    db.commit()
    db.refresh(publication)
    return {
        **assessment,
        "publication": _publication_payload(publication),
    }


@router.get("/reviewers")
def list_reviewers(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    reviewers = (
        db.query(User)
        .filter(User.role == "reviewer", User.is_active.is_(True))
        .order_by(User.display_name)
        .all()
    )
    return [
        {"id": user.id, "display_name": user.display_name, "email": user.email}
        for user in reviewers
    ]


@router.get("/{review_id}")
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    review = _get_review(db, review_id)
    _authorize_review_access(review, _user)
    return review_payload(review, _user)


@router.get("/{review_id}/visual-attachment")
def get_review_visual_attachment(
    review_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    review = _get_review(db, review_id)
    _authorize_review_access(review, _user)
    attachment = (
        db.query(ReviewVisualAttachment)
        .filter(ReviewVisualAttachment.review_id == review_id)
        .first()
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="This review has no visual attachment.")
    response = Response(content=attachment.file_data, media_type=attachment.media_type)
    response.headers["Content-Disposition"] = (
        'inline; filename="review-{}.{}"'.format(
            review_id, attachment.filename.rsplit(".", 1)[-1]
        )
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    if attachment.media_type == "application/pdf":
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@router.patch("/{review_id}/assignment")
async def assign_reviewer(
    review_id: int,
    payload: AssignmentUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    review = _get_review(db, review_id, for_update=True)
    previous_id = review.assigned_reviewer_id
    assigned = None
    if payload.reviewer_id is not None:
        assigned = (
            db.query(User)
            .filter(
                User.id == payload.reviewer_id,
                User.role == "reviewer",
                User.is_active.is_(True),
            )
            .first()
        )
        if assigned is None:
            raise HTTPException(
                status_code=422,
                detail="Select an active reviewer in this workspace.",
            )

    review.assigned_reviewer_id = assigned.id if assigned else None
    review.reviewer = assigned.display_name if assigned else None
    db.query(ReviewAssignment).filter(
        ReviewAssignment.review_id == review.id
    ).delete(synchronize_session=False)
    if assigned:
        db.add(
            ReviewAssignment(
                review_id=review.id,
                reviewer_id=assigned.id,
                assigned_by_id=admin.id,
                stage_number=1,
            )
        )
    record_activity(
        db,
        review.id,
        "reviewer_assigned" if assigned else "reviewer_unassigned",
        actor=admin.display_name,
        details={
            "previous_reviewer_id": previous_id,
            "reviewer_id": assigned.id if assigned else None,
            "reviewer_name": assigned.display_name if assigned else None,
        },
    )
    db.commit()
    await collaboration_hub.broadcast(
        review.id,
        {
            "type": "assignment_changed",
            "payload": {
                "reviewers": (
                    [{"id": assigned.id, "display_name": assigned.display_name, "stage_number": 1}]
                    if assigned
                    else []
                ),
                "actor": admin.display_name,
            },
        },
    )
    return {
        "id": review.id,
        "reviewer": review.reviewer,
        "reviewer_name": review.reviewer,
        "assigned_reviewer_id": review.assigned_reviewer_id,
        "assigned_reviewer": (
            {"id": assigned.id, "display_name": assigned.display_name}
            if assigned
            else None
        ),
        "assigned_reviewers": (
            [
                {
                    "id": assigned.id,
                    "display_name": assigned.display_name,
                    "stage_number": 1,
                }
            ]
            if assigned
            else []
        ),
    }


@router.put("/{review_id}/assignments")
async def assign_reviewers(
    review_id: int,
    payload: ReviewerAssignmentsUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    review = _get_review(db, review_id, for_update=True)
    reviewer_ids = [item.reviewer_id for item in payload.reviewers]
    reviewers = (
        db.query(User)
        .filter(
            User.id.in_(reviewer_ids),
            User.role == "reviewer",
            User.is_active.is_(True),
        )
        .all()
    )
    reviewers_by_id = {reviewer.id: reviewer for reviewer in reviewers}
    if len(reviewers_by_id) != len(reviewer_ids):
        raise HTTPException(
            status_code=422,
            detail="Every assigned reviewer must be an active Reviewer in this workspace.",
        )
    previous = [
        {
            "reviewer_id": assignment.reviewer_id,
            "stage_number": assignment.stage_number,
        }
        for assignment in review.reviewer_assignments
    ]
    db.query(ReviewAssignment).filter(
        ReviewAssignment.review_id == review.id
    ).delete(synchronize_session=False)
    for item in payload.reviewers:
        db.add(
            ReviewAssignment(
                review_id=review.id,
                reviewer_id=item.reviewer_id,
                assigned_by_id=admin.id,
                stage_number=item.stage_number,
            )
        )
    first_reviewer = next(
        (
            reviewers_by_id[item.reviewer_id]
            for item in payload.reviewers
            if item.stage_number == 1
        ),
        reviewers_by_id[payload.reviewers[0].reviewer_id],
    )
    review.assigned_reviewer_id = first_reviewer.id
    review.reviewer = first_reviewer.display_name
    assigned = [
        {
            "id": item.reviewer_id,
            "display_name": reviewers_by_id[item.reviewer_id].display_name,
            "stage_number": item.stage_number,
        }
        for item in payload.reviewers
    ]
    record_activity(
        db,
        review.id,
        "reviewers_assigned",
        actor=admin.display_name,
        details={"previous": previous, "reviewers": assigned},
    )
    db.commit()
    await collaboration_hub.broadcast(
        review.id,
        {
            "type": "assignment_changed",
            "payload": {"reviewers": assigned, "actor": admin.display_name},
        },
    )
    return {"id": review.id, "assigned_reviewers": assigned}


@router.get("/{review_id}/activity")
def get_review_activity(
    review_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    review = _get_review(db, review_id)
    _authorize_review_access(review, _user)

    entries = (
        db.query(ReviewActivity)
        .filter(ReviewActivity.review_id == review_id)
        .order_by(ReviewActivity.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    if _user.role == "contributor":
        entries = [
            entry
            for entry in entries
            if not (entry.details or {}).get("is_internal")
        ]

    return [
        {
            "id": entry.id,
            "action": entry.action,
            "actor": entry.actor,
            "details": entry.details,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


# ============================================================
# UPDATE REVIEW STATUS
# Includes contradictory evidence approval protection
# ============================================================

@router.patch("/{review_id}/status")
async def update_status(
    review_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    reviewer: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    review = _get_review(db, review_id, for_update=True)
    _authorize_review_access(review, reviewer)
    is_contributor_workflow_action = (
        reviewer.role == "contributor"
        and (
            (
                payload.status == "submitted"
                and review.status in {"draft", "changes_requested"}
            )
            or (
                payload.status == "draft"
                and review.status in {"pending", "submitted"}
            )
        )
    )
    if reviewer.role == "contributor" and not is_contributor_workflow_action:
        raise HTTPException(status_code=403, detail="Only reviewers can make this status change.")
    if (
        payload.status not in ALLOWED_STATUS_TRANSITIONS.get(review.status, set())
        and payload.status != review.status
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change review status from {review.status} to {payload.status}.",
        )
    if payload.status in {"rejected", "changes_requested"} and not (
        payload.reason and payload.reason.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="A reason is required for rejection or requested changes.",
        )
    if reviewer.role == "contributor" and payload.status not in {"draft", "submitted"}:
        raise HTTPException(
            status_code=403,
            detail="Contributors may only save drafts or submit revisions.",
        )
    if (
        reviewer.role == "reviewer"
        and review.reviewer_assignments
        and payload.status in {"approved", "rejected", "changes_requested"}
    ):
        raise HTTPException(
            status_code=409,
            detail="Use the staged approval decision endpoint to record this decision.",
        )
    if (
        payload.status == "approved"
        and review.reviewer_assignments
        and not _all_assigned_reviewers_approved(review)
    ):
        active_stage = _active_approval_stage(review)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "All assigned reviewers must approve each required stage before final approval.",
                "active_stage": active_stage,
                "approval_stages": review_payload(review, reviewer)[
                    "approval_stages"
                ],
            },
        )

    approval_warnings = (
        _approval_warnings(review) if payload.status == "approved" else []
    )
    acknowledgement_provided = (
        payload.acknowledge_warnings or payload.acknowledge_conflicts
    )

    if (
        approval_warnings
        and not acknowledgement_provided
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Unresolved critical findings, unsupported claims, or "
                    "conflicting evidence require explicit reviewer "
                    "acknowledgement before approval."
                ),
                "warnings": approval_warnings,
            },
        )

    record_status_change(
        db,
        review,
        payload.status,
        reviewer.display_name,
    )

    record_activity(
        db,
        review.id,
        "status_changed",
        actor=reviewer.display_name,
        details={
            "status": payload.status,
            **({"reason": payload.reason.strip()} if payload.reason else {}),
            **(
                {
                    "acknowledged_warning_ids": [
                        warning["finding_id"]
                        for warning in approval_warnings
                    ]
                }
                if approval_warnings and acknowledgement_provided
                else {}
            ),
        },
    )
    if payload.status in {"submitted", "changes_requested", "approved", "rejected"}:
        action_for_status = {
            "submitted": "review_submitted",
            "changes_requested": "changes_requested",
            "approved": "review_approved",
            "rejected": "review_rejected",
        }[payload.status]
        record_activity(
            db,
            review.id,
            action_for_status,
            actor=reviewer.display_name,
            details={
                "status": payload.status,
                "reason": payload.reason.strip() if payload.reason else None,
            },
        )

    if approval_warnings and acknowledgement_provided:
        record_activity(
            db,
            review.id,
            "approval_warnings_acknowledged",
            actor=reviewer.display_name,
            details={
                "finding_ids": [
                    warning["finding_id"] for warning in approval_warnings
                ],
                "reasons": sorted(
                    {
                        reason
                        for warning in approval_warnings
                        for reason in warning["reasons"]
                    }
                ),
                "acknowledged_by": reviewer.display_name,
                "acknowledged_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    db.commit()
    db.refresh(review)

    serialized = review_payload(_get_review(db, review_id), reviewer)

    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "status_changed",
            "payload": {
                "status": payload.status,
                "reviewer": reviewer.display_name,
            },
        },
    )

    return serialized


@router.post("/{review_id}/approval-decisions", status_code=status.HTTP_201_CREATED)
async def submit_approval_decision(
    review_id: int,
    payload: ApprovalDecisionCreate,
    db: Session = Depends(get_db),
    reviewer: User = Depends(require_roles("reviewer")),
):
    review = (
        db.query(ContentReview)
        .filter(ContentReview.id == review_id)
        .with_for_update()
        .first()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    assignments = (
        db.query(ReviewAssignment)
        .filter(ReviewAssignment.review_id == review_id)
        .order_by(ReviewAssignment.stage_number, ReviewAssignment.id)
        .all()
    )
    assigned = next(
        (item for item in assignments if item.reviewer_id == reviewer.id),
        None,
    )
    if assigned is None:
        raise HTTPException(
            status_code=403,
            detail="Only assigned reviewers may submit staged approval decisions.",
        )
    if not assignments:
        raise HTTPException(
            status_code=409,
            detail="No reviewer approval stages are configured for this review.",
        )
    if review.status not in {"pending", "submitted", "in_review", "changes_requested"}:
        raise HTTPException(
            status_code=409,
            detail=f"Review decisions are not available while status is {review.status}.",
        )
    active_stage = _active_approval_stage(review)
    if active_stage is None:
        raise HTTPException(
            status_code=409,
            detail="All configured approval stages are already complete.",
        )
    if assigned is None or assigned.stage_number != active_stage:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A decision can only be submitted during the reviewer's active approval stage.",
                "active_stage": active_stage,
            },
        )
    version_id = _current_version_id(review)
    if any(
        decision.reviewer_id == reviewer.id
        and decision.version_id == version_id
        for decision in review.approval_decisions
    ):
        raise HTTPException(
            status_code=409,
            detail="This reviewer has already recorded a decision for this review.",
        )
    warnings = (
        _approval_warnings(review)
        if payload.decision == "approved"
        else []
    )
    if warnings and not payload.acknowledge_warnings:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Unresolved findings require explicit acknowledgement before an approval decision.",
                "warnings": warnings,
            },
        )

    decision = ReviewApprovalDecision(
        review_id=review_id,
        reviewer_id=reviewer.id,
        version_id=version_id,
        decision=payload.decision,
        reason=payload.reason,
        acknowledged_warning_ids=(
            [warning["finding_id"] for warning in warnings]
            if warnings and payload.acknowledge_warnings
            else []
        ),
    )
    new_status = None
    if payload.decision in {"rejected", "changes_requested"}:
        new_status = payload.decision
    elif _all_assigned_reviewers_approved(
        _review_with_pending_decision(review, decision)
    ):
        new_status = "approved"
    if (
        new_status
        and new_status != review.status
        and new_status not in ALLOWED_STATUS_TRANSITIONS.get(review.status, set())
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change review status from {review.status} to {new_status}.",
        )

    db.add(decision)
    record_activity(
        db,
        review_id,
        "reviewer_decision_recorded",
        actor=reviewer.display_name,
        details={
            "reviewer_id": reviewer.id,
            "decision": payload.decision,
            "stage_number": active_stage,
            "version_id": version_id,
            "reason": payload.reason,
        },
    )
    if warnings and payload.acknowledge_warnings:
        record_activity(
            db,
            review_id,
            "approval_warnings_acknowledged",
            actor=reviewer.display_name,
            details={
                "finding_ids": [warning["finding_id"] for warning in warnings],
                "acknowledged_by": reviewer.display_name,
                "acknowledged_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    if new_status is not None and review.status != new_status:
        record_status_change(db, review, new_status, reviewer.display_name)
        record_activity(
            db,
            review_id,
            "review_approved"
            if new_status == "approved"
            else "review_rejected"
            if new_status == "rejected"
            else "changes_requested",
            actor=reviewer.display_name,
            details={
                "status": new_status,
                "reason": payload.reason,
                "stage_number": active_stage,
            },
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A decision for this reviewer was already recorded.",
        ) from exc
    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "approval_decision",
            "payload": {
                "reviewer": reviewer.display_name,
                "decision": payload.decision,
                "stage_number": active_stage,
                "version_id": version_id,
                "status": new_status or review.status,
            },
        },
    )
    return {
        "review_id": review_id,
        "reviewer_id": reviewer.id,
        "decision": payload.decision,
        "stage_number": active_stage,
        "status": new_status or review.status,
        "approval_stages": review_payload(_get_review(db, review_id), reviewer)[
            "approval_stages"
        ],
    }


def _review_with_pending_decision(review: ContentReview, decision):
    class ReviewDecisionView:
        pass

    view = ReviewDecisionView()
    view.reviewer_assignments = review.reviewer_assignments
    view.revisions = review.revisions
    view.approval_decisions = [
        *review.approval_decisions,
        decision,
    ]
    return view


@router.post("/{review_id}/approval-bypass")
async def bypass_approval_stages(
    review_id: int,
    payload: ApprovalBypassCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    review = (
        db.query(ContentReview)
        .filter(ContentReview.id == review_id)
        .with_for_update()
        .first()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    if review.status in {"approved", "rejected"}:
        raise HTTPException(
            status_code=409,
            detail="A terminal review cannot be bypassed or re-approved.",
        )
    if "approved" not in ALLOWED_STATUS_TRANSITIONS.get(review.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Review status {review.status} cannot transition to approved.",
        )
    if not review.reviewer_assignments:
        raise HTTPException(
            status_code=409,
            detail="There are no configured reviewer stages to bypass.",
        )
    if _all_assigned_reviewers_approved(review):
        raise HTTPException(
            status_code=409,
            detail="All configured reviewer stages are already complete.",
        )
    warnings = _approval_warnings(review)
    if warnings and not payload.acknowledge_warnings:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Existing unresolved-finding safeguards remain in force; explicitly acknowledge the listed warnings to bypass.",
                "warnings": warnings,
            },
        )
    bypass = ReviewApprovalBypass(
        review_id=review_id,
        version_id=_current_version_id(review),
        initiated_by_id=admin.id,
        reason=payload.reason,
        acknowledged_warning_ids=(
            [warning["finding_id"] for warning in warnings]
            if warnings and payload.acknowledge_warnings
            else []
        ),
    )
    db.add(bypass)
    record_activity(
        db,
        review_id,
        "approval_bypassed",
        actor=admin.display_name,
        details={
            "reason": payload.reason,
            "initiated_by_id": admin.id,
            "version_id": bypass.version_id,
            "acknowledged_warning_ids": bypass.acknowledged_warning_ids,
            "pending_reviewer_ids": [
                assignment.reviewer_id
                for assignment in review.reviewer_assignments
                if not any(
                    decision.reviewer_id == assignment.reviewer_id
                    and decision.version_id == _current_version_id(review)
                    and decision.decision == "approved"
                    for decision in review.approval_decisions
                )
            ],
        },
    )
    if warnings and payload.acknowledge_warnings:
        record_activity(
            db,
            review_id,
            "approval_warnings_acknowledged",
            actor=admin.display_name,
            details={
                "finding_ids": [warning["finding_id"] for warning in warnings],
                "acknowledged_by": admin.display_name,
                "acknowledged_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    record_status_change(db, review, "approved", admin.display_name)
    record_activity(
        db,
        review_id,
        "review_approved",
        actor=admin.display_name,
        details={"status": "approved", "approval_bypassed": True},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An approval bypass has already been recorded for this review version.",
        ) from exc
    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "approval_bypassed",
            "payload": {
                "actor": admin.display_name,
                "reason": payload.reason,
                "status": "approved",
            },
        },
    )
    return review_payload(_get_review(db, review_id), admin)


@router.post(
    "/{review_id}/comments",
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    review_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    author: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    review = _get_review(db, review_id)
    _authorize_review_access(review, author)
    if payload.is_internal and author.role == "contributor":
        raise HTTPException(status_code=403, detail="Contributors cannot create internal notes.")
    if payload.parent_id is not None:
        parent = db.get(ReviewComment, payload.parent_id)
        if parent is None or parent.review_id != review_id:
            raise HTTPException(status_code=422, detail="Reply target must belong to this review.")
        if parent.is_internal and not payload.is_internal:
            raise HTTPException(
                status_code=422,
                detail="Replies to internal notes must also be internal.",
            )

    comment = ReviewComment(
        review_id=review_id,
        comment=payload.comment,
        author=author.display_name,
        is_internal=payload.is_internal,
        parent_id=payload.parent_id,
    )

    db.add(comment)
    db.flush()

    record_activity(
        db,
        review_id,
        "comment_added",
        actor=author.display_name,
        details={
            "comment_id": comment.id,
            "is_internal": comment.is_internal,
            "parent_id": comment.parent_id,
        },
    )

    db.commit()
    db.refresh(comment)

    result = {
        "id": comment.id,
        "comment": comment.comment,
        "author": comment.author,
        "created_at": comment.created_at,
        "is_internal": comment.is_internal,
        "parent_id": comment.parent_id,
    }

    if not comment.is_internal:
        await collaboration_hub.broadcast(
            review_id,
            {"type": "comment_created", "payload": result},
        )
    else:
        await collaboration_hub.broadcast(
            review_id,
            {"type": "review_updated", "payload": {"kind": "internal_comment"}},
        )

    return result


@router.post(
    "/{review_id}/revisions",
    status_code=status.HTTP_201_CREATED,
)
async def add_revision(
    review_id: int,
    payload: RevisionCreate,
    db: Session = Depends(get_db),
    author: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    review = _get_review(db, review_id, for_update=True)
    _authorize_review_access(review, author)
    if author.role == "contributor" and (
        review.submitted_by_id != author.id
        or review.status not in {"draft", "changes_requested"}
    ):
        raise HTTPException(
            status_code=403,
            detail="Contributors may revise only their own draft or change-requested submission.",
        )

    revision = ReviewRevision(
        review_id=review_id,
        content=payload.content,
        title=payload.title,
        author_id=author.id,
    )

    db.add(revision)
    db.flush()

    review.content = payload.content
    previous_status = review.status
    if author.role in {"admin", "reviewer"}:
        review.status = "pending"
        review.reviewer = None
        if review.status != previous_status:
            record_status_change(db, review, review.status, author.display_name)
            record_activity(
                db,
                review_id,
                "status_changed",
                actor=author.display_name,
                details={
                    "previous_status": previous_status,
                    "status": review.status,
                    "reason": "A new revision requires fresh approval.",
                },
            )

    record_activity(
        db,
        review_id,
        "revision_added",
        actor=author.display_name,
        details={
            "revision_id": revision.id,
            "title": payload.title,
        },
    )

    db.commit()
    db.refresh(revision)

    result = {
        "id": revision.id,
        "content": revision.content,
        "title": revision.title,
        "summary": revision.title or "Revision",
        "created_at": revision.created_at,
        "author_id": revision.author_id,
        "author": author.display_name,
    }

    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "revision_created",
            "payload": result,
        },
    )

    return result


@router.get("/{review_id}/revisions/compare")
def compare_review_revisions(
    review_id: int,
    from_version_id: int = Query(ge=0),
    to_version_id: int = Query(ge=0),
    db: Session = Depends(get_db),
    viewer: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    review = _get_review(db, review_id)
    _authorize_review_access(review, viewer)
    versions = {
        item["id"]: item for item in review_payload(review, viewer)["versions"]
    }
    if from_version_id not in versions or to_version_id not in versions:
        raise HTTPException(
            status_code=404,
            detail="Both versions must belong to this review.",
        )
    before = versions[from_version_id]["content"]
    after = versions[to_version_id]["content"]
    before_tokens = re.findall(r"\s+|[^\s]+", before)
    after_tokens = re.findall(r"\s+|[^\s]+", after)
    matcher = difflib.SequenceMatcher(
        a=before_tokens,
        b=after_tokens,
    )
    segments = []
    for operation, start_before, end_before, start_after, end_after in matcher.get_opcodes():
        if operation == "equal":
            segments.append(
                {"type": "unchanged", "text": "".join(before_tokens[start_before:end_before])}
            )
        elif operation == "delete":
            segments.append(
                {"type": "removed", "text": "".join(before_tokens[start_before:end_before])}
            )
        elif operation == "insert":
            segments.append(
                {"type": "added", "text": "".join(after_tokens[start_after:end_after])}
            )
        else:
            segments.extend(
                [
                    {
                        "type": "removed",
                        "text": "".join(before_tokens[start_before:end_before]),
                    },
                    {
                        "type": "added",
                        "text": "".join(after_tokens[start_after:end_after]),
                    },
                ]
            )
    return {
        "review_id": review_id,
        "from_version": {
            key: value
            for key, value in versions[from_version_id].items()
            if key != "content"
        },
        "to_version": {
            key: value
            for key, value in versions[to_version_id].items()
            if key != "content"
        },
        "segments": segments,
    }


@router.post("/{review_id}/reanalyze")
async def reanalyze_revision(
    review_id: int,
    payload: RevisionCreate,
    db: Session = Depends(get_db),
    author: User = Depends(
        require_roles("admin", "reviewer", "contributor")
    ),
):
    if len(payload.content.encode("utf-8")) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail="Content exceeds the configured maximum length.",
        )

    review = _get_review(db, review_id, for_update=True)
    _authorize_review_access(review, author)
    if author.role == "contributor" and (
        review.submitted_by_id != author.id
        or review.status not in {"draft", "changes_requested"}
    ):
        raise HTTPException(
            status_code=403,
            detail="Contributors may revise only their own draft or change-requested submission.",
        )

    if payload.content == review.content:
        raise HTTPException(
            status_code=422,
            detail="The revision must differ from the current review content.",
        )

    guideline_ids = review.guideline_ids or []

    guidelines = (
        db.query(BrandGuideline)
        .filter(
            BrandGuideline.id.in_(guideline_ids),
            BrandGuideline.is_active.is_(True),
        )
        .all()
        if guideline_ids
        else []
    )

    sources_query = db.query(SourceDocument).filter(
        SourceDocument.approval_status == "approved",
        SourceDocument.is_active.is_(True),
    )
    sources_query = apply_source_visibility(sources_query, author)

    if guideline_ids:
        sources_query = sources_query.filter(
            (
                SourceDocument.guideline_id.is_(None)
            )
            | (
                SourceDocument.guideline_id.in_(guideline_ids)
            )
        )

    sources = sources_query.all()

    claim_candidates = list(
        dict.fromkeys(
            factual_claim_excerpts(payload.content)
            + [
                str(finding["matched_text"])
                for finding in check_promotional_claims(
                    payload.content
                )
                if finding.get("matched_text")
            ]
        )
    )

    evidence_by_claim = {}
    evidence_matches = []
    evidence_retrieval_method = retrieval_method()
    warnings = []
    embedding_failed = False

    for claim in claim_candidates[:20]:
        if embedding_failed:
            matches = retrieve_lexical_evidence(
                claim,
                sources,
            )
            evidence_retrieval_method = "bm25_lexical_fallback"

        else:
            try:
                matches, evidence_retrieval_method = await retrieve_evidence(
                    claim,
                    sources,
                    db,
                )

            except EmbeddingProviderError as exc:
                embedding_failed = True

                matches = retrieve_lexical_evidence(
                    claim,
                    sources,
                )

                evidence_retrieval_method = "bm25_lexical_fallback"

                warnings.append(
                    "Embedding retrieval failed; lexical evidence retrieval was used. {}".format(
                        str(exc)
                    )
                )

        evidence_by_claim[claim.casefold()] = matches

        for match in matches:
            if not any(
                item.get("id") == match.get("id")
                and item.get("excerpt") == match.get("excerpt")
                for item in evidence_matches
            ):
                evidence_matches.append(match)

    brand_voice = db.get(BrandVoiceConfiguration, 1)
    findings = analyze_text(
        payload.content,
        guidelines,
        evidence_matches=evidence_matches,
        evidence_by_claim=evidence_by_claim,
        brand_voice_configuration=(
            brand_voice.configuration if brand_voice else None
        ),
    )

    for finding in findings:
        if finding.get("category") not in {
            "factual_claim",
            "unsupported_claim",
        }:
            continue

        claim = str(
            finding.get("matched_text") or ""
        ).strip()

        claim_evidence = evidence_by_claim.get(
            claim.casefold(),
            [],
        )

        if not claim_evidence:
            candidate = next(
                (
                    item
                    for item in claim_candidates
                    if claim
                    and (
                        claim.casefold() in item.casefold()
                        or item.casefold() in claim.casefold()
                    )
                ),
                None,
            )

            if candidate:
                claim_evidence = evidence_by_claim.get(
                    candidate.casefold(),
                    [],
                )

        verified = verification_fields(
            claim,
            claim_evidence,
        )

        finding.update(verified)
        finding["severity"] = {
            "supported": "low",
            "unsupported": "high",
            "conflicting": "critical",
            "expired_evidence": "medium",
            "unverified": "high",
        }[verified["evidence_status"]]

        finding["explanation"] = "{} {}".format(
            finding["explanation"],
            verified["verification_explanation"],
        )

    if not review.analysis_runs:
        previous_findings = [
            finding_payload(item)
            for item in review.findings
        ]

        db.add(
            ReviewAnalysisRun(
                review_id=review.id,
                content=review.content,
                findings=previous_findings,
                analysis_engine="historical",
                evidence_retrieval_method=None,
                warnings=[],
                created_by_id=None,
            )
        )

    revision = ReviewRevision(
        review_id=review.id,
        content=payload.content,
        title=payload.title or "Revision with re-analysis",
        author_id=author.id,
    )

    db.add(revision)
    db.flush()

    review.content = payload.content
    review.analysis_timestamp = datetime.now(timezone.utc)
    previous_status = review.status
    review.status = (
        previous_status
        if author.role == "contributor"
        else "pending"
    )
    review.reviewer = None
    if review.status != previous_status:
        record_status_change(db, review, review.status, author.display_name)
        record_activity(
            db,
            review.id,
            "status_changed",
            actor=author.display_name,
            details={
                "previous_status": previous_status,
                "status": review.status,
                "reason": "Revision reanalyzed.",
            },
        )

    for old_finding in list(review.findings):
        db.delete(old_finding)

    db.flush()

    new_findings = []

    for item in findings:
        model = ReviewFinding(
            review_id=review.id,
            guideline_id=item.get("guideline_id"),
            category=item["category"],
            severity=item["severity"],
            title=item["title"],
            explanation=item["explanation"],
            matched_text=item.get("matched_text"),
            suggestion=item.get("suggestion"),
            source=item.get("source"),
            confidence=item.get("confidence"),
            review_status="pending",
            metadata_json={
                key: item[key]
                for key in (
                    "claim",
                    "claim_start",
                    "claim_end",
                    "detection_method",
                    "verification_status",
                    "evidence_status",
                    "citations",
                    "verification_explanation",
                    "verification_confidence",
                    "evidence_reason",
                    "evidence_strength",
                    "brand_voice_findings",
                    "brand_voice_category",
                    "finding_type",
                    "assessment",
                    "configuration_rule",
                    "suggestion_status",
                )
                if key in item
            },
        )

        db.add(model)
        new_findings.append(model)

    db.flush()

    finding_snapshots = [
        finding_payload(item)
        for item in new_findings
    ]

    db.add(
        ReviewAnalysisRun(
            review_id=review.id,
            content=payload.content,
            findings=finding_snapshots,
            analysis_engine="rules",
            evidence_retrieval_method=evidence_retrieval_method,
            warnings=warnings,
            created_by_id=author.id,
        )
    )

    record_activity(
        db,
        review.id,
        "revision_reanalyzed",
        actor=author.display_name,
        details={
            "revision_id": revision.id,
            "issue_count": len(findings),
            "analysis_engine": "rules",
            "evidence_retrieval_method": evidence_retrieval_method,
            "warnings": warnings,
        },
    )
    record_activity(
        db,
        review.id,
        "findings_updated",
        actor=author.display_name,
        details={
            "revision_id": revision.id,
            "issue_count": len(findings),
        },
    )

    db.commit()

    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "revision_created",
            "payload": {
                "id": revision.id,
                "content": revision.content,
                "title": revision.title,
                "summary": revision.title,
                "created_at": revision.created_at,
                "author_id": revision.author_id,
                "author": author.display_name,
            },
        },
    )
    if review.status != previous_status:
        await collaboration_hub.broadcast(
            review_id,
            {
                "type": "status_changed",
                "payload": {
                    "status": review.status,
                    "reviewer": review.reviewer,
                },
            },
        )
    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "review_updated",
            "payload": {
                "status": review.status,
                "finding_count": len(finding_snapshots),
            },
        },
    )

    serialized = review_payload(_get_review(db, review_id), author)

    return serialized


@router.websocket("/{review_id}/collaboration")
async def review_collaboration(
    websocket: WebSocket,
    review_id: int,
    db: Session = Depends(get_db),
):
    review = db.get(ContentReview, review_id)

    if review is None:
        await websocket.close(
            code=4404,
            reason="Review not found.",
        )
        return

    from app.config import AUTH_COOKIE_NAME

    if websocket.headers.get("origin") not in CORS_ORIGINS:
        await websocket.close(
            code=4403,
            reason="Origin is not allowed.",
        )
        return

    user = authenticate_token(
        db,
        websocket.cookies.get(AUTH_COOKIE_NAME),
    )

    if user is None:
        await websocket.close(
            code=4401,
            reason="Sign in to collaborate.",
        )
        return

    if user.must_change_password:
        await websocket.close(
            code=4403,
            reason="Change your temporary password first.",
        )
        return

    if user.role not in {"admin", "reviewer"} and not (
        user.role == "contributor" and review.submitted_by_id == user.id
    ):
        await websocket.close(
            code=4403,
            reason="You are not authorized to collaborate on this review.",
        )
        return

    await collaboration_hub.connect(
        review_id,
        websocket,
        user.id,
        user.display_name,
        user.role,
    )

    try:
        participants = await collaboration_hub.participants(review_id)
        await websocket.send_json(
            {
                "type": "presence",
                "payload": {
                    "event": "snapshot",
                    "review_id": review_id,
                    "participants": participants,
                },
            }
        )
        await collaboration_hub.broadcast(
            review_id,
            {
                "type": "presence",
                "payload": {
                    "event": "joined",
                    "review_id": review_id,
                    "participants": participants,
                },
            },
            exclude=websocket,
        )

        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60,
                )

            except asyncio.TimeoutError:
                db.expire_all()
                active_user = authenticate_token(
                    db,
                    websocket.cookies.get(AUTH_COOKIE_NAME),
                )

                if (
                    active_user is None
                    or active_user.must_change_password
                    or (
                        active_user.role not in {"admin", "reviewer"}
                        and not (
                            active_user.role == "contributor"
                            and review.submitted_by_id == active_user.id
                        )
                    )
                ):
                    await websocket.close(
                        code=4401,
                        reason="Workspace session expired.",
                    )
                    break

                continue

            db.expire_all()
            active_user = authenticate_token(
                db,
                websocket.cookies.get(AUTH_COOKIE_NAME),
            )
            if (
                active_user is None
                or active_user.must_change_password
                or (
                    active_user.role not in {"admin", "reviewer"}
                    and not (
                        active_user.role == "contributor"
                        and review.submitted_by_id == active_user.id
                    )
                )
            ):
                await websocket.close(
                    code=4401,
                    reason="Workspace access changed.",
                )
                break
            user = active_user

            if len(raw.encode("utf-8")) > 2048:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Message too large.",
                    }
                )
                continue

            try:
                message = json.loads(raw)

            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Send valid JSON.",
                    }
                )
                continue

            if (
                not isinstance(message, dict)
                or message.get("type") not in {"typing", "presence"}
            ):
                if (
                    isinstance(message, dict)
                    and message.get("type") == "draft_changed"
                    and isinstance(message.get("content"), str)
                    and len(
                        message["content"].encode("utf-8")
                    ) <= 100_000
                ):
                    await collaboration_hub.broadcast(
                        review_id,
                        {
                            "type": "draft_changed",
                            "payload": {
                                "content": message["content"],
                                "user": user.display_name,
                            },
                        },
                    )
                    continue

                await websocket.send_json(
                    {
                        "type": "error",
                        "message": (
                            "Unsupported collaboration event "
                            "or invalid draft size."
                        ),
                    }
                )
                continue

            payload = {
                "type": message["type"],
                "payload": {
                    "user": user.display_name,
                    "active": bool(
                        message.get("active", True)
                    ),
                },
            }

            await collaboration_hub.broadcast(
                review_id,
                payload,
            )

    except WebSocketDisconnect:
        pass

    finally:
        await collaboration_hub.disconnect(
            review_id,
            websocket,
            user.id,
        )
        await collaboration_hub.broadcast(
            review_id,
            {
                "type": "presence",
                "payload": {
                    "event": "left",
                    "review_id": review_id,
                    "participants": await collaboration_hub.participants(review_id),
                },
            },
        )
