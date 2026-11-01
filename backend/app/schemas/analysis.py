from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    content: str = Field(min_length=1)
    content_type: str = Field(default="text", min_length=1, max_length=80)
    title: Optional[str] = Field(default=None, max_length=240)
    guideline_ids: List[int] = Field(default_factory=list, max_length=100)
    source_ids: List[int] = Field(default_factory=list, max_length=100)
    alt_text: Optional[str] = Field(default=None, max_length=1000)
    allow_external_verification: bool = False

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content cannot be blank")
        return value

    @field_validator("content_type")
    @classmethod
    def content_type_trimmed(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content_type cannot be blank")
        return value


class FindingRead(BaseModel):
    id: int
    category: str
    severity: str
    title: str
    explanation: str
    message: str
    matched_text: Optional[str]
    suggestion: Optional[str]
    source: Optional[str]
    guideline: Optional[str]
    guideline_id: Optional[int]
    confidence: Optional[float]
    status: str
    review_status: str
    claim: Optional[str] = None
    claim_start: Optional[int] = None
    claim_end: Optional[int] = None
    detection_method: Optional[str] = None
    verification_status: Optional[str] = None
    evidence_status: Optional[str] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    verification_explanation: Optional[str] = None
    verification_confidence: Optional[float] = None
    evidence_reason: Optional[str] = None
    evidence_strength: Optional[float] = None
    visual_data: Optional[Dict[str, Any]] = None
