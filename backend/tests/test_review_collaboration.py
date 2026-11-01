from sqlalchemy.orm import Session
from sqlalchemy import create_engine, inspect

from app.models.review_comment import ReviewActivity
from app.models.user import User
from app.database import migrate_review_workflow
from app.models.visual_asset import ReviewVisualAttachment


def _create_user(test_engine, monkeypatch, email, role, name):
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)
    with Session(test_engine) as db:
        user = User(
            email=email,
            display_name=name,
            password_hash=auth_service.hash_password("strong-test-password"),
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
        json={"email": email, "password": "strong-test-password"},
    )
    assert response.status_code == 200
    return response


def test_admin_assigns_only_active_reviewers_and_records_activity(
    client, test_engine, monkeypatch
):
    reviewer_id = _create_user(
        test_engine, monkeypatch, "assigned@example.test", "reviewer", "Assigned Reviewer"
    )
    contributor_id = _create_user(
        test_engine, monkeypatch, "contributor@example.test", "contributor", "Contributor"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Review assignment test."}
    ).json()["id"]

    assigned = client.patch(
        f"/api/reviews/{review_id}/assignment",
        json={"reviewer_id": reviewer_id},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_reviewer"]["display_name"] == "Assigned Reviewer"

    invalid = client.patch(
        f"/api/reviews/{review_id}/assignment",
        json={"reviewer_id": contributor_id},
    )
    assert invalid.status_code == 422

    assert client.get("/api/reviews/reviewers").status_code == 200
    with Session(test_engine) as db:
        event = (
            db.query(ReviewActivity)
            .filter_by(review_id=review_id, action="reviewer_assigned")
            .one()
        )
        assert event.details["reviewer_id"] == reviewer_id
        assert event.actor == "Workspace Admin"

    _login(client, "assigned@example.test")
    forbidden = client.patch(
        f"/api/reviews/{review_id}/assignment",
        json={"reviewer_id": None},
    )
    assert forbidden.status_code == 403


def test_internal_notes_are_hidden_from_contributors(client, test_engine, monkeypatch):
    _create_user(
        test_engine, monkeypatch, "private-note@example.test", "contributor", "Contributor"
    )
    _login(client, "private-note@example.test")
    review_id = client.post(
        "/api/analyze", json={"content": "Private note test."}
    ).json()["id"]
    admin_login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert admin_login.status_code == 200
    note = client.post(
        f"/api/reviews/{review_id}/comments",
        json={"comment": "Reviewer-only deliberation.", "is_internal": True},
    )
    assert note.status_code == 201
    assert note.json()["is_internal"] is True
    internal_reply = client.post(
        f"/api/reviews/{review_id}/comments",
        json={
            "comment": "Internal follow-up.",
            "is_internal": True,
            "parent_id": note.json()["id"],
        },
    )
    assert internal_reply.status_code == 201
    public_reply_attempt = client.post(
        f"/api/reviews/{review_id}/comments",
        json={
            "comment": "Attempted public reply.",
            "parent_id": note.json()["id"],
        },
    )
    assert public_reply_attempt.status_code == 422
    public_comment = client.post(
        f"/api/reviews/{review_id}/comments",
        json={"comment": "Contributor-visible feedback."},
    )
    assert public_comment.status_code == 201
    public_reply = client.post(
        f"/api/reviews/{review_id}/comments",
        json={
            "comment": "Public follow-up.",
            "parent_id": public_comment.json()["id"],
        },
    )
    assert public_reply.status_code == 201

    _login(client, "private-note@example.test")
    review = client.get(f"/api/reviews/{review_id}")
    assert review.status_code == 200
    assert [entry["comment"] for entry in review.json()["comments"]] == [
        "Contributor-visible feedback.",
        "Public follow-up.",
    ]
    activity = client.get(f"/api/reviews/{review_id}/activity")
    assert all(
        not entry["details"].get("is_internal")
        for entry in activity.json()
    )
    blocked_note = client.post(
        f"/api/reviews/{review_id}/comments",
        json={"comment": "Unauthorized note.", "is_internal": True},
    )
    assert blocked_note.status_code == 403
    client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    unrelated_review_id = client.post(
        "/api/analyze",
        json={"content": "A different submitter's private review."},
    ).json()["id"]
    _login(client, "private-note@example.test")
    assert client.get(f"/api/reviews/{unrelated_review_id}").status_code == 404
    assert client.get("/api/reviews").json()["total"] == 1
    assert client.post(
        f"/api/reviews/{unrelated_review_id}/comments",
        json={"comment": "Unauthorized cross-review comment."},
    ).status_code == 404


def test_review_private_resources_are_scoped_to_contributor_owner(
    client, test_engine, monkeypatch
):
    contributor_id = _create_user(
        test_engine,
        monkeypatch,
        "private-resource-contributor@example.test",
        "contributor",
        "Private Resource Contributor",
    )
    reviewer_id = _create_user(
        test_engine,
        monkeypatch,
        "private-resource-reviewer@example.test",
        "reviewer",
        "Private Resource Reviewer",
    )
    review_id = client.post(
        "/api/analyze",
        json={"content": "Owner-only review resource."},
    ).json()["id"]
    revision = client.post(
        f"/api/reviews/{review_id}/revisions",
        json={"content": "Owner-only revised content.", "title": "Private revision"},
    )
    assert revision.status_code == 201
    with Session(test_engine) as db:
        db.add(
            ReviewVisualAttachment(
                review_id=review_id,
                filename="private.png",
                media_type="image/png",
                file_data=b"private attachment bytes",
                analysis_metadata={},
            )
        )
        db.commit()

    assert client.get(f"/api/reviews/{review_id}/visual-attachment").status_code == 200
    assert client.get(
        f"/api/reviews/{review_id}/revisions/compare"
        f"?from_version_id=0&to_version_id={revision.json()['id']}"
    ).status_code == 200
    assert client.get(f"/api/reviews/{review_id}/publish-readiness").status_code == 200
    assert client.get(f"/api/reviews/{review_id}/publish-history").status_code == 200

    _login(client, "private-resource-reviewer@example.test")
    assert client.get(f"/api/reviews/{review_id}/visual-attachment").status_code == 200
    assert client.get(
        f"/api/reviews/{review_id}/revisions/compare"
        f"?from_version_id=0&to_version_id={revision.json()['id']}"
    ).status_code == 200
    assert client.get(f"/api/reviews/{review_id}/publish-readiness").status_code == 200
    assert client.get(f"/api/reviews/{review_id}/publish-history").status_code == 200

    _login(client, "private-resource-contributor@example.test")
    assert client.get(f"/api/reviews/{review_id}").status_code == 404
    assert client.get(f"/api/reviews/{review_id}/activity").status_code == 404
    assert client.get(
        f"/api/reviews/{review_id}/visual-attachment"
    ).status_code == 404
    assert client.get(
        f"/api/reviews/{review_id}/revisions/compare"
        f"?from_version_id=0&to_version_id={revision.json()['id']}"
    ).status_code == 404
    assert client.get(f"/api/reviews/{review_id}/publish-readiness").status_code == 404
    assert client.get(f"/api/reviews/{review_id}/publish-history").status_code == 404
    assert client.post(
        f"/api/reviews/{review_id}/comments",
        json={"comment": "Unauthorized cross-review comment."},
    ).status_code == 404
    assert client.post(
        f"/api/reviews/{review_id}/revisions",
        json={"content": "Unauthorized revision.", "title": "Not allowed"},
    ).status_code == 404
    assert contributor_id != reviewer_id


def test_status_transition_reasons_and_contributor_submission(
    client, test_engine, monkeypatch
):
    _create_user(
        test_engine, monkeypatch, "submitter@example.test", "contributor", "Submitter"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Lifecycle test."}
    ).json()["id"]

    missing_reason = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "rejected"},
    )
    assert missing_reason.status_code == 422
    rejected = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "rejected", "reason": "Out of scope."},
    )
    assert rejected.status_code == 200
    rejection_event = next(
        entry
        for entry in client.get(f"/api/reviews/{review_id}/activity").json()
        if entry["action"] == "review_rejected"
    )
    assert rejection_event["details"]["reason"] == "Out of scope."

    reopened = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "in_review"},
    )
    assert reopened.status_code == 409

    _login(client, "submitter@example.test")
    second_review_id = client.post(
        "/api/analyze", json={"content": "Contributor submission test."}
    ).json()["id"]
    draft_review_id = client.post(
        "/api/analyze", json={"content": "Contributor draft test."}
    ).json()["id"]
    client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    requested = client.patch(
        f"/api/reviews/{second_review_id}/status",
        json={"status": "changes_requested", "reason": "Add the missing source."},
    )
    assert requested.status_code == 200

    _login(client, "submitter@example.test")
    blocked_approval = client.patch(
        f"/api/reviews/{second_review_id}/status",
        json={"status": "approved"},
    )
    assert blocked_approval.status_code == 403
    submitted = client.patch(
        f"/api/reviews/{second_review_id}/status",
        json={"status": "submitted"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    saved_draft = client.patch(
        f"/api/reviews/{draft_review_id}/status",
        json={"status": "draft"},
    )
    assert saved_draft.status_code == 200
    resubmitted = client.patch(
        f"/api/reviews/{draft_review_id}/status",
        json={"status": "submitted"},
    )
    assert resubmitted.status_code == 200


def test_review_workflow_migration_is_additive_and_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE content_reviews (id INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE review_comments (id INTEGER PRIMARY KEY)"
        )

    migrate_review_workflow(engine)
    migrate_review_workflow(engine)
    inspector = inspect(engine)
    assert "assigned_reviewer_id" in {
        column["name"] for column in inspector.get_columns("content_reviews")
    }
    assert {"is_internal", "parent_id"} <= {
        column["name"] for column in inspector.get_columns("review_comments")
    }
    engine.dispose()
