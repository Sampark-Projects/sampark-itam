"""The asset type import file: one row per field, preview and confirm agree, blank cells never clear, bad rows leave a type out."""
import csv
import io
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import AssetType
from app.routers import asset_types as asset_types_router
from app.services import asset_type_import as imp
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

FULL = {**ADMIN_DEFAULT_PERMISSIONS, "asset_types": 4}
TEMPLATE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "template_import_asset_type.csv"


def client(db, w, permissions=FULL):
    api = FastAPI()
    api.include_router(asset_types_router.router)
    api.dependency_overrides[get_db] = lambda: db
    user = w.user(permissions)
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def file_of(rows, name="types.csv"):
    columns = []
    for r in rows:
        columns += [k for k in r if k not in columns]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return {"file": (name, buf.getvalue().encode("utf-8"), "text/csv")}


def run(c, rows):
    preview = c.post("/asset-types/import/xlsx/preview", files=file_of(rows)).json()
    confirm = c.post("/asset-types/import/xlsx/confirm", files=file_of(rows)).json()
    return preview, confirm


def stored(db, w, name):
    found = db.query(AssetType).filter(AssetType.tenant_id == w.tenant.id, AssetType.name == name).first()
    if found is not None:
        db.refresh(found)
    return found


def keys(at):
    return [f["key"] for f in at.fields_schema]


# --- creating -------------------------------------------------------------------------------------------

def test_a_type_with_several_fields_is_created_from_its_rows(db):
    w = World(db)
    c = client(db, w)
    rows = [
        {"name": "Switch", "description": "Network switch", "purdue_level": "3", "field_key": "ports", "field_label": "Ports", "field_type": "number", "field_required": "yes"},
        {"name": "Switch", "field_key": "mounting", "field_label": "Mounting", "field_type": "select", "field_options": "DIN rail|Rack, Wall"},
        {"name": "Switch", "field_key": "managed", "field_label": "Managed", "field_type": "Yes / No"},
        {"name": "Panel", "description": "HMI"},
    ]
    preview, confirm = run(c, rows)
    assert preview["errors"] == [] and [x["name"] for x in preview["to_create"]] == ["Switch", "Panel"]
    assert confirm == {"created": ["Switch", "Panel"], "updated": [], "errors": []}
    switch = stored(db, w, "Switch")
    assert (switch.description, switch.purdue_level, switch.tenant_id) == ("Network switch", 3.0, w.tenant.id)
    assert keys(switch) == ["ports", "mounting", "managed"]
    ports, mounting, managed = switch.fields_schema
    assert (ports["type"], ports["required"]) == ("number", True)
    assert (mounting["type"], mounting["options"]) == ("select", ["DIN rail", "Rack", "Wall"])
    assert managed["type"] == "boolean" and managed["required"] is False
    assert stored(db, w, "Panel").fields_schema == []


def test_the_same_file_again_changes_nothing(db):
    w = World(db)
    c = client(db, w)
    rows = [{"name": "Switch", "field_key": "ports", "field_label": "Ports", "field_type": "number"}]
    run(c, rows)
    preview, confirm = run(c, rows)
    assert preview == {"to_create": [], "to_update": [], "errors": []}
    assert confirm == {"created": [], "updated": [], "errors": []}


# --- updating -------------------------------------------------------------------------------------------

def existing_switch(w):
    at = AssetType(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Switch", description="Old", purdue_level=2.0,
                   fields_schema=[{"key": "ports", "label": "Ports", "type": "number", "required": False, "options": []},
                                  {"key": "owner", "label": "Owner", "type": "text", "required": False, "options": []}])
    w.db.add(at)
    w.db.commit()
    return at


