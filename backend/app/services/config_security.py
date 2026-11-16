"""Protection of uploaded program and configuration files: encryption at rest, integrity check on
download, and an optional virus scan (ClamAV) before a file is accepted. No database."""
import hashlib
import os
import socket
import struct
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

MAGIC = b"SMPKENC1"  # marks a file written by encrypt_stream
CHUNK = 1024 * 1024

ENCRYPT_ENV = "CONFIG_ENCRYPT_AT_REST"  # default on
SCAN_ENV = "CONFIG_SCAN_CLAMD"  # "host:port" of a clamd daemon; empty = no scanning
SCAN_FAIL_OPEN_ENV = "CONFIG_SCAN_FAIL_OPEN"  # accept files when the scanner cannot be reached (default: refuse)


class IntegrityError(Exception):
    """The stored file no longer matches the checksum recorded at upload."""


class ScanError(Exception):
    """The scanner could not be used."""


class Infected(Exception):
    def __init__(self, signature: str):
        super().__init__(signature)
        self.signature = signature


def encryption_enabled() -> bool:
    return os.getenv(ENCRYPT_ENV, "true").strip().lower() not in ("0", "false", "no", "off")


KEY_ENV = "CONFIG_ENCRYPTION_KEY"  # own key for configuration files (default: the application key)
PREVIOUS_KEYS_ENV = "CONFIG_ENCRYPTION_KEY_PREVIOUS"  # comma separated older keys, kept so old files stay readable
TEXT_PREFIX = "enc1:"


def _fernet():
    """Encrypts with CONFIG_ENCRYPTION_KEY when set (else the application key); decrypts with any of
    the configured keys and the application key, so a key can be rotated without losing old files."""
    from app.services.sso_encryption import _get_fernet
    app_key = _get_fernet()
    keys = [os.getenv(KEY_ENV, "").strip()] + [k.strip() for k in os.getenv(PREVIOUS_KEYS_ENV, "").split(",")]
    ferns = [Fernet(k.encode()) for k in keys if k]
    return MultiFernet(ferns + [app_key])


def protect_text(text: Optional[str]) -> Optional[str]:
    """The text copy kept for comparing versions, encrypted like the file itself."""
    if text is None or not encryption_enabled():
        return text
    return TEXT_PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def reveal_text(stored: Optional[str]) -> Optional[str]:
    if stored is None or not stored.startswith(TEXT_PREFIX):
        return stored  # older rows were stored in plain form
    try:
        return _fernet().decrypt(stored[len(TEXT_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise IntegrityError("the stored text was changed or the encryption key differs")


def encrypt_stream(source: BinaryIO, target: BinaryIO, on_plain=None) -> int:
    """Read `source` in chunks and write each as a Fernet token (4-byte length + token). Returns the
    plain size; on_plain(chunk) sees every plain chunk (hashing, size limits)."""
    f, size = _fernet(), 0
    target.write(MAGIC)
    while True:
        chunk = source.read(CHUNK)
        if not chunk:
            break
        if on_plain:
            on_plain(chunk)
        size += len(chunk)
        token = f.encrypt(chunk)
        target.write(struct.pack(">I", len(token)) + token)
    return size


def is_encrypted(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def decrypt_to(path: Path, target: BinaryIO) -> None:
    f = _fernet()
    with path.open("rb") as fh:
        if fh.read(len(MAGIC)) != MAGIC:
            raise IntegrityError("the stored file is not in the expected format")
        while True:
            head = fh.read(4)
            if not head:
                return
            if len(head) < 4:
                raise IntegrityError("the stored file is truncated")
            (length,) = struct.unpack(">I", head)
            token = fh.read(length)
            if len(token) < length:
                raise IntegrityError("the stored file is truncated")
            try:
                target.write(f.decrypt(token))
            except InvalidToken:
                raise IntegrityError("the stored file was changed or the encryption key differs")


def verified_copy(path: Path, encrypted: bool, expected_sha256: str) -> Tuple[Path, str]:
    """A plain temporary copy of the stored file whose SHA-256 was checked against `expected_sha256`.
    Raises IntegrityError on any mismatch. The caller removes the returned file when done."""
    fd, name = tempfile.mkstemp(prefix="cfg-", suffix=".bin")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            if encrypted:
                decrypt_to(path, out)
            else:
                with path.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(CHUNK), b""):
                        out.write(chunk)
        digest = hashlib.sha256()
        with tmp.open("rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise IntegrityError("the file does not match the checksum recorded at upload")
        return tmp, digest.hexdigest()
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# --- virus scan (clamd INSTREAM) ---------------------------------------------------------------

def scanner_address() -> Optional[Tuple[str, int]]:
    value = os.getenv(SCAN_ENV, "").strip()
    if not value:
        return None
    host, _, port = value.partition(":")
    return host, int(port or 3310)


def scan(stream: BinaryIO, timeout: float = 30.0) -> Tuple[str, Optional[str]]:
    """('not_scanned', None) when no scanner is configured, ('clean', None), or raises Infected / ScanError.
    The stream is rewound afterwards."""
    addr = scanner_address()
    if addr is None:
        return "not_scanned", None
    try:
        stream.seek(0)
        with socket.create_connection(addr, timeout=timeout) as sock:
            sock.sendall(b"zINSTREAM\0")
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                sock.sendall(struct.pack(">I", len(chunk)) + chunk)
            sock.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0") and len(reply) < 4096:
                part = sock.recv(4096)
                if not part:
                    break
                reply += part
    except (OSError, ValueError) as exc:
        stream.seek(0)
        raise ScanError(str(exc))
    stream.seek(0)
    text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    if text.endswith("OK"):
        return "clean", None
    if "FOUND" in text:
        raise Infected(text.split(":", 1)[-1].replace("FOUND", "").strip()[:200])
    raise ScanError(text or "no answer from the scanner")


def fail_open() -> bool:
    return os.getenv(SCAN_FAIL_OPEN_ENV, "false").strip().lower() in ("1", "true", "yes", "on")
