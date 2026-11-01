from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session
import pytest

from app.models.content_review import ContentReview, ReviewFinding
from app.models.review_comment import ReviewActivity, ReviewAssignment
from app.models.review_publish import ReviewPublication, ReviewPublishAuditEvent
from app.models.source_document import SourceDocument
from app.models.user import User
from app.services import auth_service
from app.services.risk_intelligence import (
    calculate_risk,
    evaluate_publish_readiness,
)


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


def _approved_review(client, content="A simple description for our customers."):
    review_id = client.post("/api/analyze", json={"content": content}).json()["id"]
    response = client.patch(
        f"/api/reviews/{review_id}/status",
        json={"status": "approved", "acknowledge_warnings": True},
    )
    assert response.status_code == 200
    return review_id


def test_risk_score_deduplicates_overlapping_findings_and_counts_evidence():
    findings = [
        {
            "id": 1,
            "category": "promotional_claim",
            "severity": "high",
            "matched_text": "guaranteed results",
            "claim_start": 4,
            "claim_end": 22,
            "evidence_status": "unsupported",
            "confidence": 0.9,
        },
        {
            "id": 2,
            "category": "factual_claim",
            "severity": "medium",
            "matched_text": "results",
            "claim_start": 15,
            "claim_end": 22,
            "evidence_status": "expired_evidence",
            "confidence": 0.7,
        },
        {
            "id": 3,
            "category": "visual_identity",
            "severity": "critical",
            "matched_text": "logo",
            "visual_data": {"detection_method": "hash"},
            "confidence": 0.8,
        },
    ]
    risk = calculate_risk(
        findings,
        [
            {"source_id": 9, "status": "expired"},
            {"source_id": 9, "status": "expired"},
        ],
    )

    assert risk["score"] > 0
    assert risk["is_heuristic_estimate"] is True
    assert risk["verified_fact_assessment"] is False
    assert len(risk["breakdown"]["finding_contributions"]) == 2
    assert len(risk["breakdown"]["deduplicated_overlaps"]) == 1
    assert len(risk["breakdown"]["evidence_freshness_contributions"]) == 1
    assert risk["breakdown"]["category_points"]["visual_findings"] == 5
    assert sum(risk["breakdown"]["category_points"].values()) == risk[
        "breakdown"
    ]["raw_score"]


def test_readiness_distinguishes_ready_warning_and_blocked_states():
    risk = calculate_risk([])
    ready = evaluate_publish_readiness(
        review_status="approved",
        risk=risk,
        findings=[],
        analysis_is_current=True,
        approvals_complete=True,
        approval_bypassed=False,
    )
    warning_risk = calculate_risk(
        [],
        [{"source_id": 1, "status": "review_overdue"}],
    )
    warning = evaluate_publish_readiness(
        review_status="approved",
        risk=warning_risk,
        findings=[],
        analysis_is_current=True,
        approvals_complete=True,
        approval_bypassed=False,
    )
    blocked = evaluate_publish_readiness(
        review_status="approved",
        risk=calculate_risk(
            [
                {
                    "id": 7,
                    "category": "promotional_claim",
                    "severity": "high",
                    "evidence_status": "unsupported",
                }
            ]
        ),
        findings=[
            {
                "id": 7,
                "category": "promotional_claim",
                "severity": "high",
                "evidence_status": "unsupported",
            }
        ],
        analysis_is_current=False,
        approvals_complete=False,
        approval_bypassed=False,
    )

    assert ready["state"] == "Ready"
    assert warning["state"] == "Ready with Warnings"
    assert blocked["state"] == "Blocked"
    assert {item["code"] for item in blocked["blockers"]} == {
        "analysis_stale",
        "approvals_incomplete",
        "unsupported_high_risk_claim",
    }


def test_risk_breakdown_includes_all_unverified_evidence_states():
    statuses = [
        "unsupported",
        "conflicting",
        "unverified",
        "expired_evidence",
    ]
    risk = calculate_risk(
        [
            {
                "id": index,
                "category": "promotional_claim",
                "severity": "high",
                "matched_text": f"claim {index}",
                "evidence_status": evidence_status,
            }
            for index, evidence_status in enumerate(statuses, start=1)
        ]
    )

    assert {
        finding["evidence_status"]
        for finding in risk["breakdown"]["finding_contributions"]
    } == set(statuses)
    assert risk["score"] > 0