def test_an_existing_type_gets_the_new_fields_and_keeps_the_others(db):
    w = World(db)
    existing_switch(w)
    c = client(db, w)
    rows = [{"name": "switch", "description": "New", "field_key": "ports", "field_label": "Port count", "field_type": "number", "field_required": "yes"},
            {"name": "Switch", "field_key": "poe", "field_label": "PoE", "field_type": "boolean"}]
    preview, confirm = run(c, rows)
    diff = preview["to_update"][0]["diff"]
    assert set(diff) == {"description", "field ports", "field poe"} and diff["description"] == {"old": "Old", "new": "New"}
    assert confirm["updated"] == ["Switch"] and confirm["errors"] == []
    at = stored(db, w, "Switch")
    assert (at.description, at.purdue_level) == ("New", 2.0)
    assert keys(at) == ["ports", "owner", "poe"]
    assert at.fields_schema[0]["label"] == "Port count" and at.fields_schema[0]["required"] is True


def test_a_blank_cell_never_clears_what_is_stored(db):
    w = World(db)
    existing_switch(w)
    c = client(db, w)
    preview, confirm = run(c, [{"name": "Switch", "description": "", "purdue_level": ""}])
    assert preview["to_update"] == [] and confirm["updated"] == []
    at = stored(db, w, "Switch")
    assert (at.description, at.purdue_level) == ("Old", 2.0) and keys(at) == ["ports", "owner"]


def test_the_type_of_an_existing_field_cannot_change(db):
    w = World(db)
    existing_switch(w)
    c = client(db, w)
    preview, confirm = run(c, [{"name": "Switch", "description": "X", "field_key": "ports", "field_label": "Ports", "field_type": "text"}])
    assert "cannot be changed" in preview["errors"][0]["error"] and preview["errors"][0]["row"] == 2
    assert confirm["updated"] == [] and stored(db, w, "Switch").description == "Old"


def test_a_global_type_is_not_changed_by_an_import(db):
    w = World(db)
    db.add(AssetType(id=uuid.uuid4(), tenant_id=None, name="Global Sensor", fields_schema=[]))
    db.commit()
    c = client(db, w)
    preview, confirm = run(c, [{"name": "Global Sensor", "description": "x"}])
    assert "global asset type" in preview["errors"][0]["error"] and confirm["created"] == [] and confirm["updated"] == []


# --- bad rows -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cols,text", [
    ({"purdue_level": "7"}, "purdue_level"),
    ({"purdue_level": "high"}, "purdue_level"),
    ({"field_key": "Bad Key", "field_label": "L"}, "key"),
    ({"field_key": "k", "field_label": "L", "field_type": "colour"}, "field_type"),
    ({"field_key": "k", "field_label": "L", "field_required": "maybe"}, "field_required"),
    ({"field_key": "k", "field_label": "L", "field_type": "select"}, "option"),
    ({"field_key": "k"}, "field_label"),
    ({"field_label": "L"}, "field_key"),
    ({"description": "x" * 300}, "description"),
])
def test_a_bad_cell_is_an_error_and_leaves_the_type_out(db, cols, text):
    w = World(db)
    c = client(db, w)
    good = {"name": "Good", "field_key": "ok", "field_label": "Ok"}
    preview, confirm = run(c, [{"name": "Bad", **cols}, good])
    assert preview["errors"] and text in preview["errors"][0]["error"] and preview["errors"][0]["row"] == 2
    assert [x["name"] for x in preview["to_create"]] == ["Good"]
    assert confirm["created"] == ["Good"] and stored(db, w, "Bad") is None


def test_one_bad_row_leaves_the_whole_type_out(db):
    w = World(db)
    c = client(db, w)
    rows = [{"name": "Switch", "field_key": "a", "field_label": "A"}, {"name": "Switch", "field_key": "a", "field_label": "A again"},
            {"name": "Switch", "field_key": "b", "field_label": "B"}]
    preview, confirm = run(c, rows)
    assert [e["row"] for e in preview["errors"]] == [3] and "twice" in preview["errors"][0]["error"]
    assert confirm["created"] == [] and stored(db, w, "Switch") is None


