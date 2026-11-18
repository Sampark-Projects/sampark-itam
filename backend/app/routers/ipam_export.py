"""CSV export of IPAM prefixes, IP addresses and VLANs. Needs the read level (1) of the `ipam` section, like the lists."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services import ipam_csv
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.ipam_service import bad, check_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam/export", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])


@router.get("/{kind}")
def export_csv(kind: str, vrf_id: Optional[uuid.UUID] = None, global_table: bool = Query(False), audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """prefixes, ip-addresses or vlans as a CSV file with the columns the import reads. vrf_id or global_table limit the
    prefixes and addresses to one routing table."""
    if kind not in ipam_csv.KINDS:
        raise bad("Unknown kind of file", 404)
    if vrf_id:
        from app.models import IpamVrf
        check_owned(db, IpamVrf, current_user.tenant_id, vrf_id, "VRF")
    rows = ipam_csv.export_rows(db, current_user.tenant_id, kind, vrf_id, global_table)
    audit.log("export", "IpamCsvExport", None, f"Exported {len(rows)} {kind} to CSV", None, {"kind": kind, "rows": len(rows)})
    name = f"ipam-{kind}-{datetime.utcnow():%Y%m%d}.csv"
    return StreamingResponse(ipam_csv.write_csv(kind, rows), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
