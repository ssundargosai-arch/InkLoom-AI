from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import MAX_SOURCE_UPLOAD_SIZE
from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.source_document import SourceApprovalEvent, SourceDocument, SourceVersion
from app.schemas.sources import (
    SourceApprovalUpdate,
    SourceCreate,
    SourceRead,
    SourceUpdate,
    SourceVerificationRequest,
)
from app.services.document_ingestion import extract_source_text
from app.services.freshness_service import (
    normalize_utc,
    source_freshness,
    source_next_review_due_at,
)
from app.models.user import User
from app.services.auth_service import require_roles
from app.services.source_access import apply_source_visibility

router = APIRouter(
    prefix="/api/sources",
    tags=["evidence sources"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


def _source_snapshot(source: SourceDocument):
    return {
        "name": source.name,
        "description": source.description,
        "source_type": source.source_type,
        "content": source.content,
        "guideline_id": source.guideline_id,
        "url": source.url,
        "source_date": source.source_date.isoformat() if source.source_date else None,
        "expiry_date": source.expiry_date.isoformat() if source.expiry_date else None,
        "valid_from": source.valid_from.isoformat() if source.valid_from else None,
        "valid_until": source.valid_until.isoformat() if source.valid_until else None,
        "review_interval_days": source.review_interval_days,
        "is_active": source.is_active,
        "approval_status": source.approval_status,
        "last_verified_at": (
            normalize_utc(source.last_verified_at).isoformat()
            if source.last_verified_at
            else None
        ),
    }


def _serialize(source: SourceDocument):
    today = datetime.now(timezone.utc).date()
    valid_from = source.valid_from or source.source_date
    valid_until = source.valid_until or source.expiry_date
    if not source.is_active:
        lifecycle_status = "inactive"
    elif valid_until is not None and valid_until < today:
        lifecycle_status = "expired"
    elif valid_from is not None and valid_from > today:
        lifecycle_status = "not_yet_valid"
    else:
        lifecycle_status = source.approval_status
    return {
        "id": source.id,
        "name": source.name,
        "description": source.description,
        "source_type": source.source_type,
        "content": source.content,
        "guideline_id": source.guideline_id,
        "url": source.url,
        "source_date": source.source_date,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "expiry_date": valid_until,
        "review_interval_days": source.review_interval_days,
        "last_verified_at": normalize_utc(
            source.last_verified_at
            or (
                source.reviewed_at
                if source.approval_status == "approved"
                else None
            )
        ),
        "freshness_status": source_freshness(source),
        "next_review_due_at": source_next_review_due_at(source),
        "is_active": source.is_active,
        "lifecycle_status": lifecycle_status,
        "approval_status": source.approval_status,
        "created_by_id": source.created_by_id,
        "created_by": source.created_by.display_name if source.created_by else None,
        "updated_by_id": source.updated_by_id,
        "updated_by": source.updated_by.display_name if source.updated_by else None,
        "reviewed_by_id": source.reviewed_by_id,
        "reviewed_by": source.reviewed_by.display_name if source.reviewed_by else None,
        "reviewed_at": normalize_utc(source.reviewed_at),
        "review_note": source.review_note,
        "approval_history": [
            {
                "status": event.status,
                "reviewer": event.reviewer.display_name if event.reviewer else None,
                "note": event.note,
                "created_at": normalize_utc(event.created_at),
            }
            for event in source.approval_history
        ],
        "version_count": len(source.versions),
        "created_at": normalize_utc(source.created_at),
        "updated_at": normalize_utc(source.updated_at),
    }


def _visible_source_query(query, viewer: User):
    return apply_source_visibility(query, viewer)


@router.get("", response_model=list[SourceRead])
def list_sources(
    guideline_id: int = Query(default=None, ge=1),
    search: Optional[str] = Query(default=None, max_length=160),
    approval_status: Optional[str] = Query(default=None),
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    query = _visible_source_query(db.query(SourceDocument), viewer)
    if guideline_id is not None:
        query = query.filter(SourceDocument.guideline_id == guideline_id)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SourceDocument.name.ilike(pattern),
                SourceDocument.description.ilike(pattern),
                SourceDocument.content.ilike(pattern),
            )
        )
    if approval_status:
        if approval_status not in {"draft", "pending", "approved", "rejected"}:
            raise HTTPException(status_code=422, detail="Unsupported approval status.")
        query = query.filter(SourceDocument.approval_status == approval_status)
    if active is not None:
        query = query.filter(SourceDocument.is_active.is_(active))
    return [_serialize(source) for source in query.order_by(SourceDocument.id.desc()).all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SourceRead)
def create_source(
    payload: SourceCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    if payload.guideline_id is not None and db.get(BrandGuideline, payload.guideline_id) is None:
        raise HTTPException(status_code=422, detail="The selected guideline does not exist.")
    values = payload.model_dump()
    if "valid_from" not in payload.model_fields_set:
        values["valid_from"] = payload.source_date
    values["expiry_date"] = values.pop("valid_until")
    source = SourceDocument(
        **values,
        created_by_id=admin.id,
        updated_by_id=admin.id,
    )
    db.add(source)
    db.flush()
    db.add(
        SourceVersion(
            source_id=source.id,
            version_number=1,
            snapshot=_source_snapshot(source),
            editor_id=admin.id,
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=SourceRead)
async def upload_source(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    guideline_id: int = Form(default=None),
    url: str = Form(default=""),
    source_date: date = Form(default=None),
    expiry_date: date = Form(default=None),
    valid_from: date = Form(default=None),
    valid_until: date = Form(default=None),
    review_interval_days: int = Form(default=90),
    description: str = Form(default=""),
    source_type: str = Form(default="document"),
    approval_status: str = Form(default="pending"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=422, detail="A valid source filename is required.")
    if guideline_id is not None and db.get(BrandGuideline, guideline_id) is None:
        raise HTTPException(status_code=422, detail="The selected guideline does not exist.")
    effective_valid_from = valid_from or source_date
    effective_valid_until = valid_until or expiry_date
    if (
        effective_valid_from
        and effective_valid_until
        and effective_valid_until < effective_valid_from
    ):
        raise HTTPException(
            status_code=422,
            detail="valid_until cannot precede valid_from.",
        )
    if not 1 <= review_interval_days <= 3650:
        raise HTTPException(
            status_code=422,
            detail="review_interval_days must be between 1 and 3650.",
        )
    if approval_status not in {"draft", "pending"}:
        raise HTTPException(status_code=422, detail="Uploaded evidence must be draft or pending approval.")
    file_bytes = await file.read(MAX_SOURCE_UPLOAD_SIZE + 1)
    if len(file_bytes) > MAX_SOURCE_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Source file exceeds the configured size limit.")
    try:
        content = extract_source_text(filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    source = SourceDocument(
        name=(name or "").strip()[:160] or filename[:160],
        description=(description or "").strip() or None,
        source_type=(source_type or "document").strip()[:48] or "document",
        content=content,
        guideline_id=guideline_id,
        url=(url or "").strip() or None,
        source_date=source_date,
        expiry_date=effective_valid_until,
        valid_from=effective_valid_from,
        valid_until=effective_valid_until,
        review_interval_days=review_interval_days,
        approval_status=approval_status,
        created_by_id=admin.id,
        updated_by_id=admin.id,
    )
    db.add(source)
    db.flush()
    db.add(
        SourceVersion(
            source_id=source.id,
            version_number=1,
            snapshot=_source_snapshot(source),
            editor_id=admin.id,
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.get("/{source_id}", response_model=SourceRead)
def get_source(
    source_id: int,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    source = _visible_source_query(
        db.query(SourceDocument),
        viewer,
    ).filter(SourceDocument.id == source_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    return _serialize(source)


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Provide at least one source field to update.")
    if "valid_from" not in updates and "source_date" in updates:
        updates["valid_from"] = updates["source_date"]
    if "valid_until" in updates:
        updates["expiry_date"] = updates["valid_until"]
    if any(
        updates.get(key) is None
        for key in ("name", "source_type", "content", "is_active", "approval_status")
        if key in updates
    ):
        raise HTTPException(status_code=422, detail="Required source fields cannot be null.")
    if "guideline_id" in updates and updates["guideline_id"] is not None:
        if db.get(BrandGuideline, updates["guideline_id"]) is None:
            raise HTTPException(status_code=422, detail="The selected guideline does not exist.")
    new_valid_from = updates.get(
        "valid_from", source.valid_from or source.source_date
    )
    new_valid_until = updates.get(
        "valid_until", source.valid_until or source.expiry_date
    )
    if new_valid_from and new_valid_until and new_valid_until < new_valid_from:
        raise HTTPException(
            status_code=422, detail="valid_until cannot precede valid_from."
        )

    previous_approval_status = source.approval_status
    was_reviewed = previous_approval_status in {"approved", "rejected"}
    changes_evidence = any(
        key in updates and updates[key] != getattr(source, key)
        for key in (
            "name",
            "description",
            "source_type",
            "content",
            "url",
            "source_date",
            "valid_from",
            "valid_until",
            "expiry_date",
            "guideline_id",
        )
    )
    reactivated = updates.get("is_active") is True and not source.is_active
    approval_downgraded = (
        "approval_status" in updates
        and updates["approval_status"] != previous_approval_status
        and updates["approval_status"] != "approved"
    )
    content_changed = "content" in updates and updates["content"] != source.content
    has_changes = any(
        updates[key] != getattr(source, key)
        for key in updates
    )
    baseline = _source_snapshot(source)
    if has_changes:
        latest_version = (
            db.query(SourceVersion.version_number)
            .filter(SourceVersion.source_id == source.id)
            .order_by(SourceVersion.version_number.desc())
            .first()
        )
        if latest_version is None:
            db.add(
                SourceVersion(
                    source_id=source.id,
                    version_number=1,
                    snapshot=baseline,
                    editor_id=source.updated_by_id or source.created_by_id,
                )
            )
            db.flush()
            next_version = 2
        else:
            next_version = latest_version[0] + 1
    for key, value in updates.items():
        setattr(source, key, value)
    source.updated_by_id = admin.id
    if has_changes:
        db.add(
            SourceVersion(
                source_id=source.id,
                version_number=next_version,
                snapshot=_source_snapshot(source),
                editor_id=admin.id,
            )
        )
    if (changes_evidence and was_reviewed) or reactivated:
        source.approval_status = "pending"
    if (changes_evidence and was_reviewed) or reactivated or approval_downgraded:
        source.reviewed_by_id = None
        source.reviewed_at = None
        source.last_verified_at = None
        source.review_note = None
        db.add(
            SourceApprovalEvent(
                source_id=source.id,
                reviewer_id=admin.id,
                status=source.approval_status,
                note=(
                    "Evidence change or reactivation requires reapproval."
                    if not approval_downgraded
                    else "Approval state changed by an Admin."
                ),
            )
        )
    if content_changed or updates.get("is_active") is False:
        source.embeddings.clear()
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.get("/{source_id}/versions")
def list_source_versions(
    source_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    if db.get(SourceDocument, source_id) is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    versions = (
        db.query(SourceVersion)
        .filter(SourceVersion.source_id == source_id)
        .order_by(SourceVersion.version_number.desc())
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


@router.patch("/{source_id}/approval", response_model=SourceRead)
def update_source_approval(
    source_id: int,
    payload: SourceApprovalUpdate,
    db: Session = Depends(get_db),
    reviewer: User = Depends(require_roles("admin", "reviewer")),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    if payload.status == "approved" and not source.is_active:
        raise HTTPException(status_code=409, detail="Inactive evidence cannot be approved.")
    if source.approval_status == payload.status and source.review_note == payload.note:
        return _serialize(source)
    baseline = _source_snapshot(source)
    source.approval_status = payload.status
    source.reviewed_by_id = reviewer.id
    source.updated_by_id = reviewer.id
    source.reviewed_at = datetime.now(timezone.utc)
    source.last_verified_at = (
        source.reviewed_at if payload.status == "approved" else None
    )
    source.review_note = payload.note
    db.add(
        SourceApprovalEvent(
            source=source,
            reviewer_id=reviewer.id,
            status=payload.status,
            note=payload.note,
        )
    )
    latest = (
        db.query(SourceVersion.version_number)
        .filter(SourceVersion.source_id == source.id)
        .order_by(SourceVersion.version_number.desc())
        .first()
    )
    if latest is None:
        db.add(
            SourceVersion(
                source_id=source.id,
                version_number=1,
                snapshot=baseline,
                editor_id=source.created_by_id,
            )
        )
        db.flush()
        next_version = 2
    else:
        next_version = latest[0] + 1
    db.add(
        SourceVersion(
            source_id=source.id,
            version_number=next_version,
            snapshot=_source_snapshot(source),
            editor_id=reviewer.id,
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.post("/{source_id}/verify", response_model=SourceRead)
def verify_source_freshness(
    source_id: int,
    payload: SourceVerificationRequest,
    db: Session = Depends(get_db),
    reviewer: User = Depends(require_roles("admin", "reviewer")),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    if not source.is_active or source.approval_status != "approved":
        raise HTTPException(
            status_code=409,
            detail="Only active, approved evidence can be freshness-verified.",
        )
    today = datetime.now(timezone.utc).date()
    valid_from = source.valid_from or source.source_date
    valid_until = source.valid_until or source.expiry_date
    if (valid_from and valid_from > today) or (valid_until and valid_until < today):
        raise HTTPException(
            status_code=409,
            detail="Evidence outside its validity window cannot be freshness-verified.",
        )

    verified_at = datetime.now(timezone.utc)
    note = payload.note or "Evidence freshness verification recorded."
    source.last_verified_at = verified_at
    source.reviewed_at = verified_at
    source.reviewed_by_id = reviewer.id
    source.updated_by_id = reviewer.id
    source.review_note = note
    db.add(
        SourceApprovalEvent(
            source_id=source.id,
            reviewer_id=reviewer.id,
            status="approved",
            note=note,
            created_at=verified_at,
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    if not source.is_active:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    baseline = _source_snapshot(source)
    source.is_active = False
    source.updated_by_id = _admin.id
    source.embeddings.clear()
    latest = (
        db.query(SourceVersion.version_number)
        .filter(SourceVersion.source_id == source.id)
        .order_by(SourceVersion.version_number.desc())
        .first()
    )
    if latest is None:
        db.add(
            SourceVersion(
                source_id=source.id,
                version_number=1,
                snapshot=baseline,
                editor_id=source.created_by_id,
            )
        )
        db.flush()
        next_version = 2
    else:
        next_version = latest[0] + 1
    db.add(
        SourceVersion(
            source_id=source.id,
            version_number=next_version,
            snapshot=_source_snapshot(source),
            editor_id=_admin.id,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
