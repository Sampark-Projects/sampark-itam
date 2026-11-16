"""Database and file side of configuration management."""
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Asset,
    ChangeRequest,
    ConfigAlertSent,
    ConfigArtifact,
    ConfigVersion,
    User,
)
from app.services import change_logic
from app.services import webhook_service
from app.services import config_logic as cl
from app.services import config_security as sec
from app.services.lifecycle_service import alert_recipients
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

ALERT_TEMPLATE = "config_alert"
MAX_CONFIG_BYTES = int(os.getenv("CONFIG_MAX_BYTES", str(50 * 1024 * 1024)))
CHUNK = 1024 * 1024


def _bad(code, detail=None, status_code=400):
    return ErrorCodeException(status_code=status_code, error_code=code, detail=detail)


def upload_root() -> Path:
    return Path(settings.UPLOAD_DIR)


def absolute_path(relative: str) -> Path:
    """The file on disk; never outside the uploads folder."""
    root = upload_root().resolve()
    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CONFIG_NOT_FOUND)
    return path


# --- artifacts --------------------------------------------------------------------------------

def get_artifact(db: Session, tenant_id, artifact_id) -> ConfigArtifact:
    art = db.query(ConfigArtifact).filter(ConfigArtifact.id == artifact_id, ConfigArtifact.tenant_id == tenant_id).first()
    if not art:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CONFIG_NOT_FOUND)
    return art


def get_version(db: Session, tenant_id, version_id) -> ConfigVersion:
    ver = db.query(ConfigVersion).filter(ConfigVersion.id == version_id, ConfigVersion.tenant_id == tenant_id).first()
    if not ver:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CONFIG_NOT_FOUND)
    return ver


def _check_interval(value):
    try:
        return cl.clean_interval(value)
    except cl.ConfigInputError as exc:
        raise _bad(ErrorCode.CONFIG_INVALID, str(exc))


def create_artifact(db: Session, asset: Asset, data) -> ConfigArtifact:
    if db.query(ConfigArtifact.id).filter(
            ConfigArtifact.asset_id == asset.id, func.lower(ConfigArtifact.name) == data.name.lower()).first():
        raise _bad(ErrorCode.CONFIG_DUPLICATE, status_code=409)
    art = ConfigArtifact(
        tenant_id=asset.tenant_id, asset_id=asset.id, name=data.name, kind=data.kind,
        description=data.description, backup_interval_days=_check_interval(data.backup_interval_days),
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


def update_artifact(db: Session, art: ConfigArtifact, data) -> ConfigArtifact:
    if db.query(ConfigArtifact.id).filter(
            ConfigArtifact.asset_id == art.asset_id, func.lower(ConfigArtifact.name) == data.name.lower(),
            ConfigArtifact.id != art.id).first():
        raise _bad(ErrorCode.CONFIG_DUPLICATE, status_code=409)
    art.name, art.kind, art.description = data.name, data.kind, data.description
    art.backup_interval_days = _check_interval(data.backup_interval_days)
    db.commit()
    db.refresh(art)
    return art


def _remove_file(relative: str) -> None:
    try:
        absolute_path(relative).unlink(missing_ok=True)
    except (OSError, ErrorCodeException):
        logger.warning("Could not remove file %s", relative)


def delete_artifact(db: Session, art: ConfigArtifact) -> None:
    paths = [v.file_path for v in art.versions]
    art.baseline_version_id = None
    db.flush()
    db.delete(art)
    db.commit()
    for p in paths:
        _remove_file(p)
    try:  # the item's own folder, now empty
        absolute_path(str(Path("tenants") / str(art.tenant_id) / "configs" / str(art.id))).rmdir()
    except (OSError, ErrorCodeException):
        pass


# --- versions ---------------------------------------------------------------------------------

def _scan(upload):
    """Virus scan before anything is stored. An infected file is refused; if a scanner is configured
    but unreachable the upload is refused too, unless CONFIG_SCAN_FAIL_OPEN is set."""
    try:
        return sec.scan(upload.file)
    except sec.Infected as exc:
        raise _bad(ErrorCode.CONFIG_INFECTED, f"Malware detected: {exc.signature}", 422)
    except sec.ScanError as exc:
        logger.error("Configuration file scan failed: %s", exc)
        if sec.fail_open():
            return "error", str(exc)[:255]
        raise _bad(ErrorCode.CONFIG_SCAN_UNAVAILABLE, "The virus scanner could not be reached", 503)


def open_verified(ver: ConfigVersion):
    """(temporary plain copy, path to delete afterwards) after checking the stored file against the
    checksum recorded at upload. Raises CONFIG_INTEGRITY_FAILED (409) on any mismatch."""
    path = absolute_path(ver.file_path)
    if not path.is_file():
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CONFIG_NOT_FOUND)
    try:
        tmp, _ = sec.verified_copy(path, bool(ver.encrypted), ver.sha256)
    except sec.IntegrityError as exc:
        logger.error("Integrity check failed for config version %s: %s", ver.id, exc)
        raise _bad(ErrorCode.CONFIG_INTEGRITY_FAILED, str(exc), 409)
    return tmp


