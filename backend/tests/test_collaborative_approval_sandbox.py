from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.models.content_review import ReviewFinding
from app.models.review_comment import ReviewActivity, ReviewApprovalBypass
from app.models.user import User
from app.services import auth_service


def _create_user(test_engine, monkeypatch, email, role, name):
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
    return response.json()["user"]["id"]


def _assign_reviewers(client, review_id, reviewer_ids):
    return client.put(
        f"/api/reviews/{review_id}/assignments",
        json={
            "reviewers": [
                {"reviewer_id": reviewer_id, "stage_number": stage}
                for stage, reviewer_id in enumerate(reviewer_ids, start=1)
            ]
        },
    )


def test_staged_approval_requires_all_reviewers_and_prevents_duplicates(
    client, test_engine, monkeypatch
):
    reviewer_one_id = _create_user(
        test_engine, monkeypatch, "stage-one@example.test", "reviewer", "Stage One"
    )
    reviewer_two_id = _create_user(
        test_engine, monkeypatch, "stage-two@example.test", "reviewer", "Stage Two"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Approval stage test."}
    ).json()["id"]

    assigned = _assign_reviewers(client, review_id, [reviewer_one_id, reviewer_two_id])
    assert assigned.status_code == 200
    assert [entry["stage_number"] for entry in assigned.json()["assigned_reviewers"]] == [1, 2]
    queue_item = next(
        entry
        for entry in client.get("/api/reviews").json()["items"]
        if entry["id"] == review_id
    )
    assert len(queue_item["assigned_reviewers"]) == 2

    first_user_id = _login(client, "stage-one@example.test")
    first = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved"},
    )
    assert first.status_code == 201
    assert first.json()["status"] == "pending"
    assert first.json()["approval_stages"][0]["status"] == "completed"
    assert first.json()["approval_stages"][1]["status"] == "pending"

    duplicate = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved"},
    )
    assert duplicate.status_code == 409
    blocked_final_approval = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "approved"},
    )
    assert blocked_final_approval.status_code == 409

    _login(client, "stage-two@example.test")
    second = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved", "reason": "Second-stage approval."},
    )
    assert second.status_code == 201
    assert second.json()["status"] == "approved"
    detail = client.get(f"/api/reviews/{review_id}").json()
    assert detail["status"] == "approved"
    assert {decision["reviewer_id"] for decision in detail["approval_decisions"]} == {
        first_user_id,
        reviewer_two_id,
    }

    with Session(test_engine) as db:
        actions = {
            entry.action
            for entry in db.query(ReviewActivity)
            .filter_by(review_id=review_id)
            .all()
        }
    assert "reviewer_decision_recorded" in actions
    assert "review_approved" in actions

    _login(client, "admin@example.test")
    revision = client.post(
        f"/api/reviews/{review_id}/reanalyze",
        json={"content": "Approval stage test, updated.", "title": "New version"},
    )
    assert revision.status_code == 200
    assert revision.json()["status"] == "pending"
    assert len(revision.json()["approval_decisions"]) == 2
    assert revision.json()["approval_stages"][0]["approved"] == 0

    _login(client, "stage-one@example.test")
    assert client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved"},
    ).status_code == 201
    _login(client, "stage-two@example.test")
    revised_approval = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved"},
    )
    assert revised_approval.status_code == 201
    assert len(client.get(f"/api/reviews/{review_id}").json()["approval_decisions"]) == 4


def test_assignment_validates_active_reviewers_and_admin_permissions(
    client, test_engine, monkeypatch
):
    contributor_id = _create_user(
        test_engine, monkeypatch, "not-reviewer@example.test", "contributor", "Contributor"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Assignment permission test."}
    ).json()["id"]

    invalid_stage_order = client.put(
        f"/api/reviews/{review_id}/assignments",
        json={"reviewers": [{"reviewer_id": contributor_id, "stage_number": 2}]},
    )
    assert invalid_stage_order.status_code == 422
    invalid = _assign_reviewers(client, review_id, [contributor_id])
    assert invalid.status_code == 422
    assert client.put(
        f"/api/reviews/{review_id}/assignments",
        json={"reviewers": [{"reviewer_id": 999999, "stage_number": 1}]},
    ).status_code == 422

    _create_user(
        test_engine, monkeypatch, "assignment-reviewer@example.test", "reviewer", "Reviewer"
    )
    _login(client, "assignment-reviewer@example.test")
    forbidden = _assign_reviewers(client, review_id, [contributor_id])
    assert forbidden.status_code == 403


