"""Plan and procure: a purchase request (demand, specification) that is approved, ordered and received.
Its lines are what a delivered asset is checked against."""
import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_purchase_orders_number"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(Integer, nullable=False)  # shown as PR-0001
    title = Column(String(150), nullable=False)
    justification = Column(Text, nullable=True)  # the demand: why it is needed
    specification = Column(Text, nullable=True)  # technical specification
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    vendor_name = Column(String(255), nullable=True)
    po_number = Column(String(100), nullable=True)  # the ERP purchase order number, once ordered
    currency = Column(String(3), nullable=True)
    expected_delivery_date = Column(Date, nullable=True)
    # draft / submitted / approved / rejected / ordered / received / closed / cancelled
    status = Column(String(12), nullable=False, default="draft")
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    ordered_at = Column(DateTime, nullable=True)
    # the approval levels this request has to pass, copied from the settings when it is submitted
    approval_chain = Column(JSONB, nullable=True)
    # the purchase order document itself (optional); stored under uploads/
    po_file_name = Column(String(255), nullable=True)
    po_file_path = Column(String(500), nullable=True)
    po_file_size = Column(Integer, nullable=True)
    po_file_uploaded_at = Column(DateTime, nullable=True)
    po_file_uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    lines = relationship("PurchaseOrderLine", cascade="all, delete-orphan", order_by="PurchaseOrderLine.position",
                         back_populates="order", lazy="selectin")


class PurchaseApproval(Base):
    """One level's decision on a purchase request. Cleared when the request goes back to draft."""
    __tablename__ = "purchase_approvals"
    __table_args__ = (UniqueConstraint("order_id", "level", name="uq_purchase_approval_level"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(Integer, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision = Column(String(10), nullable=False)  # approved / rejected
    note = Column(Text, nullable=True)
    decided_at = Column(DateTime, default=func.now())


class PurchaseApprovalSettings(Base):
    """The approval chain of a tenant: ordered levels [{level, name, role_id}]. Empty = one level, any approver."""
    __tablename__ = "purchase_approval_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True)
    levels = Column(JSONB, nullable=False, default=list)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    asset_type_id = Column(UUID(as_uuid=True), ForeignKey("asset_types.id", ondelete="SET NULL"), nullable=True)
    manufacturer_id = Column(UUID(as_uuid=True), ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True)
    model = Column(String(255), nullable=True)
    description = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_cost = Column(Numeric(14, 2), nullable=True)

    order = relationship("PurchaseOrder", back_populates="lines")


class AssetSoftware(Base):
    """Software and firmware components installed on an asset (operating system, runtime, HMI or
    engineering application, firmware module, ...)."""
    __tablename__ = "asset_software"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="application")
    name = Column(String(150), nullable=False)
    vendor = Column(String(150), nullable=True)
    version = Column(String(100), nullable=True)
    install_date = Column(Date, nullable=True)
    licence_expiry_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
