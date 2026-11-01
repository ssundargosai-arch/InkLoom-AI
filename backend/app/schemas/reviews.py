
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.analysis import FindingRead


REVIEW_STATUSES = {
    "draft",
    "submitted",
    "pending",
    "in_review",
    "approved",
    "changes_requested",
    "rejected",
}


class StatusUpdate(BaseModel):
    status: str
    reviewer: Optional[str] = Field(default=None, max_length=160)
    acknowledge_warnings: bool = False
    # Kept for clients that used the earlier conflict-only safeguard.
    acknowledge_conflicts: bool = False
    reason: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        value = value.strip().lower()

        if value not in REVIEW_STATUSES:
            raise ValueError("Unsupported review status.")

        return value


class CommentCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False
    parent_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("comment")
    @classmethod
    def comment_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment cannot be blank")

        return value.strip()


class AssignmentUpdate(BaseModel):
    reviewer_id: Optional[int] = Field(default=None, ge=1)


class ReviewerStageAssignment(BaseModel):
    reviewer_id: int = Field(ge=1)
    stage_number: int = Field(default=1, ge=1, le=10)


class ReviewerAssignmentsUpdate(BaseModel):
    reviewers: List[ReviewerStageAssignment] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_reviewers(self):
        ids = [item.reviewer_id for item in self.reviewers]
        if len(ids) != len(set(ids)):
            raise ValueError("A reviewer can only be assigned once.")
        stages = sorted({item.stage_number for item in self.reviewers})
        if stages != list(range(1, stages[-1] + 1)):
            raise ValueError("Approval stages must start at 1 and be sequential.")
        return self


class ApprovalDecisionCreate(BaseModel):
    decision: str
    reason: Optional[str] = Field(default=None, max_length=2000)
    acknowledge_warnings: bool = False

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"approved", "rejected", "changes_requested"}:
            raise ValueError("Decision must be approved, rejected, or changes_requested.")
        return value

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_reason(self):
        if self.decision in {"rejected", "changes_requested"} and not self.reason:
            raise ValueError("A reason is required for rejection or requested changes.")
        return self


class ApprovalBypassCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)
    acknowledge_warnings: bool = False

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Bypass justification must contain at least 10 characters.")
        return value


class PublishOverrideCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Override justification must contain at least 10 characters.")
        return value


class RevisionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    title: Optional[str] = Field(default=None, max_length=240)

    @field_validator("content")
    @classmethod
    def revision_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("revision content cannot be blank")

        return value


class CommentRead(BaseModel):
    id: int
    comment: str
    author: Optional[str]
    created_at: datetime
    is_internal: bool = False
    parent_id: Optional[int] = None


class RevisionRead(BaseModel):
    id: int
    content: str
    title: Optional[str]
    created_at: datetime
    author_id: Optional[int] = None
    author: Optional[str] = None


class ReviewRead(BaseModel):
    id: int
    title: str
    content: str
    content_type: str
    status: str
    reviewer: Optional[str]
    reviewer_name: Optional[str]
    assigned_reviewer_id: Optional[int] = None
    submitted_at: datetime
    analysis_timestamp: datetime
    issue_count: int
    findings: List[FindingRead]
    comments: List[CommentRead]
    revisions: List[RevisionRead]
