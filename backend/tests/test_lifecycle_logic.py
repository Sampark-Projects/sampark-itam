"""Pure tests for the phase 2 lifecycle rules (no database)."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import lifecycle_logic as ll


def entry(maker="Siemens", model="S7-1200", eos=None, eosl=None, eol=None):
    return SimpleNamespace(
        manufacturer_name=maker, model_pattern=model,
        end_of_sale_date=eos, end_of_support_date=eosl, end_of_life_date=eol,
    )


def test_lead_days_are_cleaned_and_sorted():
    assert ll.normalize_lead_days([7, 90, 30, 30]) == [90, 30, 7]
    assert ll.normalize_lead_days([30.0]) == [30]


@pytest.mark.parametrize("bad", [None, [], "30", [0], [-5], [3651], [True], ["7"], [1.5], list(range(1, 14))])
def test_bad_lead_days_are_rejected(bad):
    with pytest.raises(ll.LifecycleInputError):
        ll.normalize_lead_days(bad)


def test_threshold_is_the_step_reached():
    steps = [90, 30, 7]
    assert ll.threshold_for(120, steps) is None      # nothing due yet
    assert ll.threshold_for(90, steps) == 90
    assert ll.threshold_for(60, steps) == 90
    assert ll.threshold_for(20, steps) == 30         # first seen late: one alert, at the 30 step
    assert ll.threshold_for(7, steps) == 7
    assert ll.threshold_for(0, steps) == 7           # the expiry day is not yet expired
    assert ll.threshold_for(-1, steps) == 0          # expired
    assert ll.threshold_for(-365, steps) == 0
    assert ll.threshold_for(-366, steps) is None     # history


def test_days_until():
    assert ll.days_until(date(2026, 3, 11), date(2026, 3, 1)) == 10
    assert ll.days_until(date(2026, 2, 28), date(2026, 3, 1)) == -1


def test_model_matching_is_case_insensitive_with_wildcards():
    assert ll.model_matches("S7-1200", "s7-1200")
    assert ll.model_matches("S7-12*", "S7-1214C DC/DC/DC")
    assert ll.model_matches("CP 1?43", "cp 1543")
    assert not ll.model_matches("S7-1200", "S7-1200 PLUS")   # exact means exact
    assert not ll.model_matches("", "S7")
    assert not ll.model_matches("S7*", None)
    assert ll.model_matches("S7  1200", "s7 1200")            # whitespace is normalised


def test_most_specific_entry_wins():
    broad = entry(model="S7-*", eosl=date(2030, 1, 1))
    narrow = entry(model="S7-12*", eosl=date(2028, 1, 1))
    exact = entry(model="S7-1200", eosl=date(2027, 1, 1))
    assert ll.match_vendor_entry([broad, narrow], "siemens", "S7-1214") is narrow
    assert ll.match_vendor_entry([broad, narrow, exact], "SIEMENS", "S7-1200") is exact
    assert ll.match_vendor_entry([broad], "Rockwell", "S7-1200") is None   # other manufacturer
    assert ll.match_vendor_entry([broad], None, "S7-1200") is None
    assert ll.match_vendor_entry([broad], "Siemens", None) is None


def test_obsolescence_date_prefers_earliest_support_end():
    assert ll.obsolescence_date(entry(eosl=date(2028, 1, 1), eol=date(2030, 1, 1))) == date(2028, 1, 1)
    assert ll.obsolescence_date(entry(eol=date(2030, 1, 1))) == date(2030, 1, 1)
    assert ll.obsolescence_date(entry(eos=date(2025, 1, 1))) is None   # end of sale is not obsolescence
    assert ll.obsolescence_date(None) is None


def test_obsolescence_state():
    today = date(2026, 6, 1)
    assert ll.obsolescence_state(None, today) == "unknown"
    assert ll.obsolescence_state(date(2026, 5, 31), today) == "obsolete"
    assert ll.obsolescence_state(date(2026, 6, 1), today) == "soon"
    assert ll.obsolescence_state(date(2027, 6, 1), today) == "soon"
    assert ll.obsolescence_state(date(2027, 6, 2), today) == "later"


CSV_OK = (
    "Manufacturer,Model,End of Sale,End of Support,End of Life,Source\n"
    "Siemens,S7-1200,2024-01-31,31/12/2028,,Siemens lifecycle site\n"
    "Rockwell,1756-*,,,2030-06-30,\n"
    ",,,,,\n"
)


def test_csv_is_parsed_with_aliases_and_date_formats():
    rows, errors = ll.parse_vendor_csv(CSV_OK)
    assert errors == []
    assert len(rows) == 2
    assert rows[0]["end_of_support_date"] == date(2028, 12, 31)
    assert rows[0]["source"] == "Siemens lifecycle site"
    assert rows[1]["end_of_life_date"] == date(2030, 6, 30)
    assert rows[1]["source"] is None


def test_csv_accepts_semicolons_bom_and_vendor_headers():
    rows, errors = ll.parse_vendor_csv("﻿vendor;model;eol\nABB;AC500;2031-01-01\n")
    assert errors == [] and rows[0]["manufacturer_name"] == "ABB"


def test_csv_bad_rows_are_reported_and_good_rows_kept():
    text = "manufacturer,model,end_of_support\nA,M1,2030-01-01\nB,,2030-01-01\nC,M3,not-a-date\nD,M4,\n"
    rows, errors = ll.parse_vendor_csv(text)
    assert [r["model_pattern"] for r in rows] == ["M1"]
    assert [e["line"] for e in errors] == [3, 4, 5]


def test_csv_needs_manufacturer_and_model_columns():
    with pytest.raises(ll.LifecycleInputError):
        ll.parse_vendor_csv("name,eol\nX,2030-01-01\n")
    with pytest.raises(ll.LifecycleInputError):
        ll.parse_vendor_csv("")
