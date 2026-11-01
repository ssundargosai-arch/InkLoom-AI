from io import BytesIO
import os
import shutil

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest
from sqlalchemy.orm import Session

from app.models.review_comment import ReviewActivity, ReviewAuditEvent


def _approve_source(client, source_id):
    response = client.patch(
        "/api/sources/{}/approval".format(source_id),
        json={"status": "approved"},
    )
    assert response.status_code == 200
    return response.json()


def test_health_docs_and_seeded_guidelines(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["evidence_retrieval_mode"] in {
        "embedding_cosine",
        "bm25_lexical",
    }
    assert client.get("/docs").status_code == 200

    guidelines = client.get("/api/guidelines")
    assert guidelines.status_code == 200
    assert any(item["is_seed"] for item in guidelines.json())


def test_authentication_uses_http_only_cookie_and_protects_workspace(client):
    client.cookies.clear()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/guidelines").status_code == 401

    login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "admin"
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert client.get("/api/guidelines").status_code == 200

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/guidelines").status_code == 401


def test_password_recovery_requires_configured_smtp(client, monkeypatch):
    from app.routes import auth

    monkeypatch.setattr(auth, "SMTP_ENABLED", False)
    response = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_password_recovery_response_is_generic_and_stores_only_token_hash(
    client, test_engine, monkeypatch
):
    import hashlib

    from app.models.user import PasswordResetToken, RecoveryAttempt
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda email, url: sent.append((email, url)),
    )

    known = client.post(
        "/api/auth/password/forgot",
        json={"email": " ADMIN@example.test "},
    )
    unknown = client.post(
        "/api/auth/password/forgot",
        json={"email": "missing@example.test"},
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert sent[0][0] == "admin@example.test"
    assert sent[0][1].startswith(
        "http://localhost:5173/reset-password#token="
    )
    assert sent[1] == ("missing@example.test", None)

    raw_token = sent[0][1].split("token=", 1)[1]
    with Session(test_engine) as db:
        record = db.query(PasswordResetToken).one()
        assert record.token_hash == hashlib.sha256(
            raw_token.encode()
        ).hexdigest()
        assert record.token_hash != raw_token
        assert record.used_at is None

        attempts = db.query(RecoveryAttempt).all()
        assert len(attempts) == 2

        email_fingerprints = {
            row.email_fingerprint for row in attempts
        }
        assert hashlib.sha256(
            b"inkloom-recovery-email:admin@example.test"
        ).hexdigest() in email_fingerprints
        assert hashlib.sha256(
            b"inkloom-recovery-email:missing@example.test"
        ).hexdigest() in email_fingerprints

        assert all(
            row.ip_fingerprint
            == hashlib.sha256(
                b"inkloom-recovery-ip:testclient"
            ).hexdigest()
            for row in attempts
        )


def test_password_reset_is_single_use_and_revokes_existing_sessions(
    client, test_engine, monkeypatch
):
    from urllib.parse import unquote

    from app.models.user import AuthSession, PasswordResetToken, User
    from app.routes import auth
    from app.services.auth_service import verify_password

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda _email, url: sent.append(url),
    )

    recovery = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert recovery.status_code == 202

    token = unquote(sent[0].split("token=", 1)[1])
    result = client.post(
        "/api/auth/password/reset",
        json={
            "token": token,
            "new_password": "a-new-strong-password-456",
        },
    )
    assert result.status_code == 200
    assert "set-cookie" in result.headers
    assert client.get("/api/auth/me").status_code == 401

    invalid = client.post(
        "/api/auth/password/reset",
        json={
            "token": "x" * 40,
            "new_password": "another-strong-password-789",
        },
    )
    assert invalid.status_code == 400

    assert client.post(
        "/api/auth/password/reset",
        json={
            "token": token,
            "new_password": "another-strong-password-789",
        },
    ).status_code == 400

    with Session(test_engine) as db:
        user = db.query(User).one()
        assert verify_password(
            "a-new-strong-password-456",
            user.password_hash,
        )
        assert (
            db.query(AuthSession)
            .filter(AuthSession.user_id == user.id)
            .count()
            == 0
        )
        record = db.query(PasswordResetToken).one()
        assert record.used_at is not None

    login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "a-new-strong-password-456",
        },
    )
    assert login.status_code == 200


def test_password_reset_rejects_expired_tokens(
    client, test_engine, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    from app.models.user import PasswordResetToken, User
    from app.routes import auth
    from app.services.auth_service import verify_password

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda _email, url: sent.append(url),
    )

    response = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert response.status_code == 202

    token = sent[0].split("token=", 1)[1]

    with Session(test_engine) as db:
        record = db.query(PasswordResetToken).one()
        record.expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        db.commit()

    expired = client.post(
        "/api/auth/password/reset",
        json={
            "token": token,
            "new_password": "a-new-strong-password-456",
        },
    )
    assert expired.status_code == 400

    with Session(test_engine) as db:
        user = db.query(User).one()
        assert verify_password(
            "test-admin-password-123",
            user.password_hash,
        )
        assert db.query(PasswordResetToken).one().used_at is None


def test_password_recovery_email_failure_does_not_leave_reset_token(
    client, test_engine, monkeypatch
):
    from app.models.user import PasswordResetToken
    from app.routes import auth
    from app.services.password_recovery import RecoveryEmailError

    def fail_sending(_email, _url):
        raise RecoveryEmailError("delivery failed")

    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(auth, "send_recovery_email", fail_sending)

    response = client.post(
        "/api/auth/password/forgot",
        json={"email": "admin@example.test"},
    )
    assert response.status_code == 503
    assert "delivery failed" not in response.text

    with Session(test_engine) as db:
        assert db.query(PasswordResetToken).count() == 0


def test_password_recovery_is_rate_limited(client, monkeypatch):
    from app.routes import auth
    from app.services import password_recovery

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_recovery_email",
        lambda email, url: sent.append((email, url)),
    )
    monkeypatch.setattr(
        password_recovery,
        "RECOVERY_EMAIL_LIMIT",
        2,
    )

    for _ in range(2):
        response = client.post(
            "/api/auth/password/forgot",
            json={"email": "unknown@example.test"},
        )
        assert response.status_code == 202

    blocked = client.post(
        "/api/auth/password/forgot",
        json={"email": "unknown@example.test"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert len(sent) == 2


def test_login_rejects_incorrect_password_without_creating_session(client):
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "incorrect-password",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Email or password is incorrect."
    )
    assert "set-cookie" not in response.headers


def test_login_throttles_repeated_failures_with_retry_after(
    client, test_engine, monkeypatch
):
    from app.services import auth_service
    from app.models.user import LoginAttempt

    monkeypatch.setattr(auth_service, "LOGIN_PAIR_LIMIT", 3)
    client.cookies.clear()

    payload = {
        "email": "admin@example.test",
        "password": "wrong-password",
    }

    for _ in range(3):
        response = client.post("/api/auth/login", json=payload)
        assert response.status_code == 401

    blocked = client.post("/api/auth/login", json=payload)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == (
        "Too many sign-in attempts. Try again later."
    )
    assert int(blocked.headers["retry-after"]) > 0
    assert "set-cookie" not in blocked.headers

    with Session(test_engine) as db:
        attempt = db.query(LoginAttempt).first()
        assert attempt is not None
        assert attempt.email_fingerprint != "admin@example.test"
        assert len(attempt.ip_fingerprint) == 64
        assert not hasattr(attempt, "password")


def test_successful_login_clears_email_failure_history(
    client, test_engine, monkeypatch
):
    from app.services import auth_service
    from app.models.user import LoginAttempt

    monkeypatch.setattr(auth_service, "LOGIN_PAIR_LIMIT", 3)
    client.cookies.clear()

    for _ in range(2):
        assert client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.test",
                "password": "wrong-password",
            },
        ).status_code == 401

    success = client.post(
        "/api/auth/login",
        json={
            "email": " admin@example.test ",
            "password": "test-admin-password-123",
        },
    )
    assert success.status_code == 200

    with Session(test_engine) as db:
        assert db.query(LoginAttempt).count() == 0

    client.cookies.clear()
    assert client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "wrong-password",
        },
    ).status_code == 401


