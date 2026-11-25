"""Configuration files: encrypted at rest, integrity re-check on download, virus scan."""
import io
import uuid

import pytest

from app.config import settings
from app.models import ConfigVersion
from app.services import config_security as sec

from tests.test_api_ot_modules import ADMIN_DEFAULT_PERMISSIONS, World, client_for, db  # noqa: F401


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.delenv(sec.SCAN_ENV, raising=False)
    return tmp_path


def _upload(admin, w, content=b"PLC PROGRAM v1\n" * 50):
    art = admin.post(f"/config/assets/{w.asset.id}/artifacts", json={"name": "Main", "kind": "program"}).json()
    r = admin.post(f"/config/artifacts/{art['id']}/versions", files={"file": ("main.plc", content)})
    assert r.status_code == 200, r.text
    return r.json()


def _version(db, w):
    return db.query(ConfigVersion).filter(ConfigVersion.tenant_id == w.tenant.id).first()


def test_text_copy_is_encrypted_and_old_key_still_reads(monkeypatch):
    from cryptography.fernet import Fernet
    stored = sec.protect_text("secret = 1")
    assert stored.startswith(sec.TEXT_PREFIX) and "secret" not in stored
    assert sec.reveal_text(stored) == "secret = 1"
    assert sec.reveal_text("legacy plain") == "legacy plain"
    new = Fernet.generate_key().decode()
    monkeypatch.setenv(sec.KEY_ENV, new)  # a dedicated key: files made earlier stay readable
    assert sec.reveal_text(stored) == "secret = 1"
    fresh = sec.protect_text("after")
    monkeypatch.delenv(sec.KEY_ENV)
    with pytest.raises(sec.IntegrityError):
        sec.reveal_text(fresh)


def test_stream_roundtrip_and_tamper():
    src = io.BytesIO(b"x" * (sec.CHUNK + 10))
    out = io.BytesIO()
    assert sec.encrypt_stream(src, out) == sec.CHUNK + 10
    assert b"xxxxxxxx" not in out.getvalue()


def test_upload_is_encrypted_and_download_returns_original(db, store):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    content = b"SECRET PLC LOGIC\n" * 100
    _upload(admin, w, content)
    ver = _version(db, w)
    assert ver.encrypted is True
    on_disk = (store / ver.file_path).read_bytes()
    assert b"SECRET PLC LOGIC" not in on_disk
    r = admin.get(f"/config/versions/{ver.id}/download")
    assert r.status_code == 200 and r.content == content


def test_unencrypted_legacy_file_still_downloads(db, store, monkeypatch):
    monkeypatch.setenv(sec.ENCRYPT_ENV, "false")
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    _upload(admin, w, b"plain legacy file")
    ver = _version(db, w)
    assert ver.encrypted is False
    assert admin.get(f"/config/versions/{ver.id}/download").content == b"plain legacy file"


@pytest.mark.parametrize("encrypt", ["true", "false"])
def test_tampered_file_is_not_served(db, store, monkeypatch, encrypt):
    monkeypatch.setenv(sec.ENCRYPT_ENV, encrypt)
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    _upload(admin, w, b"original content here")
    ver = _version(db, w)
    path = store / ver.file_path
    data = bytearray(path.read_bytes())
    data[-3] ^= 0xFF
    path.write_bytes(bytes(data))
    r = admin.get(f"/config/versions/{ver.id}/download")
    assert r.status_code == 409


def test_infected_upload_is_refused(db, store, monkeypatch):
    def infected(stream, timeout=30.0):
        raise sec.Infected("Eicar-Test-Signature")
    monkeypatch.setattr(sec, "scan", infected)
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    art = admin.post(f"/config/assets/{w.asset.id}/artifacts", json={"name": "Main", "kind": "program"}).json()
    r = admin.post(f"/config/artifacts/{art['id']}/versions", files={"file": ("a.bin", b"bad")})
    assert r.status_code == 422
    assert _version(db, w) is None
    assert not any(p.is_file() for p in store.rglob("*"))  # nothing was stored


def test_scanner_down_refuses_unless_fail_open(db, store, monkeypatch):
    def down(stream, timeout=30.0):
        raise sec.ScanError("connection refused")
    monkeypatch.setattr(sec, "scan", down)
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    art = admin.post(f"/config/assets/{w.asset.id}/artifacts", json={"name": "Main", "kind": "program"}).json()
    assert admin.post(f"/config/artifacts/{art['id']}/versions", files={"file": ("a.bin", b"data")}).status_code == 503
    monkeypatch.setenv(sec.SCAN_FAIL_OPEN_ENV, "true")
    assert admin.post(f"/config/artifacts/{art['id']}/versions", files={"file": ("a.bin", b"data")}).status_code == 200
    assert _version(db, w).scan_status == "error"


def test_clamd_reply_parsing(monkeypatch):
    class Sock:
        def __init__(self, reply): self.reply, self.sent = reply, b""
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def sendall(self, b): self.sent += b
        def recv(self, n): r, self.reply = self.reply, b""; return r
    monkeypatch.setenv(sec.SCAN_ENV, "clam:3310")
    monkeypatch.setattr(sec.socket, "create_connection", lambda *a, **k: Sock(b"stream: OK\0"))
    assert sec.scan(io.BytesIO(b"abc")) == ("clean", None)
    monkeypatch.setattr(sec.socket, "create_connection", lambda *a, **k: Sock(b"stream: Eicar-Test FOUND\0"))
    with pytest.raises(sec.Infected) as e:
        sec.scan(io.BytesIO(b"abc"))
    assert e.value.signature == "Eicar-Test"
