"""DCIM: racks, rack roles and device types (the catalogue of manufacturer + model with its rack height).

The placement of an asset in a rack (rack, unit position, face) is stored on the asset itself (`assets.rack_id`,
`rack_position`, `rack_face`, `device_type_id`, `airflow`), so an asset stays one row. The rules are in `app.services.dcim_logic`."""
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


def _tenant():
    return Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)


class DcimRackRole(Base):
    """What a rack is used for (network, servers, OT cabinet ...)."""
    __tablename__ = "dcim_rack_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_dcim_rack_roles_name"),
        UniqueConstraint("tenant_id", "slug", name="uq_dcim_rack_roles_slug"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    color = Column(String(7), nullable=True)  # #rrggbb
    description = Column(String(200), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class DcimDeviceType(Base):
    """A model of a device of one manufacturer: its height in rack units and whether it takes the full depth of the rack."""
    __tablename__ = "dcim_device_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "manufacturer_id", "model", name="uq_dcim_device_types_model"),
        Index("ix_dcim_device_types_tenant_model", "tenant_id", "model"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    manufacturer_id = Column(UUID(as_uuid=True), ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False, index=True)
    model = Column(String(100), nullable=False)
    u_height = Column(Numeric(4, 1), nullable=True)  # rack units; empty = not known yet (counted as 1U), 0 = does not use rack space
    is_full_depth = Column(Boolean, nullable=False, default=True, server_default="true")
    airflow = Column(String(20), nullable=True)
    part_number = Column(String(100), nullable=True)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class DcimRack(Base):
    """A rack or cabinet at a site (and optionally a location of that site)."""
    __tablename__ = "dcim_racks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "name", name="uq_dcim_racks_name"),
        Index("ix_dcim_racks_tenant_asset_tag", "tenant_id", "asset_tag"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("dcim_rack_roles.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(15), nullable=False, default="active", server_default="active")
    facility_id = Column(String(50), nullable=True)  # the number the facility gives the rack
    serial = Column(String(100), nullable=True)
    asset_tag = Column(String(100), nullable=True)
    width = Column(SmallInteger, nullable=False, default=19, server_default="19")  # inches between the rails: 10, 19, 21 or 23
    u_height = Column(SmallInteger, nullable=False, default=42, server_default="42")
    starting_unit = Column(SmallInteger, nullable=False, default=1, server_default="1")
    desc_units = Column(Boolean, nullable=False, default=False, server_default="false")  # units are numbered from the top
    airflow = Column(String(20), nullable=True)
    form_factor = Column(String(30), nullable=True)  # 4-post cabinet, wall-mounted frame ... (NetBox RackFormFactorChoices)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
