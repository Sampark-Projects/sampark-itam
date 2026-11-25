"""Pure tests for configuration management rules."""
from datetime import datetime, timedelta

import pytest

from app.services import config_logic as cl


def test_extension_is_short_and_safe():
    assert cl.safe_extension("Line1.ZAP") == ".zap"
    assert cl.safe_extension("backup.tar.gz") == ".gz"
    assert cl.safe_extension("noext") == ""
    assert cl.safe_extension("evil.php;rm") == ""
    assert cl.safe_extension("a.verylongextension") == ""
    assert cl.safe_extension("C:\\dir\\prog.acd") == ".acd"
    assert cl.safe_extension(None) == ""


def test_displayed_filename_is_cleaned():
    assert cl.clean_filename("../../etc/passwd") == "passwd"
    assert cl.clean_filename("C:\\x\\prog.zap") == "prog.zap"
    assert cl.clean_filename("a\x00b\x1f.txt") == "ab.txt"
    assert cl.clean_filename("") == "file" and cl.clean_filename(None) == "file"
    assert len(cl.clean_filename("x" * 400)) == 255


def test_text_detection():
    assert cl.text_content(b"hello\nworld") == "hello\nworld"
    assert cl.text_content("\ufeffbom".encode("utf-8")) == "bom"
    assert cl.text_content(b"bin\x00ary") is None
    assert cl.text_content(b"\xff\xfe\xfa") is None
    assert cl.text_content(b"a" * (cl.MAX_TEXT_BYTES + 1)) is None


def test_diff_counts_and_truncation():
    d = cl.diff_text("a\nb\nc", "a\nB\nc\nd", "v1", "v2")
    assert d["added"] == 2 and d["removed"] == 1 and not d["truncated"]
    assert d["lines"][0] == "--- v1" and d["lines"][1] == "+++ v2"
    same = cl.diff_text("x\ny", "x\ny", "v1", "v2")
    assert same["lines"] == [] and same["added"] == 0 and same["removed"] == 0
    big = cl.diff_text("", "\n".join(str(i) for i in range(5000)), "a", "b", max_lines=100)
    assert big["truncated"] and len(big["lines"]) == 100 and big["added"] == 5000


def test_baseline_state():
    assert cl.baseline_state(None, None) == "no_versions"
    assert cl.baseline_state("a", None) == "no_versions"
    assert cl.baseline_state(None, "a") == "no_baseline"
    assert cl.baseline_state("a", "a") == "matches"
    assert cl.baseline_state("a", "b") == "differs"


def test_backup_state():
    now = datetime(2026, 6, 10)
    assert cl.backup_state(None, 30, now) == "none"
    assert cl.backup_state(now - timedelta(days=100), None, now) == "unmanaged"
    assert cl.backup_state(now - timedelta(days=29), 30, now) == "ok"
    assert cl.backup_state(now - timedelta(days=30), 30, now) == "ok"       # exactly on the limit
    assert cl.backup_state(now - timedelta(days=31), 30, now) == "stale"


def test_interval_validation():
    assert cl.clean_interval(None) is None and cl.clean_interval("") is None
    assert cl.clean_interval(30) == 30
    for bad in (0, -1, 3651, True, "30", 1.5):
        with pytest.raises(cl.ConfigInputError):
            cl.clean_interval(bad)