def test_rows_of_one_type_must_agree(db):
    w = World(db)
    c = client(db, w)
    preview, _ = run(c, [{"name": "T", "description": "one"}, {"name": "t", "description": "two"}])
    assert "differs" in preview["errors"][0]["error"]


def test_a_row_without_a_name_is_an_error(db):
    w = World(db)
    c = client(db, w)
    preview, _ = run(c, [{"name": "", "field_key": "k", "field_label": "K"}])
    assert preview["errors"] == [{"row": 2, "error": "name is required"}]


def test_a_type_cannot_have_more_than_the_allowed_number_of_fields(db):
    w = World(db)
    c = client(db, w)
    rows = [{"name": "Big", "field_key": f"f{i}", "field_label": f"F{i}"} for i in range(41)]
    preview, _ = run(c, rows)
    assert "at most 40" in preview["errors"][0]["error"]


def test_a_file_that_cannot_be_read_is_reported(db):
    w = World(db)
    c = client(db, w)
    no_name = c.post("/asset-types/import/xlsx/preview", files=file_of([{"title": "x"}])).json()
    assert "name" in no_name["error"]
    wrong = c.post("/asset-types/import/xlsx/preview", files={"file": ("types.txt", b"name\nx", "text/plain")}).json()
    assert ".csv" in wrong["error"]


def test_the_import_needs_the_bulk_permission(db):
    w = World(db)
    c = client(db, w, {**ADMIN_DEFAULT_PERMISSIONS, "asset_types": 2})
    assert c.post("/asset-types/import/xlsx/preview", files=file_of([{"name": "T"}])).status_code == 403


# --- Excel and the template file ----------------------------------------------------------------------

def test_an_excel_file(db):
    import openpyxl
    w = World(db)
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["name", "description", "purdue_level", "field_key", "field_label", "field_type", "field_required", "field_options"])
    sheet.append(["Excel Type", "From Excel", 1.5, "volts", "Volts", "number", None, None])
    sheet.append(["Excel Type", None, None, "mode", "Mode", "select", True, "a|b"])
    buf = io.BytesIO()
    book.save(buf)
    files = {"file": ("types.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    c = client(db, w)
    assert c.post("/asset-types/import/xlsx/preview", files=files).json()["errors"] == []
    assert c.post("/asset-types/import/xlsx/confirm", files=files).json()["created"] == ["Excel Type"]
    at = stored(db, w, "Excel Type")
    assert at.purdue_level == 1.5 and keys(at) == ["volts", "mode"] and at.fields_schema[1]["required"] is True


def test_the_template_has_the_import_columns():
    if not TEMPLATE.exists():
        pytest.skip("the frontend folder is not part of this environment")
    with TEMPLATE.open(newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == imp.COLUMNS


def test_the_template_is_processed_on_upload(db):
    if not TEMPLATE.exists():
        pytest.skip("the frontend folder is not part of this environment")
    w = World(db)
    c = client(db, w)
    raw = TEMPLATE.read_bytes()
    with TEMPLATE.open(newline="", encoding="utf-8") as f:
        names = {r["name"] for r in csv.DictReader(f)}
    preview = c.post("/asset-types/import/xlsx/preview", files={"file": ("template.csv", raw, "text/csv")}).json()
    assert preview["errors"] == [] and {x["name"] for x in preview["to_create"]} == names
    confirm = c.post("/asset-types/import/xlsx/confirm", files={"file": ("template.csv", raw, "text/csv")}).json()
    assert confirm["errors"] == [] and set(confirm["created"]) == names
    machine = stored(db, w, "Conventional Machine")
    assert keys(machine) == ["voltage", "amperage", "power_kw", "mechanical_schematic_url", "electrical_schematic_url"]
    assert machine.fields_schema[0]["required"] is True and machine.fields_schema[3]["type"] == "url"
    assert stored(db, w, "Operator Panel").fields_schema == []
    again = c.post("/asset-types/import/xlsx/confirm", files={"file": ("template.csv", raw, "text/csv")}).json()
    assert again == {"created": [], "updated": [], "errors": []}
