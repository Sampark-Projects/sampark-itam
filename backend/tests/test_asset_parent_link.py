"""Parent-child ("component of") validation for assets, using an in-memory stand-in for the session."""
import uuid
from types import SimpleNamespace

import pytest

from app.crud.assets import validate_parent_asset
from app.errors.exceptions import ErrorCodeException
from app.models import Asset
from app.schemas.asset import AssetCreate, AssetUpdate

TENANT = uuid.uuid4()


class _Query:
    def __init__(self, rows, columns):
        self.rows, self.columns, self.wanted = rows, columns, None

    def filter(self, criterion):
        # the criterion is `Asset.id == <uuid>`; read the compared value off the expression
        self.wanted = criterion.right.value
        return self

    def first(self):
        return self.rows.get(self.wanted)

    def scalar(self):
        row = self.rows.get(self.wanted)
        return row.parent_asset_id if row else None


class FakeDb:
    def __init__(self, assets):
        self.assets = assets

    def query(self, *columns):
        return _Query(self.assets, columns)


def _row(parent=None, tenant=TENANT, deleted=None):
    return SimpleNamespace(tenant_id=tenant, deleted_at=deleted, parent_asset_id=parent)


def test_no_parent_is_always_valid():
    validate_parent_asset(FakeDb({}), TENANT, None)


def test_parent_must_exist():
    with pytest.raises(ErrorCodeException):
        validate_parent_asset(FakeDb({}), TENANT, uuid.uuid4())


def test_parent_must_be_same_tenant():
    parent = uuid.uuid4()
    with pytest.raises(ErrorCodeException):
        validate_parent_asset(FakeDb({parent: _row(tenant=uuid.uuid4())}), TENANT, parent)


def test_deleted_parent_is_rejected():
    from datetime import datetime

    parent = uuid.uuid4()
    with pytest.raises(ErrorCodeException):
        validate_parent_asset(FakeDb({parent: _row(deleted=datetime.utcnow())}), TENANT, parent)


def test_asset_cannot_be_its_own_parent():
    a = uuid.uuid4()
    with pytest.raises(ErrorCodeException):
        validate_parent_asset(FakeDb({a: _row()}), TENANT, a, asset_id=a)


def test_loops_are_rejected():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # c is a component of b, b is a component of a. Making a a component of c closes a loop.
    db = FakeDb({a: _row(), b: _row(parent=a), c: _row(parent=b)})
    with pytest.raises(ErrorCodeException):
        validate_parent_asset(db, TENANT, c, asset_id=a)


def test_valid_parent_chain_is_accepted():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = FakeDb({a: _row(), b: _row(parent=a), c: _row()})
    validate_parent_asset(db, TENANT, b, asset_id=c)  # c becomes a component of b


def test_schemas_carry_parent_asset_id():
    parent = uuid.uuid4()
    assert AssetCreate(name="Module", site_id=uuid.uuid4(), parent_asset_id=parent).parent_asset_id == parent
    assert AssetUpdate(parent_asset_id=None).model_dump(exclude_unset=True) == {"parent_asset_id": None}
    assert hasattr(Asset, "parent") and hasattr(Asset, "components")