def test_bypass_is_admin_only_requires_justification_and_is_audited(
    client, test_engine, monkeypatch
):
    reviewer_id = _create_user(
        test_engine, monkeypatch, "bypass-reviewer@example.test", "reviewer", "Reviewer"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Bypass test."}
    ).json()["id"]
    assert _assign_reviewers(client, review_id, [reviewer_id]).status_code == 200

    warning_id = None
    with Session(test_engine) as db:
        finding = ReviewFinding(
            review_id=review_id,
            category="quality",
            severity="critical",
            title="Unresolved critical issue",
            explanation="Needs a human decision.",
            review_status="pending",
        )
        db.add(finding)
        db.commit()
        db.refresh(finding)
        warning_id = finding.id

    missing_reason = client.post(
        f"/api/reviews/{review_id}/approval-bypass",
        json={"reason": "short"},
    )
    assert missing_reason.status_code == 422
    unacknowledged = client.post(
        f"/api/reviews/{review_id}/approval-bypass",
        json={"reason": "Urgent launch with accountable owner."},
    )
    assert unacknowledged.status_code == 409

    _login(client, "bypass-reviewer@example.test")
    unauthorized = client.post(
        f"/api/reviews/{review_id}/approval-bypass",
        json={
            "reason": "Urgent launch with accountable owner.",
            "acknowledge_warnings": True,
        },
    )
    assert unauthorized.status_code == 403

    _login(client, "admin@example.test")
    bypassed = client.post(
        f"/api/reviews/{review_id}/approval-bypass",
        json={
            "reason": "Urgent launch with accountable owner.",
            "acknowledge_warnings": True,
        },
    )
    assert bypassed.status_code == 200
    assert bypassed.json()["status"] == "approved"
    assert bypassed.json()["approval_bypasses"][0]["acknowledged_warning_ids"] == [
        warning_id
    ]
    with Session(test_engine) as db:
        event = (
            db.query(ReviewActivity)
            .filter_by(review_id=review_id, action="approval_bypassed")
            .one()
        )
        assert event.actor == "Workspace Admin"
        assert event.details["reason"] == "Urgent launch with accountable owner."
        assert db.query(ReviewApprovalBypass).filter_by(review_id=review_id).count() == 1


def test_staged_decisions_require_reasons_and_warning_acknowledgement(
    client, test_engine, monkeypatch
):
    reviewer_id = _create_user(
        test_engine, monkeypatch, "decision-reviewer@example.test", "reviewer", "Reviewer"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Decision safeguards."}
    ).json()["id"]
    _assign_reviewers(client, review_id, [reviewer_id])
    with Session(test_engine) as db:
        finding = ReviewFinding(
            review_id=review_id,
            category="quality",
            severity="critical",
            title="Critical warning",
            explanation="Needs explicit acknowledgement.",
            review_status="pending",
        )
        db.add(finding)
        db.commit()
        db.refresh(finding)
        warning_id = finding.id

    _login(client, "decision-reviewer@example.test")
    missing_reason = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "rejected"},
    )
    assert missing_reason.status_code == 422
    missing_acknowledgement = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved"},
    )
    assert missing_acknowledgement.status_code == 409
    approved = client.post(
        f"/api/reviews/{review_id}/approval-decisions",
        json={"decision": "approved", "acknowledge_warnings": True},
    )
    assert approved.status_code == 201
    decision = client.get(f"/api/reviews/{review_id}").json()["approval_decisions"][0]
    assert decision["acknowledged_warning_ids"] == [warning_id]
    assert any(
        event["action"] == "approval_warnings_acknowledged"
        for event in client.get(f"/api/reviews/{review_id}/activity").json()
    )


def test_revision_versions_are_immutable_and_comparable(client):
    review_id = client.post(
        "/api/analyze", json={"content": "Original wording remains."}
    ).json()["id"]
    revision = client.post(
        f"/api/reviews/{review_id}/revisions",
        json={"content": "Updated wording remains.", "title": "Second version"},
    )
    assert revision.status_code == 201
    assert revision.json()["author"] == "Workspace Admin"

    comparison = client.get(
        f"/api/reviews/{review_id}/revisions/compare"
        f"?from_version_id=0&to_version_id={revision.json()['id']}"
    )
    assert comparison.status_code == 200
    segments = comparison.json()["segments"]
    assert any(segment["type"] == "removed" and "Original" in segment["text"] for segment in segments)
    assert any(segment["type"] == "added" and "Updated" in segment["text"] for segment in segments)
    assert client.get(
        f"/api/reviews/{review_id}/revisions/compare?from_version_id=0&to_version_id=999999"
    ).status_code == 404


