import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.orm import Session

from app.models.user import AccountAuditEvent, User, UserInvitation
from app.services.auth_service import verify_password


def configure_invitation_delivery(monkeypatch, sent=None):
    from app.routes import auth

    deliveries = sent if sent is not None else []
    monkeypatch.setattr(auth, "SMTP_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda email, name, link: deliveries.append((email, name, link)),
    )
    return deliveries


def issue_invitation(client, monkeypatch, email="member@example.test", role="reviewer"):
    sent = configure_invitation_delivery(monkeypatch)
    response = client.post(
        "/api/auth/users",
        json={"email": email, "display_name": "Workspace Member", "role": role},
    )
    assert response.status_code == 201
    return response, sent


def _token_from_link(link):
    parsed = urlsplit(link)
    return (
        parse_qs(parsed.query).get("token", [None])[0]
        or parse_qs(parsed.fragment).get("token", [None])[0]
    )


@pytest.mark.parametrize("role", ["admin", "reviewer", "contributor"])
def test_admin_invitation_creates_inactive_account_and_hashed_token(
    client, test_engine, monkeypatch, role
):
    response, sent = issue_invitation(
        client,
        monkeypatch,
        email="new-member@example.test",
        role=role,
    )
    body = response.json()
    assert body["user"]["role"] == role
    assert body["user"]["is_active"] is False
    assert body["user"]["invitation_pending"] is True
    assert "temporary_password" not in body
    assert "token=" not in response.text
    assert sent[0][0:2] == ("new-member@example.test", "Workspace Member")
    assert sent[0][2].startswith(
        "http://localhost:5173/accept-invitation?token="
    )
    raw_token = _token_from_link(sent[0][2])

    with Session(test_engine) as db:
        invited = db.query(User).filter_by(email="new-member@example.test").one()
        invitation = db.query(UserInvitation).filter_by(user_id=invited.id).one()
        event = (
            db.query(AccountAuditEvent)
            .filter_by(target_user_id=invited.id, action="invitation.created")
            .one()
        )
        assert invited.is_active is False
        assert invited.must_change_password is True
        assert not verify_password(raw_token, invited.password_hash)
        assert invitation.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert raw_token not in invitation.token_hash
        assert raw_token not in str(event.details)


def test_invitation_creation_requires_admin_and_public_registration_is_disabled(
    client,
):
    client.cookies.clear()
    assert client.get("/api/auth/users").status_code == 401
    assert client.post(
        "/api/auth/users",
        json={
            "email": "self@example.test",
            "display_name": "Self",
            "role": "admin",
        },
    ).status_code == 401
    assert client.post(
        "/api/auth/register",
        json={
            "email": "self@example.test",
            "display_name": "Self",
            "password": "a-password-that-is-long-enough",
        },
    ).status_code == 404


def test_invitation_creation_requires_smtp(client, test_engine, monkeypatch):
    from app.routes import auth

    monkeypatch.setattr(auth, "SMTP_ENABLED", False)
    response = client.post(
        "/api/auth/users",
        json={
            "email": "not-created@example.test",
            "display_name": "Not Created",
            "role": "contributor",
        },
    )
    assert response.status_code == 503
    with Session(test_engine) as db:
        assert db.query(User).filter_by(email="not-created@example.test").count() == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "display_name": "Bad email", "role": "reviewer"},
        {"email": "valid@example.test", "display_name": "  ", "role": "reviewer"},
        {"email": "valid@example.test", "display_name": "Valid", "role": "owner"},
    ],
)
def test_invitation_input_validation(client, monkeypatch, payload):
    configure_invitation_delivery(monkeypatch)
    response = client.post("/api/auth/users", json=payload)
    assert response.status_code == 422