def test_login_failure_window_expires(client, monkeypatch):
    from datetime import timedelta

    from app.services import auth_service

    start = auth_service._utc_now()
    current = [start]

    monkeypatch.setattr(
        auth_service,
        "_utc_now",
        lambda: current[0],
    )
    monkeypatch.setattr(
        auth_service,
        "LOGIN_RATE_WINDOW",
        timedelta(seconds=60),
    )
    monkeypatch.setattr(
        auth_service,
        "LOGIN_PAIR_LIMIT",
        1,
    )

    client.cookies.clear()
    payload = {
        "email": "admin@example.test",
        "password": "wrong-password",
    }

    assert client.post("/api/auth/login", json=payload).status_code == 401
    assert client.post("/api/auth/login", json=payload).status_code == 429

    current[0] = start + timedelta(seconds=61)
    assert client.post("/api/auth/login", json=payload).status_code == 401


def test_login_email_and_ip_limits_apply_across_pairs(
    test_engine, monkeypatch
):
    from datetime import timedelta

    from app.database import Base
    from app.models.user import LoginAttempt
    from app.services import auth_service

    Base.metadata.create_all(bind=test_engine)

    monkeypatch.setattr(
        auth_service,
        "LOGIN_RATE_WINDOW",
        timedelta(minutes=15),
    )
    monkeypatch.setattr(auth_service, "LOGIN_EMAIL_LIMIT", 2)
    monkeypatch.setattr(auth_service, "LOGIN_IP_LIMIT", 3)

    now = auth_service._utc_now()

    with Session(test_engine) as db:
        auth_service.record_login_failure(
            db, "person@example.test", "192.0.2.1", now
        )
        auth_service.record_login_failure(
            db, "person@example.test", "192.0.2.2", now
        )
        assert auth_service.login_retry_after(
            db,
            "person@example.test",
            "192.0.2.3",
            now,
        ) > 0

    with Session(test_engine) as db:
        db.query(LoginAttempt).delete()
        db.commit()

        auth_service.record_login_failure(
            db, "first@example.test", "192.0.2.9", now
        )
        auth_service.record_login_failure(
            db, "second@example.test", "192.0.2.9", now
        )
        auth_service.record_login_failure(
            db, "third@example.test", "192.0.2.9", now
        )

        assert auth_service.login_retry_after(
            db,
            "another@example.test",
            "192.0.2.9",
            now,
        ) > 0


def test_bootstrap_missing_configuration_does_not_create_admin(
    test_engine, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.models.user import User
    from app.services import auth_service

    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_EMAIL",
        "",
    )
    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_PASSWORD",
        "",
    )

    app = create_app(test_engine)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.test",
                "password": "not-configured",
            },
        )
        assert response.status_code == 401
        assert response.json()["detail"] == (
            "Email or password is incorrect."
        )

    with Session(test_engine) as db:
        assert db.query(User).count() == 0


def test_bootstrap_creates_initial_admin_when_database_is_empty(
    test_engine, monkeypatch
):
    from app.database import Base
    from app.models.user import User
    from app.services import auth_service

    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_EMAIL",
        "first-admin@example.test",
    )
    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_PASSWORD",
        "first-admin-password-123",
    )
    monkeypatch.setattr(
        auth_service,
        "PASSWORD_ITERATIONS",
        100_000,
    )

    Base.metadata.create_all(bind=test_engine)

    with Session(test_engine) as db:
        auth_service.bootstrap_admin(db)
        admin = db.query(User).one()

        assert admin.email == "first-admin@example.test"
        assert admin.role == "admin"
        assert auth_service.verify_password(
            "first-admin-password-123",
            admin.password_hash,
        )


def test_bootstrap_does_not_reset_an_existing_admin_account(
    test_engine, monkeypatch
):
    from app.database import Base
    from app.models.user import User
    from app.services import auth_service

    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_EMAIL",
        "admin@example.test",
    )
    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_PASSWORD",
        "new-bootstrap-password-123",
    )
    monkeypatch.setattr(
        auth_service,
        "PASSWORD_ITERATIONS",
        100_000,
    )

    Base.metadata.create_all(bind=test_engine)

    with Session(test_engine) as db:
        existing_hash = auth_service.hash_password(
            "existing-admin-password-123"
        )
        db.add(
            User(
                email="admin@example.test",
                display_name="Existing Admin",
                password_hash=existing_hash,
                role="admin",
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()

        auth_service.bootstrap_admin(db)
        admin = db.query(User).one()

        assert admin.password_hash == existing_hash
        assert auth_service.verify_password(
            "existing-admin-password-123",
            admin.password_hash,
        )
        assert not auth_service.verify_password(
            "new-bootstrap-password-123",
            admin.password_hash,
        )


def test_environment_loader_uses_explicit_file_without_overriding_shell(
    tmp_path, monkeypatch
):
    from app.config import load_environment

    env_file = tmp_path / ".env"
    env_file.write_text(
        "INKLOOM_TEST_FROM_FILE=file-value\n"
        "INKLOOM_TEST_FROM_SHELL=file-value\n",
        encoding="utf-8",
    )

    monkeypatch.delenv(
        "INKLOOM_TEST_FROM_FILE",
        raising=False,
    )
    monkeypatch.setenv(
        "INKLOOM_TEST_FROM_SHELL",
        "shell-value",
    )

    assert load_environment(env_file)
    assert os.environ["INKLOOM_TEST_FROM_FILE"] == "file-value"
    assert os.environ["INKLOOM_TEST_FROM_SHELL"] == "shell-value"


def test_invited_contributor_sets_password_and_cannot_create_guidelines(
    client, monkeypatch
):
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda _email, _name, link: sent.append(link),
    )

    invitation = client.post(
        "/api/auth/users",
        json={
            "email": "editor@example.test",
            "display_name": "Content Editor",
            "role": "contributor",
        },
    )

    assert invitation.status_code == 201
    body = invitation.json()
    assert body["user"]["must_change_password"]
    assert not body["user"]["is_active"]

    invite_token = sent[0].split("token=", 1)[1]

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite_token,
            "new_password": "a-strong-editor-password",
        },
    )
    assert accepted.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={
            "email": "editor@example.test",
            "password": "a-strong-editor-password",
        },
    )
    assert login.status_code == 200
    assert not login.json()["user"]["must_change_password"]
    assert client.get("/api/guidelines").status_code == 200

    assert client.post(
        "/api/guidelines",
        json={
            "name": "Unauthorized rule",
            "category": "tone",
            "description": "Should not be created by contributor.",
        },
    ).status_code == 403