def test_contributor_can_reanalyze_and_resubmit_a_requested_revision(
    client, test_engine, monkeypatch
):
    _create_user(
        test_engine, monkeypatch, "revision-owner@example.test", "contributor", "Submitter"
    )
    _login(client, "revision-owner@example.test")
    review_id = client.post(
        "/api/analyze", json={"content": "The original submitted wording."}
    ).json()["id"]

    _login(client, "admin@example.test")
    requested = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "changes_requested", "reason": "Clarify the claim."},
    )
    assert requested.status_code == 200

    _login(client, "revision-owner@example.test")
    revised = client.post(
        f"/api/reviews/{review_id}/reanalyze",
        json={"content": "The clarified resubmitted wording.", "title": "Clarified"},
    )
    assert revised.status_code == 200
    assert revised.json()["status"] == "changes_requested"
    submitted = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "submitted"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["versions"][0]["content"] == "The original submitted wording."


def test_websocket_is_review_scoped_and_broadcasts_public_comments(
    client, test_engine, monkeypatch
):
    reviewer_id = _create_user(
        test_engine, monkeypatch, "live-reviewer@example.test", "reviewer", "Live Reviewer"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Live collaboration test."}
    ).json()["id"]
    assert _assign_reviewers(client, review_id, [reviewer_id]).status_code == 200

    with TestClient(client.app) as reviewer_client:
        reviewer_client.headers.update({"Origin": "http://localhost:5173"})
        _login(reviewer_client, "live-reviewer@example.test")
        with client.websocket_connect(
            f"/api/reviews/{review_id}/collaboration",
            headers={"origin": "http://localhost:5173"},
        ) as admin_socket:
            assert admin_socket.receive_json()["payload"]["participants"][0]["display_name"] == "Workspace Admin"
            with reviewer_client.websocket_connect(
                f"/api/reviews/{review_id}/collaboration",
                headers={"origin": "http://localhost:5173"},
            ) as reviewer_socket:
                snapshot = reviewer_socket.receive_json()["payload"]["participants"]
                assert {person["display_name"] for person in snapshot} == {
                    "Workspace Admin",
                    "Live Reviewer",
                }
                assert admin_socket.receive_json()["type"] == "presence"
                client.post(
                    f"/api/reviews/{review_id}/comments",
                    json={"comment": "private internal deliberation", "is_internal": True},
                )
                public = client.post(
                    f"/api/reviews/{review_id}/comments",
                    json={"comment": "shared public comment"},
                )
                assert public.status_code == 201
                assert admin_socket.receive_json()["type"] == "review_updated"
                assert reviewer_socket.receive_json()["type"] == "review_updated"
                assert admin_socket.receive_json()["payload"]["comment"] == "shared public comment"
                assert reviewer_socket.receive_json()["payload"]["comment"] == "shared public comment"


def test_contributor_cannot_open_another_submitters_collaboration_socket(
    client, test_engine, monkeypatch
):
    _create_user(
        test_engine, monkeypatch, "unrelated-contributor@example.test", "contributor", "Contributor"
    )
    review_id = client.post(
        "/api/analyze", json={"content": "Private review socket."}
    ).json()["id"]
    client.post(
        f"/api/reviews/{review_id}/comments",
        json={"comment": "Review-owner-only discussion."},
    )
    with TestClient(client.app) as contributor_client:
        contributor_client.headers.update({"Origin": "http://localhost:5173"})
        _login(contributor_client, "unrelated-contributor@example.test")
        assert contributor_client.get(f"/api/reviews/{review_id}").status_code == 404
        assert (
            contributor_client.get(
                f"/api/reviews/{review_id}/activity"
            ).status_code
            == 404
        )
        try:
            with contributor_client.websocket_connect(
                f"/api/reviews/{review_id}/collaboration",
                headers={"origin": "http://localhost:5173"},
            ):
                raise AssertionError("Unauthorized contributor socket was accepted.")
        except WebSocketDisconnect as exc:
            assert exc.code == 4403
