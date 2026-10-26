"""Private, encrypted evidence storage.

* Files are encrypted (Fernet: AES-128-CBC + HMAC-SHA256) before they touch disk,
  so a stolen disk or backup does not expose evidence without the key.
  Application-level encryption does NOT protect against an attacker who controls
  the running application or has the key. Rotate keys by listing the new key
  first in EVIDENCE_ENCRYPTION_KEY (comma separated).
* Storage keys are random server-generated names; user input never reaches a path.
* The directory is outside any static or media URL. There is deliberately no way
  to build a URL to a stored file: every read goes through an authorised view.
"""
import os
import re
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

KEY_RE = re.compile(r"^[0-9a-f]{32}\.bin$")


class StorageError(Exception):
    """Raised for missing, tampered or unreadable stored files. Message is safe to log."""


def _fernet():
    keys = [k.strip() for k in str(settings.EVIDENCE_ENCRYPTION_KEY).split(",") if k.strip()]
    if not keys:
        raise StorageError("no_encryption_key")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError) as exc:
        raise StorageError("invalid_encryption_key") from exc


def _path(key):
    if not KEY_RE.match(key or ""):
        raise StorageError("invalid_storage_key")
    root = Path(settings.EVIDENCE_ROOT).resolve()
    path = (root / key[:2] / key).resolve()
    if root not in path.parents:  # defence in depth; KEY_RE already forbids this
        raise StorageError("invalid_storage_key")
    return path


def save(plaintext: bytes) -> str:
    """Encrypt and store bytes. Returns the new random storage key."""
    key = f"{uuid.uuid4().hex}.bin"
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    token = _fernet().encrypt(plaintext)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(token)
    os.replace(tmp, path)
    return key


def load(key: str) -> bytes:
    """Read and decrypt. Raises StorageError if missing or if the data was altered."""
    path = _path(key)
    try:
        token = path.read_bytes()
    except FileNotFoundError as exc:
        raise StorageError("file_missing") from exc
    try:
        return _fernet().decrypt(token)
    except InvalidToken as exc:
        raise StorageError("integrity_check_failed") from exc


def remove(key: str) -> None:
    """Delete a stored file. Silent if it is already gone or the key is invalid."""
    try:
        _path(key).unlink(missing_ok=True)
    except StorageError:
        pass
