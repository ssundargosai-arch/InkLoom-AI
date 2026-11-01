from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.database import (
    migrate_brand_voice,
    migrate_guidelines_and_sources,
    migrate_source_approval,
)
from app.models.brand_guideline import BrandGuideline, GuidelineVersion
from app.models.brand_voice import BrandVoiceConfiguration, BrandVoiceVersion
from app.models.source_document import SourceDocument
from app.models.user import User
from app.services.auth_service import hash_password


def _add_user(test_engine, email, name, role):
    with Session(test_engine) as db:
        user = User(
            email=email,
            display_name=name,
            password_hash=hash_password("strong-test-password"),
            role=role,
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _login(client, email):
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": (
                "test-admin-password-123"
                if email == "admin@example.test"
                else "strong-test-password"
            ),
        },
    )
    assert response.status_code == 200


def test_guideline_edit_activation_history_and_permissions(
    client, test_engine
):
    created = client.post(
        "/api/guidelines",
        json={
            "name": "Claims substantiation",
            "category": "Promotional Claims",
            "description": "Substantiate performance statements.",
            "examples": ["Use a dated study."],
            "severity": "high",
        },
    )
    assert created.status_code == 201
    guideline_id = created.json()["id"]
    assert created.json()["created_by"] == "Workspace Admin"

    updated = client.patch(
        f"/api/guidelines/{guideline_id}",
        json={
            "description": "Substantiate every performance statement.",
            "examples": ["Include methodology and dates."],
            "severity": "critical",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["updated_by"] == "Workspace Admin"

    versions = client.get(f"/api/guidelines/{guideline_id}/versions")
    assert versions.status_code == 200
    assert [version["version_number"] for version in versions.json()] == [2, 1]
    assert versions.json()[0]["snapshot"]["severity"] == "critical"
    assert versions.json()[1]["snapshot"]["description"] == (
        "Substantiate performance statements."
    )

    with Session(test_engine) as db:
        legacy = BrandGuideline(
            name="Legacy guideline",
            category="Content Formatting",
            description="Original guidance.",
            severity="medium",
            status="approved",
            is_seed=True,
        )
        db.add(legacy)
        db.commit()
        db.refresh(legacy)
        legacy_id = legacy.id
    legacy_update = client.patch(
        f"/api/guidelines/{legacy_id}",
        json={"description": "Revised guidance."},
    )
    assert legacy_update.status_code == 200
    legacy_versions = client.get(
        f"/api/guidelines/{legacy_id}/versions"
    ).json()
    assert [version["version_number"] for version in legacy_versions] == [2, 1]
    assert legacy_versions[1]["snapshot"]["description"] == "Original guidance."

    inactive = client.patch(
        f"/api/guidelines/{guideline_id}",
        json={"is_active": False},
    )
    assert inactive.status_code == 200
    assert inactive.json()["is_active"] is False
    assert client.get("/api/guidelines?active=false").json()[0]["id"] == guideline_id
    assert client.get("/api/guidelines/categories").json()

    _add_user(test_engine, "guideline-reviewer@example.test", "Reviewer", "reviewer")
    _login(client, "guideline-reviewer@example.test")
    reviewer_edit = client.patch(
        f"/api/guidelines/{guideline_id}",
        json={"description": "Reviewer edit."},
    )
    assert reviewer_edit.status_code == 403

    contributor_id = _add_user(
        test_engine, "guideline-contributor@example.test", "Contributor", "contributor"
    )
    _login(client, "guideline-contributor@example.test")
    forbidden_edit = client.patch(
        f"/api/guidelines/{guideline_id}",
        json={"description": "Unauthorized edit."},
    )
    assert forbidden_edit.status_code == 403
    forbidden_versions = client.get(f"/api/guidelines/{guideline_id}/versions")
    assert forbidden_versions.status_code == 403

    with Session(test_engine) as db:
        history = (
            db.query(GuidelineVersion)
            .filter_by(guideline_id=guideline_id)
            .order_by(GuidelineVersion.version_number)
            .all()
        )
        assert [version.editor_id for version in history] == [
            created.json()["created_by_id"],
            created.json()["created_by_id"],
            created.json()["created_by_id"],
        ]
        assert contributor_id is not None


def test_contributors_only_read_approved_active_current_sources(
    client, test_engine
):
    _add_user(
        test_engine,
        "source-visibility-reviewer@example.test",
        "Source Visibility Reviewer",
        "reviewer",
    )
    contributor_id = _add_user(
        test_engine,
        "source-visibility-contributor@example.test",
        "Source Visibility Contributor",
        "contributor",
    )
    today = datetime.now(timezone.utc).date()
    records = [
        SourceDocument(
            name="Current approved source",
            content="Shared approved evidence.",
            approval_status="approved",
            is_active=True,
            valid_from=today,
            valid_until=today,
        ),
        SourceDocument(
            name="Private pending submission",
            content="Pending contributor evidence.",
            approval_status="pending",
            is_active=True,
            created_by_id=contributor_id,
        ),
        SourceDocument(
            name="Rejected source",
            content="Rejected evidence.",
            approval_status="rejected",
            is_active=True,
        ),
        SourceDocument(
            name="Inactive source",
            content="Inactive approved evidence.",
            approval_status="approved",
            is_active=False,
        ),
        SourceDocument(
            name="Expired source",
            content="Expired approved evidence.",
            approval_status="approved",
            is_active=True,
            valid_until=today - timedelta(days=1),
        ),
        SourceDocument(
            name="Future source",
            content="Not-yet-valid approved evidence.",
            approval_status="approved",
            is_active=True,
            valid_from=today + timedelta(days=1),
        ),
    ]
    with Session(test_engine) as db:
        db.add_all(records)
        db.commit()
        source_ids = {source.name: source.id for source in records}

    all_names = {source["name"] for source in client.get("/api/sources").json()}
    assert all_names == {source.name for source in records}
    for source_id in source_ids.values():
        assert client.get(f"/api/sources/{source_id}").status_code == 200

    _login(client, "source-visibility-reviewer@example.test")
    assert {source["name"] for source in client.get("/api/sources").json()} == all_names
    for source_id in source_ids.values():
        assert client.get(f"/api/sources/{source_id}").status_code == 200

    _login(client, "source-visibility-contributor@example.test")
    visible = client.get("/api/sources")
    assert visible.status_code == 200
    assert [source["name"] for source in visible.json()] == [
        "Current approved source"
    ]
    assert client.get(
        f"/api/sources/{source_ids['Current approved source']}"
    ).status_code == 200
    for name in (
        "Private pending submission",
        "Rejected source",
        "Inactive source",
        "Expired source",
        "Future source",
    ):
        assert client.get(f"/api/sources/{source_ids[name]}").status_code == 404
        assert all(source["name"] != name for source in visible.json())


def test_evidence_lifecycle_edits_deactivation_and_authorization(
    client, test_engine
):
    reviewer_id = _add_user(
        test_engine, "evidence-reviewer@example.test", "Evidence Reviewer", "reviewer"
    )
    contributor_id = _add_user(
        test_engine, "evidence-contributor@example.test", "Contributor", "contributor"
    )
    created = client.post(
        "/api/sources",
        json={
            "name": "Pricing specification",
            "description": "Current approved pricing information.",
            "source_type": "product facts",
            "content": "The annual plan costs $240.",
            "valid_from": "2026-01-01",
            "expiry_date": "2027-01-01",
        },
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    assert created.json()["approval_status"] == "pending"
    assert created.json()["valid_from"] == "2026-01-01"
    assert created.json()["created_by"] == "Workspace Admin"

    _login(client, "evidence-reviewer@example.test")
    approved = client.patch(
        f"/api/sources/{source_id}/approval",
        json={"status": "approved", "note": "Checked against source."},
    )
    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"
    assert approved.json()["reviewed_by"] == "Evidence Reviewer"
    reviewer_edit = client.patch(
        f"/api/sources/{source_id}",
        json={"content": "Reviewer cannot edit source content."},
    )
    assert reviewer_edit.status_code == 403

    _login(client, "admin@example.test")
    edited = client.patch(
        f"/api/sources/{source_id}",
        json={"content": "The annual plan costs $260."},
    )
    assert edited.status_code == 200
    assert edited.json()["approval_status"] == "pending"
    assert edited.json()["content"] == "The annual plan costs $260."
    source_versions = client.get(f"/api/sources/{source_id}/versions")
    assert source_versions.status_code == 200
    assert [version["version_number"] for version in source_versions.json()] == [3, 2, 1]
    assert source_versions.json()[2]["snapshot"]["content"] == (
        "The annual plan costs $240."
    )

    reapproved = client.patch(
        f"/api/sources/{source_id}/approval",
        json={"status": "approved"},
    )
    assert reapproved.status_code == 200

    _login(client, "evidence-contributor@example.test")
    forbidden = client.patch(
        f"/api/sources/{source_id}/approval",
        json={"status": "rejected"},
    )
    assert forbidden.status_code == 403
    forbidden_edit = client.patch(
        f"/api/sources/{source_id}",
        json={"content": "Unauthorized"},
    )
    assert forbidden_edit.status_code == 403

    _login(client, "admin@example.test")
    deactivated = client.delete(f"/api/sources/{source_id}")
    assert deactivated.status_code == 204
    assert client.get(f"/api/sources/{source_id}").json()["is_active"] is False
    record = client.get(f"/api/sources?active=false").json()
    assert any(item["id"] == source_id and item["lifecycle_status"] == "inactive" for item in record)
    blocked_retrieval = client.post(
        "/api/analyze",
        json={
            "content": "The annual plan costs $260.",
            "source_ids": [source_id],
        },
    )
    assert blocked_retrieval.status_code == 422

    reactivated = client.patch(
        f"/api/sources/{source_id}",
        json={"is_active": True},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["approval_status"] == "pending"
    assert reactivated.json()["is_active"] is True
    assert reactivated.json()["updated_by"] == "Workspace Admin"


def test_legacy_guideline_and_source_migration_is_additive_and_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE brand_guidelines ("
            "id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, "
            "category VARCHAR(80) NOT NULL, description TEXT NOT NULL, "
            "severity VARCHAR(16) NOT NULL, prohibited_terms JSON NOT NULL, "
            "preferred_terms JSON NOT NULL, approved_sources JSON NOT NULL, "
            "status VARCHAR(24) NOT NULL, is_seed BOOLEAN NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE source_documents ("
            "id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, "
            "content TEXT NOT NULL, source_date DATE, expiry_date DATE, "
            "created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO brand_guidelines VALUES "
            "(1, 'Legacy rule', 'claims', 'Keep the claim grounded.', 'high', "
            "'[]', '[]', '[]', 'approved', 0, '2026-01-01 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO source_documents VALUES "
            "(1, 'Legacy source', 'Evidence content', NULL, NULL, "
            "'2026-01-01 00:00:00')"
        )

    migrate_source_approval(engine)
    migrate_guidelines_and_sources(engine)
    migrate_source_approval(engine)
    migrate_guidelines_and_sources(engine)
    inspector = inspect(engine)
    guideline_columns = {
        column["name"] for column in inspector.get_columns("brand_guidelines")
    }
    source_columns = {
        column["name"] for column in inspector.get_columns("source_documents")
    }
    assert {"examples", "is_active", "created_by_id", "updated_by_id", "updated_at"} <= guideline_columns
    assert {"description", "source_type", "is_active", "created_by_id", "updated_by_id", "updated_at", "approval_status"} <= source_columns
    with engine.connect() as connection:
        guideline = connection.exec_driver_sql(
            "SELECT name, is_active, updated_at, examples FROM brand_guidelines WHERE id=1"
        ).one()
        source = connection.exec_driver_sql(
            "SELECT name, is_active, updated_at, approval_status FROM source_documents WHERE id=1"
        ).one()
    assert guideline[0] == "Legacy rule"
    assert guideline[1] == 1
    assert guideline[2] == "2026-01-01 00:00:00"
    assert source[0] == "Legacy source"
    assert source[1] == 1
    assert source[2] == "2026-01-01 00:00:00"
    assert source[3] == "pending"
    engine.dispose()


def test_brand_voice_table_migration_preserves_existing_guidelines():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE brand_guidelines ("
            "id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, "
            "category VARCHAR(80) NOT NULL, description TEXT NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO brand_guidelines VALUES "
            "(17, 'Existing standard', 'tone', 'Preserve the existing rule.', "
            "'2026-01-01 00:00:00')"
        )

    migrate_brand_voice(engine)
    migrate_brand_voice(engine)

    inspector = inspect(engine)
    assert inspector.has_table("brand_voice_configurations")
    assert inspector.has_table("brand_voice_versions")
    with engine.connect() as connection:
        record = connection.exec_driver_sql(
            "SELECT id, name, description FROM brand_guidelines WHERE id=17"
        ).one()
    assert record == (17, "Existing standard", "Preserve the existing rule.")
    assert BrandVoiceConfiguration.__table__.name == "brand_voice_configurations"
    assert BrandVoiceVersion.__table__.name == "brand_voice_versions"
    engine.dispose()
