import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import migrate_temporal_freshness
from app.models.brand_guideline import BrandGuideline
from app.models.freshness import FreshnessCheckRun
from app.models.source_document import SourceChunkEmbedding, SourceDocument
from app.models.user import User
from app.services.auth_service import hash_password
from app.services.factual_verifier import verification_fields
from app.services.freshness_service import (
    guideline_freshness,
    release_scheduler_lease,
    run_freshness_check,
    source_freshness,
    try_acquire_scheduler_lease,
)


def _login(client, email, password="strong-test-password"):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200


def _add_user(test_engine, email, role):
    with Session(test_engine) as db:
        db.add(
            User(
                email=email,
                display_name=role.title(),
                password_hash=hash_password("strong-test-password"),
                role=role,
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()


def test_freshness_check_creates_deduplicates_and_resolves_alerts(client, test_engine):
    now = datetime.now(timezone.utc)
    today = now.date()
    created_source = client.post(
        "/api/sources",
        json={
            "name": "Expired evidence",
            "content": "Our product increases revenue by 30%.",
            "valid_from": (today - timedelta(days=30)).isoformat(),
            "valid_until": (today - timedelta(days=1)).isoformat(),
            "review_interval_days": 30,
        },
    )
    assert created_source.status_code == 201
    source_id = created_source.json()["id"]
    approved = client.patch(
        f"/api/sources/{source_id}/approval",
        json={"status": "approved"},
    )
    assert approved.status_code == 200

    stale_source = client.post(
        "/api/sources",
        json={
            "name": "Needs review evidence",
            "content": "Our product has 20 years of experience.",
            "valid_from": (today - timedelta(days=30)).isoformat(),
            "valid_until": (today + timedelta(days=90)).isoformat(),
            "review_interval_days": 30,
        },
    )
    assert stale_source.status_code == 201
    stale_source_id = stale_source.json()["id"]
    assert client.patch(
        f"/api/sources/{stale_source_id}/approval",
        json={"status": "approved"},
    ).status_code == 200

    created_guideline = client.post(
        "/api/guidelines",
        json={
            "name": "Fresh policy",
            "category": "Brand Messaging",
            "description": "Use current product language.",
            "review_interval_days": 30,
        },
    )
    assert created_guideline.status_code == 201
    guideline_id = created_guideline.json()["id"]

    old_review = now - timedelta(days=60)
    with Session(test_engine) as db:
        source = db.get(SourceDocument, source_id)
        source.last_verified_at = old_review
        source.reviewed_at = old_review
        stale = db.get(SourceDocument, stale_source_id)
        stale.last_verified_at = old_review
        stale.reviewed_at = old_review
        guideline = db.get(BrandGuideline, guideline_id)
        guideline.last_reviewed_at = old_review
        db.commit()

    first = client.post("/api/freshness/check")
    assert first.status_code == 201
    assert first.json()["status"] == "completed"
    assert first.json()["sources_checked"] >= 1
    assert first.json()["guidelines_checked"] >= 1
    assert first.json()["alerts_created"] == 3

    overview = client.get("/api/freshness")
    assert overview.status_code == 200
    assert overview.json()["open_alert_count"] == 3
    assert {
        alert["alert_type"] for alert in overview.json()["alerts"]
    } == {
        "source_expired",
        "source_review_overdue",
        "guideline_review_overdue",
    }

    duplicate = client.post("/api/freshness/check")
    assert duplicate.status_code == 201
    assert duplicate.json()["alerts_created"] == 0
    assert client.get("/api/freshness").json()["open_alert_count"] == 3

    marked = client.post(f"/api/guidelines/{guideline_id}/review", json={"note": "Policy reconfirmed."})
    assert marked.status_code == 200
    assert marked.json()["freshness_status"] == "current"
    assert marked.json()["review_history"][-1]["note"] == "Policy reconfirmed."

    with Session(test_engine) as db:
        source = db.get(SourceDocument, source_id)
        source.valid_until = today + timedelta(days=10)
        source.last_verified_at = datetime.now(timezone.utc)
        source.reviewed_at = source.last_verified_at
        stale = db.get(SourceDocument, stale_source_id)
        stale.last_verified_at = source.last_verified_at
        stale.reviewed_at = source.reviewed_at
        db.commit()
    resolved = client.post("/api/freshness/check")
    assert resolved.status_code == 201
    assert resolved.json()["alerts_created"] == 1
    remaining = client.get("/api/freshness").json()["alerts"]
    assert {alert["alert_type"] for alert in remaining} == {"source_expiring"}


def test_freshness_and_manual_check_permissions(client, test_engine):
    _add_user(test_engine, "freshness-reviewer@example.test", "reviewer")
    _add_user(test_engine, "freshness-contributor@example.test", "contributor")

    _login(client, "freshness-reviewer@example.test")
    assert client.get("/api/freshness").status_code == 200
    assert client.post("/api/freshness/check").status_code == 403
    assert client.post("/api/guidelines/1/review", json={}).status_code == 403

    _login(client, "freshness-contributor@example.test")
    assert client.get("/api/freshness").status_code == 403
    assert client.post("/api/freshness/check").status_code == 403


def test_source_freshness_verification_requires_valid_approved_evidence(
    client, test_engine
):
    today = datetime.now(timezone.utc).date()
    created = client.post(
        "/api/sources",
        json={
            "name": "Reverification source",
            "content": "Current approved evidence.",
            "valid_from": (today - timedelta(days=10)).isoformat(),
            "valid_until": (today + timedelta(days=30)).isoformat(),
            "review_interval_days": 10,
        },
    )
    source_id = created.json()["id"]
    assert client.patch(
        f"/api/sources/{source_id}/approval",
        json={"status": "approved"},
    ).status_code == 200
    with Session(test_engine) as db:
        source = db.get(SourceDocument, source_id)
        source.last_verified_at = datetime.now(timezone.utc) - timedelta(days=20)
        db.commit()

    overdue = client.get(f"/api/sources/{source_id}")
    assert overdue.json()["freshness_status"] == "review_overdue"
    verified = client.post(
        f"/api/sources/{source_id}/verify",
        json={"note": "Reconfirmed against the signed report."},
    )
    assert verified.status_code == 200
    assert verified.json()["freshness_status"] == "expiring_soon"
    assert verified.json()["approval_history"][-1]["note"] == (
        "Reconfirmed against the signed report."
    )

    expired = client.post(
        "/api/sources",
        json={
            "name": "Expired source",
            "content": "Expired evidence.",
            "valid_until": (today - timedelta(days=1)).isoformat(),
        },
    )
    expired_id = expired.json()["id"]
    assert client.patch(
        f"/api/sources/{expired_id}/approval",
        json={"status": "approved"},
    ).status_code == 200
    assert client.post(f"/api/sources/{expired_id}/verify", json={}).status_code == 409


def test_freshness_check_lease_prevents_parallel_runs(test_engine, client):
    with Session(test_engine) as db:
        assert try_acquire_scheduler_lease(db, "worker-one")
        assert not try_acquire_scheduler_lease(db, "worker-two")
        release_scheduler_lease(db, "worker-one")
        assert try_acquire_scheduler_lease(db, "worker-two")
        release_scheduler_lease(db, "worker-two")


def test_scheduled_freshness_runner_persists_a_scheduled_run(
    test_engine, client, monkeypatch
):
    from app.services import freshness_service

    calls = []

    class StopScheduler(Exception):
        pass

    async def immediate_sleep(seconds):
        calls.append(seconds)
        if len(calls) == 2:
            raise StopScheduler

    monkeypatch.setattr(freshness_service.asyncio, "sleep", immediate_sleep)

    async def run_once():
        try:
            await freshness_service.run_freshness_scheduler(
                lambda: Session(test_engine), 60
            )
        except StopScheduler:
            return
        raise AssertionError("The scheduled loop did not reach its stop condition.")

    asyncio.run(run_once())
    with Session(test_engine) as db:
        run = (
            db.query(FreshnessCheckRun)
            .order_by(FreshnessCheckRun.id.desc())
            .first()
        )
        assert run.trigger == "scheduled"
        assert run.status == "completed"
    assert calls == [60, 60]


def test_failed_freshness_check_is_recorded_and_reported(client, test_engine):
    from app.services.freshness_service import FreshnessCheckError

    with Session(test_engine) as db:
        def fail_query(*_args, **_kwargs):
            raise RuntimeError("database query failed")

        db.query = fail_query
        with pytest.raises(FreshnessCheckError):
            run_freshness_check(db, "manual")

    with Session(test_engine) as db:
        failed = (
            db.query(FreshnessCheckRun)
            .filter_by(status="failed")
            .order_by(FreshnessCheckRun.id.desc())
            .first()
        )
        assert failed is not None
        assert "RuntimeError" in failed.error


def test_deactivating_source_invalidates_cached_embeddings(client, test_engine):
    created = client.post(
        "/api/sources",
        json={
            "name": "Cached source",
            "content": "Approved claim text.",
        },
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    with Session(test_engine) as db:
        db.add(
            SourceChunkEmbedding(
                source_id=source_id,
                chunk_index=0,
                chunk_text="Approved claim text.",
                model_name="test-model",
                vector=[0.1, 0.2],
            )
        )
        db.commit()
    assert client.delete(f"/api/sources/{source_id}").status_code == 204
    with Session(test_engine) as db:
        assert (
            db.query(SourceChunkEmbedding)
            .filter_by(source_id=source_id)
            .count()
            == 0
        )


def test_explicit_validity_boundaries_gate_claim_support():
    today = datetime.now(timezone.utc).date()
    claim = "Our product increases revenue by 30%."
    current_source = {
        "name": "Current report",
        "excerpt": claim,
        "source_type": "approved_internal_source",
        "approval_status": "approved",
        "is_active": True,
        "valid_from": (today - timedelta(days=1)).isoformat(),
        "valid_until": (today + timedelta(days=1)).isoformat(),
        "freshness": "current",
    }
    assert verification_fields(claim, [current_source])["evidence_status"] == "supported"

    future_source = {
        **current_source,
        "valid_from": (today + timedelta(days=1)).isoformat(),
        "freshness": "not_yet_valid",
    }
    assert verification_fields(claim, [future_source])["evidence_status"] == "unverified"

    expired_source = {
        **current_source,
        "valid_until": (today - timedelta(days=1)).isoformat(),
        "freshness": "expired",
    }
    assert verification_fields(claim, [expired_source])["evidence_status"] == "expired_evidence"


def test_analysis_citations_capture_validity_approval_and_retrieval_time(client):
    today = datetime.now(timezone.utc).date()
    created = client.post(
        "/api/sources",
        json={
            "name": "Current product report",
            "content": "Our product increases revenue by 30%.",
            "source_date": (today - timedelta(days=10)).isoformat(),
            "valid_from": (today - timedelta(days=5)).isoformat(),
            "valid_until": (today + timedelta(days=10)).isoformat(),
        },
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    approved = client.patch(
        f"/api/sources/{source_id}/approval",
        json={"status": "approved"},
    )
    assert approved.status_code == 200

    analysis = client.post(
        "/api/analyze",
        json={
            "content": "Our product increases revenue by 30%.",
            "source_ids": [source_id],
        },
    )
    assert analysis.status_code == 200
    finding = next(
        item
        for item in analysis.json()["findings"]
        if item.get("evidence_status") == "supported"
    )
    citation = finding["citations"][0]
    assert citation["source_date"] == (today - timedelta(days=10)).isoformat()
    assert citation["valid_from"] == (today - timedelta(days=5)).isoformat()
    assert citation["valid_until"] == (today + timedelta(days=10)).isoformat()
    assert citation["approval_at"]
    assert citation["last_verified_at"]
    assert citation["retrieved_at"]


def test_source_and_guideline_freshness_boundaries():
    now = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    source = SourceDocument(
        name="Source",
        content="Evidence",
        source_type="document",
        approval_status="approved",
        is_active=True,
        review_interval_days=30,
        last_verified_at=now - timedelta(days=29),
        valid_from=now.date(),
        valid_until=(now + timedelta(days=10)).date(),
    )
    guideline = BrandGuideline(
        name="Guideline",
        category="Brand Messaging",
        description="Use clear language.",
        severity="medium",
        status="approved",
        is_active=True,
        review_interval_days=30,
        last_reviewed_at=now - timedelta(days=29),
    )
    assert source_freshness(source, now) == "expiring_soon"
    assert guideline_freshness(guideline, now) == "current"
    assert guideline_freshness(
        guideline, now + timedelta(days=1)
    ) == "review_overdue"
    source.last_verified_at = now - timedelta(days=31)
    assert source_freshness(source, now) == "review_overdue"


def test_temporal_migration_is_additive_idempotent_and_backfills_legacy_dates():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE source_documents (id INTEGER PRIMARY KEY, "
                    "source_date DATE, expiry_date DATE, approval_status TEXT, "
                    "reviewed_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE brand_guidelines (id INTEGER PRIMARY KEY, "
                    "created_at DATETIME, updated_at DATETIME, updated_by_id INTEGER)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO source_documents "
                    "(id, source_date, expiry_date, approval_status, reviewed_at) "
                    "VALUES (1, '2026-01-01', '2026-12-31', 'approved', "
                    "'2026-04-01 10:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO brand_guidelines "
                    "(id, created_at, updated_at, updated_by_id) "
                    "VALUES (1, '2026-01-01 10:00:00', "
                    "'2026-03-01 10:00:00', 7)"
                )
            )

        migrate_temporal_freshness(engine)
        migrate_temporal_freshness(engine)

        with engine.connect() as connection:
            source = connection.execute(
                text(
                    "SELECT valid_from, valid_until, last_verified_at "
                    "FROM source_documents WHERE id = 1"
                )
            ).one()
            guideline = connection.execute(
                text(
                    "SELECT last_reviewed_at, last_reviewed_by_id "
                    "FROM brand_guidelines WHERE id = 1"
                )
            ).one()
        assert str(source.valid_from) == "2026-01-01"
        assert str(source.valid_until) == "2026-12-31"
        assert source.last_verified_at is not None
        assert guideline.last_reviewed_at is not None
        assert guideline.last_reviewed_by_id == 7
        assert "valid_from" in {
            column["name"]
            for column in inspect(engine).get_columns("source_documents")
        }
    finally:
        engine.dispose()