def test_reviewer_can_decide_but_cannot_manage_users(
    client, monkeypatch
):
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda _email, _name, link: sent.append(link),
    )

    invitation = client.post(
        "/api/auth/users",
        json={
            "email": "reviewer@example.test",
            "display_name": "Brand Reviewer",
            "role": "reviewer",
        },
    ).json()

    invite_token = sent[0].split("token=", 1)[1]

    review_id = client.post(
        "/api/analyze",
        json={"content": "A product draft."},
    ).json()["id"]

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite_token,
            "new_password": "a-strong-reviewer-password",
        },
    )
    assert accepted.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={
            "email": "reviewer@example.test",
            "password": "a-strong-reviewer-password",
        },
    )
    assert login.status_code == 200

    updated = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={
            "status": "approved",
            "reviewer": "Spoofed Name",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["reviewer"] == "Brand Reviewer"
    assert client.get("/api/auth/users").status_code == 403


def test_admin_cannot_remove_the_last_active_admin(client):
    admin = client.get("/api/auth/me").json()

    response = client.patch(
        "/api/auth/users/{}".format(admin["id"]),
        json={
            "role": "reviewer",
            "is_active": False,
        },
    )
    assert response.status_code == 422


def test_session_mutations_reject_untrusted_origins(client):
    response = client.post(
        "/api/analyze",
        headers={"origin": "https://untrusted.example"},
        json={"content": "An attempted cross-origin submission."},
    )
    assert response.status_code == 403
    assert client.get("/api/reviews").json()["total"] == 0


def test_deactivating_an_account_revokes_its_active_session(
    client, monkeypatch
):
    from app.routes import auth

    sent = []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda _email, _name, link: sent.append(link),
    )

    invitation = client.post(
        "/api/auth/users",
        json={
            "email": "disabled@example.test",
            "display_name": "Disabled Member",
            "role": "contributor",
        },
    ).json()

    invite_token = sent[0].split("token=", 1)[1]

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite_token,
            "new_password": "a-strong-member-password",
        },
    )
    assert accepted.status_code == 200

    invited_login = client.post(
        "/api/auth/login",
        json={
            "email": "disabled@example.test",
            "password": "a-strong-member-password",
        },
    )
    assert invited_login.status_code == 200

    revoked_cookie = client.cookies.get("inkloom_session")
    client.post("/api/auth/logout")

    admin_login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert admin_login.status_code == 200

    member = invitation["user"]

    deactivated = client.patch(
        "/api/auth/users/{}".format(member["id"]),
        json={
            "role": "contributor",
            "is_active": False,
        },
    )
    assert deactivated.status_code == 200

    client.cookies.clear()

    assert client.get(
        "/api/auth/me",
        headers={
            "cookie": "inkloom_session={}".format(revoked_cookie)
        },
    ).status_code == 401


def test_create_guideline_and_analyze_compatible_content(client):
    created = client.post(
        "/api/guidelines",
        json={
            "name": "Preferred product language",
            "category": "terminology",
            "description": "Use approved product wording.",
            "severity": "medium",
            "prohibited_terms": ["world class"],
            "preferred_terms": ["excellent"],
            "approved_sources": [],
        },
    )

    assert created.status_code == 201
    guideline_id = created.json()["id"]

    response = client.post(
        "/api/analyze",
        json={
            "content": (
                "Our world class product guarantees 100% success "
                "for every customer. Click here."
            ),
            "content_type": "text",
            "title": "Launch message",
            "guideline_ids": [guideline_id],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == body["review_id"]
    assert body["overall_status"] == "needs_review"
    assert body["summary"]["total_issues"] >= 3

    categories = {
        finding["category"] for finding in body["findings"]
    }
    assert {
        "terminology",
        "unsupported_claim",
        "accessibility",
    } <= categories

    assert any(
        "excellent" in (finding["suggestion"] or "")
        for finding in body["findings"]
    )
    assert body["findings"][0]["review_status"] == "pending"

    detail = client.get(
        "/api/reviews/{}".format(body["id"])
    )
    assert detail.status_code == 200
    assert detail.json()["content_type"] == "text"
    assert detail.json()["issue_count"] == body["total_issues"]


def test_invalid_content_and_unknown_guideline_are_reported(client):
    blank = client.post(
        "/api/analyze",
        json={"content": "  "},
    )
    assert blank.status_code == 422

    unknown = client.post(
        "/api/analyze",
        json={
            "content": "A valid draft",
            "guideline_ids": [999999],
        },
    )
    assert unknown.status_code == 422


def test_review_workflow_comments_revisions_and_pagination(
    client, test_engine
):
    analysis = client.post(
        "/api/analyze",
        json={
            "content": "A simple product description.",
            "title": "Product copy",
        },
    )
    review_id = analysis.json()["id"]

    changed = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={
            "status": "in_review",
            "reviewer": "Reviewer One",
        },
    )

    assert changed.status_code == 200
    assert changed.json()["status"] == "in_review"
    assert changed.json()["reviewer"] == "Workspace Admin"

    with Session(test_engine) as db:
        event = (
            db.query(ReviewAuditEvent)
            .filter_by(review_id=review_id)
            .one()
        )
        assert event.previous_status == "pending"
        assert event.new_status == "in_review"
        assert event.reviewer == "Workspace Admin"

    invalid_status = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "published"},
    )
    assert invalid_status.status_code == 422

    comment = client.post(
        "/api/reviews/{}/comments".format(review_id),
        json={
            "comment": "Please verify the source.",
            "author": "Reviewer One",
        },
    )
    assert comment.status_code == 201
    assert comment.json()["comment"] == "Please verify the source."
    assert comment.json()["author"] == "Workspace Admin"

    revision = client.post(
        "/api/reviews/{}/revisions".format(review_id),
        json={
            "content": "Revised product description.",
            "title": "Revision 1",
        },
    )
    assert revision.status_code == 201
    assert revision.json()["content"] == "Revised product description."

    detail = client.get(
        "/api/reviews/{}".format(review_id)
    ).json()

    assert len(detail["comments"]) == 1
    assert len(detail["revisions"]) == 1

    listing = client.get("/api/reviews?offset=0&limit=1")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert len(listing.json()["items"]) == 1


def test_revision_reanalysis_preserves_prior_findings_and_resets_approval(
    client
):
    guideline = client.post(
        "/api/guidelines",
        json={
            "name": "Avoid boastful language",
            "category": "terminology",
            "description": "Use measured language.",
            "severity": "medium",
            "prohibited_terms": ["world class"],
            "preferred_terms": ["well-made"],
        },
    )

    assert guideline.status_code == 201

    initial = client.post(
        "/api/analyze",
        json={
            "content": (
                "Our world class service guarantees 100% success."
            ),
            "guideline_ids": [guideline.json()["id"]],
        },
    )

    assert initial.status_code == 200
    review_id = initial.json()["id"]

    before = client.get(
        "/api/reviews/{}".format(review_id)
    ).json()

    assert len(before["analysis_runs"]) == 1
    assert any(
        item["category"] == "unsupported_claim"
        for item in before["findings"]
    )

    approved = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={
            "status": "approved",
            "acknowledge_warnings": True,
        },
    )
    assert approved.status_code == 200

    revised_text = (
        "Our thoughtful service supports your everyday work."
    )

    revised = client.post(
        "/api/reviews/{}/reanalyze".format(review_id),
        json={
            "content": revised_text,
            "title": "Removed unsupported claim",
        },
    )

    assert revised.status_code == 200
    body = revised.json()

    assert body["content"] == revised_text
    assert body["status"] == "pending"
    assert len(body["revisions"]) == 1
    assert len(body["analysis_runs"]) == 2
    assert body["analysis_runs"][0]["findings"]
    assert body["analysis_runs"][0]["content"] == before["content"]
    assert body["analysis_runs"][1]["content"] == revised_text
    assert body["analysis_runs"][1]["analysis_engine"] == "rules"
    assert body["findings"] == []

    unchanged = client.post(
        "/api/reviews/{}/reanalyze".format(review_id),
        json={"content": revised_text},
    )
    assert unchanged.status_code == 422


def test_revision_reanalysis_enforces_content_byte_limit(
    client, monkeypatch
):
    from app.routes import reviews

    review_id = client.post(
        "/api/analyze",
        json={"content": "A simple draft."},
    ).json()["id"]

    monkeypatch.setattr(
        reviews,
        "MAX_CONTENT_LENGTH",
        3,
    )

    response = client.post(
        "/api/reviews/{}/reanalyze".format(review_id),
        json={"content": "four"},
    )
    assert response.status_code == 413


