"""Seed the OT asset classes and lifecycle statuses (requirements gap plan, phase 0).

Idempotent and additive: it only creates asset types / statuses that a tenant does not
already have (matching by name, case-insensitive, also against known aliases), and never
edits or deletes existing rows.

Usage (from the backend folder, inside the container):
    python -m app.init_ot_lifecycle                 # every tenant
    python -m app.init_ot_lifecycle <tenant-uuid>   # one tenant
"""
import sys
import uuid

from app.database import SessionLocal
from app.models import Tenant
from app.models.asset_status import AssetStatus
from app.models.asset_type import AssetType

# Asset classes listed in the requirements (section 4.1), Purdue levels 0 - 3.5.
# "aliases": names that already mean the same class (e.g. the Sampark tenant uses "CNC").
OT_ASSET_TYPES = [
    {"name": "Safety PLC", "description": "Safety programmable logic controller", "purdue_level": 1, "aliases": []},
    {"name": "Remote I/O", "description": "Remote I/O station", "purdue_level": 1, "aliases": ["RIO", "Remote IO"]},
    {"name": "SCADA Server", "description": "SCADA server", "purdue_level": 2, "aliases": []},
    {"name": "SCADA Client", "description": "SCADA client / operator client", "purdue_level": 2, "aliases": []},
    {"name": "Historian", "description": "Process data historian", "purdue_level": 3, "aliases": []},
    {"name": "OPC Server", "description": "OPC server", "purdue_level": 2, "aliases": []},
    {"name": "Industrial PC", "description": "Industrial PC (IPC)", "purdue_level": 2, "aliases": ["IPC"]},
    {"name": "Operator Station", "description": "Operator station", "purdue_level": 2, "aliases": []},
    {"name": "Drive", "description": "AC / DC drive", "purdue_level": 1, "aliases": ["VFD"]},
    {"name": "Servo System", "description": "Servo drive and motor system", "purdue_level": 1, "aliases": ["Servo"]},
    {"name": "Motion Controller", "description": "Motion controller", "purdue_level": 1, "aliases": []},
    {"name": "CNC Controller", "description": "CNC machine controller", "purdue_level": 1, "aliases": ["CNC"]},
    {"name": "Robot Controller", "description": "Robot controller", "purdue_level": 1, "aliases": []},
    {"name": "Welding Line Controller", "description": "Welding line controller", "purdue_level": 1, "aliases": []},
    {"name": "Painting Line Controller", "description": "Painting line controller", "purdue_level": 1, "aliases": []},
    {"name": "Torque Controller", "description": "Torque and tightening controller", "purdue_level": 1, "aliases": []},
    {"name": "Vision System", "description": "Machine vision system", "purdue_level": 1, "aliases": []},
    {"name": "End-of-Line Test Equipment", "description": "End-of-line test equipment", "purdue_level": 2, "aliases": []},
    {"name": "Managed Switch", "description": "Managed industrial switch", "purdue_level": 1, "aliases": []},
    {"name": "Unmanaged Switch", "description": "Unmanaged industrial switch", "purdue_level": 1, "aliases": []},
    {"name": "Wireless Access Point", "description": "Wireless access point", "purdue_level": 2, "aliases": ["WAP", "Access Point"]},
    {"name": "Protocol Gateway", "description": "Protocol gateway / converter", "purdue_level": 1.5, "aliases": []},
    {"name": "Barcode Reader", "description": "Barcode reader", "purdue_level": 1, "aliases": []},
    {"name": "RFID Reader", "description": "RFID reader", "purdue_level": 1, "aliases": []},
    {"name": "Industrial Printer", "description": "Printer connected to the plant network", "purdue_level": 2, "aliases": ["Printer"]},
    {"name": "Data Collection Device", "description": "Data collection device", "purdue_level": 1, "aliases": []},
    {"name": "Smart Sensor", "description": "Smart sensor", "purdue_level": 0, "aliases": []},
    {"name": "Instrument", "description": "Field instrument", "purdue_level": 0, "aliases": []},
    {"name": "IIoT Gateway", "description": "IIoT gateway", "purdue_level": 1.5, "aliases": []},
]

# Lifecycle stages of the requirements (section 4.2). "Active", "In stock",
# "In maintenance" and "Disposed" already exist in every tenant and cover
# operate / receive / maintain / dispose, so only the missing stages are added.
LIFECYCLE_STATUSES = [
    {"name": "Planned", "description": "Lifecycle 1: demand captured, not yet ordered", "color": "#8b5cf6", "order": 10, "aliases": []},
    {"name": "Procured", "description": "Lifecycle 1: ordered / purchased, awaiting delivery", "color": "#6366f1", "order": 20, "aliases": ["Ordered"]},
    {"name": "Received", "description": "Lifecycle 2: received and registered, awaiting commissioning", "color": "#0ea5e9", "order": 30, "aliases": []},
    {"name": "Commissioning", "description": "Lifecycle 3: being installed and accepted", "color": "#14b8a6", "order": 40, "aliases": []},
    {"name": "Under change", "description": "Lifecycle 5: change or upgrade in progress", "color": "#f97316", "order": 70, "aliases": ["Under upgrade"]},
    {"name": "Retired", "description": "Lifecycle 7: decommissioned, not yet disposed", "color": "#475569", "order": 90, "aliases": ["Decommissioned"]},
]


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _missing(definitions, existing_names):
    """Definitions whose name and aliases are all absent from existing_names (lower-case set)."""
    result = []
    for d in definitions:
        names = {_norm(d["name"])} | {_norm(a) for a in d.get("aliases", [])}
        if not (names & existing_names):
            result.append(d)
    return result


def setup_ot_lifecycle(tenant_id=None):
    """Create the missing OT asset types and lifecycle statuses. Returns {tenant: (types, statuses)}."""
    db = SessionLocal()
    summary = {}
    try:
        query = db.query(Tenant)
        if tenant_id:
            query = query.filter(Tenant.id == tenant_id)
        tenants = query.all()
        if not tenants:
            print("No tenant found.")
            return summary

        for tenant in tenants:
            type_names = {_norm(n) for (n,) in db.query(AssetType.name).filter(AssetType.tenant_id == tenant.id)}
            status_names = {_norm(n) for (n,) in db.query(AssetStatus.name).filter(AssetStatus.tenant_id == tenant.id)}

            new_types = _missing(OT_ASSET_TYPES, type_names)
            new_statuses = _missing(LIFECYCLE_STATUSES, status_names)

            for d in new_types:
                db.add(AssetType(
                    name=d["name"], description=d["description"],
                    purdue_level=d["purdue_level"], tenant_id=tenant.id,
                ))
            for d in new_statuses:
                db.add(AssetStatus(
                    name=d["name"], description=d["description"], color=d["color"],
                    order=d["order"], tenant_id=tenant.id,
                ))
            summary[tenant.name] = ([d["name"] for d in new_types], [d["name"] for d in new_statuses])

        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    tid = uuid.UUID(sys.argv[1]) if len(sys.argv) > 1 else None
    for tenant_name, (types, statuses) in setup_ot_lifecycle(tid).items():
        print(f"{tenant_name}: +{len(types)} asset types, +{len(statuses)} statuses")
        if types:
            print("   types   :", ", ".join(types))
        if statuses:
            print("   statuses:", ", ".join(statuses))
