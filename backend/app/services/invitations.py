import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.config import PASSWORD_RESET_BASE_URL
from app.models.user import User, UserInvitation
from app.services.email_delivery import send_email

INVITATION_LIFETIME = timedelta(hours=48)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_invitation(
    db: Session, user: User, now: Optional[datetime] = None
) -> str:
    now = now or utc_now()
    db.query(UserInvitation).filter(
        UserInvitation.user_id == user.id,
        UserInvitation.used_at.is_(None),
        UserInvitation.revoked_at.is_(None),
    ).update({"revoked_at": now}, synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.add(
        UserInvitation(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=now + INVITATION_LIFETIME,
        )
    )
    db.flush()
    return token


def invitation_link(token: str) -> str:
    return "{}/accept-invitation?{}".format(
        PASSWORD_RESET_BASE_URL,
        urlencode({"token": token}),
    )


def send_invitation_email(email: str, display_name: str, link: str) -> None:
    send_email(
        email,
        "Your InkLoom workspace invitation",
        (
            "Hello {},\n\n".format(display_name)
            + "An administrator invited you to join the InkLoom workspace. "
            + "Use the secure, single-use link below within 48 hours to set your "
            + "password and activate your account:\n{}\n\n".format(link)
            + "If you were not expecting this invitation, you can ignore this email."
        ),
    )