def test_image_upload_is_validated_and_explains_visual_limits(client):
    buffer = BytesIO()
    Image.new("RGB", (12, 10), color="white").save(
        buffer,
        format="PNG",
    )

    response = client.post(
        "/api/analyze",
        data={
            "content": "Campaign image description",
            "content_type": "Campaign",
        },
        files={
            "file": (
                "asset.png",
                buffer.getvalue(),
                "image/png",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["image_analysis"]["format"] == "png"
    assert (
        body["image_analysis"]["layout_metrics"]["orientation"]
        == "landscape"
    )
    assert (
        "edge_density_percent"
        in body["image_analysis"]["layout_metrics"]
    )
    assert any(
        "logo safe-zone compliance" in limitation
        for limitation in body["image_analysis"]["limitations"]
    )
    assert any(
        item["title"] == "Image alternative text not provided"
        for item in body["findings"]
    )

    invalid = client.post(
        "/api/analyze",
        data={"content": "A valid draft"},
        files={
            "file": (
                "asset.png",
                b"not an image",
                "image/png",
            )
        },
    )
    assert invalid.status_code == 422


def test_image_upload_size_limit_is_enforced(client, monkeypatch):
    from app.routes import analysis

    monkeypatch.setattr(
        analysis,
        "MAX_UPLOAD_SIZE",
        3,
    )

    response = client.post(
        "/api/analyze",
        data={"content": "A valid draft"},
        files={
            "file": (
                "asset.png",
                b"four",
                "image/png",
            )
        },
    )
    assert response.status_code == 413


def test_configured_palette_comparison_creates_advisory_finding(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(
        image_analyzer,
        "BRAND_PALETTE",
        ["#000000"],
    )
    monkeypatch.setattr(
        image_analyzer,
        "PALETTE_TOLERANCE",
        0,
    )

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(
        buffer,
        format="PNG",
    )

    response = client.post(
        "/api/analyze",
        data={"content": "A campaign image"},
        files={
            "file": (
                "asset.png",
                buffer.getvalue(),
                "image/png",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["image_analysis"][
        "palette_comparison"
    ]["potential_mismatch"]
    assert any(
        item["category"] == "visual_brand"
        for item in response.json()["findings"]
    )


def test_visual_asset_reference_similarity_is_advisory(
    client, monkeypatch, tmp_path
):
    from app.services import image_analyzer

    reference_path = tmp_path / "approved-logo.png"

    reference = Image.new("RGB", (64, 64), "black")
    draw = ImageDraw.Draw(reference)
    draw.rectangle(
        (32, 0, 63, 63),
        fill="white",
    )
    reference.save(reference_path, format="PNG")

    monkeypatch.setattr(
        image_analyzer,
        "BRAND_ASSET_REFERENCES",
        [str(reference_path)],
    )
    monkeypatch.setattr(
        image_analyzer,
        "BRAND_ASSET_SIMILARITY_THRESHOLD",
        95,
    )

    different = Image.new("RGB", (64, 64), "black")
    draw = ImageDraw.Draw(different)
    draw.rectangle(
        (0, 32, 63, 63),
        fill="white",
    )

    buffer = BytesIO()
    different.save(buffer, format="PNG")

    response = client.post(
        "/api/analyze",
        data={"content": "A campaign image"},
        files={
            "file": (
                "campaign.png",
                buffer.getvalue(),
                "image/png",
            )
        },
    )

    assert response.status_code == 200

    analysis = response.json()["image_analysis"]
    assert analysis["brand_asset_similarity"]["configured"]
    assert analysis["brand_asset_similarity"]["potential_mismatch"]

    assert any(
        finding["title"]
        == "Image differs from configured brand asset references"
        for finding in response.json()["findings"]
    )


def test_unreadable_configured_asset_reference_is_reported(
    client, monkeypatch, tmp_path
):
    from app.services import image_analyzer

    monkeypatch.setattr(
        image_analyzer,
        "BRAND_ASSET_REFERENCES",
        [str(tmp_path / "missing-reference.png")],
    )

    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(
        buffer,
        format="PNG",
    )

    response = client.post(
        "/api/analyze",
        data={"content": "A campaign image"},
        files={
            "file": (
                "campaign.png",
                buffer.getvalue(),
                "image/png",
            )
        },
    )

    assert response.status_code == 503
    assert (
        "configured brand asset reference"
        in response.json()["detail"]
    )


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract runtime is optional",
)
def test_optional_tesseract_ocr_extracts_image_copy():
    from app.services.image_analyzer import inspect_image

    image = Image.new("RGB", (900, 140), "white")

    ImageDraw.Draw(image).text(
        (25, 40),
        "guarantees 100% success",
        font=ImageFont.load_default(size=48),
        fill="black",
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    result = inspect_image(
        buffer.getvalue(),
        ocr_enabled=True,
    )

    assert result["ocr_available"]
    assert "guarantees 100% success" in (
        result["extracted_text"].lower()
    )


def test_analytics_are_based_on_persisted_review_data(client):
    client.post(
        "/api/analyze",
        json={
            "content": "Our product guarantees results.",
            "title": "Claim review",
        },
    )

    summary = client.get("/api/analytics/summary")
    assert summary.status_code == 200

    body = summary.json()
    assert body["total_reviews"] == 1
    assert body["total_issues"] >= 1
    assert body["pending_approvals"] == 1
    assert body["issues_by_severity"]["high"] >= 1
    assert body["average_review_time_hours"] is None
    assert body["completed_reviews_with_duration"] == 0
    assert body["claim_verification_statuses"]

    assert any(
        row["status"] == "pending"
        for row in body["status_distribution"]
    )

    blind_spots = client.get(
        "/api/analytics/guideline-blind-spots"
    )
    assert blind_spots.status_code == 200
    assert (
        blind_spots.json()[0]["guideline"]
        == "Substantiated promotional claims"
    )
    assert (
        "does not prove guideline ambiguity"
        in blind_spots.json()[0]["heuristic"]
    )


def test_analytics_date_range_filters_reviews_and_rejects_reversed_range(client):
    from datetime import datetime, timedelta, timezone

    client.post(
        "/api/analyze",
        json={"content": "Our service guarantees great results."},
    )
    current_utc_date = datetime.now(timezone.utc).date()
    today = current_utc_date.isoformat()
    tomorrow = (current_utc_date + timedelta(days=1)).isoformat()

    current = client.get(
        "/api/analytics/summary",
        params={"start_date": today, "end_date": today},
    )
    assert current.status_code == 200
    assert current.json()["total_reviews"] == 1
    assert current.json()["date_range"] == {
        "start_date": today,
        "end_date": today,
    }

    future = client.get(
        "/api/analytics/summary",
        params={"start_date": tomorrow, "end_date": tomorrow},
    )
    assert future.status_code == 200
    assert future.json()["total_reviews"] == 0
    assert future.json()["total_issues"] == 0

    reversed_range = client.get(
        "/api/analytics/summary",
        params={"start_date": tomorrow, "end_date": today},
    )
    assert reversed_range.status_code == 422


def test_analytics_includes_real_reviewer_decisions_and_review_time(client):
    from datetime import datetime, timezone

    analysis = client.post(
        "/api/analyze",
        json={"content": "A neutral content draft."},
    )
    review_id = analysis.json()["id"]
    approved = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "approved"},
    )
    assert approved.status_code == 200

    summary = client.get(
        "/api/analytics/summary",
        params={
            "start_date": datetime.now(timezone.utc).date().isoformat(),
            "end_date": datetime.now(timezone.utc).date().isoformat(),
        },
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["average_review_time_hours"] is not None
    assert body["completed_reviews_with_duration"] == 1
    assert body["reviewer_activity"]
    assert body["reviewer_activity"][0]["decisions"] == 1


def test_guideline_delete_and_missing_resources(client):
    response = client.post(
        "/api/guidelines",
        json={
            "name": "Temporary rule",
            "category": "tone",
            "description": "A test guideline.",
        },
    )

    guideline_id = response.json()["id"]

    assert client.delete(
        "/api/guidelines/{}".format(guideline_id)
    ).status_code == 204

    inactive_guideline = next(
        item
        for item in client.get("/api/guidelines?active=false").json()
        if item["id"] == guideline_id
    )
    assert inactive_guideline["is_active"] is False
    assert len(client.get(
        "/api/guidelines/{}/versions".format(guideline_id)
    ).json()) >= 2

    assert client.delete(
        "/api/guidelines/{}".format(guideline_id)
    ).status_code == 404

    assert client.get("/api/reviews/12345").status_code == 404


def test_approved_sources_retrieval_and_expiry_metadata(client):
    guideline = next(
        item
        for item in client.get("/api/guidelines").json()
        if item["category"] == "factual_claim"
    )

    source = client.post(
        "/api/sources",
        json={
            "name": "Product metrics, Q4",
            "content": (
                "The annual subscription price is $240. "
                "This source confirms current pricing."
            ),
            "guideline_id": guideline["id"],
            "source_date": "2026-10-01",
            "expiry_date": "2027-01-01",
        },
    )

    assert source.status_code == 201
    source_id = source.json()["id"]
    assert source.json()["approval_status"] == "pending"

    _approve_source(client, source_id)

    response = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source_id],
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert (
        body["factual_verification"]
        == "claim_level_verification_advisory"
    )

    # Retrieved evidence identity and provenance.
    retrieved = body["retrieved_evidence"][0]

    assert retrieved["name"] == "Product metrics, Q4"
    assert (
        retrieved["verification"]
        == "candidate_evidence_requires_human_review"
    )
    assert retrieved["source_id"] == source_id
    assert retrieved["source_type"] == "approved_internal_source"
    assert retrieved["approval_status"] == "approved"
    assert retrieved["guideline_id"] == guideline["id"]

    # Finding verification.
    factual = next(
        item
        for item in body["findings"]
        if item["category"] == "factual_claim"
    )

    # Retrieval is only candidate evidence. The separate
    # claim-level verifier establishes whether the claim is supported.
    assert (
        "Retrieved source candidates were found"
        in factual["explanation"]
        or "approved evidence sources are configured"
        in factual["explanation"].lower()
        or "approved source" in factual["explanation"].lower()
    )

    assert factual["verification_status"] == "verified"
    assert factual["claim"] == "The annual subscription price is $240"

    # Citation provenance.
    citation = factual["citations"][0]

    assert citation["name"] == "Product metrics, Q4"
    assert citation["source_id"] == source_id
    assert citation["source_type"] == "approved_internal_source"
    assert citation["approval_status"] == "approved"
    assert citation["guideline_id"] == guideline["id"]
    assert citation["url"] == source.json()["url"]
    assert citation["excerpt"]

    assert factual["confidence"] == 0.62
    assert factual["verification_confidence"] == 0.9
    assert factual["evidence_status"] == "supported"
    assert factual["evidence_strength"] == 0.9
    assert factual["claim_start"] == 0
    assert factual["claim_end"] == len(
        "The annual subscription price is $240"
    )

    # Verify provenance survives database persistence.
    persisted = client.get(
        "/api/reviews/{}".format(body["review_id"])
    ).json()

    persisted_factual = next(
        item
        for item in persisted["findings"]
        if item["category"] == "factual_claim"
    )

    assert persisted_factual["verification_status"] == "verified"
    assert persisted_factual["evidence_status"] == "supported"
    assert persisted_factual["evidence_strength"] == 0.9
    assert persisted_factual["citations"][0]["source_id"] == source_id
    assert (
        persisted_factual["citations"][0]["approval_status"]
        == "approved"
    )

    # Unknown source IDs must be rejected.
    unknown = client.post(
        "/api/analyze",
        json={
            "content": "Price is $240",
            "source_ids": [99999],
        },
    )

    assert unknown.status_code == 422

    # Existing source deletion behavior.
    assert client.delete(
        "/api/sources/{}".format(source_id)
    ).status_code == 204

    # Unsafe URLs must be rejected.
    unsafe_url = client.post(
        "/api/sources",
        json={
            "name": "Unsafe link",
            "content": "Trusted copy",
            "url": "javascript:alert(1)",
        },
    )

    assert unsafe_url.status_code == 422


def test_evidence_requires_review_and_records_reviewer_decisions(
    client, test_engine
):
    source = client.post(
        "/api/sources",
        json={
            "name": "Product evidence",
            "content": "The annual subscription price is $240.",
        },
    )

    assert source.status_code == 201
    source_id = source.json()["id"]
    assert source.json()["approval_status"] == "pending"

    blocked = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source_id],
        },
    )

    assert blocked.status_code == 422
    assert "unapproved source" in blocked.json()["detail"]

    from app.models.user import User
    from app.services.auth_service import hash_password

    with Session(test_engine) as db:
        db.add(
            User(
                email="evidence-reviewer@example.test",
                display_name="Evidence Reviewer",
                password_hash=hash_password("reviewer-password-123"),
                role="reviewer",
                is_active=True,
            )
        )
        db.add(
            User(
                email="evidence-contributor@example.test",
                display_name="Evidence Contributor",
                password_hash=hash_password("contributor-password-123"),
                role="contributor",
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()

    login = client.post(
        "/api/auth/login",
        json={
            "email": "evidence-reviewer@example.test",
            "password": "reviewer-password-123",
        },
    )
    assert login.status_code == 200

    rejected = client.patch(
        "/api/sources/{}/approval".format(source_id),
        json={
            "status": "rejected",
            "note": "The source scope is unclear.",
        },
    )

    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == "rejected"
    assert rejected.json()["reviewed_by"] == "Evidence Reviewer"
    assert rejected.json()["review_note"] == (
        "The source scope is unclear."
    )

    rejected_source = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source_id],
        },
    )
    assert rejected_source.status_code == 422

    approved = client.patch(
        "/api/sources/{}/approval".format(source_id),
        json={"status": "approved"},
    )

    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"
    assert len(approved.json()["approval_history"]) == 2
    assert [
        event["status"]
        for event in approved.json()["approval_history"]
    ] == ["rejected", "approved"]

    client.post("/api/auth/logout")

    contributor_login = client.post(
        "/api/auth/login",
        json={
            "email": "evidence-contributor@example.test",
            "password": "contributor-password-123",
        },
    )
    assert contributor_login.status_code == 200

    unauthorized_decision = client.patch(
        "/api/sources/{}/approval".format(source_id),
        json={"status": "rejected"},
    )
    assert unauthorized_decision.status_code == 403

    analysis = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source_id],
        },
    )

    assert analysis.status_code == 200
    assert (
        analysis.json()["retrieved_evidence"][0]["name"]
        == "Product evidence"
    )