def test_publish_is_admin_only_idempotent_and_history_is_audited(
    client, test_engine, monkeypatch
):
    review_id = _approved_review(client)
    _create_user(
        test_engine,
        monkeypatch,
        "publish-permission-reviewer@example.test",
        "reviewer",
        "Publish Permission Reviewer",
    )
    readiness = client.get(
        f"/api/reviews/{review_id}/publish-readiness"
    )
    assert readiness.status_code == 200
    assert readiness.json()["state"] == "Ready"

    _login(client, "publish-permission-reviewer@example.test")
    assert client.post(f"/api/reviews/{review_id}/publish").status_code == 403
    _login(client, "admin@example.test")
    first = client.post(f"/api/reviews/{review_id}/publish")
    second = client.post(f"/api/reviews/{review_id}/publish")
    assert first.status_code == 200
    assert first.json()["state"] == "Published"
    assert first.json()["idempotent"] is False
    assert second.status_code == 200
    assert second.json()["idempotent"] is True

    history = client.get(f"/api/reviews/{review_id}/publish-history")
    assert history.status_code == 200
    assert len(history.json()["publications"]) == 1
    assert {event["action"] for event in history.json()["events"]} == {
        "published",
        "publish_duplicate_request",
    }
    with Session(test_engine) as db:
        assert db.query(ReviewPublication).filter_by(review_id=review_id).count() == 1
        assert db.query(ReviewPublishAuditEvent).filter_by(review_id=review_id).count() == 2
        assert {
            entry.action
            for entry in db.query(ReviewActivity).filter_by(review_id=review_id)
        } >= {"published", "publish_duplicate_request"}


def test_concurrent_publish_requests_create_only_one_publication(client, test_engine):
    review_id = _approved_review(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _index: client.post(f"/api/reviews/{review_id}/publish"),
                range(2),
            )
        )
    assert [response.status_code for response in responses] == [200, 200]
    assert len({response.json()["publication"]["id"] for response in responses}) == 1
    with Session(test_engine) as db:
        assert db.query(ReviewPublication).filter_by(review_id=review_id).count() == 1


def test_publish_rejects_stale_revision_and_incomplete_approvals(
    client, test_engine, monkeypatch
):
    reviewer_id = _create_user(
        test_engine,
        monkeypatch,
        "publish-reviewer@example.test",
        "reviewer",
        "Publish Reviewer",
    )
    review_id = _approved_review(client)
    with Session(test_engine) as db:
        db.add(
            ReviewAssignment(
                review_id=review_id,
                reviewer_id=reviewer_id,
                stage_number=1,
            )
        )
        db.commit()
    readiness = client.get(
        f"/api/reviews/{review_id}/publish-readiness"
    ).json()
    assert "approvals_incomplete" in {
        blocker["code"] for blocker in readiness["blockers"]
    }
    assert client.post(f"/api/reviews/{review_id}/publish").status_code == 409
    assert client.post(
        f"/api/reviews/{review_id}/publish/override",
        json={"reason": "Try to bypass required review approval."},
    ).status_code == 409

    with Session(test_engine) as db:
        db.query(ReviewAssignment).filter_by(review_id=review_id).delete()
        db.commit()
    revision = client.post(
        f"/api/reviews/{review_id}/revisions",
        json={"content": "A materially revised description.", "title": "Changed"},
    )
    assert revision.status_code == 201
    stale = client.get(f"/api/reviews/{review_id}/publish-readiness").json()
    assert stale["state"] == "Blocked"
    assert stale["analysis"]["is_current"] is False
    assert "review_not_approved" in {
        blocker["code"] for blocker in stale["blockers"]
    }
    assert client.post(f"/api/reviews/{review_id}/publish").status_code == 409
    assert client.post(
        f"/api/reviews/{review_id}/publish/override",
        json={"reason": "Try to publish without current analysis."},
    ).status_code == 409


