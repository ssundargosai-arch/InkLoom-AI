from datetime import date, datetime, timezone
from pathlib import PurePosixPath
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import MAX_UPLOAD_SIZE
from app.database import get_db
from app.models.user import User
from app.models.visual_asset import VisualAsset
from app.services.auth_service import require_roles
from app.services.visual_analysis import asset_lifecycle_status, validate_visual_upload

router = APIRouter(
    prefix="/api/visual-assets",
    tags=["visual assets"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)

VISUAL_ASSET_TYPES = {
    "logo",
    "brand_icon",
    "illustration",
    "product_image",
    "template",
    "background",
    "other",
}


class VisualAssetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    asset_type: Optional[str] = Field(default=None, min_length=1, max_length=48)
    usage_restrictions: Optional[str] = Field(default=None, max_length=4000)
    valid_from: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.valid_from
            and self.expiry_date
            and self.expiry_date < self.valid_from
        ):
            raise ValueError("expiry_date cannot precede valid_from")
        for field in ("name", "asset_type"):
            value = getattr(self, field)
            if value is not None:
                value = value.strip()
                if not value:
                    raise ValueError("{} cannot be blank".format(field))
                setattr(self, field, value)
        if self.asset_type and self.asset_type not in VISUAL_ASSET_TYPES:
            raise ValueError("Unsupported visual asset type.")
        if self.description is not None:
            self.description = self.description.strip() or None
        if self.usage_restrictions is not None:
            self.usage_restrictions = self.usage_restrictions.strip() or None
        return self


class VisualAssetApproval(BaseModel):
    status: str
    note: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_decision(self):
        if self.status not in {"approved", "rejected"}:
            raise ValueError("status must be approved or rejected")
        if self.note is not None:
            self.note = self.note.strip() or None
        if self.status == "rejected" and not self.note:
            raise ValueError("A rejection reason is required.")
        return self


def _serialize(asset: VisualAsset):
    return {
        "id": asset.id,
        "name": asset.name,
        "description": asset.description,
        "asset_type": asset.asset_type,
        "filename": asset.filename,
        "media_type": asset.media_type,
        "version": asset.version,
        "approval_status": asset.approval_status,
        "lifecycle_status": asset_lifecycle_status(asset),
        "is_active": asset.is_active,
        "usage_restrictions": asset.usage_restrictions,
        "valid_from": asset.valid_from,
        "expiry_date": asset.expiry_date,
        "uploaded_by_id": asset.uploaded_by_id,
        "uploaded_by": asset.uploaded_by.display_name if asset.uploaded_by else None,
        "updated_by_id": asset.updated_by_id,
        "updated_by": asset.updated_by.display_name if asset.updated_by else None,
        "reviewed_by_id": asset.reviewed_by_id,
        "reviewed_by": asset.reviewed_by.display_name if asset.reviewed_by else None,
        "reviewed_at": asset.reviewed_at,
        "review_note": asset.review_note,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "file_url": "/api/visual-assets/{}/file".format(asset.id),
    }