def test_legacy_sources_migrate_as_pending_and_are_not_trusted(
    test_engine, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services import auth_service

    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_EMAIL",
        "admin@example.test",
    )
    monkeypatch.setattr(
        auth_service,
        "BOOTSTRAP_ADMIN_PASSWORD",
        "test-admin-password-123",
    )

    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE source_documents ("
            "id INTEGER PRIMARY KEY, "
            "name VARCHAR(160) NOT NULL, "
            "content TEXT NOT NULL, "
            "guideline_id INTEGER, "
            "url VARCHAR(2048), "
            "source_date DATE, "
            "expiry_date DATE, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )

        connection.exec_driver_sql(
            "INSERT INTO source_documents (id, name, content) "
            "VALUES (1, 'Legacy source', "
            "'The annual subscription price is $240.')"
        )

    app = create_app(test_engine)

    with TestClient(app) as legacy_client:
        login = legacy_client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.test",
                "password": "test-admin-password-123",
            },
        )
        assert login.status_code == 200

        sources = legacy_client.get("/api/sources")
        assert sources.status_code == 200
        assert sources.json()[0]["approval_status"] == "pending"

        blocked = legacy_client.post(
            "/api/analyze",
            json={
                "content": "The annual subscription price is $240.",
                "source_ids": [1],
            },
        )
        assert blocked.status_code == 422




