import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.brand_guideline import BrandGuideline
from app.models.freshness import (
    FreshnessAlert,
    FreshnessCheckRun,
    FreshnessSchedulerLease,
)
from app.models.source_document import SourceDocument

logger = logging.getLogger(__name__)
SOURCE_EXPIRY_WARNING_DAYS = 30
SCHEDULER_LEASE_SECONDS = 600


class FreshnessCheckError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _source_valid_from(source: SourceDocument) -> Optional[date]:
    return source.valid_from or source.source_date


def _source_valid_until(source: SourceDocument) -> Optional[date]:
    return source.valid_until or source.expiry_date


def source_freshness(source: SourceDocument, now: Optional[datetime] = None) -> str:
    current_time = normalize_utc(now) or _utcnow()
    today = current_time.date()
    if not source.is_active:
        return "inactive"
    if source.approval_status != "approved":
        return source.approval_status
    valid_from = _source_valid_from(source)
    valid_until = _source_valid_until(source)
    if valid_from and valid_from > today:
        return "not_yet_valid"
    if valid_until and valid_until < today:
        return "expired"
    last_verified_at = normalize_utc(
        source.last_verified_at or source.reviewed_at
    )
    if (
        last_verified_at is None
        or last_verified_at
        + timedelta(days=max(1, source.review_interval_days))
        <= current_time
    ):
        return "review_overdue"
    if valid_until and valid_until <= today + timedelta(days=SOURCE_EXPIRY_WARNING_DAYS):
        return "expiring_soon"
    return "current"


def guideline_freshness(
    guideline: BrandGuideline, now: Optional[datetime] = None
) -> str:
    current_time = normalize_utc(now) or _utcnow()
    if not guideline.is_active:
        return "inactive"
    last_reviewed_at = normalize_utc(guideline.last_reviewed_at)
    if (
        last_reviewed_at is None
        or last_reviewed_at
        + timedelta(days=max(1, guideline.review_interval_days))
        <= current_time
    ):
        return "review_overdue"
    return "current"


def source_next_review_due_at(source: SourceDocument) -> Optional[datetime]:
    last_verified_at = normalize_utc(
        source.last_verified_at or source.reviewed_at
    )
    if last_verified_at is None:
        return None
    return last_verified_at + timedelta(days=max(1, source.review_interval_days))


def guideline_next_review_due_at(
    guideline: BrandGuideline,
) -> Optional[datetime]:
    last_reviewed_at = normalize_utc(guideline.last_reviewed_at)
    if last_reviewed_at is None:
        return None
    return last_reviewed_at + timedelta(days=max(1, guideline.review_interval_days))