def test_invitation_expiry_resend_and_single_use(client, test_engine, monkeypatch):
    from app.routes import auth

    response, sent = issue_invitation(client, monkeypatch)
    user_id = response.json()["user"]["id"]
    expired_token = _token_from_link(sent[0][2])
    with Session(test_engine) as db:
        invitation = db.query(UserInvitation).filter_by(user_id=user_id).one()
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    listed = client.get("/api/auth/users").json()
    expired_member = next(item for item in listed if item["id"] == user_id)
    assert expired_member["invitation_pending"] is True
    assert expired_member["invitation_expired"] is True
    expired = client.post(
        "/api/auth/invitations/accept",
        json={"token": expired_token, "new_password": "member-password-long-123"},
    )
    assert expired.status_code == 400

    new_delivery = []
    monkeypatch.setattr(
        auth,
        "send_invitation_email",
        lambda email, name, link: new_delivery.append((email, name, link)),
    )
    resent = client.post(f"/api/auth/users/{user_id}/invitation")
    assert resent.status_code == 202
    replacement_token = _token_from_link(new_delivery[0][2])
    assert replacement_token != expired_token
    assert client.post(
        "/api/auth/invitations/accept",
        json={"token": expired_token, "new_password": "member-password-long-123"},
    ).status_code == 400

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={"token": replacement_token, "new_password": "member-password-long-123"},
    )
    assert accepted.status_code == 200
    assert client.post(
        "/api/auth/invitations/accept",
        json={"token": replacement_token, "new_password": "member-password-long-456"},
    ).status_code == 400
    with Session(test_engine) as db:
        invited = db.get(User, user_id)
        assert invited.is_active is True
        assert invited.must_change_password is False
        assert invited.role == "reviewer"
        assert verify_password("member-password-long-123", invited.password_hash)
        assert (
            db.query(AccountAuditEvent)
            .filter_by(target_user_id=user_id, action="invitation.accepted")
            .count()
            == 1
        )


def test_invited_member_cannot_assign_role_or_use_admin_endpoints(
    client, monkeypatch
):
    response, sent = issue_invitation(client, monkeypatch, role="reviewer")
    token = _token_from_link(sent[0][2])
    payload = {
        "token": token,
        "new_password": "member-password-long-123",
        "role": "admin",
    }
    accepted = client.post("/api/auth/invitations/accept", json=payload)
    assert accepted.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={
            "email": "member@example.test",
            "password": "member-password-long-123",
        },
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "reviewer"
    assert client.get("/api/auth/users").status_code == 403
    assert client.post(
        "/api/auth/users",
        json={
            "email": "another@example.test",
            "display_name": "Another",
            "role": "admin",
        },
    ).status_code == 403


def test_generated_query_invitation_url_token_is_accepted(client, monkeypatch):
    response, sent = issue_invitation(
        client,
        monkeypatch,
        email="query-invitation@example.test",
        role="reviewer",
    )
    link = urlsplit(sent[0][2])
    assert link.path == "/accept-invitation"
    assert link.fragment == ""
    token = _token_from_link(sent[0][2])
    assert token

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": token,
            "new_password": "reviewer-password-long-123",
        },
    )
    assert accepted.status_code == 200
    member = client.post(
        "/api/auth/login",
        json={
            "email": "query-invitation@example.test",
            "password": "reviewer-password-long-123",
        },
    )
    assert member.status_code == 200
    assert member.json()["user"]["role"] == "reviewer"


def test_invitation_validation_duplicate_email_and_admin_activation_guard(
    client, monkeypatch
):
    response, _sent = issue_invitation(client, monkeypatch)
    user_id = response.json()["user"]["id"]
    duplicate = client.post(
        "/api/auth/users",
        json={
            "email": " MEMBER@example.test ",
            "display_name": "Duplicate",
            "role": "admin",
        },
    )
    assert duplicate.status_code == 409
    premature_activation = client.patch(
        f"/api/auth/users/{user_id}",
        json={"role": "reviewer", "is_active": True},
    )
    assert premature_activation.status_code == 422
    pending_deactivation = client.patch(
        f"/api/auth/users/{user_id}",
        json={"role": "reviewer", "is_active": False},
    )
    assert pending_deactivation.status_code == 422
    assert client.get("/api/auth/users").json()[-1]["invitation_pending"] is True


def test_invitation_email_failure_does_not_return_token_or_password(
    client, test_engine, monkeypatch
):
    from app.routes import auth
    from app.services.email_delivery import EmailDeliveryError

    monkeypatch.setattr(auth, "SMTP_ENABLED", True)

    def fail_delivery(*_args):
        raise EmailDeliveryError("transport rejected")

    monkeypatch.setattr(auth, "send_invitation_email", fail_delivery)
    response = client.post(
        "/api/auth/users",
        json={
            "email": "retry@example.test",
            "display_name": "Retry Invite",
            "role": "contributor",
        },
    )
    assert response.status_code == 503
    assert "token" not in response.text.lower()
    assert "password" not in response.text.lower()
    with Session(test_engine) as db:
        invited = db.query(User).filter_by(email="retry@example.test").one()
        assert invited.is_active is False
        assert (
            db.query(UserInvitation)
            .filter_by(user_id=invited.id, revoked_at=None)
            .count()
            == 1
        )