def test_approval_requires_acknowledgement_of_contradictory_evidence(client):
    source = client.post(
        "/api/sources",
        json={
            "name": "Current subscription price",
            "content": "The annual subscription price is $240.",
        },
    )
    assert source.status_code == 201

    _approve_source(client, source.json()["id"])

    analysis = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $300.",
            "source_ids": [source.json()["id"]],
        },
    )
    assert analysis.status_code == 200

    review_id = analysis.json()["id"]

    # Approval without acknowledgement must be blocked.
    blocked = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "approved"},
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["warnings"]

    # Explicit acknowledgement must allow approval.
    acknowledged = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={
            "status": "approved",
            "acknowledge_conflicts": True,
        },
    )

    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "approved"

    activity = client.get(
        "/api/reviews/{}/activity".format(review_id)
    )
    assert activity.status_code == 200
    acknowledgement = next(
        entry
        for entry in activity.json()
        if entry["action"] == "approval_warnings_acknowledged"
    )
    assert acknowledgement["actor"]
    assert acknowledgement["details"]["finding_ids"]


def test_approval_requires_acknowledgement_of_unresolved_critical_findings(
    client, test_engine
):
    from sqlalchemy import text

    analysis = client.post(
        "/api/analyze",
        json={"content": "This content is ready for review."},
    )
    assert analysis.status_code == 200
    review_id = analysis.json()["id"]

    with test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO review_findings "
                "(review_id, category, severity, title, explanation, "
                "matched_text, suggestion, source, confidence, review_status, metadata) "
                "VALUES (:review_id, 'tone', 'critical', 'Critical issue', "
                "'Resolve this before publishing.', 'ready for review', NULL, "
                "NULL, 0.99, 'pending', '{}')"
            ),
            {"review_id": review_id},
        )

    blocked = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "approved"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["warnings"][0]["severity"] == "critical"

    acknowledged = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={
            "status": "approved",
            "acknowledge_warnings": True,
        },
    )
    assert acknowledged.status_code == 200


def test_resolved_critical_finding_does_not_block_approval(client, test_engine):
    from sqlalchemy import text

    analysis = client.post(
        "/api/analyze",
        json={"content": "This content is ready for review."},
    )
    assert analysis.status_code == 200
    review_id = analysis.json()["id"]

    with test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO review_findings "
                "(review_id, category, severity, title, explanation, "
                "matched_text, suggestion, source, confidence, review_status, metadata) "
                "VALUES (:review_id, 'tone', 'critical', 'Resolved issue', "
                "'This issue has been resolved.', 'ready for review', NULL, "
                "NULL, 0.99, 'resolved', '{}')"
            ),
            {"review_id": review_id},
        )

    approved = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_factual_claim_without_evidence_remains_unverified(client):
    response = client.post(
        "/api/analyze",
        json={
            "content": "Our annual subscription price is $300."
        },
    )

    assert response.status_code == 200

    finding = next(
        item
        for item in response.json()["findings"]
        if item["category"] == "factual_claim"
    )

    assert finding["verification_status"] == "unverified"
    assert finding["citations"] == []
    assert finding["confidence"] == 0.62
    assert finding["verification_confidence"] > 0.5
    assert finding["evidence_strength"] == 0.0
    assert finding["evidence_status"] == "unverified"
    assert "not proof" in finding["verification_explanation"]


