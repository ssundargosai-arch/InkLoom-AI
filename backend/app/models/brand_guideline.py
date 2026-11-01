from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BrandGuideline(Base):
    __tablename__ = "brand_guidelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    examples: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    review_interval_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default="180"
    )
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reviewed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    prohibited_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    preferred_terms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    approved_sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="approved")
    is_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    last_reviewed_by = relationship("User", foreign_keys=[last_reviewed_by_id])
    versions = relationship(
        "GuidelineVersion",
        back_populates="guideline",
        cascade="all, delete-orphan",
        order_by="GuidelineVersion.version_number",
    )
    review_events: Mapped[list["GuidelineReviewEvent"]] = relationship(
        back_populates="guideline",
        cascade="all, delete-orphan",
        order_by="GuidelineReviewEvent.id",
    )


class GuidelineReviewEvent(Base):
    __tablename__ = "guideline_review_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guideline_id: Mapped[int] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    guideline = relationship("BrandGuideline", back_populates="review_events")
    reviewer = relationship("User")


class GuidelineVersion(Base):
    __tablename__ = "guideline_versions"
    __table_args__ = (
        UniqueConstraint(
            "guideline_id", "version_number", name="uq_guideline_version_number"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guideline_id: Mapped[int] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    editor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    guideline = relationship("BrandGuideline", back_populates="versions")
    editor = relationship("User")
