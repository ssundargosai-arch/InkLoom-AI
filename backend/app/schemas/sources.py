from datetime import date, datetime
from typing import List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceApprovalUpdate(BaseModel):
    status: Literal["approved", "rejected"]
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SourceVerificationRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    source_type: str = Field(default="document", min_length=1, max_length=48)
    content: str = Field(min_length=1, max_length=200_000)
    guideline_id: Optional[int] = None
    url: Optional[str] = Field(default=None, max_length=2048)
    source_date: Optional[date] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = Field(
        default=None,
        validation_alias=AliasChoices("valid_until", "expiry_date"),
    )
    review_interval_days: int = Field(default=90, ge=1, le=3650)
    approval_status: Literal["draft", "pending"] = "pending"

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("source URL must be an HTTP or HTTPS URL without credentials")
        return value

    @field_validator("name", "source_type", "content")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def check_dates(self):
        valid_from = self.valid_from or self.source_date
        if valid_from and self.valid_until and self.valid_until < valid_from:
            raise ValueError("valid_until cannot precede valid_from")
        return self


class SourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    source_type: Optional[str] = Field(default=None, min_length=1, max_length=48)
    content: Optional[str] = Field(default=None, min_length=1, max_length=200_000)
    guideline_id: Optional[int] = None
    url: Optional[str] = Field(default=None, max_length=2048)
    source_date: Optional[date] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = Field(
        default=None,
        validation_alias=AliasChoices("valid_until", "expiry_date"),
    )
    review_interval_days: Optional[int] = Field(default=None, ge=1, le=3650)
    is_active: Optional[bool] = None
    approval_status: Optional[Literal["draft", "pending"]] = None

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("source URL must be an HTTP or HTTPS URL without credentials")
        return value

    @field_validator("name", "source_type", "content")
    @classmethod
    def strip_optional_nonblank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def strip_optional_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SourceApprovalHistoryRead(BaseModel):
    status: Literal["draft", "pending", "approved", "rejected"]
    reviewer: Optional[str]
    note: Optional[str]
    created_at: datetime


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    source_type: str = "document"
    content: str
    guideline_id: Optional[int]
    url: Optional[str]
    source_date: Optional[date]
    expiry_date: Optional[date]
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    review_interval_days: int = 90
    last_verified_at: Optional[datetime] = None
    freshness_status: str = "unknown"
    next_review_due_at: Optional[datetime] = None
    is_active: bool = True
    lifecycle_status: str = "pending"
    approval_status: Literal["draft", "pending", "approved", "rejected"]
    created_by_id: Optional[int] = None
    created_by: Optional[str] = None
    updated_by_id: Optional[int] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    reviewed_by_id: Optional[int]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    approval_history: List[SourceApprovalHistoryRead] = Field(default_factory=list)
    created_at: datetime
