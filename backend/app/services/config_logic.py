"""Pure rules for configuration management (no database, no files)."""
import difflib
import re
from datetime import datetime
from typing import Dict, List, Optional

KINDS = ("program", "configuration", "firmware", "other")
MAX_TEXT_BYTES = 512 * 1024          # larger text files are kept as files only, without a line-by-line view
MAX_DIFF_LINES = 2000
MAX_INTERVAL_DAYS = 3650


class ConfigInputError(ValueError):
    pass


def safe_extension(filename: Optional[str]) -> str:
    """The file extension to keep on disk: short, letters and digits only (".zap" -> ".zap")."""
    name = (filename or "").strip().replace("\\", "/").split("/")[-1]
    if "." not in name:
        return ""
    ext = name.rsplit(".", 1)[1].lower()
    return f".{ext}" if re.fullmatch(r"[a-z0-9]{1,10}", ext) else ""


def clean_filename(filename: Optional[str]) -> str:
    """Name shown to people: the base name only, control characters removed, max 255 characters."""
    name = (filename or "file").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return (name or "file")[:255]


def text_content(data: bytes) -> Optional[str]:
    """The decoded text when the file is a small text file (UTF-8, no NUL bytes), else None."""
    if len(data) > MAX_TEXT_BYTES or b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def diff_text(old: str, new: str, old_label: str, new_label: str, max_lines: int = MAX_DIFF_LINES) -> Dict:
    """A unified diff with counts. Lines beyond max_lines are dropped and `truncated` is set."""
    lines = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(), fromfile=old_label, tofile=new_label, lineterm="", n=3))
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    truncated = len(lines) > max_lines
    return {"lines": lines[:max_lines], "added": added, "removed": removed, "truncated": truncated}


def baseline_state(baseline_sha: Optional[str], latest_sha: Optional[str]) -> str:
    """no_versions / no_baseline / matches / differs: how the newest version stands against the golden one."""
    if latest_sha is None:
        return "no_versions"
    if baseline_sha is None:
        return "no_baseline"
    return "matches" if baseline_sha == latest_sha else "differs"


def backup_state(last_at: Optional[datetime], interval_days: Optional[int], now: Optional[datetime] = None) -> str:
    """none (nothing stored) / unmanaged (no interval set) / ok / stale."""
    if last_at is None:
        return "none"
    if not interval_days:
        return "unmanaged"
    now = now or datetime.utcnow()
    return "stale" if (now - last_at).total_seconds() > interval_days * 86400 else "ok"


def clean_interval(value) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= MAX_INTERVAL_DAYS):
        raise ConfigInputError(f"the backup interval must be between 1 and {MAX_INTERVAL_DAYS} days")
    return value
