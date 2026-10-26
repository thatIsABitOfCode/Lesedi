"""Evidence Vault services: validation, encrypted private storage, hashing, export, sharing.

Limitations (also written into every exported pack):
  * A SHA-256 hash can reveal later changes to a file; it does not prove authenticity, an accurate
    timestamp, or admissibility in court.
  * LESEDI does not claim the vault is tamper-proof or court-certified.
  * Malware scanning is NOT implemented; `scan_hook` is a no-op placeholder so a scanner can be wired in."""
import csv
import hashlib
import io
import json
import os
import re
import secrets
import unicodedata
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from audit.services import record

from .models import EvidenceAccessEvent, EvidenceItem, EvidenceKind, EvidenceShare

ALLOWED_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf", ".txt": "text/plain",
}
KEY_RE = re.compile(r"^[0-9a-f]{32}\.enc$")

LIMITATIONS_TEXT = """ABOUT THIS EVIDENCE PACK
========================
Prepared by LESEDI from records the account owner chose to include.

What the records are
- Notes and files were entered or uploaded by the account owner. LESEDI has not verified their content.
- "Event time" is what the owner entered. "Stored at" is the LESEDI server clock when the record was saved.
  Neither is independently verified.

What the SHA-256 hashes mean
- A hash was calculated when each record was stored. Re-calculating it later can show whether the stored
  copy has changed since then.
- A hash does NOT prove that a photo or document is authentic, that it shows what it is said to show, that
  a timestamp is accurate, or that any court or authority will accept it.

What this pack is not
- It is not legal advice and contains no legal conclusions.
- LESEDI does not claim the vault is tamper-proof or court-certified.

Speak to a qualified legal professional or a support organisation about how to use these records.
"""


class EvidenceError(ValueError):
    """A problem the user can fix (shown to them)."""


# ---------------------------------------------------------------- storage
def _fernet():
    return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in settings.EVIDENCE_ENCRYPTION_KEYS])


def _root() -> Path:
    root = Path(settings.EVIDENCE_STORAGE_DIR)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _path(key: str) -> Path:
    if not KEY_RE.match(key or ""):
        raise EvidenceError("Invalid storage key.")
    path = _root() / key
    if path.resolve().parent != _root().resolve():  # defence in depth against traversal
        raise EvidenceError("Invalid storage key.")
    return path


def _write_blob(key: str, ciphertext: bytes) -> None:
    path = _path(key)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(ciphertext)
    os.replace(tmp, path)


def delete_blob(key: str) -> None:
    try:
        _path(key).unlink(missing_ok=True)
    except EvidenceError:
        pass


def read_bytes(item: EvidenceItem) -> bytes:
    if item.kind != EvidenceKind.FILE:
        raise EvidenceError("This record has no file.")
    try:
        return _fernet().decrypt(_path(item.storage_key).read_bytes())
    except (InvalidToken, FileNotFoundError) as exc:
        raise EvidenceError("The stored file could not be read.") from exc


# ---------------------------------------------------------------- validation
def sanitise_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "").replace("\\", "/").split("/")[-1]
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._-")[:80] or "file"
    ext = re.sub(r"[^a-z0-9.]", "", ext.lower())[:8]
    return stem + ext


def _looks_like(ext: str, data: bytes) -> bool:
    if ext in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".pdf":
        return data.startswith(b"%PDF-")
    if ext == ".txt":
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


def scan_hook(data: bytes) -> None:
    """Placeholder for a malware scanner (for example ClamAV). Not implemented in this build."""
    return None


# ---------------------------------------------------------------- items
def log_access(item, actor, action, via="owner"):
    return EvidenceAccessEvent.objects.create(
        item=item, item_label=(item.title or item.original_filename or "note")[:140], actor=actor, action=action, via=via)


def _require_owner(incident, user):
    if incident.owner_id != user.pk:
        raise PermissionDenied


def add_note(*, incident, user, text, title="", event_time=None):
    _require_owner(incident, user)
    text = (text or "").strip()
    if not text:
        raise EvidenceError("Please write something in the note.")
    item = EvidenceItem.objects.create(
        incident=incident, owner=user, uploaded_by=user, kind=EvidenceKind.NOTE, title=title[:120], note_text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), event_time=event_time or timezone.now())
    log_access(item, user, "note")
    return item