def test_override_requires_admin_justification_and_is_audited(
    client, test_engine, monkeypatch
):
    reviewer_id = _create_user(
        test_engine,
        monkeypatch,
        "override-reviewer@example.test",
        "reviewer",
        "Override Reviewer",
    )
    review_id = _approved_review(client)
    with Session(test_engine) as db:
        review = db.query(ContentReview).filter_by(id=review_id).one()
        db.add(
            ReviewFinding(
                review_id=review_id,
                category="promotional_claim",
                severity="critical",
                title="Unsubstantiated claim",
                explanation="Evidence is missing.",
                matched_text="guaranteed outcome",
                confidence=0.95,
                review_status="pending",
                metadata_json={"evidence_status": "unsupported"},
            )
        )
        db.commit()
    reviewer_login = _login(client, "override-reviewer@example.test")
    unauthorized = client.post(
        f"/api/reviews/{review_id}/publish/override",
        json={"reason": "A properly detailed exception."},
    )
    assert unauthorized.status_code == 403
    _login(client, "admin@example.test")
    short_reason = client.post(
        f"/api/reviews/{review_id}/publish/override",
        json={"reason": "short"},
    )
    assert short_reason.status_code == 422
    result = client.post(
        f"/api/reviews/{review_id}/publish/override",
        json={"reason": "Urgent launch approved by accountable Admin."},
    )
    assert result.status_code == 200
    assert result.json()["state"] == "Published"
    assert result.json()["overridden_blockers"][0]["code"] == "unresolved_critical_finding"
    history = client.get(f"/api/reviews/{review_id}/publish-history").json()
    override = next(event for event in history["events"] if event["action"] == "publish_override")
    assert override["actor"] == "Workspace Admin"
    assert override["details"]["reason"] == "Urgent launch approved by accountable Admin."
    assert override["details"]["overridden_blockers"]


@pytest.mark.parametrize(
    ("active", "valid_until", "expected_status"),
    [
        (
            True,
            datetime.now(timezone.utc).date() - timedelta(days=1),
            "expired",
        ),
        (False, None, "inactive"),
    ],
)
def test_current_source_validity_blocks_and_is_override_eligible(
    client, test_engine, active, valid_until, expected_status
):
    review_id = _approved_review(client)
    with Session(test_engine) as db:
        source = SourceDocument(
            name="Expired source",
            content="Supporting source text.",
            approval_status="approved",
            is_active=active,
            valid_until=valid_until,
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(source)
        db.flush()
        db.add(
            ReviewFinding(
                review_id=review_id,
                category="promotional_claim",
                severity="high",
                title="Claim supported by stale source",
                explanation="Historical evidence reference.",
                matched_text="long-lasting",
                confidence=0.8,
                review_status="pending",
                metadata_json={
                    "evidence_status": "supported",
                    "citations": [
                        {
                            "source_id": source.id,
                            "source_type": "approved_internal_source",
                            "name": source.name,
                        }
                    ],
                },
            )
        )
        db.commit()

    readiness = client.get(
        f"/api/reviews/{review_id}/publish-readiness"
    ).json()
    invalid_evidence = next(
        blocker
        for blocker in readiness["blockers"]
        if blocker["code"] == "cited_evidence_invalid"
    )
    assert invalid_evidence["freshness"] == expected_status
    assert readiness["can_override"] is True


def test_contributors_cannot_publish_or_view_another_users_readiness(
    client, test_engine, monkeypatch
):
    contributor_id = _create_user(
        test_engine,
        monkeypatch,
        "publish-contributor@example.test",
        "contributor",
        "Publish Contributor",
    )
    reviewer_id = _create_user(
        test_engine,
        monkeypatch,
        "assigned-publisher@example.test",
        "reviewer",
        "Assigned Reviewer",
    )
    unassigned_reviewer_id = _create_user(
        test_engine,
        monkeypatch,
        "unassigned-publisher@example.test",
        "reviewer",
        "Unassigned Reviewer",
    )
    review_id = _approved_review(client)
    client.put(
        f"/api/reviews/{review_id}/assignments",
        json={"reviewers": [{"reviewer_id": reviewer_id, "stage_number": 1}]},
    )
    _login(client, "unassigned-publisher@example.test")
    assert client.get(
        f"/api/reviews/{review_id}/publish-readiness"
    ).status_code == 200
    assert client.post(f"/api/reviews/{review_id}/publish").status_code == 403
    _login(client, "publish-contributor@example.test")
    assert client.get(
        f"/api/reviews/{review_id}/publish-readiness"
    ).status_code == 404
    assert client.post(f"/api/reviews/{review_id}/publish").status_code == 403