def test_external_search_failure_keeps_claim_unverified(
    client, monkeypatch
):
    from app.routes import analysis
    from app.services.factual_verifier import ExternalSearchError

    async def unavailable(_claim):
        raise ExternalSearchError(
            "provider error with no sensitive request data"
        )

    monkeypatch.setattr(analysis, "FACT_CHECK_ENABLED", True)
    monkeypatch.setattr(analysis, "FACT_CHECK_PROVIDER", "brave")
    monkeypatch.setattr(
        analysis,
        "TRUSTED_SOURCE_DOMAINS",
        ("example.com",),
    )
    monkeypatch.setattr(
        analysis,
        "search_trusted_sources",
        unavailable,
    )

    response = client.post(
        "/api/analyze",
        json={
            "content": "Our annual subscription price is $300.",
            "allow_external_verification": True,
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["external_verification"]["status"]
        == "provider_error"
    )
    assert (
        response.json()["external_verification"]["claims_failed"]
        == 1
    )

    finding = next(
        item
        for item in response.json()["findings"]
        if item["category"] == "factual_claim"
    )

    assert finding["verification_status"] == "unverified"


def test_external_search_results_are_candidates_not_approved_evidence(
    client, monkeypatch
):
    from app.routes import analysis

    async def candidate_only(claim):
        return [
            {
                "name": "External candidate",
                "url": "https://example.com/facts",
                "excerpt": claim,
                "source_type": "external_trusted_source",
                "freshness": "unknown",
                "verification": (
                    "candidate_evidence_requires_human_review"
                ),
            }
        ]

    monkeypatch.setattr(analysis, "FACT_CHECK_ENABLED", True)
    monkeypatch.setattr(analysis, "FACT_CHECK_PROVIDER", "brave")
    monkeypatch.setattr(
        analysis,
        "TRUSTED_SOURCE_DOMAINS",
        ("example.com",),
    )
    monkeypatch.setattr(
        analysis,
        "search_trusted_sources",
        candidate_only,
    )

    response = client.post(
        "/api/analyze",
        json={
            "content": "Our annual subscription price is $300.",
            "allow_external_verification": True,
        },
    )

    assert response.status_code == 200

    finding = next(
        item
        for item in response.json()["findings"]
        if item["category"] == "factual_claim"
    )

    assert finding["verification_status"] == "unverified"
    assert finding["citations"] == []


def test_external_search_requires_explicit_opt_in(
    client, monkeypatch
):
    from app.routes import analysis

    calls = []

    async def should_not_run(claim):
        calls.append(claim)
        raise AssertionError(
            "external lookup ran without consent"
        )

    monkeypatch.setattr(analysis, "FACT_CHECK_ENABLED", True)
    monkeypatch.setattr(
        analysis,
        "search_trusted_sources",
        should_not_run,
    )

    response = client.post(
        "/api/analyze",
        json={
            "content": "Our annual subscription price is $300."
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["external_verification"]["status"]
        == "not_requested"
    )
    assert calls == []


def test_external_search_discards_results_outside_trusted_domains(
    monkeypatch
):
    from app.services import factual_verifier

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "web": {
                    "results": [
                        {
                            "title": "Trusted result",
                            "url": "https://news.example.com/facts",
                            "description": (
                                "The annual subscription price is $240."
                            ),
                        },
                        {
                            "title": "Lookalike result",
                            "url": (
                                "https://example.com.attacker.test/facts"
                            ),
                            "description": "Untrusted text.",
                        },
                        {
                            "title": "Insecure result",
                            "url": "http://example.com/facts",
                            "description": "Insecure transport.",
                        },
                    ]
                }
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers, params):
            assert headers["X-Subscription-Token"] == "test-key"
            assert params["q"] == (
                "The annual subscription price is $240."
            )
            return FakeResponse()

    monkeypatch.setattr(
        factual_verifier,
        "FACT_CHECK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        factual_verifier,
        "FACT_CHECK_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        factual_verifier,
        "TRUSTED_SOURCE_DOMAINS",
        ("example.com",),
    )
    monkeypatch.setattr(
        factual_verifier.httpx,
        "AsyncClient",
        FakeClient,
    )

    import asyncio

    results = asyncio.run(
        factual_verifier.search_trusted_sources(
            "The annual subscription price is $240."
        )
    )

    assert [item["name"] for item in results] == [
        "Trusted result"
    ]
    assert results[0]["url"] == (
        "https://news.example.com/facts"
    )


def test_text_source_file_upload_and_unsupported_format(client):
    upload = client.post(
        "/api/sources/upload",
        data={
            "name": "Uploaded source",
            "source_date": "2026-10-01",
        },
        files={
            "file": (
                "facts.txt",
                b"Approved product price is $240.",
                "text/plain",
            )
        },
    )

    assert upload.status_code == 201
    assert upload.json()["content"] == (
        "Approved product price is $240."
    )

    unsupported = client.post(
        "/api/sources/upload",
        files={
            "file": (
                "facts.docx",
                b"not supported",
                "application/octet-stream",
            )
        },
    )

    assert unsupported.status_code == 422


def test_pdf_source_upload_extracts_searchable_text(client):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )

    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font}
            ),
        }
    )

    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 72 720 Td "
        b"(annual subscription price is $240) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)

    pdf_bytes = BytesIO()
    writer.write(pdf_bytes)

    response = client.post(
        "/api/sources/upload",
        files={
            "file": (
                "price-sheet.pdf",
                pdf_bytes.getvalue(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201
    assert "annual subscription price is $240" in (
        response.json()["content"]
    )


def test_expired_source_is_never_presented_as_current_evidence(
    client, test_engine
):
    source = client.post(
        "/api/sources",
        json={
            "name": "Expired product price",
            "content": "The annual subscription price is $240.",
            "source_date": "2024-01-01",
            "expiry_date": "2024-12-31",
        },
    )

    assert source.status_code == 201
    _approve_source(client, source.json()["id"])

    result = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source.json()["id"]],
        },
    ).json()

    assert result["retrieved_evidence"][0]["freshness"] == "expired"

    finding = next(
        item
        for item in result["findings"]
        if item["category"] == "factual_claim"
    )

    assert (
        "Only expired approved source material matched"
        in finding["explanation"]
    )
    assert finding["evidence_status"] == "expired_evidence"
    assert finding["verification_status"] == "expired_evidence"
    assert finding["evidence_strength"] == 0.0
    assert finding["citations"][0]["source_id"] == source.json()["id"]

    from app.models.user import User
    from app.services.auth_service import hash_password

    with Session(test_engine) as db:
        db.add(
            User(
                email="historical-evidence-reviewer@example.test",
                display_name="Historical Evidence Reviewer",
                password_hash=hash_password("historical-reviewer-password"),
                role="reviewer",
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()
    reviewer_login = client.post(
        "/api/auth/login",
        json={
            "email": "historical-evidence-reviewer@example.test",
            "password": "historical-reviewer-password",
        },
    )
    assert reviewer_login.status_code == 200
    reviewer_result = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "source_ids": [source.json()["id"]],
        },
    )
    assert reviewer_result.status_code == 200
    assert reviewer_result.json()["retrieved_evidence"][0]["source_id"] == (
        source.json()["id"]
    )
    assert reviewer_result.json()["retrieved_evidence"][0]["freshness"] == "expired"


def test_contributor_analysis_and_reanalysis_exclude_inaccessible_sources(
    client, test_engine
):
    from datetime import datetime, timedelta, timezone

    from app.models.source_document import SourceDocument
    from app.models.user import User
    from app.services.auth_service import hash_password

    guideline = next(
        item
        for item in client.get("/api/guidelines").json()
        if item["category"] == "factual_claim"
    )
    today = datetime.now(timezone.utc).date()
    inaccessible = [
        {
            "name": "Expired private candidate",
            "approval_status": "approved",
            "is_active": True,
            "valid_until": today - timedelta(days=1),
            "marker": "EXPIRED_PRIVATE_EXCERPT",
        },
        {
            "name": "Future private candidate",
            "approval_status": "approved",
            "is_active": True,
            "valid_from": today + timedelta(days=1),
            "marker": "FUTURE_PRIVATE_EXCERPT",
        },
        {
            "name": "Pending private candidate",
            "approval_status": "pending",
            "is_active": True,
            "marker": "PENDING_PRIVATE_EXCERPT",
        },
        {
            "name": "Rejected private candidate",
            "approval_status": "rejected",
            "is_active": True,
            "marker": "REJECTED_PRIVATE_EXCERPT",
        },
        {
            "name": "Inactive private candidate",
            "approval_status": "approved",
            "is_active": False,
            "marker": "INACTIVE_PRIVATE_EXCERPT",
        },
    ]
    current_marker = "CURRENT_APPROVED_EXCERPT"

    with Session(test_engine) as db:
        db.add(
            User(
                email="analysis-visibility-contributor@example.test",
                display_name="Analysis Visibility Contributor",
                password_hash=hash_password("analysis-contributor-password"),
                role="contributor",
                is_active=True,
            )
        )
        current_source = SourceDocument(
            name="Current approved candidate",
            content=(
                "The annual subscription price is $240. "
                + current_marker
            ),
            guideline_id=guideline["id"],
            approval_status="approved",
            is_active=True,
            valid_from=today,
            valid_until=today + timedelta(days=30),
        )
        db.add(current_source)
        db.flush()
        for item in inaccessible:
            db.add(
                SourceDocument(
                    name=item["name"],
                    content=(
                        "The annual subscription price is $240. "
                        + item["marker"]
                    ),
                    guideline_id=guideline["id"],
                    approval_status=item["approval_status"],
                    is_active=item["is_active"],
                    valid_from=item.get("valid_from"),
                    valid_until=item.get("valid_until"),
                )
            )
        db.commit()
        current_source_id = current_source.id
        inaccessible_ids = {
            row.name: row.id
            for row in db.query(SourceDocument)
            .filter(SourceDocument.name.in_([item["name"] for item in inaccessible]))
            .all()
        }

    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={
            "email": "analysis-visibility-contributor@example.test",
            "password": "analysis-contributor-password",
        },
    )
    assert login.status_code == 200

    for source_id in inaccessible_ids.values():
        denied = client.post(
            "/api/analyze",
            json={
                "content": "The annual subscription price is $240.",
                "source_ids": [source_id],
            },
        )
        assert denied.status_code == 422
        assert all(item["marker"] not in denied.text for item in inaccessible)

    initial = client.post(
        "/api/analyze",
        json={
            "content": "The annual subscription price is $240.",
            "guideline_ids": [guideline["id"]],
        },
    )
    assert initial.status_code == 200
    assert [
        item["source_id"] for item in initial.json()["retrieved_evidence"]
    ] == [current_source_id]
    assert all(item["marker"] not in initial.text for item in inaccessible)

    review_id = initial.json()["id"]
    client.cookies.clear()
    admin_login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert admin_login.status_code == 200
    requested = client.patch(
        "/api/reviews/{}/status".format(review_id),
        json={
            "status": "changes_requested",
            "reason": "Recheck the claim against current evidence.",
        },
    )
    assert requested.status_code == 200

    client.cookies.clear()
    contributor_login = client.post(
        "/api/auth/login",
        json={
            "email": "analysis-visibility-contributor@example.test",
            "password": "analysis-contributor-password",
        },
    )
    assert contributor_login.status_code == 200
    revised = client.post(
        "/api/reviews/{}/reanalyze".format(review_id),
        json={
            "content": (
                "The annual subscription price is $240. "
                "This is the current annual subscription price."
            )
        },
    )
    assert revised.status_code == 200
    assert all(item["marker"] not in revised.text for item in inaccessible)
    citations = [
        citation
        for finding in revised.json()["findings"]
        for citation in finding.get("citations", [])
    ]
    assert citations
    assert {citation.get("source_id") for citation in citations} == {
        current_source_id
    }


