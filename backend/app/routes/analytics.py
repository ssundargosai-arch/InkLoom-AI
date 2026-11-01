from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.content_review import ContentReview, ReviewFinding
from app.models.review_comment import ReviewAuditEvent
from app.services.auth_service import require_roles

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


def _review_window(query, start_date: Optional[date], end_date: Optional[date]):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date.",
        )
    if start_date:
        query = query.filter(
            ContentReview.created_at
            >= datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        )
    if end_date:
        query = query.filter(
            ContentReview.created_at
            < datetime.combine(
                end_date + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
        )
    return query


def _review_ids(db: Session, start_date: Optional[date], end_date: Optional[date]):
    query = _review_window(db.query(ContentReview.id), start_date, end_date)
    return query.subquery()


@router.get("/summary")
def analytics_summary(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    review_query = _review_window(db.query(ContentReview), start_date, end_date)
    review_ids = _review_ids(db, start_date, end_date)
    finding_query = db.query(ReviewFinding).join(
        review_ids, ReviewFinding.review_id == review_ids.c.id
    )

    total_reviews = review_query.count()
    total_issues = finding_query.count()
    severity_counts = {
        severity: count
        for severity, count in (
            db.query(ReviewFinding.severity, func.count(ReviewFinding.id))
            .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
            .group_by(ReviewFinding.severity)
        )
    }
    for severity in ("critical", "high", "medium", "low"):
        severity_counts.setdefault(severity, 0)

    categories = [
        {"category": name, "count": count}
        for name, count in (
            db.query(ReviewFinding.category, func.count(ReviewFinding.id))
            .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
            .group_by(ReviewFinding.category)
            .order_by(
                func.count(ReviewFinding.id).desc(), ReviewFinding.category.asc()
            )
        ).all()
    ]
    statuses = [
        {"status": name, "count": count}
        for name, count in (
            db.query(ContentReview.status, func.count(ContentReview.id))
            .join(review_ids, ContentReview.id == review_ids.c.id)
            .group_by(ContentReview.status)
            .order_by(ContentReview.status.asc())
        ).all()
    ]
    guideline_counts = Counter(
        {
            name: count
            for name, count in (
                db.query(ReviewFinding.source, func.count(ReviewFinding.id))
                .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
                .filter(ReviewFinding.guideline_id.is_not(None))
                .group_by(ReviewFinding.source)
            ).all()
            if name
        }
    )
    frequent_guidelines = [
        {"name": name, "count": count}
        for name, count in guideline_counts.most_common(10)
    ]
    pending_approvals = (
        db.query(func.count(ContentReview.id))
        .join(review_ids, ContentReview.id == review_ids.c.id)
        .filter(ContentReview.status.in_(("pending", "in_review")))
        .scalar()
        or 0
    )

    review_rows = review_query.with_entities(
        ContentReview.id, ContentReview.created_at
    ).all()
    created_by_id = {review_id: created_at for review_id, created_at in review_rows}
    decision_rows = (
        db.query(
            ReviewAuditEvent.review_id,
            ReviewAuditEvent.reviewer,
            ReviewAuditEvent.new_status,
            ReviewAuditEvent.changed_at,
        )
        .join(review_ids, ReviewAuditEvent.review_id == review_ids.c.id)
        .filter(ReviewAuditEvent.new_status.in_(("approved", "changes_requested")))
        .order_by(ReviewAuditEvent.id.asc())
        .all()
    )
    first_decisions = {}
    reviewer_counts = Counter()
    for review_id, reviewer, new_status, changed_at in decision_rows:
        reviewer_name = reviewer or "Unknown reviewer"
        reviewer_counts[reviewer_name] += 1
        first_decisions.setdefault(
            review_id, (reviewer_name, new_status, changed_at)
        )

    review_durations = []
    for review_id, (reviewer_name, decision, changed_at) in first_decisions.items():
        created_at = created_by_id.get(review_id)
        if created_at and changed_at:
            elapsed = (changed_at - created_at).total_seconds()
            if elapsed >= 0:
                review_durations.append(elapsed)
    average_review_time_hours = (
        round(sum(review_durations) / len(review_durations) / 3600, 2)
        if review_durations
        else None
    )
    reviewer_activity = [
        {"reviewer": name, "decisions": count}
        for name, count in reviewer_counts.most_common(10)
    ]

    verification_counts = Counter()
    for (metadata,) in finding_query.with_entities(ReviewFinding.metadata_json).all():
        verification_status = (metadata or {}).get("verification_status")
        if verification_status:
            verification_counts[verification_status] += 1

    return {
        "total_reviews": total_reviews,
        "total_issues": total_issues,
        "pending_approvals": pending_approvals,
        "issues_by_severity": severity_counts,
        "issues_by_category": categories,
        "status_distribution": statuses,
        "frequent_guidelines": frequent_guidelines,
        "average_review_time_hours": average_review_time_hours,
        "completed_reviews_with_duration": len(review_durations),
        "reviewer_activity": reviewer_activity,
        "claim_verification_statuses": dict(verification_counts),
        "date_range": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
    }


@router.get("/guideline-blind-spots")
def guideline_blind_spots(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    review_ids = _review_ids(db, start_date, end_date)
    counts = (
        db.query(ReviewFinding.guideline_id, func.count(ReviewFinding.id))
        .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
        .filter(ReviewFinding.guideline_id.is_not(None))
        .group_by(ReviewFinding.guideline_id)
        .order_by(func.count(ReviewFinding.id).desc())
        .all()
    )
    if not counts:
        return []
    max_count = max(count for _, count in counts)
    guidelines = {
        item.id: item
        for item in db.query(BrandGuideline)
        .filter(BrandGuideline.id.in_([guideline_id for guideline_id, _ in counts]))
        .all()
    }
    results = []
    for guideline_id, count in counts:
        item = guidelines.get(guideline_id)
        if item is None:
            continue
        results.append(
            {
                "guideline_id": item.id,
                "guideline": item.name,
                "mentions": count,
                "count": count,
                "ambiguity_score": round(count / max_count, 2),
                "heuristic": (
                    "Relative trigger frequency only. Repeated findings may warrant "
                    "human review; this score does not prove guideline ambiguity."
                ),
            }
        )
    return results
