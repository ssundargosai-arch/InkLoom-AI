from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_guideline import (
    BrandGuideline,
    GuidelineReviewEvent,
    GuidelineVersion,
)
from app.models.brand_voice import BrandVoiceConfiguration, BrandVoiceVersion
from app.models.user import User
from app.schemas.guidelines import (
    GuidelineCreate,
    GuidelineReviewRequest,
    GuidelineUpdate,
    BrandVoiceConfigurationUpdate,
)
from app.services.auth_service import require_roles
from app.services.guideline_diagnostics import diagnose_guidelines
from app.services.freshness_service import (
    guideline_freshness,
    guideline_next_review_due_at,
    normalize_utc,
)

router = APIRouter(
    prefix="/api/guidelines",
    tags=["guidelines"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


def _snapshot(item: BrandGuideline):
    return {
        "name": item.name,
        "category": item.category,
        "description": item.description,
        "examples": item.examples or [],
        "severity": item.severity,
        "prohibited_terms": item.prohibited_terms or [],
        "preferred_terms": item.preferred_terms or [],
        "approved_sources": item.approved_sources or [],
        "is_active": item.is_active,
        "review_interval_days": item.review_interval_days,
    }


def serialize_guideline(item: BrandGuideline):
    return {
        "id": item.id,
        **_snapshot(item),
        "status": item.status,
        "is_seed": item.is_seed,
        "created_by_id": item.created_by_id,
        "created_by": item.created_by.display_name if item.created_by else None,
        "updated_by_id": item.updated_by_id,
        "updated_by": item.updated_by.display_name if item.updated_by else None,
        "last_reviewed_at": normalize_utc(item.last_reviewed_at),
        "last_reviewed_by": (
            item.last_reviewed_by.display_name if item.last_reviewed_by else None
        ),
        "freshness_status": guideline_freshness(item),
        "next_review_due_at": guideline_next_review_due_at(item),
        "review_history": [
            {
                "reviewer": event.reviewer.display_name if event.reviewer else None,
                "note": event.note,
                "created_at": normalize_utc(event.created_at),
            }
            for event in item.review_events
        ],
        "created_at": normalize_utc(item.created_at),
        "updated_at": normalize_utc(item.updated_at),
    }


def _empty_brand_voice_configuration():
    return BrandVoiceConfigurationUpdate().model_dump(mode="json")


def serialize_brand_voice_configuration(item=None):
    if item is None:
        return {
            **_empty_brand_voice_configuration(),
            "version_number": 0,
            "updated_by": None,
            "updated_at": None,
        }
    return {
        **BrandVoiceConfigurationUpdate.model_validate(
            item.configuration or {}
        ).model_dump(mode="json"),
        "version_number": item.version_number,
        "updated_by": item.updated_by.display_name if item.updated_by else None,
        "updated_at": normalize_utc(item.updated_at),
    }


@router.get("")
def list_guidelines(
    search: Optional[str] = Query(default=None, max_length=160),
    category: Optional[str] = Query(default=None, max_length=80),
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    query = db.query(BrandGuideline)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                BrandGuideline.name.ilike(pattern),
                BrandGuideline.description.ilike(pattern),
                BrandGuideline.category.ilike(pattern),
            )
        )
    if category:
        query = query.filter(BrandGuideline.category == category)
    if active is not None:
        query = query.filter(BrandGuideline.is_active.is_(active))
    return [
        serialize_guideline(item)
        for item in query.order_by(BrandGuideline.id.asc()).all()
    ]


@router.get("/categories")
def list_guideline_categories(db: Session = Depends(get_db)):
    return [
        category
        for (category,) in db.query(BrandGuideline.category)
        .distinct()
        .order_by(BrandGuideline.category)
        .all()
        if category
    ]


@router.get("/diagnostics")
def get_guideline_diagnostics(
    db: Session = Depends(get_db),
    _admin_or_reviewer: User = Depends(require_roles("admin", "reviewer")),
):
    active_guidelines = (
        db.query(BrandGuideline)
        .filter(BrandGuideline.is_active.is_(True))
        .order_by(BrandGuideline.id.asc())
        .all()
    )
    return diagnose_guidelines(active_guidelines)


@router.get("/brand-voice")
def get_brand_voice_configuration(
    db: Session = Depends(get_db),
    _admin_or_reviewer: User = Depends(require_roles("admin", "reviewer")),
):
    item = db.get(BrandVoiceConfiguration, 1)
    return serialize_brand_voice_configuration(item)


@router.put("/brand-voice")
def update_brand_voice_configuration(
    payload: BrandVoiceConfigurationUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    configuration = payload.model_dump(mode="json")
    item = db.get(BrandVoiceConfiguration, 1)
    latest = (
        db.query(BrandVoiceVersion.version_number)
        .order_by(BrandVoiceVersion.version_number.desc())
        .first()
    )
    if item is not None and item.configuration == configuration:
        return serialize_brand_voice_configuration(item)

    version_number = (latest[0] if latest else 0) + 1
    if item is None:
        item = BrandVoiceConfiguration(
            id=1,
            configuration=configuration,
            version_number=version_number,
            updated_by_id=admin.id,
        )
        db.add(item)
    else:
        item.configuration = configuration
        item.version_number = version_number
        item.updated_by_id = admin.id
    db.add(
        BrandVoiceVersion(
            version_number=version_number,
            snapshot=configuration,
            editor_id=admin.id,
        )
    )
    db.commit()
    db.refresh(item)
    return serialize_brand_voice_configuration(item)


@router.get("/brand-voice/versions")
def list_brand_voice_versions(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    versions = (
        db.query(BrandVoiceVersion)
        .order_by(BrandVoiceVersion.version_number.desc())
        .all()
    )
    return [
        {
            "id": version.id,
            "version_number": version.version_number,
            "snapshot": version.snapshot,
            "editor_id": version.editor_id,
            "editor": version.editor.display_name if version.editor else None,
            "created_at": normalize_utc(version.created_at),
        }
        for version in versions
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_guideline(
    payload: GuidelineCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    approved_sources = [
        source.model_dump(mode="json") for source in payload.approved_sources
    ]
    item = BrandGuideline(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        examples=payload.examples,
        severity=payload.severity,
        review_interval_days=payload.review_interval_days,
        prohibited_terms=payload.prohibited_terms,
        preferred_terms=payload.preferred_terms,
        approved_sources=approved_sources,
        status="approved",
        is_active=payload.is_active,
        is_seed=False,
        created_by_id=admin.id,
        updated_by_id=admin.id,
        last_reviewed_at=datetime.now(timezone.utc),
        last_reviewed_by_id=admin.id,
    )
    db.add(item)
    db.flush()
    db.add(
        GuidelineVersion(
            guideline_id=item.id,
            version_number=1,
            snapshot=_snapshot(item),
            editor_id=admin.id,
        )
    )
    db.commit()
    db.refresh(item)
    return serialize_guideline(item)


@router.patch("/{guideline_id}")
def update_guideline(
    guideline_id: int,
    payload: GuidelineUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    item = db.get(BrandGuideline, guideline_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Guideline not found.")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Provide at least one guideline field to update.")
    nullable_fields = {
        "name",
        "category",
        "description",
        "examples",
        "severity",
        "review_interval_days",
        "prohibited_terms",
        "preferred_terms",
        "is_active",
    }
    if any(key in updates and updates[key] is None for key in nullable_fields):
        raise HTTPException(status_code=422, detail="Guideline fields cannot be null.")
    latest = (
        db.query(GuidelineVersion.version_number)
        .filter(GuidelineVersion.guideline_id == item.id)
        .order_by(GuidelineVersion.version_number.desc())
        .first()
    )
    if latest is None:
        db.add(
            GuidelineVersion(
                guideline_id=item.id,
                version_number=1,
                snapshot=_snapshot(item),
                editor_id=item.updated_by_id or item.created_by_id,
            )
        )
        db.flush()
        latest_version = 1
    else:
        latest_version = latest[0]
    if "approved_sources" in updates:
        updates["approved_sources"] = [
            source.model_dump(mode="json") for source in payload.approved_sources or []
        ]
    policy_fields = {
        "name",
        "category",
        "description",
        "examples",
        "severity",
        "review_interval_days",
        "prohibited_terms",
        "preferred_terms",
        "approved_sources",
    }
    policy_changed = any(
        key in updates and updates[key] != getattr(item, key)
        for key in policy_fields
    )
    for key, value in updates.items():
        setattr(item, key, value)
    item.updated_by_id = admin.id
    if policy_changed:
        item.last_reviewed_at = datetime.now(timezone.utc)
        item.last_reviewed_by_id = admin.id
    db.flush()
    db.add(
        GuidelineVersion(
            guideline_id=item.id,
            version_number=latest_version + 1,
            snapshot=_snapshot(item),
            editor_id=admin.id,
        )
    )
    db.commit()
    db.refresh(item)
    return serialize_guideline(item)


@router.post("/{guideline_id}/review")
def mark_guideline_reviewed(
    guideline_id: int,
    payload: GuidelineReviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    item = db.get(BrandGuideline, guideline_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Guideline not found.")
    if not item.is_active:
        raise HTTPException(
            status_code=409,
            detail="Inactive guidelines do not require freshness review.",
        )
    reviewed_at = datetime.now(timezone.utc)
    item.last_reviewed_at = reviewed_at
    item.last_reviewed_by_id = admin.id
    item.updated_by_id = admin.id
    db.add(
        GuidelineReviewEvent(
            guideline_id=item.id,
            reviewer_id=admin.id,
            note=payload.note,
            created_at=reviewed_at,
        )
    )
    db.commit()
    db.refresh(item)
    return serialize_guideline(item)


@router.get("/{guideline_id}/versions")
def list_guideline_versions(
    guideline_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    if db.get(BrandGuideline, guideline_id) is None:
        raise HTTPException(status_code=404, detail="Guideline not found.")
    versions = (
        db.query(GuidelineVersion)
        .filter(GuidelineVersion.guideline_id == guideline_id)
        .order_by(GuidelineVersion.version_number.desc())
        .all()
    )
    return [
        {
            "id": version.id,
            "version_number": version.version_number,
            "snapshot": version.snapshot,
            "editor_id": version.editor_id,
            "editor": version.editor.display_name if version.editor else None,
            "created_at": version.created_at,
        }
        for version in versions
    ]


@router.delete("/{guideline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_guideline(
    guideline_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    item = db.get(BrandGuideline, guideline_id)
    if item is None or not item.is_active:
        raise HTTPException(status_code=404, detail="Guideline not found.")
    latest = (
        db.query(GuidelineVersion.version_number)
        .filter(GuidelineVersion.guideline_id == item.id)
        .order_by(GuidelineVersion.version_number.desc())
        .first()
    )
    if latest is None:
        db.add(
            GuidelineVersion(
                guideline_id=item.id,
                version_number=1,
                snapshot=_snapshot(item),
                editor_id=item.updated_by_id or item.created_by_id,
            )
        )
        db.flush()
        version_number = 2
    else:
        version_number = latest[0] + 1
    item.is_active = False
    item.updated_by_id = admin.id
    db.flush()
    db.add(
        GuidelineVersion(
            guideline_id=item.id,
            version_number=version_number,
            snapshot=_snapshot(item),
            editor_id=admin.id,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
