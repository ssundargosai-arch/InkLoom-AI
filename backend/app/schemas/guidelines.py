from datetime import datetime
from typing import Annotated, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

VoiceText = Annotated[str, Field(min_length=1, max_length=200)]
Tone = Literal[
    "professional",
    "friendly",
    "conversational",
    "formal",
    "authoritative",
    "informative",
]
VoiceAttribute = Literal["clear", "trustworthy", "concise", "approachable"]


def _normalize_choices(values):
    if not isinstance(values, list):
        return values
    return [
        value.strip().lower() if isinstance(value, str) else value
        for value in values
    ]


def _clean_unique_text(values):
    if not isinstance(values, list):
        return values
    cleaned = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("values must be text")
        value = value.strip()
        if not value:
            raise ValueError("values cannot be blank")
        key = value.casefold()
        if key in seen:
            raise ValueError("values must be unique, ignoring case")
        seen.add(key)
        cleaned.append(value)
    return cleaned


class ApprovedSource(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: Optional[str] = Field(default=None, max_length=2048)
    reference: Optional[str] = Field(default=None, max_length=1000)
    source_date: Optional[str] = Field(default=None, max_length=40)
    expiry_date: Optional[str] = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("source URL must be an HTTP or HTTPS URL without credentials")
        return value


class GuidelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=4000)
    examples: List[str] = Field(default_factory=list, max_length=50)
    is_active: bool = True
    severity: str = "medium"
    review_interval_days: int = Field(default=180, ge=1, le=3650)
    prohibited_terms: List[str] = Field(default_factory=list, max_length=100)
    preferred_terms: List[str] = Field(default_factory=list, max_length=100)
    approved_sources: List[ApprovedSource] = Field(default_factory=list, max_length=50)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        value = value.lower()
        if value not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")
        return value

    @field_validator("name", "category", "description")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("prohibited_terms", "preferred_terms", "examples")
    @classmethod
    def trim_terms(cls, values: List[str]) -> List[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 500 for value in cleaned):
            raise ValueError("examples or terms cannot exceed 500 characters")
        return cleaned


class GuidelineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    examples: Optional[List[str]] = Field(default=None, max_length=50)
    severity: Optional[str] = None
    review_interval_days: Optional[int] = Field(default=None, ge=1, le=3650)
    prohibited_terms: Optional[List[str]] = Field(default=None, max_length=100)
    preferred_terms: Optional[List[str]] = Field(default=None, max_length=100)
    approved_sources: Optional[List[ApprovedSource]] = Field(default=None, max_length=50)
    is_active: Optional[bool] = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.lower()
        if value not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")
        return value

    @field_validator("name", "category", "description")
    @classmethod
    def trim_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("prohibited_terms", "preferred_terms", "examples")
    @classmethod
    def trim_optional_lists(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return values
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 500 for value in cleaned):
            raise ValueError("examples or terms cannot exceed 500 characters")
        return cleaned


class GuidelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    description: str
    examples: List[str] = Field(default_factory=list)
    severity: str
    prohibited_terms: List[str]
    preferred_terms: List[str]
    approved_sources: List[dict]
    status: str
    is_seed: bool
    is_active: bool = True
    review_interval_days: int = 180
    last_reviewed_at: Optional[datetime] = None
    last_reviewed_by: Optional[str] = None
    freshness_status: str = "unknown"
    next_review_due_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class GuidelineReviewRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class BrandVoiceConfigurationUpdate(BaseModel):
    desired_tones: List[Tone] = Field(default_factory=list, max_length=6)
    voice_attributes: List[VoiceAttribute] = Field(default_factory=list, max_length=4)
    preferred_expressions: List[VoiceText] = Field(default_factory=list, max_length=100)
    prohibited_expressions: List[VoiceText] = Field(default_factory=list, max_length=100)
    target_audiences: List[VoiceText] = Field(default_factory=list, max_length=50)
    supported_channels: List[VoiceText] = Field(default_factory=list, max_length=50)
    messaging_principles: List[VoiceText] = Field(default_factory=list, max_length=100)

    @field_validator("desired_tones", "voice_attributes", mode="before")
    @classmethod
    def normalize_enum_values(cls, values):
        return _normalize_choices(values)

    @field_validator(
        "preferred_expressions",
        "prohibited_expressions",
        "target_audiences",
        "supported_channels",
        "messaging_principles",
        mode="before",
    )
    @classmethod
    def trim_and_validate_unique_values(cls, values):
        return _clean_unique_text(values)

    @field_validator(
        "desired_tones",
        "voice_attributes",
        mode="after",
    )
    @classmethod
    def reject_duplicate_choices(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("values must be unique")
        return values

    @model_validator(mode="after")
    def reject_expression_overlap(self):
        preferred = {
            expression.casefold() for expression in self.preferred_expressions
        }
        prohibited = {
            expression.casefold() for expression in self.prohibited_expressions
        }
        if preferred & prohibited:
            raise ValueError(
                "an expression cannot be both preferred and prohibited"
            )
        return self