def test_semantic_retrieval_finds_non_lexical_match_and_caches_source_vectors(
    client, monkeypatch
):
    from app.services import source_retrieval

    source_ids = []

    for name, content in [
        (
            "Booking guidance",
            "Reservations can be arranged with a booking team.",
        ),
        (
            "Astronomy note",
            "The distant galaxy contains many stars and planets.",
        ),
    ]:
        response = client.post(
            "/api/sources",
            json={
                "name": name,
                "content": content,
            },
        )

        assert response.status_code == 201
        _approve_source(client, response.json()["id"])
        source_ids.append(response.json()["id"])

    monkeypatch.setattr(
        source_retrieval,
        "EMBEDDING_MODEL",
        "test-embedding",
    )
    monkeypatch.setattr(source_retrieval, "EMBEDDINGS_ENABLED", True)

    provider_inputs = []

    async def fake_embed(texts):
        provider_inputs.append(list(texts))
        vectors = []

        for text in texts:
            if text.startswith("Studies show"):
                vectors.append([1.0, 0.0])
            elif "booking team" in text:
                vectors.append([0.98, 0.2])
            else:
                vectors.append([0.0, 1.0])

        return vectors

    monkeypatch.setattr(
        source_retrieval,
        "_embed_texts",
        fake_embed,
    )

    payload = {
        "content": "Studies show our service is popular.",
        "source_ids": source_ids,
    }

    first = client.post("/api/analyze", json=payload)
    assert first.status_code == 200

    first_body = first.json()

    assert first_body["evidence_retrieval_method"] == (
        "embedding_cosine"
    )
    assert (
        first_body["retrieved_evidence"][0]["name"]
        == "Booking guidance"
    )
    assert (
        first_body["retrieved_evidence"][0]["verification"]
        == "candidate_evidence_requires_human_review"
    )
    assert len(provider_inputs[0]) == 3

    second = client.post("/api/analyze", json=payload)
    assert second.status_code == 200
    assert (
        second.json()["evidence_retrieval_method"]
        == "embedding_cosine"
    )
    assert len(provider_inputs[1]) == 1


def test_semantic_embedding_provider_failure_falls_back_to_lexical_retrieval(
    client, monkeypatch
):
    from app.routes import analysis
    from app.services import source_retrieval

    monkeypatch.setattr(
        source_retrieval,
        "EMBEDDING_MODEL",
        "test-embedding",
    )
    monkeypatch.setattr(source_retrieval, "EMBEDDINGS_ENABLED", True)

    source = client.post(
        "/api/sources",
        json={
            "name": "Approved customer study",
            "content": (
                "Studies show our service is popular among "
                "42 percent of surveyed customers."
            ),
        },
    )

    assert source.status_code == 201
    _approve_source(client, source.json()["id"])

    async def fail_provider(*_args, **_kwargs):
        raise source_retrieval.EmbeddingProviderError(
            "Configured embedding provider request failed (ConnectError)."
        )

    monkeypatch.setattr(
        analysis,
        "retrieve_evidence",
        fail_provider,
    )

    response = client.post(
        "/api/analyze",
        json={
            "content": (
                "Studies show our service is popular among "
                "42 percent of surveyed customers."
            ),
            "source_ids": [source.json()["id"]],
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["evidence_retrieval_method"] == (
        "bm25_lexical_fallback"
    )
    assert any(
        "embedding provider request failed" in warning
        for warning in body["provider_warnings"]
    )
    assert client.get("/api/reviews").json()["total"] == 1


def test_embedding_provider_uses_openai_compatible_endpoint_and_orders_vectors(
    monkeypatch
):
    import asyncio
    import json
    import httpx

    from app.services import source_retrieval

    monkeypatch.setattr(
        source_retrieval,
        "LLM_API_BASE_URL",
        "https://provider.test/v1",
    )
    monkeypatch.setattr(
        source_retrieval,
        "LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        source_retrieval,
        "EMBEDDING_MODEL",
        "test-embedding",
    )

    async def handle_request(request):
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content)["model"] == "test-embedding"

        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "index": 1,
                        "embedding": [0.0, 1.0],
                    },
                    {
                        "index": 0,
                        "embedding": [1.0, 0.0],
                    },
                ]
            },
        )

    transport = httpx.MockTransport(handle_request)
    async_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        kwargs["transport"] = transport
        return async_client(*args, **kwargs)

    monkeypatch.setattr(
        source_retrieval.httpx,
        "AsyncClient",
        mocked_client,
    )

    vectors = asyncio.run(
        source_retrieval._embed_texts(
            ["query", "source chunk"]
        )
    )

    assert vectors == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]


def test_review_activity_records_analysis_comment_and_revision(client):
    review_id = client.post(
        "/api/analyze",
        json={"content": "A simple draft."},
    ).json()["id"]

    client.post(
        "/api/reviews/{}/comments".format(review_id),
        json={"comment": "Review this sentence."},
    )

    client.post(
        "/api/reviews/{}/revisions".format(review_id),
        json={"content": "A revised draft."},
    )

    activity = client.get(
        "/api/reviews/{}/activity".format(review_id)
    )

    assert activity.status_code == 200

    actions = {
        entry["action"] for entry in activity.json()
    }

    assert {
        "analysis_completed",
        "comment_added",
        "revision_added",
    } <= actions

    assert any(
        entry["action"] == "analysis_completed"
        and entry["actor"] == "Workspace Admin"
        for entry in activity.json()
    )


def test_review_websocket_receives_persisted_comments(client):
    review_id = client.post(
        "/api/analyze",
        json={"content": "A websocket test draft."},
    ).json()["id"]

    with client.websocket_connect(
        "/api/reviews/{}/collaboration".format(review_id),
        headers={"origin": "http://localhost:5173"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "presence"

        response = client.post(
            "/api/reviews/{}/comments".format(review_id),
            json={
                "comment": "Live team note",
                "author": "Reviewer",
            },
        )

        assert response.status_code == 201

        event = websocket.receive_json()
        assert event["type"] == "comment_created"
        assert event["payload"]["comment"] == "Live team note"

        websocket.send_json(
            {
                "type": "draft_changed",
                "content": "Collaboratively edited text.",
            }
        )

        draft = websocket.receive_json()
        assert draft["type"] == "draft_changed"

        revision = client.post(
            "/api/reviews/{}/revisions".format(review_id),
            json={
                "content": "Persisted collaborative text",
            },
        )

        assert revision.status_code == 201
        assert websocket.receive_json()["type"] == "revision_created"

    assert client.get(
        "/api/reviews/{}".format(review_id)
    ).json()["content"] == "Persisted collaborative text"


def test_llm_provider_failure_is_reported_without_blocking_deterministic_analysis(
    client, monkeypatch
):
    from app.routes import analysis
    from app.services.llm_analyzer import LLMProviderError

    async def fail_provider(*_args, **_kwargs):
        raise LLMProviderError(
            "Configured LLM provider request failed (ConnectError)."
        )

    monkeypatch.setattr(
        analysis,
        "llm_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        analysis,
        "analyze_with_llm",
        fail_provider,
    )

    response = client.post(
        "/api/analyze",
        json={
            "content": (
                "Our service guarantees 100% success "
                "for every customer."
            )
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["analysis_engine"] == "rules"
    assert any(
        "provider request failed" in warning
        for warning in body["provider_warnings"]
    )
    assert any(
        finding["category"] == "unsupported_claim"
        for finding in body["findings"]
    )
    assert client.get("/api/reviews").json()["total"] == 1


def test_configured_llm_findings_are_merged_and_labeled(
    client, monkeypatch
):
    from app.routes import analysis

    async def provide_finding(content, guidelines, evidence):
        return [
            {
                "category": "tone_of_voice",
                "severity": "low",
                "title": "Review the tone",
                "explanation": (
                    "The phrasing may not match the guidelines."
                ),
                "matched_text": content,
                "suggestion": "Use the approved voice.",
                "guideline": None,
                "confidence": 0.7,
                "source": "Configured LLM advisory",
                "guideline_id": None,
            }
        ]

    monkeypatch.setattr(
        analysis,
        "llm_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        analysis,
        "analyze_with_llm",
        provide_finding,
    )

    response = client.post(
        "/api/analyze",
        json={"content": "A neutral draft."},
    )

    assert response.status_code == 200
    assert (
        response.json()["analysis_engine"]
        == "rules+configured_llm"
    )
    assert any(
        finding["category"] == "tone_of_voice"
        for finding in response.json()["findings"]
    )