def try_acquire_scheduler_lease(
    db: Session,
    owner_token: str,
    now: Optional[datetime] = None,
) -> bool:
    current_time = normalize_utc(now) or _utcnow()
    expires_at = current_time + timedelta(seconds=SCHEDULER_LEASE_SECONDS)
    lease = db.get(FreshnessSchedulerLease, 1)
    if lease is None:
        db.add(
            FreshnessSchedulerLease(
                id=1, owner_token=owner_token, expires_at=expires_at
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
        return True

    updated = (
        db.query(FreshnessSchedulerLease)
        .filter(
            FreshnessSchedulerLease.id == 1,
            or_(
                FreshnessSchedulerLease.expires_at <= current_time,
                FreshnessSchedulerLease.owner_token == owner_token,
            ),
        )
        .update(
            {
                FreshnessSchedulerLease.owner_token: owner_token,
                FreshnessSchedulerLease.expires_at: expires_at,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return updated == 1


def release_scheduler_lease(db: Session, owner_token: str) -> None:
    (
        db.query(FreshnessSchedulerLease)
        .filter(
            FreshnessSchedulerLease.id == 1,
            FreshnessSchedulerLease.owner_token == owner_token,
        )
        .update(
            {FreshnessSchedulerLease.expires_at: _utcnow()},
            synchronize_session=False,
        )
    )
    db.commit()


def _alerts_for_source(
    source: SourceDocument, now: datetime
) -> list[tuple[str, str]]:
    if not source.is_active:
        return []
    alerts = []
    valid_until = _source_valid_until(source)
    today = now.date()
    if valid_until and valid_until < today:
        alerts.append(
            ("source_expired", "Evidence validity ended on {}.".format(valid_until))
        )
    elif valid_until and valid_until <= today + timedelta(days=SOURCE_EXPIRY_WARNING_DAYS):
        alerts.append(
            (
                "source_expiring",
                "Evidence expires on {}.".format(valid_until),
            )
        )
    if source.approval_status == "approved" and source_freshness(source, now) == "review_overdue":
        alerts.append(
            (
                "source_review_overdue",
                "Approved evidence requires freshness review.",
            )
        )
    return alerts


def _alerts_for_guideline(
    guideline: BrandGuideline, now: datetime
) -> list[tuple[str, str]]:
    if (
        guideline.is_active
        and guideline_freshness(guideline, now) == "review_overdue"
    ):
        return [
            (
                "guideline_review_overdue",
                "Active guideline requires policy freshness review.",
            )
        ]
    return []


def run_freshness_check(
    db: Session, trigger: str, now: Optional[datetime] = None
) -> FreshnessCheckRun:
    if trigger not in {"manual", "scheduled"}:
        raise ValueError("Freshness check trigger must be manual or scheduled.")
    started_at = normalize_utc(now) or _utcnow()
    sources_checked = 0
    guidelines_checked = 0
    try:
        sources = db.query(SourceDocument).all()
        guidelines = db.query(BrandGuideline).all()
        sources_checked = len(sources)
        guidelines_checked = len(guidelines)
        expected_alerts: dict[tuple[str, int, str], tuple[str, str]] = {}
        for source in sources:
            for alert_type, message in _alerts_for_source(source, started_at):
                expected_alerts[
                    ("source", source.id, alert_type)
                ] = (source.name, message)
        for guideline in guidelines:
            for alert_type, message in _alerts_for_guideline(guideline, started_at):
                expected_alerts[
                    ("guideline", guideline.id, alert_type)
                ] = (guideline.name, message)

        current_alerts = (
            db.query(FreshnessAlert)
            .filter(FreshnessAlert.status == "open")
            .all()
        )
        current_by_key = {
            (alert.resource_type, alert.resource_id, alert.alert_type): alert
            for alert in current_alerts
        }
        for key, alert in current_by_key.items():
            if key not in expected_alerts:
                alert.status = "resolved"
                alert.resolved_at = started_at

        alerts_created = 0
        for (resource_type, resource_id, alert_type), (
            resource_name,
            message,
        ) in expected_alerts.items():
            existing = current_by_key.get(
                (resource_type, resource_id, alert_type)
            )
            if existing is None:
                db.add(
                    FreshnessAlert(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        resource_name=resource_name,
                        alert_type=alert_type,
                        message=message,
                        status="open",
                        detected_at=started_at,
                    )
                )
                alerts_created += 1
            else:
                existing.resource_name = resource_name
                existing.message = message

        run = FreshnessCheckRun(
            trigger=trigger,
            status="completed",
            started_at=started_at,
            completed_at=_utcnow(),
            sources_checked=len(sources),
            guidelines_checked=len(guidelines),
            alerts_created=alerts_created,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        logger.exception("Freshness check failed.")
        failed_at = _utcnow()
        failed_run = FreshnessCheckRun(
            trigger=trigger,
            status="failed",
            started_at=started_at,
            completed_at=failed_at,
            sources_checked=sources_checked,
            guidelines_checked=guidelines_checked,
            alerts_created=0,
            error="Freshness check failed ({}).".format(type(exc).__name__),
        )
        db.add(failed_run)
        db.commit()
        raise FreshnessCheckError("Freshness check failed.") from exc


def freshness_run_payload(run: FreshnessCheckRun) -> dict:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": normalize_utc(run.started_at),
        "completed_at": normalize_utc(run.completed_at),
        "sources_checked": run.sources_checked,
        "guidelines_checked": run.guidelines_checked,
        "alerts_created": run.alerts_created,
        "error": run.error,
    }


def freshness_alert_payload(alert: FreshnessAlert) -> dict:
    return {
        "id": alert.id,
        "resource_type": alert.resource_type,
        "resource_id": alert.resource_id,
        "resource_name": alert.resource_name,
        "alert_type": alert.alert_type,
        "message": alert.message,
        "status": alert.status,
        "detected_at": normalize_utc(alert.detected_at),
        "resolved_at": normalize_utc(alert.resolved_at),
    }


def _run_scheduled_iteration(
    session_factory: Callable[[], Session], owner_token: str
) -> None:
    db = session_factory()
    try:
        if not try_acquire_scheduler_lease(db, owner_token):
            return
        try:
            run_freshness_check(db, "scheduled")
        except FreshnessCheckError:
            logger.error("Scheduled freshness check failure was recorded.")
        finally:
            release_scheduler_lease(db, owner_token)
    except Exception:
        db.rollback()
        logger.exception("Scheduled freshness check could not start.")
    finally:
        db.close()


async def run_freshness_scheduler(
    session_factory: Callable[[], Session], interval_seconds: int
) -> None:
    owner_token = str(uuid4())
    first_run = True
    while True:
        delay = min(60, interval_seconds) if first_run else interval_seconds
        await asyncio.sleep(delay)
        first_run = False
        await asyncio.to_thread(
            _run_scheduled_iteration, session_factory, owner_token
        )
