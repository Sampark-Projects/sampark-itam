"""Lifecycle workflows (requirements gap plan, phase 3): onboarding and retirement stages with
role-based tasks and approvals. One definition per kind and tenant; each run copies the steps."""
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class LifecycleWorkflow(Base):
    __tablename__ = "lifecycle_workflows"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", name="uq_lifecycle_workflow_kind"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # onboarding / retirement
    name = Column(String(100), nullable=False)
    # when False, whoever started a run may also approve its approval steps
    allow_self_approval = Column(Boolean, nullable=False, default=False, server_default="false")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    steps = relationship(
        "LifecycleWorkflowStep", back_populates="workflow",
        cascade="all, delete-orphan", order_by="LifecycleWorkflowStep.position",
    )


class LifecycleWorkflowStep(Base):
    __tablename__ = "lifecycle_workflow_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("lifecycle_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    step_type = Column(String(10), nullable=False, default="task")  # task / approval
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    required_fields = Column(JSONB, nullable=False, default=list)  # asset fields that must be filled in
    requires_document = Column(Boolean, nullable=False, default=False, server_default="false")
    requires_comment = Column(Boolean, nullable=False, default=False, server_default="false")
    confirm_statement = Column(String(255), nullable=True)  # the person must tick this statement
    document_category = Column(String(30), nullable=True)  # the required document must be of this category
    sets_status_id = Column(UUID(as_uuid=True), ForeignKey("asset_statuses.id", ondelete="SET NULL"), nullable=True)

    workflow = relationship("LifecycleWorkflow", back_populates="steps")


class AssetLifecycleRun(Base):
    __tablename__ = "asset_lifecycle_runs"
    __table_args__ = (
        # one open run per asset
        Index(
            "uq_asset_lifecycle_run_open", "asset_id", unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    workflow_name = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="in_progress")  # in_progress / completed / rejected / cancelled
    allow_self_approval = Column(Boolean, nullable=False, default=False)
    started_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime, default=func.now())
    finished_at = Column(DateTime, nullable=True)
    finish_note = Column(Text, nullable=True)

    steps = relationship(
        "AssetLifecycleRunStep", back_populates="run",
        cascade="all, delete-orphan", order_by="AssetLifecycleRunStep.position",
    )


class AssetLifecycleRunStep(Base):
    __tablename__ = "asset_lifecycle_run_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("asset_lifecycle_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    step_type = Column(String(10), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    required_fields = Column(JSONB, nullable=False, default=list)
    requires_document = Column(Boolean, nullable=False, default=False)
    requires_comment = Column(Boolean, nullable=False, default=False)
    confirm_statement = Column(String(255), nullable=True)
    document_category = Column(String(30), nullable=True)
    sets_status_id = Column(UUID(as_uuid=True), ForeignKey("asset_statuses.id", ondelete="SET NULL"), nullable=True)

    state = Column(String(10), nullable=False, default="pending")  # pending / done / rejected
    acted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acted_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    confirmed = Column(Boolean, nullable=False, default=False)
    overridden = Column(Boolean, nullable=False, default=False)  # done by an administrator outside the step role

    run = relationship("AssetLifecycleRun", back_populates="steps")