def add_version(
    db: Session, art: ConfigArtifact, user: User, upload, label: Optional[str], note: Optional[str],
    change_request_id=None,
) -> ConfigVersion:
    if change_request_id and not db.query(ChangeRequest.id).filter(
            ChangeRequest.id == change_request_id, ChangeRequest.tenant_id == art.tenant_id).first():
        raise _bad(ErrorCode.CONFIG_INVALID, "Unknown change request")

    relative_dir = Path("tenants") / str(art.tenant_id) / "configs" / str(art.id)
    relative = relative_dir / f"{uuid.uuid4()}{cl.safe_extension(upload.filename)}"
    target = upload_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)

    scan_status, scan_detail = _scan(upload)
    encrypt = sec.encryption_enabled()
    digest, head, seen = hashlib.sha256(), bytearray(), [0]

    def on_plain(chunk: bytes) -> None:
        seen[0] += len(chunk)
        if seen[0] > MAX_CONFIG_BYTES:
            raise _bad(ErrorCode.CONFIG_FILE_TOO_LARGE, f"Maximum {MAX_CONFIG_BYTES // (1024 * 1024)} MB", 413)
        digest.update(chunk)
        if len(head) <= cl.MAX_TEXT_BYTES:
            head.extend(chunk)

    try:
        with target.open("wb") as out:
            if encrypt:  # the file on disk is encrypted; the checksum is of the original content
                sec.encrypt_stream(upload.file, out, on_plain)
            else:
                while True:
                    chunk = upload.file.read(CHUNK)
                    if not chunk:
                        break
                    on_plain(chunk)
                    out.write(chunk)
        size = seen[0]
        if size == 0:
            raise _bad(ErrorCode.CONFIG_INVALID, "The file is empty")
    except Exception:
        target.unlink(missing_ok=True)
        raise

    text = cl.text_content(bytes(head)) if size <= cl.MAX_TEXT_BYTES else None
    for _ in range(3):
        number = (db.query(func.max(ConfigVersion.version_number)).filter(ConfigVersion.artifact_id == art.id).scalar() or 0) + 1
        ver = ConfigVersion(
            tenant_id=art.tenant_id, artifact_id=art.id, version_number=number, label=label, note=note,
            file_name=cl.clean_filename(upload.filename), file_path=str(relative).replace("\\", "/"),
            size_bytes=size, sha256=digest.hexdigest(), content_text=sec.protect_text(text),
            encrypted=encrypt, scan_status=scan_status, scan_detail=scan_detail,
            change_request_id=change_request_id, uploaded_by=user.id,
        )
        db.add(ver)
        try:
            db.commit()
            break
        except IntegrityError:  # another upload took this number
            db.rollback()
    else:
        target.unlink(missing_ok=True)
        raise _bad(ErrorCode.CONFIG_INVALID, "Could not allocate a version number", 409)
    db.refresh(ver)

    art = db.query(ConfigArtifact).filter(ConfigArtifact.id == art.id).first()
    if art.baseline_version_id:
        baseline = db.query(ConfigVersion).filter(ConfigVersion.id == art.baseline_version_id).first()
        if baseline and baseline.sha256 != ver.sha256:
            webhook_service.emit(art.tenant_id, "config.drift", {
                "artifact_id": str(art.id), "artifact": art.name, "asset_id": str(art.asset_id),
                "version": ver.version_number, "sha256": ver.sha256, "baseline_sha256": baseline.sha256,
            })
            send_alert(db, art, "drift", ver)
    return ver


