"""Pure tests for the asset tag / naming standard (no database)."""
from datetime import date

import pytest

from app.services import tag_standard as ts


def test_render_zero_pads_and_fills_tokens():
    assert ts.render("DEW-{SITE}-PLC-{SEQ:4}", 7, "P1") == "DEW-P1-PLC-0007"
    assert ts.render("{YYYY}/{SEQ}", 12, today=date(2026, 3, 1)) == "2026/12"
    assert ts.render("A{YY}-{SEQ:3}", 5, today=date(2026, 3, 1)) == "A26-005"


def test_counter_can_outgrow_the_padding():
    assert ts.render("X-{SEQ:2}", 1234) == "X-1234"


def test_matches_what_it_generates():
    for pattern, site in [("DEW-{SITE}-PLC-{SEQ:4}", "P1"), ("{YYYY}-{SEQ:3}", None), ("PLC {SEQ}", None)]:
        assert ts.matches(pattern, ts.render(pattern, 42, site), site)


def test_matching_is_case_insensitive_and_strict():
    assert ts.matches("DEW-PLC-{SEQ:4}", "dew-plc-0001")
    assert not ts.matches("DEW-PLC-{SEQ:4}", "DEW-PLC-001")        # too few digits
    assert not ts.matches("DEW-PLC-{SEQ:4}", "XDEW-PLC-0001")      # anchored
    assert not ts.matches("DEW-PLC-{SEQ:4}", "DEW-PLC-0001 ")      # trailing space
    assert not ts.matches("DEW-{SITE}-{SEQ:2}", "DEW-P2-01", "P1")  # other site code


def test_site_code_is_escaped_in_the_regex():
    assert ts.matches("{SITE}-{SEQ:2}", "A.B-01", "A.B")
    assert not ts.matches("{SITE}-{SEQ:2}", "AxB-01", "A.B")


@pytest.mark.parametrize("pattern", ["", "   ", "NOSEQ", "{SEQ}{SEQ}", "A-{SEQ:0}", "A-{SEQ:11}", "A-{BAD}-{SEQ}", "A-{SEQ", "A*{SEQ}", "x" * 101])
def test_bad_patterns_are_rejected(pattern):
    with pytest.raises(ts.PatternError):
        ts.check_pattern(pattern)


def test_good_pattern_is_trimmed():
    assert ts.check_pattern("  DEW-{SITE}-{SEQ:4} ") == "DEW-{SITE}-{SEQ:4}"
