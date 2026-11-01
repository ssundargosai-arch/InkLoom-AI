from datetime import datetime, timezone

from sqlalchemy import func, or_

from app.models.source_document import SourceDocument


def apply_source_visibility(query, viewer):
    if viewer.role != "contributor":
        return query

    today = datetime.now(timezone.utc).date()
    valid_from = func.coalesce(
        SourceDocument.valid_from,
        SourceDocument.source_date,
    )
    valid_until = func.coalesce(
        SourceDocument.valid_until,
        SourceDocument.expiry_date,
    )
    return query.filter(
        SourceDocument.approval_status == "approved",
        SourceDocument.is_active.is_(True),
        or_(valid_from.is_(None), valid_from <= today),
        or_(valid_until.is_(None), valid_until >= today),
    )