def set_baseline(db: Session, art: ConfigArtifact, ver: ConfigVersion, user: User) -> ConfigArtifact:
    if ver.artifact_id != art.id:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CONFIG_NOT_FOUND)
    art.baseline_version_id, art.baseline_set_by, art.baseline_set_at = ver.id, user.id, datetime.utcnow()
    db.commit()
    db.refresh(art)
    return art


def clear_baseline(db: Session, art: ConfigArtifact) -> ConfigArtifact:
    art.baseline_version_id = art.baseline_set_by = art.baseline_set_at = None
    db.commit()
    db.refresh(art)
    return art


def delete_version(db: Session, ver: ConfigVersion) -> None:
    art = db.query(ConfigArtifact).filter(ConfigArtifact.id == ver.artifact_id).first()
    if art and art.baseline_version_id == ver.id:
        raise _bad(ErrorCode.CONFIG_BASELINE_VERSION, status_code=409)
    path = ver.file_path
    db.delete(ver)
    db.commit()
    _remove_file(path)


def compare(db: Session, tenant_id, a_id, b_id) -> Dict:
    a, b = get_version(db, tenant_id, a_id), get_version(db, tenant_id, b_id)
    if a.artifact_id != b.artifact_id:
        raise _bad(ErrorCode.CONFIG_INVALID, "The versions belong to different items")
    meta = lambda v: {"id": v.id, "version_number": v.version_number, "label": v.label, "file_name": v.file_name,
                      "size_bytes": v.size_bytes, "sha256": v.sha256, "uploaded_at": v.uploaded_at}
    out = {"a": meta(a), "b": meta(b), "identical": a.sha256 == b.sha256, "text": False, "diff": None}
    if not out["identical"] and a.content_text is not None and b.content_text is not None:
        try:
            text_a, text_b = sec.reveal_text(a.content_text), sec.reveal_text(b.content_text)
        except sec.IntegrityError:
            raise _bad(ErrorCode.CONFIG_INTEGRITY_FAILED, None, 409)
        out["text"] = True
        out["diff"] = cl.diff_text(text_a, text_b, f"v{a.version_number}", f"v{b.version_number}")
    return out


# --- reading ----------------------------------------------------------------------------------

def serialize_artifact(db: Session, art: ConfigArtifact, with_versions: bool = True) -> Dict:
    versions = list(art.versions)  # newest first
    latest = versions[0] if versions else None
    baseline = next((v for v in versions if v.id == art.baseline_version_id), None)
    ids = {x for v in versions for x in (v.uploaded_by,) if x} | ({art.baseline_set_by} if art.baseline_set_by else set())
    names = {u.id: (u.name or u.email) for u in db.query(User).filter(User.id.in_(ids or [uuid.uuid4()])).all()}
    cr_ids = {v.change_request_id for v in versions if v.change_request_id}
    codes = {c.id: change_logic.format_number(c.number) for c in db.query(ChangeRequest).filter(
        ChangeRequest.id.in_(cr_ids or [uuid.uuid4()])).all()}
    out = {
        "id": art.id, "asset_id": art.asset_id, "name": art.name, "kind": art.kind, "description": art.description,
        "backup_interval_days": art.backup_interval_days,
        "baseline_version_id": art.baseline_version_id,
        "baseline_set_by": names.get(art.baseline_set_by), "baseline_set_at": art.baseline_set_at,
        "version_count": len(versions),
        "latest": ({"id": latest.id, "version_number": latest.version_number, "label": latest.label,
                    "uploaded_at": latest.uploaded_at} if latest else None),
        "baseline_state": cl.baseline_state(baseline.sha256 if baseline else None, latest.sha256 if latest else None),
        "backup_state": cl.backup_state(latest.uploaded_at if latest else None, art.backup_interval_days),
    }
    if with_versions:
        out["versions"] = [{
            "id": v.id, "version_number": v.version_number, "label": v.label, "note": v.note,
            "file_name": v.file_name, "size_bytes": v.size_bytes, "sha256": v.sha256,
            "encrypted": bool(v.encrypted), "scan_status": v.scan_status,
            "has_text": v.content_text is not None, "uploaded_by": names.get(v.uploaded_by),
            "uploaded_at": v.uploaded_at, "is_baseline": v.id == art.baseline_version_id,
            "change_request": codes.get(v.change_request_id),
        } for v in versions]
    return out


