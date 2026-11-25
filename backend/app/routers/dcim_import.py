"""CSV import and export of DCIM racks, device types and rack positions.

The import path contains /import/, so it needs level 4 (full administration) on the `dcim` section; the export is a read (level 1)."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services import dcim_csv
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.dcim_service import bad
from app.services.rbac import require_section_access

router = APIRouter(prefix="/dcim", tags=["dcim"], dependencies=[Depends(require_section_access("dcim"))])


@router.post("/import/csv/{kind}")
def import_csv(kind: str, file: UploadFile = File(...), dry_run: bool = Form(True), update_existing: bool = Form(False),
               skip_invalid: bool = Form(False), audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Import racks, device-types or rack-positions from a CSV file (the columns of the export). dry_run only reports;
    update_existing replaces the objects the rows match; skip_invalid imports the valid rows of a file that has invalid ones."""
    data = file.file.read(dcim_csv.MAX_BYTES + 1)
    result = dcim_csv.run_import(db, current_user, kind, data, dry_run=dry_run, update_existing=update_existing, skip_invalid=skip_invalid)
    if not dry_run:
        s = result["summary"]
        audit.log("create", "DcimCsvImport", None,
                  f"Imported {kind} from {file.filename or 'a CSV file'}: {s['create']} created, {s['update']} updated, "
                  f"{s['skipped_duplicate']} skipped, {s['skipped_invalid']} invalid", None,
                  {"kind": kind, "file": file.filename, **{k: v for k, v in s.items() if k != "ignored_columns"}, "update_existing": update_existing})
    return result


@router.get("/export/csv/{kind}")
def export_csv(kind: str, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """racks, device-types or rack-positions as a CSV file with the columns the import reads."""
    if kind not in dcim_csv.KINDS:
        raise bad("Unknown kind of file", 404)
    rows = dcim_csv.export_rows(db, current_user.tenant_id, kind)
    audit.log("export", "DcimCsvExport", None, f"Exported {len(rows)} {kind} to CSV", None, {"kind": kind, "rows": len(rows)})
    name = f"dcim-{kind}-{datetime.utcnow():%Y%m%d}.csv"
    return StreamingResponse(dcim_csv.write_csv(kind, rows), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
