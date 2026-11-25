"""Import of asset types from a CSV or Excel file.

One asset type can have several type-specific fields, so the file has one row per field: the rows of one type repeat its name.
A row without a field_key is a type with no fields (or just the type-level cells of a type whose fields follow).

Columns:
  name            required; the type is found by name (case-insensitive) among the tenant's own types
  description     optional text (up to 255)
  purdue_level    optional: 0, 1, 1.5, 2, 3 or 4
  field_key       lower-case letters, digits and _ ; starts with a letter (the key the asset stores its value under)
  field_label     required when there is a field_key
  field_type      text (default), number, date, select (choice), boolean (yes / no) or url (web link)
  field_required  yes / no (default no)
  field_options   the choices of a select field, separated by | ; or ,

Rules: a blank cell never clears what is stored. An existing type keeps the fields the file does not mention (assets hold values
under them); a field named in the file is updated, but its type cannot change. A type is imported whole or not at all: one bad row
leaves the whole type out and is reported with its row number. The preview and the confirm run the same plan.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AssetType
from app.schemas.asset_type import MAX_FIELDS_PER_TYPE, AssetFieldDef
from app.services.asset_import_extra import cell

COLUMNS = ["name", "description", "purdue_level", "field_key", "field_label", "field_type", "field_required", "field_options"]
PURDUE_LEVELS = {0.0, 1.0, 1.5, 2.0, 3.0, 4.0}
FIELD_TYPES = {
    "text": "text", "number": "number", "date": "date", "select": "select", "boolean": "boolean", "url": "url",
    "choice": "select", "yes / no": "boolean", "yes/no": "boolean", "web link": "url", "link": "url",
}
YES = {"yes", "y", "true", "1", "si", "sì"}
NO = {"no", "n", "false", "0"}
NAME_MAX = 100
DESCRIPTION_MAX = 255


class FileError(Exception):
    """The file cannot be read at all."""


@dataclass
class Planned:
    name: str
    row: int                                    # the first row of the type, where errors that concern the whole type are shown
    existing: Optional[AssetType] = None
    description: Optional[str] = None
    purdue_level: Optional[float] = None
    fields: List[dict] = field(default_factory=list)   # the fields named in the file, in order
    errors: List[dict] = field(default_factory=list)   # {"row", "error"}


def read_table(file) -> pd.DataFrame:
    """The rows of an uploaded CSV or Excel file, every cell as text, the column names lower-cased."""
    name = (getattr(file, "filename", "") or "").lower()
    try:
        if name.endswith(".csv"):
            try:
                df = pd.read_csv(file.file, dtype=str, encoding="utf-8-sig")
            except UnicodeDecodeError:
                file.file.seek(0)
                df = pd.read_csv(file.file, dtype=str, encoding="cp1252")
        elif name.endswith((".xlsx", ".xlsm")):
            df = pd.read_excel(file.file, engine="openpyxl", dtype=str)
        else:
            raise FileError("the file must be a .csv or .xlsx file")
    except FileError:
        raise
    except Exception as exc:
        raise FileError(f"Error reading file: {exc}")
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "name" not in df.columns:
        raise FileError("the file needs a 'name' column")
    return df


def _message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    text = str(first.get("msg", "")).removeprefix("Value error, ")
    where = ".".join(str(p) for p in first.get("loc", ()))
    return f"{where}: {text}" if where else text


def _field_def(row_cells: Dict[str, Optional[str]]) -> dict:
    """One field definition from the field_* cells, checked like the asset type form checks it. Raises ValueError."""
    key = row_cells["field_key"]
    label = row_cells["field_label"]
    if not label:
        raise ValueError("field_label is required when there is a field_key")
    raw_type = (row_cells["field_type"] or "text").lower()
    if raw_type not in FIELD_TYPES:
        raise ValueError(f"field_type '{row_cells['field_type']}' is not one of text, number, date, select, boolean, url")
    required_text = (row_cells["field_required"] or "no").lower()
    if required_text in YES:
        required = True
    elif required_text in NO:
        required = False
    else:
        raise ValueError(f"field_required '{row_cells['field_required']}' must be yes or no")
    options = [o.strip() for o in re.split(r"[|;,]", row_cells["field_options"] or "") if o.strip()]
    try:
        definition = AssetFieldDef(key=key.lower(), label=label, type=FIELD_TYPES[raw_type], required=required, options=options)
    except ValidationError as exc:
        raise ValueError(_message(exc))
    return {"key": definition.key, "label": definition.label, "type": definition.type, "required": definition.required,
            "options": definition.options}


def describe_field(definition: dict) -> str:
    """'Supply voltage (number, required)' - how a field is shown in the preview."""
    parts = [definition.get("type", "text")]
    if definition.get("required"):
        parts.append("required")
    if definition.get("options"):
        parts.append("/".join(definition["options"]))
    return f"{definition.get('label') or definition.get('key')} ({', '.join(parts)})"


def plan(db: Session, tenant_id, df: pd.DataFrame) -> List[Planned]:
    """What the file asks for, type by type, with every problem found. Nothing is written."""
    planned: Dict[str, Planned] = {}
    order: List[str] = []
    for idx, row in df.iterrows():
        number = int(idx) + 2
        cells = {c: cell(row, c) for c in COLUMNS}
        if not any(cells.values()):
            continue                                  # an empty line
        name = cells["name"]
        if not name:
            # a row of fields with no type name belongs to no type: report it on its own
            stray = Planned(name=f"(row {number})", row=number)
            stray.errors.append({"row": number, "error": "name is required"})
            planned[f"\0{number}"] = stray
            order.append(f"\0{number}")
            continue
        key = name.lower()
        item = planned.get(key)
        if item is None:
            item = Planned(name=name, row=number)
            planned[key] = item
            order.append(key)
        problems: List[str] = []
        if len(name) > NAME_MAX:
            problems.append(f"name is longer than {NAME_MAX} characters")
        description = cells["description"]
        if description is not None:
            if len(description) > DESCRIPTION_MAX:
                problems.append(f"description is longer than {DESCRIPTION_MAX} characters")
            elif item.description not in (None, description):
                problems.append("description differs from an earlier row of the same type")
            else:
                item.description = description
        level_text = cells["purdue_level"]
        if level_text is not None:
            try:
                level = float(level_text)
            except ValueError:
                level = None
            if level is None or level not in PURDUE_LEVELS:
                problems.append(f"purdue_level '{level_text}' must be 0, 1, 1.5, 2, 3 or 4")
            elif item.purdue_level not in (None, level):
                problems.append("purdue_level differs from an earlier row of the same type")
            else:
                item.purdue_level = level
        field_cells = [cells[c] for c in ("field_key", "field_label", "field_type", "field_required", "field_options")]
        if any(field_cells):
            if not cells["field_key"]:
                problems.append("field_key is required when the row describes a field")
            else:
                try:
                    definition = _field_def(cells)
                    if any(f["key"] == definition["key"] for f in item.fields):
                        problems.append(f"field '{definition['key']}' appears twice for this type")
                    else:
                        item.fields.append(definition)
                except ValueError as exc:
                    problems.append(str(exc))
        item.errors.extend({"row": number, "error": p} for p in problems)

    # match the types already stored and merge the fields
    result = [planned[k] for k in order]
    lowered = [p.name.lower() for p in result if not p.name.startswith("(row ")]
    stored = {}
    if lowered:
        for at in db.query(AssetType).filter(func.lower(AssetType.name).in_(lowered),
                                            (AssetType.tenant_id == tenant_id) | (AssetType.tenant_id.is_(None))).all():
            stored.setdefault(at.name.lower(), []).append(at)
    for item in result:
        if item.name.startswith("(row "):
            continue
        matches = stored.get(item.name.lower(), [])
        own = [a for a in matches if a.tenant_id == tenant_id]
        if own:
            item.existing = own[0]
        elif matches:
            item.errors.append({"row": item.row, "error": f"'{item.name}' is a global asset type; it cannot be changed by an import"})
        if item.existing is not None:
            by_key = {f.get("key"): f for f in (item.existing.fields_schema or []) if isinstance(f, dict)}
            for definition in item.fields:
                old = by_key.get(definition["key"])
                if old is not None and old.get("type", "text") != definition["type"]:
                    item.errors.append({"row": item.row, "error": f"field '{definition['key']}' is of type {old.get('type', 'text')} and its type cannot be changed"})
            kept = len(by_key) + sum(1 for d in item.fields if d["key"] not in by_key)
        else:
            kept = len(item.fields)
        if kept > MAX_FIELDS_PER_TYPE:
            item.errors.append({"row": item.row, "error": f"an asset type can have at most {MAX_FIELDS_PER_TYPE} fields"})
    return result


def merged_fields(item: Planned) -> List[dict]:
    """The field list the type ends up with: the stored fields (updated where the file names them), then the new ones."""
    stored = [dict(f) for f in ((item.existing.fields_schema if item.existing else None) or []) if isinstance(f, dict)]
    new_by_key = {d["key"]: d for d in item.fields}
    merged = []
    for f in stored:
        update = new_by_key.pop(f.get("key"), None)
        merged.append({**f, **update} if update else f)
    merged.extend(new_by_key.values())
    return merged


def diff_of(item: Planned) -> Dict[str, dict]:
    """What would change on an existing type: {column: {old, new}}, empty when the file adds nothing."""
    existing = item.existing
    diff: Dict[str, dict] = {}
    if item.description is not None and item.description != (existing.description or None):
        diff["description"] = {"old": existing.description, "new": item.description}
    if item.purdue_level is not None and item.purdue_level != existing.purdue_level:
        diff["purdue_level"] = {"old": existing.purdue_level, "new": item.purdue_level}
    by_key = {f.get("key"): f for f in (existing.fields_schema or []) if isinstance(f, dict)}
    for definition in item.fields:
        old = by_key.get(definition["key"])
        if old is None:
            diff[f"field {definition['key']}"] = {"old": None, "new": describe_field(definition)}
        else:
            changed = {**old, **definition}
            if (changed.get("label"), changed.get("required"), changed.get("options") or []) != (
                    old.get("label"), old.get("required"), old.get("options") or []):
                diff[f"field {definition['key']}"] = {"old": describe_field(old), "new": describe_field(changed)}
    return diff


def preview(db: Session, tenant_id, df: pd.DataFrame) -> dict:
    to_create, to_update, errors = [], [], []
    for item in plan(db, tenant_id, df):
        errors.extend(item.errors)
        if item.errors:
            continue
        if item.existing is None:
            to_create.append({
                "name": item.name, "description": item.description, "purdue_level": item.purdue_level,
                "fields": "; ".join(describe_field(d) for d in item.fields),
            })
        else:
            diff = diff_of(item)
            if diff:
                to_update.append({"name": item.existing.name, "diff": diff})
    errors.sort(key=lambda e: e["row"])
    return {"to_create": to_create, "to_update": to_update, "errors": errors}


def confirm(db: Session, tenant_id, df: pd.DataFrame) -> dict:
    created, updated, errors = [], [], []
    for item in plan(db, tenant_id, df):
        errors.extend(item.errors)
        if item.errors:
            continue
        try:
            if item.existing is None:
                db.add(AssetType(tenant_id=tenant_id, name=item.name, description=item.description,
                                 purdue_level=item.purdue_level, fields_schema=merged_fields(item)))
                db.commit()
                created.append(item.name)
            elif diff_of(item):
                at = item.existing
                if item.description is not None:
                    at.description = item.description
                if item.purdue_level is not None:
                    at.purdue_level = item.purdue_level
                at.fields_schema = merged_fields(item)      # a new list, so the JSON column is seen as changed
                db.commit()
                updated.append(at.name)
        except Exception as exc:
            db.rollback()
            errors.append({"row": item.row, "error": str(exc)})
    errors.sort(key=lambda e: e["row"])
    return {"created": created, "updated": updated, "errors": errors}
