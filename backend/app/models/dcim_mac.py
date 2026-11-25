"""DCIM: the MAC addresses of an interface, several per interface like NetBox.

One of them is the primary MAC of the interface (a partial unique index allows one per interface). The older column
`asset_interfaces.mac_address` is kept and always holds the primary MAC, because the asset form, the discovery and the exports
read it. The two are kept in step in both directions:

* changes made through the DCIM API (`app.services.dcim_mac`) write both;
* a change of `asset_interfaces.mac_address` made anywhere else (the asset form, the network discovery, a PCAP import) is carried
  into this table by the mapper events below, so no other code has to know about this table."""
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint, delete, event, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm.attributes import get_history

from app.database import Base
from app.models.asset_interface import AssetInterface
from app.services.mac_utils import normalize_mac_address


class DcimMacAddress(Base):
    __tablename__ = "dcim_mac_addresses"
    __table_args__ = (
        UniqueConstraint("interface_id", "mac_address", name="uq_dcim_mac_interface_mac"),
        Index("ux_dcim_mac_primary", "interface_id", unique=True, postgresql_where=text("is_primary = true"), sqlite_where=text("is_primary = 1")),
        Index("ix_dcim_mac_tenant_mac", "tenant_id", "mac_address"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    interface_id = Column(UUID(as_uuid=True), ForeignKey("asset_interfaces.id", ondelete="CASCADE"), nullable=False, index=True)
    mac_address = Column(String(17), nullable=False)  # AA:BB:CC:DD:EE:FF
    is_primary = Column(Boolean, nullable=False, default=False, server_default="false")
    description = Column(String(200), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


def carry_legacy_mac(connection, interface) -> None:
    """Make the primary row of the table follow `asset_interfaces.mac_address`: a cleared MAC removes the primary row, an address the
    interface already has becomes the primary one, otherwise the primary row takes the new address (or one is created). A value that
    is not a MAC address leaves the table alone (the schemas refuse such values; old rows may hold them)."""
    table = DcimMacAddress.__table__
    raw = (interface.mac_address or "").strip()
    mac = normalize_mac_address(raw) if raw else None
    if raw and mac is None:
        return
    rows = connection.execute(select(table.c.id, table.c.mac_address, table.c.is_primary).where(table.c.interface_id == interface.id)).all()
    primary = next((r for r in rows if r.is_primary), None)
    if mac is None:
        if primary is not None:
            connection.execute(delete(table).where(table.c.id == primary.id))
        return
    if primary is not None and primary.mac_address == mac:
        return
    same = next((r for r in rows if r.mac_address == mac), None)
    if same is not None:
        if primary is not None:
            connection.execute(update(table).where(table.c.id == primary.id).values(is_primary=False))
        connection.execute(update(table).where(table.c.id == same.id).values(is_primary=True))
    elif primary is not None:
        connection.execute(update(table).where(table.c.id == primary.id).values(mac_address=mac))
    else:
        connection.execute(insert(table).values(id=uuid.uuid4(), tenant_id=interface.tenant_id, interface_id=interface.id, mac_address=mac, is_primary=True))


@event.listens_for(AssetInterface, "after_insert")
def _interface_added(mapper, connection, interface):
    if interface.mac_address and not getattr(interface, "_dcim_mac_manual", False):
        carry_legacy_mac(connection, interface)


@event.listens_for(AssetInterface, "after_update")
def _interface_changed(mapper, connection, interface):
    if getattr(interface, "_dcim_mac_manual", False):
        return   # the DCIM API is writing both sides itself
    if get_history(interface, "mac_address").has_changes():
        carry_legacy_mac(connection, interface)
