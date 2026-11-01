from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.freshness import FreshnessAlert, FreshnessCheckRun
from app.models.user import User
from app.services.auth_service import require_roles
from app.services.freshness_service import (
    FreshnessCheckError,
    freshness_alert_payload,
    freshness_run_payload,
    release_scheduler_lease,
    run_freshness_check,
    try_acquire_scheduler_lease,
)

router = APIRouter(
    prefix="/api/freshness",
    tags=["freshness"],
    dependencies=[Depends(require_roles("admin", "reviewer"))],
)


@router.get("")
def get_freshness_overview(db: Session = Depends(get_db)):
    alerts = (
        db.query(FreshnessAlert)
        .filter(FreshnessAlert.status == "open")
        .order_by(FreshnessAlert.detected_at.desc(), FreshnessAlert.id.desc())
        .limit(100)
        .all()
    )
    open_alert_count = (
        db.query(func.count(FreshnessAlert.id))
        .filter(FreshnessAlert.status == "open")
        .scalar()
        or 0
    )
    runs = (
        db.query(FreshnessCheckRun)
        .order_by(FreshnessCheckRun.started_at.desc(), FreshnessCheckRun.id.desc())
        .limit(10)
        .all()
    )
    recent_alerts = (
        db.query(FreshnessAlert)
        .order_by(FreshnessAlert.detected_at.desc(), FreshnessAlert.id.desc())
        .limit(50)
        .all()
    )
    return {
        "open_alert_count": open_alert_count,
        "alerts": [freshness_alert_payload(alert) for alert in alerts],
        "recent_alerts": [
            freshness_alert_payload(alert) for alert in recent_alerts
        ],
        "last_run": freshness_run_payload(runs[0]) if runs else None,
        "recent_runs": [freshness_run_payload(run) for run in runs],
    }


@router.post("/check", status_code=status.HTTP_201_CREATED)
def run_manual_freshness_check(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    owner_token = str(uuid4())
    if not try_acquire_scheduler_lease(db, owner_token):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A freshness check is already running.",
        )
    try:
        try:
            run = run_freshness_check(db, "manual")
        except FreshnessCheckError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Freshness check failed. The failed run was recorded.",
            ) from exc
        return freshness_run_payload(run)
    finally:
        release_scheduler_lease(db, owner_token)