def add_file(*, incident, user, upload, title="", event_time=None):
    _require_owner(incident, user)
    ext = os.path.splitext(os.path.basename((upload.name or "").replace("\\", "/")))[1].lower()
    if ext not in ALLOWED_TYPES:
        raise EvidenceError("That file type is not allowed. Allowed: " + ", ".join(sorted(ALLOWED_TYPES)) + ".")
    limit = settings.EVIDENCE_MAX_BYTES
    if upload.size and upload.size > limit:
        raise EvidenceError(f"That file is too large (limit {limit // (1024 * 1024)} MB).")
    data = upload.read(limit + 1)
    if len(data) > limit:
        raise EvidenceError(f"That file is too large (limit {limit // (1024 * 1024)} MB).")
    if not data:
        raise EvidenceError("That file is empty.")
    if not _looks_like(ext, data):
        raise EvidenceError("The file's contents do not match its type, so it was not stored.")
    scan_hook(data)

    key = f"{uuid.uuid4().hex}.enc"
    _write_blob(key, _fernet().encrypt(data))
    try:
        item = EvidenceItem.objects.create(
            incident=incident, owner=user, uploaded_by=user, kind=EvidenceKind.FILE, title=title[:120],
            original_filename=sanitise_filename(upload.name), content_type=ALLOWED_TYPES[ext], size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), storage_key=key, event_time=event_time or timezone.now())
    except Exception:
        delete_blob(key)
        raise
    log_access(item, user, "upload")
    return item


def delete_item(item, user):
    if item.owner_id != user.pk:
        raise PermissionDenied
    log_access(item, user, "delete")
    item.delete()  # post_delete signal removes the encrypted file


# ---------------------------------------------------------------- export
def _csv_safe(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_pack(*, user, incident, items) -> bytes:
    _require_owner(incident, user)
    items = sorted(items, key=lambda i: (i.event_time, i.uploaded_at))
    for it in items:
        if it.owner_id != user.pk or it.incident_id != incident.pk:
            raise PermissionDenied
    now = timezone.now()
    manifest_items, timeline = [], io.StringIO()
    writer = csv.writer(timeline)
    writer.writerow(["event_time", "stored_at", "kind", "title", "text_or_filename", "sha256"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, it in enumerate(items, start=1):
            entry = {
                "id": str(it.id), "kind": it.kind, "title": it.title, "event_time": it.event_time.isoformat(),
                "stored_at": it.uploaded_at.isoformat(), "stored_by": it.uploaded_by.display_name,
                "sha256_at_upload": it.sha256,
            }
            if it.kind == EvidenceKind.FILE:
                data = read_bytes(it)
                entry.update({"original_filename": it.original_filename, "content_type": it.content_type,
                              "size_bytes": it.size_bytes,
                              "integrity_check": "match" if hashlib.sha256(data).hexdigest() == it.sha256 else "MISMATCH"})
                z.writestr(f"files/{n:03d}_{it.original_filename}", data)
                shown = it.original_filename
            else:
                entry["text"] = it.note_text
                entry["integrity_check"] = "match" if hashlib.sha256(it.note_text.encode()).hexdigest() == it.sha256 else "MISMATCH"
                shown = it.note_text
            manifest_items.append(entry)
            writer.writerow([_csv_safe(it.event_time.isoformat()), _csv_safe(it.uploaded_at.isoformat()),
                             it.kind, _csv_safe(it.title), _csv_safe(shown), it.sha256])
        z.writestr("README_limitations.txt", LIMITATIONS_TEXT)
        z.writestr("timeline.csv", timeline.getvalue())
        z.writestr("manifest.json", json.dumps({
            "generated_at": now.isoformat(), "incident_title": incident.title, "item_count": len(items),
            "items": manifest_items}, indent=2))
    for it in items:
        log_access(it, user, "export")
    return buf.getvalue()


# ---------------------------------------------------------------- sharing
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_share(*, item, user, label, hours):
    if item.owner_id != user.pk:
        raise PermissionDenied
    hours = max(1, min(int(hours), 24 * 14))
    token = secrets.token_urlsafe(32)
    share = EvidenceShare.objects.create(
        item=item, owner=user, recipient_label=label[:80] or "Recipient", token_hash=_hash_token(token),
        expires_at=timezone.now() + timedelta(hours=hours))
    log_access(item, user, "share_create")
    record("evidence.share_created", actor=user, obj=share)
    return share, token


def revoke_share(share, user):
    if share.owner_id != user.pk:
        raise PermissionDenied
    if share.revoked_at is None:
        share.revoked_at = timezone.now()
        share.save(update_fields=["revoked_at"])
        log_access(share.item, user, "share_revoke")
        record("evidence.share_revoked", actor=user, obj=share)


def find_active_share(token: str):
    share = EvidenceShare.objects.select_related("item").filter(token_hash=_hash_token(token)).first()
    return share if share is not None and share.is_active else None


def record_share_access(share):
    share.access_count += 1
    share.last_accessed_at = timezone.now()
    share.save(update_fields=["access_count", "last_accessed_at"])
    log_access(share.item, None, "share_download", via="share")