def overview(db: Session, tenant_id, state: str = "attention") -> List[Dict]:
    """Every item with its states. `attention` keeps drifted, stale, unprotected (no baseline) and empty ones."""
    rows = (
        db.query(ConfigArtifact, Asset)
        .join(Asset, Asset.id == ConfigArtifact.asset_id)
        .filter(ConfigArtifact.tenant_id == tenant_id, Asset.deleted_at.is_(None))
        .order_by(Asset.name, ConfigArtifact.name)
        .all()
    )
    items = []
    for art, asset in rows:
        item = serialize_artifact(db, art, with_versions=False)
        item.update({"asset_name": asset.name, "asset_tag": asset.tag})
        bad = item["baseline_state"] in ("differs", "no_baseline", "no_versions") or item["backup_state"] in ("stale", "none")
        if state == "all" or (state == "attention" and bad) or (
                state == "drift" and item["baseline_state"] == "differs") or (
                state == "stale" and item["backup_state"] == "stale"):
            items.append(item)
    return items


# --- alerts -----------------------------------------------------------------------------------

def send_alert(db: Session, art: ConfigArtifact, kind: str, ref: Optional[ConfigVersion]) -> int:
    """E-mail the owners and contacts of the asset once per drift (per version) or stale backup."""
    ref_id = ref.id if ref else art.id
    if db.query(ConfigAlertSent.id).filter(
            ConfigAlertSent.artifact_id == art.id, ConfigAlertSent.kind == kind, ConfigAlertSent.ref_id == ref_id).first():
        return 0
    asset = db.query(Asset).filter(Asset.id == art.asset_id).first()
    if asset is None:
        return 0
    recipients = alert_recipients(db, asset)
    if not recipients:
        return 0  # not recorded: it goes out once someone is set as owner or contact
    if kind == "drift":
        cr_text = "no change request referenced"
        if ref and ref.change_request_id:
            cr = db.query(ChangeRequest).filter(ChangeRequest.id == ref.change_request_id).first()
            if cr:
                cr_text = f"change request {change_logic.format_number(cr.number)} ({cr.status})"
        message = (f"Version {ref.version_number} differs from the golden baseline; {cr_text}.")
        title = "differs from baseline"
    else:
        message = f"No new version has been stored for {art.backup_interval_days} days."
        title = "backup is overdue"
    sent = 0
    for user in recipients:
        context = {
            "user_name": user.name or user.email, "artifact_name": art.name, "asset_name": asset.name,
            "asset_id": str(asset.id), "site_id": str(asset.site_id), "alert_title": title, "message": message,
            "asset_url": f"/assets/{asset.id}",
        }
        try:
            if NotificationService.send_notification(db, user.id, ALERT_TEMPLATE, context):
                sent += 1
        except Exception as exc:
            logger.error("Configuration alert to %s failed: %s", user.id, exc)
            db.rollback()
    db.add(ConfigAlertSent(tenant_id=art.tenant_id, artifact_id=art.id, kind=kind, ref_id=ref_id, recipients=sent))
    db.commit()
    return sent


def run_stale_alerts(db: Session, tenant_id) -> Dict[str, int]:
    """Backups that are overdue. Each stale period alerts once; a new version starts a new period."""
    result = {"checked": 0, "alerts": 0}
    arts = (
        db.query(ConfigArtifact).join(Asset, Asset.id == ConfigArtifact.asset_id)
        .filter(ConfigArtifact.tenant_id == tenant_id, ConfigArtifact.backup_interval_days.isnot(None),
                Asset.deleted_at.is_(None)).all()
    )
    for art in arts:
        latest = art.versions[0] if art.versions else None
        result["checked"] += 1
        if cl.backup_state(latest.uploaded_at if latest else art.created_at, art.backup_interval_days) != "stale":
            continue
        if send_alert(db, art, "stale", latest):
            result["alerts"] += 1
    return result


def run_stale_alerts_all_tenants(db: Session) -> Dict:
    from app.models import Tenant
    out = {}
    for tenant in db.query(Tenant).all():
        try:
            out[str(tenant.id)] = run_stale_alerts(db, tenant.id)
        except Exception as exc:
            logger.error("Config alerts failed for tenant %s: %s", tenant.id, exc, exc_info=True)
            db.rollback()
    return out
