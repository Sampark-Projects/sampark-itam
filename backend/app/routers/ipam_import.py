"""Import into IPAM from other parts of the application. The path contains /import/, so it needs level 4 (full
administration) on the `ipam` section."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services import ipam_csv, ipam_import
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam/import", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])


class InterfaceImportIn(BaseModel):
    vrf_id: Optional[uuid.UUID] = None  # the routing table for the addresses (empty: the global table)
    per_site: bool = False  # one VRF per site, named after the site (created when missing); assets without a site use vrf_id
    create_prefixes: bool = False  # also create the network of every address that has a mask shorter than a host
    dry_run: bool = True  # only report what would happen


@router.post("/csv/{kind}")
def import_csv(kind: str, file: UploadFile = File(...), dry_run: bool = Form(True), update_existing: bool = Form(False),
               skip_invalid: bool = Form(False), audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Import prefixes, ip-addresses or vlans from a CSV file (the columns of the export). dry_run only reports;
    update_existing replaces the objects the rows match; skip_invalid imports the valid rows of a file that has invalid ones."""
    data = file.file.read(ipam_csv.MAX_BYTES + 1)
    result = ipam_csv.run_import(db, current_user, kind, data, dry_run=dry_run, update_existing=update_existing, skip_invalid=skip_invalid)
    if not dry_run:
        s = result["summary"]
        audit.log("create", "IpamCsvImport", None,
                  f"Imported {kind} from {file.filename or 'a CSV file'}: {s['create']} created, {s['update']} updated, "
                  f"{s['skipped_duplicate']} skipped, {s['skipped_invalid']} invalid", None,
                  {"kind": kind, "file": file.filename, **{k: v for k, v in s.items() if k != "ignored_columns"}, "update_existing": update_existing})
    return result


@router.post("/asset-interfaces")
def import_asset_interfaces(data: InterfaceImportIn, audit: AuditContext = Depends(),
                            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create IPAM addresses from the IP addresses typed on asset interfaces, assigned to those interfaces."""
    result = ipam_import.run(db, current_user, vrf_id=data.vrf_id, per_site=data.per_site,
                             create_prefixes=data.create_prefixes, dry_run=data.dry_run)
    if not data.dry_run:
        s = result["summary"]
        audit.log("create", "IpamImport", None,
                  f"Imported IP addresses from asset interfaces: {s['create']} created, {s['link']} linked, "
                  f"{s['prefixes_to_create']} prefix(es)", None, {**s, "per_site": data.per_site, "create_prefixes": data.create_prefixes})
    return result
