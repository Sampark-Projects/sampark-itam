"""Pure tests for the site hierarchy helpers."""
from app.services import site_tree as st

# company > plant dewas > units engine, axle ; plant pune (alone) ; a bad loop x <-> y
PARENTS = {
    "company": None, "dewas": "company", "engine": "dewas", "axle": "dewas", "pune": None,
    "x": "y", "y": "x",
}


def test_ancestors_start_with_the_site():
    assert st.ancestors(PARENTS, "engine") == ["engine", "dewas", "company"]
    assert st.ancestors(PARENTS, "pune") == ["pune"]
    assert st.ancestors(PARENTS, None) == []


def test_descendants_include_every_unit():
    assert sorted(st.descendants(PARENTS, "dewas")) == ["axle", "dewas", "engine"]
    assert sorted(st.descendants(PARENTS, "company")) == ["axle", "company", "dewas", "engine"]
    assert st.descendants(PARENTS, "engine") == ["engine"]


def test_top_level_site():
    assert st.top(PARENTS, "axle") == "company"
    assert st.top(PARENTS, "pune") == "pune"


def test_a_loop_in_the_data_does_not_hang():
    assert len(st.ancestors(PARENTS, "x")) == 2
    assert sorted(st.descendants(PARENTS, "x")) == ["x", "y"]


def test_nearest_value_up_the_chain():
    values = {"dewas": 5, "company": 9}
    assert st.nearest(PARENTS, "engine", values) == 5
    assert st.nearest(PARENTS, "dewas", {"company": 9}) == 9
    assert st.nearest(PARENTS, "pune", values) is None
    assert st.nearest(PARENTS, "engine", {"engine": 1, "dewas": 5}) == 1