def _get_asset(db: Session, asset_id: int) -> VisualAsset:
    asset = db.get(VisualAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Visual asset not found.")
    return asset


def _require_contributor_access(asset: VisualAsset, viewer: User):
    if viewer.role == "contributor" and (
        asset_lifecycle_status(asset) != "approved"
    ):
        raise HTTPException(status_code=404, detail="Visual asset not found.")


@router.get("")
def list_visual_assets(
    search: Optional[str] = None,
    asset_type: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    query = db.query(VisualAsset)
    if viewer.role == "contributor":
        today = date.today()
        query = query.filter(
            VisualAsset.approval_status == "approved",
            VisualAsset.is_active.is_(True),
            (VisualAsset.valid_from.is_(None)) | (VisualAsset.valid_from <= today),
            (VisualAsset.expiry_date.is_(None)) | (VisualAsset.expiry_date >= today),
        )
    if search:
        pattern = "%{}%".format(search.strip()[:160])
        query = query.filter(
            VisualAsset.name.ilike(pattern)
            | VisualAsset.description.ilike(pattern)
            | VisualAsset.usage_restrictions.ilike(pattern)
        )
    if asset_type:
        if asset_type not in VISUAL_ASSET_TYPES:
            raise HTTPException(status_code=422, detail="Unsupported visual asset type.")
        query = query.filter(VisualAsset.asset_type == asset_type)
    if active is not None and viewer.role != "contributor":
        query = query.filter(VisualAsset.is_active.is_(active))
    records = query.order_by(VisualAsset.id.desc()).limit(500).all()
    if lifecycle_status:
        if lifecycle_status not in {
            "draft",
            "pending",
            "approved",
            "rejected",
            "expired",
            "inactive",
            "not_yet_valid",
        }:
            raise HTTPException(status_code=422, detail="Unsupported lifecycle status.")
        records = [
            item
            for item in records
            if asset_lifecycle_status(item) == lifecycle_status
        ]
    return [_serialize(item) for item in records]


@router.post("", status_code=201)
async def upload_visual_asset(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    asset_type: str = Form(...),
    description: str = Form(default=""),
    usage_restrictions: str = Form(default=""),
    valid_from: Optional[date] = Form(default=None),
    expiry_date: Optional[date] = Form(default=None),
    db: Session = Depends(get_db),
    uploader: User = Depends(require_roles("admin", "contributor")),
):
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=422, detail="A valid visual asset filename is required.")
    if asset_type not in VISUAL_ASSET_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported visual asset type.")
    if valid_from and expiry_date and expiry_date < valid_from:
        raise HTTPException(status_code=422, detail="expiry_date cannot precede valid_from.")
    file_bytes = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Visual asset exceeds the configured size limit.")
    try:
        media_type = validate_visual_upload(filename, file.content_type, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    asset = VisualAsset(
        name=(name or "").strip()[:160] or filename[:160],
        description=(description or "").strip() or None,
        asset_type=asset_type,
        filename=filename[:160],
        media_type=media_type,
        file_data=file_bytes,
        approval_status="pending",
        is_active=True,
        usage_restrictions=(usage_restrictions or "").strip() or None,
        valid_from=valid_from,
        expiry_date=expiry_date,
        uploaded_by_id=uploader.id,
        updated_by_id=uploader.id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize(asset)


@router.get("/{asset_id}")
def get_visual_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    asset = _get_asset(db, asset_id)
    _require_contributor_access(asset, viewer)
    return _serialize(asset)


@router.get("/{asset_id}/file")
def get_visual_asset_file(
    asset_id: int,
    db: Session = Depends(get_db),
    viewer: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    asset = _get_asset(db, asset_id)
    _require_contributor_access(asset, viewer)
    response = Response(content=asset.file_data, media_type=asset.media_type)
    response.headers["Content-Disposition"] = (
        'inline; filename="visual-asset-{}.{}"'.format(
            asset.id, PurePosixPath(asset.filename).suffix.lstrip(".") or "bin"
        )
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    if asset.media_type == "application/pdf":
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@router.patch("/{asset_id}")
def update_visual_asset(
    asset_id: int,
    payload: VisualAssetUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    asset = _get_asset(db, asset_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one asset field to update.")
    reapproval_required = asset.approval_status == "approved" or (
        asset.is_active is False and changes.get("is_active") is True
    )
    for key, value in changes.items():
        setattr(asset, key, value)
    if reapproval_required or any(
        key in changes
        for key in ("name", "description", "asset_type", "usage_restrictions", "valid_from", "expiry_date")
    ):
        asset.approval_status = "pending"
        asset.reviewed_by_id = None
        asset.reviewed_at = None
        asset.review_note = None
    asset.version += 1
    asset.updated_by_id = admin.id
    db.commit()
    db.refresh(asset)
    return _serialize(asset)


@router.put("/{asset_id}/file")
async def replace_visual_asset_file(
    asset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    asset = _get_asset(db, asset_id)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=422, detail="A valid visual asset filename is required.")
    file_bytes = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Visual asset exceeds the configured size limit.")
    try:
        media_type = validate_visual_upload(filename, file.content_type, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    asset.file_data = file_bytes
    asset.filename = filename[:160]
    asset.media_type = media_type
    asset.version += 1
    asset.approval_status = "pending"
    asset.reviewed_by_id = None
    asset.reviewed_at = None
    asset.review_note = None
    asset.updated_by_id = admin.id
    db.commit()
    db.refresh(asset)
    return _serialize(asset)


@router.patch("/{asset_id}/approval")
def review_visual_asset(
    asset_id: int,
    payload: VisualAssetApproval,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    asset = _get_asset(db, asset_id)
    if asset.approval_status not in {"pending", "draft"}:
        raise HTTPException(status_code=409, detail="Only pending visual assets can be reviewed.")
    asset.approval_status = payload.status
    asset.reviewed_by_id = admin.id
    asset.reviewed_at = datetime.now(timezone.utc)
    asset.review_note = payload.note
    asset.updated_by_id = admin.id
    db.commit()
    db.refresh(asset)
    return _serialize(asset)
