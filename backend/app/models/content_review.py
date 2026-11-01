from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ContentReview(Base):
    __tablename__ = "content_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    submitted_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_reviewer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    guideline_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    analysis_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    findings: Mapped[list["ReviewFinding"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="ReviewFinding.id"
    )
    comments: Mapped[list["ReviewComment"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="ReviewComment.id"
    )
    revisions: Mapped[list["ReviewRevision"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="ReviewRevision.id"
    )
    analysis_runs: Mapped[list["ReviewAnalysisRun"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="ReviewAnalysisRun.id",
    )
    assigned_reviewer = relationship("User", foreign_keys=[assigned_reviewer_id])
    submitted_by = relationship("User", foreign_keys=[submitted_by_id])
    reviewer_assignments = relationship(
        "ReviewAssignment",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="ReviewAssignment.stage_number, ReviewAssignment.id",
    )
    approval_decisions = relationship(
        "ReviewApprovalDecision",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="ReviewApprovalDecision.id",
    )
    approval_bypasses = relationship(
        "ReviewApprovalBypass",
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="ReviewApprovalBypass.id",
    )
    visual_attachment = relationship(
        "ReviewVisualAttachment",
        back_populates="review",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("content_reviews.id"), index=True)
    guideline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    matched_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    review: Mapped[ContentReview] = relationship(back_populates="findings")


class ReviewRevision(Base):
    __tablename__ = "review_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("content_reviews.id"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review: Mapped[ContentReview] = relationship(back_populates="revisions")
    author = relationship("User", foreign_keys=[author_id])


class ReviewAnalysisRun(Base):
    __tablename__ = "review_analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("content_reviews.id"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    analysis_engine: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_retrieval_method: Mapped[Optional[str]] = mapped_column(String(80))
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review: Mapped[ContentReview] = relationship(back_populates="analysis_runs")
    created_by = relationship("User")
