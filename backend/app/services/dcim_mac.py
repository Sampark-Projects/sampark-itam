"""MAC addresses of an interface (database side): add, change, make primary and remove, keeping `asset_interfaces.mac_address` equal to
the primary MAC. The rules of the address itself are in `dcim_logic`; the reverse direction (the old column changed elsewhere) is
handled by the mapper events of `app.models.dcim_mac`."""
from contextlib import contextmanager
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models import AssetInterface, DcimMacAddress
from app.services.dcim_service import bad


@contextmanager
def _both_sides(db: Session, interface: AssetInterface):
    """The caller writes the table and the old column itself, so the mapper events must not do it a second time."""
    interface._dcim_mac_manual = True
    try:
        yield
        db.flush()
    finally:
        interface._dcim_mac_manual = False


def macs_of(db: Session, interface_id) -> List[DcimMacAddress]:
    """The MAC addresses of one interface, the primary first."""
    rows = db.query(DcimMacAddress).filter(DcimMacAddress.interface_id == interface_id).all()
    return sorted(rows, key=lambda r: (not r.is_primary, r.created_at is None, r.created_at, r.mac_address))


def _promote(db: Session, interface: AssetInterface, rows: List[DcimMacAddress], chosen: DcimMacAddress) -> None:
    """Make `chosen` the primary MAC: the old primary is released first (one primary per interface, enforced by an index)."""
    for r in rows:
        if r.is_primary and r is not chosen:
            r.is_primary = False
    db.flush()
    chosen.is_primary = True
    interface.mac_address = chosen.mac_address
    db.flush()


def add_mac(db: Session, user, interface: AssetInterface, values: Dict) -> DcimMacAddress:
    """Add an address to the interface. It is the primary one when asked, or when the interface has no primary yet."""
    rows = macs_of(db, interface.id)
    if any(r.mac_address == values["mac_address"] for r in rows):
        raise bad(f"{values['mac_address']} is already listed on this interface", 409)
    row = DcimMacAddress(tenant_id=interface.tenant_id, interface_id=interface.id, mac_address=values["mac_address"], is_primary=False,
                         description=values.get("description"), created_by=getattr(user, "id", None))
    with _both_sides(db, interface):
        db.add(row)
        db.flush()
        if values.get("is_primary") or not any(r.is_primary for r in rows):
            _promote(db, interface, rows, row)
    return row


def change_mac(db: Session, interface: AssetInterface, row: DcimMacAddress, values: Dict) -> DcimMacAddress:
    """Replace the address, note and primary flag of a row. The primary row cannot be demoted directly: pick another one as primary."""
    rows = macs_of(db, interface.id)
    if any(r.id != row.id and r.mac_address == values["mac_address"] for r in rows):
        raise bad(f"{values['mac_address']} is already listed on this interface", 409)
    if row.is_primary and not values.get("is_primary"):
        raise bad("This is the primary MAC address. Make another address the primary one instead")
    with _both_sides(db, interface):
        row.mac_address = values["mac_address"]
        row.description = values.get("description")
        db.flush()
        if values.get("is_primary") and not row.is_primary:
            _promote(db, interface, rows, row)
        elif row.is_primary:
            interface.mac_address = row.mac_address
    return row


def remove_mac(db: Session, interface: AssetInterface, row: DcimMacAddress) -> None:
    """Delete an address. When it was the primary one the next address (the oldest) becomes primary, or the old column is cleared."""
    rows = [r for r in macs_of(db, interface.id) if r.id != row.id]
    was_primary = row.is_primary
    with _both_sides(db, interface):
        db.delete(row)
        db.flush()
        if was_primary:
            if rows:
                _promote(db, interface, rows, sorted(rows, key=lambda r: (r.created_at is None, r.created_at, r.mac_address))[0])
            else:
                interface.mac_address = None
