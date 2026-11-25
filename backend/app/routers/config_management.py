"""Configuration management API: versioned programs, configurations and firmware per asset."""
import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, ConfigArtifact, User
from app.services import config_service as cs
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext, snapshot
from app.services.rbac import require_section_access

ART_FIELDS = ("asset_id", "name", "kind", "description", "backup_interval_days", "baseline_version_id")
VER_FIELDS = ("artifact_id", "version_number", "label", "note", "file_name", "size_bytes", "sha256")

router = APIRouter(
    prefix="/config",
    tags=["config"],
    dependencies=[Depends(require_section_access("configurations"))],
)


class ArtifactIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: Literal["program", "configuration", "firmware", "other"]
    description: Optional[str] = Field(None, max_length=255)
    backup_interval_days: Optional[int] = Field(None, ge=1, le=3650)

    @field_validator("name", mode="before")
    @classmethod
    def _trim(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("description", mode="before")
    @classmethod
    def _blank(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v


def _asset(db: Session, tenant_id, asset_id) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    return asset


@router.get("/overview")
def overview(
    state: str = Query("attention", pattern="^(attention|all|drift|stale)$"),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    items = cs.overview(db, current_user.tenant_id, state)
    return {"total": len(items), "items": items}


@router.post("/alerts/run")
def run_alerts(audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send the overdue-backup alerts now (the scheduler does this once a day)."""
    result = cs.run_stale_alerts(db, current_user.tenant_id)
    audit.log("run", "ConfigAlerts", None, "Ran the overdue-backup alerts", None, result if isinstance(result, dict) else None)
    return result


@router.get("/compare")
def compare(a: uuid.UUID, b: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return cs.compare(db, current_user.tenant_id, a, b)


@router.get("/assets/{asset_id}/artifacts")
def asset_artifacts(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id)
    arts = db.query(ConfigArtifact).filter(
        ConfigArtifact.asset_id == asset.id, ConfigArtifact.tenant_id == current_user.tenant_id,
    ).order_by(ConfigArtifact.name).all()
    return [cs.serialize_artifact(db, a) for a in arts]


@router.post("/assets/{asset_id}/artifacts")
def create_artifact(
    asset_id: uuid.UUID, data: ArtifactIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    asset = _asset(db, current_user.tenant_id, asset_id)
    art = cs.create_artifact(db, asset, data)
    audit.log("create", "ConfigItem", art.id, f"Created configuration item '{art.name}' on '{asset.name}'",
              None, snapshot(art, ART_FIELDS))
    return cs.serialize_artifact(db, art)


@router.put("/artifacts/{artifact_id}")
def update_artifact(
    artifact_id: uuid.UUID, data: ArtifactIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    art = cs.get_artifact(db, current_user.tenant_id, artifact_id)
    old = snapshot(art, ART_FIELDS)
    art = cs.update_artifact(db, art, data)
    audit.log("update", "ConfigItem", art.id, f"Updated configuration item '{art.name}'", old, snapshot(art, ART_FIELDS))
    return cs.serialize_artifact(db, art)


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    art = cs.get_artifact(db, current_user.tenant_id, artifact_id)
    old, name = {**snapshot(art, ART_FIELDS), "versions": len(art.versions)}, art.name
    cs.delete_artifact(db, art)
    audit.log("delete", "ConfigItem", artifact_id, f"Deleted configuration item '{name}' and its versions", old, None)


@router.post("/artifacts/{artifact_id}/versions")
def upload_version(
    artifact_id: uuid.UUID,
    file: UploadFile = File(...),
    label: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    art = cs.get_artifact(db, current_user.tenant_id, artifact_id)
    label = (label or "").strip()[:100] or None
    note = (note or "").strip()[:5000] or None
    ver = cs.add_version(db, art, current_user, file, label, note)
    audit.log("upload", "ConfigVersion", ver.id, f"Uploaded version {ver.version_number} of '{art.name}'",
              None, snapshot(ver, VER_FIELDS))
    return cs.serialize_artifact(db, cs.get_artifact(db, current_user.tenant_id, artifact_id))


@router.get("/versions/{version_id}/download")
def download_version(version_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ver = cs.get_version(db, current_user.tenant_id, version_id)
    try:
        # decrypts if needed and re-checks the SHA-256 recorded at upload: a file changed on disk is not served
        path = cs.open_verified(ver)
    except ErrorCodeException as exc:
        if exc.error_code == ErrorCode.CONFIG_INTEGRITY_FAILED.value:
            audit.log("integrity_failure", "ConfigVersion", ver.id,
                      f"Stored file of '{ver.file_name}' (version {ver.version_number}) failed the integrity check")
        raise
    # programs and device configurations are sensitive: every download is recorded
    audit.log("download", "ConfigVersion", ver.id, f"Downloaded '{ver.file_name}' (version {ver.version_number})",
              None, snapshot(ver, VER_FIELDS))
    # always a download, never shown in the browser, whatever the file claims to be
    return FileResponse(
        path, media_type="application/octet-stream", filename=ver.file_name,
        headers={"X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),  # the temporary plain copy
    )


@router.delete("/versions/{version_id}", status_code=204)
def delete_version(version_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ver = cs.get_version(db, current_user.tenant_id, version_id)
    old = snapshot(ver, VER_FIELDS)
    cs.delete_version(db, ver)
    audit.log("delete", "ConfigVersion", version_id, f"Deleted version {old['version_number']} ('{old['file_name']}')", old, None)


@router.post("/versions/{version_id}/baseline")
def set_baseline(version_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ver = cs.get_version(db, current_user.tenant_id, version_id)
    art = cs.get_artifact(db, current_user.tenant_id, ver.artifact_id)
    old = {"baseline_version_id": art.baseline_version_id}
    art = cs.set_baseline(db, art, ver, current_user)
    audit.log("set_baseline", "ConfigItem", art.id, f"Set version {ver.version_number} as baseline of '{art.name}'",
              old, {"baseline_version_id": art.baseline_version_id})
    return cs.serialize_artifact(db, art)


@router.delete("/artifacts/{artifact_id}/baseline")
def clear_baseline(artifact_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    art = cs.get_artifact(db, current_user.tenant_id, artifact_id)
    old = {"baseline_version_id": art.baseline_version_id}
    art = cs.clear_baseline(db, art)
    audit.log("clear_baseline", "ConfigItem", art.id, f"Removed the baseline of '{art.name}'", old, {"baseline_version_id": None})
    return cs.serialize_artifact(db, art)
