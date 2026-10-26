"""Evidence Vault services: validated uploads, integrity checks, sharing, packs."""
import hashlib
import io
import json
import os
import zipfile

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import get_valid_filename

from apps import audit

from . import storage
from .models import EvidenceAccessEvent, EvidenceItem, EvidenceShare

ALLOWED_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


class UploadRejected(Exception):
    """The message is safe to show to the person uploading."""


class ShareError(Exception):
    pass


# ------------------------------------------------------------------ uploads

def clean_display_name(raw):
    """A safe label. Strips any path, odd characters and leading dots."""
    base = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    try:
        base = get_valid_filename(base)
    except SuspiciousFileOperation:
        base = ""
    base = base.lstrip(".")
    if not base:
        return "file"
    stem, ext = os.path.splitext(base)
    return stem[: 100 - len(ext)] + ext


def _matches_signature(ext, data):
    if ext in (".jpg", ".jpeg"):
        return data[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".pdf":
        return data[:5] == b"%PDF-"
    if ext == ".txt":
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


def read_upload(uploaded):
    """Validate an uploaded file. Returns (display_name, content_type, bytes)."""
    limit = settings.EVIDENCE_MAX_BYTES
    limit_mb = max(1, limit // (1024 * 1024))
    too_big = f"This file is larger than the {limit_mb} MB limit."
    if uploaded.size is not None and uploaded.size > limit:
        raise UploadRejected(too_big)
    data = uploaded.read(limit + 1)
    if len(data) > limit:
        raise UploadRejected(too_big)
    if not data:
        raise UploadRejected("This file is empty.")
    name = clean_display_name(getattr(uploaded, "name", ""))
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_TYPES:
        accepted = ", ".join(sorted(e.lstrip(".") for e in ALLOWED_TYPES))
        raise UploadRejected(f"This type of file is not accepted. Accepted types: {accepted}.")
    if not _matches_signature(ext, data):
        raise UploadRejected("The contents of this file do not match its type, so it was not saved.")
    return name, ALLOWED_TYPES[ext], data


def add_file(incident, user, uploaded, entry=None):
    name, content_type, data = read_upload(uploaded)
    if entry is not None and entry.incident_id != incident.id:
        raise UploadRejected("That timeline entry does not belong to this incident.")
    digest = hashlib.sha256(data).hexdigest()
    key = storage.save(data)
    try:
        with transaction.atomic():
            item = EvidenceItem.objects.create(
                incident=incident,
                entry=entry,
                display_name=name,
                storage_key=key,
                content_type=content_type,
                size_bytes=len(data),
                sha256=digest,
                uploaded_by=user,
            )
    except Exception:
        storage.remove(key)
        raise
    audit.record(user, "evidence.uploaded", item, size_bytes=len(data))
    return item


def open_item(item):
    """Return (bytes or None, integrity_ok). integrity_ok means the stored bytes
    decrypt cleanly AND still match the hash recorded at upload."""
    try:
        data = storage.load(item.storage_key)
    except storage.StorageError:
        return None, False
    return data, hashlib.sha256(data).hexdigest() == item.sha256


def record_access(item, user, action):
    EvidenceAccessEvent.objects.create(item=item, user=user, action=action)


@transaction.atomic
def delete_item(user, item):
    """Remove the file itself; keep a metadata stub so the timeline stays honest."""
    storage.remove(item.storage_key)
    EvidenceShare.objects.filter(item=item, revoked_at__isnull=True).update(revoked_at=timezone.now())
    item.storage_key = ""
    item.deleted_at = timezone.now()
    item.save(update_fields=["storage_key", "deleted_at"])
    record_access(item, user, EvidenceAccessEvent.Action.DELETE)
    audit.record(user, "evidence.deleted", item)


# ------------------------------------------------------------------ sharing

def share_item(owner, item, contact, expires_at=None):
    if item.incident.owner_id != owner.id or contact.owner_id != owner.id or item.is_deleted:
        raise ShareError("That item or contact is not available.")
    if contact.removed_at is not None:
        raise ShareError("That contact is not available.")
    if contact.linked_user_id is None:
        raise ShareError(
            f"{contact.name} needs to accept a LESEDI invitation first, so that only their own account can open this."
        )
    with transaction.atomic():
        share, created = EvidenceShare.objects.get_or_create(
            item=item,
            shared_with=contact,
            revoked_at__isnull=True,
            defaults={"shared_by": owner, "expires_at": expires_at},
        )
        if created:
            record_access(item, owner, EvidenceAccessEvent.Action.SHARE)
            audit.record(owner, "evidence.shared", item)
    return share


@transaction.atomic
def revoke_share(owner, share):
    if share.item.incident.owner_id != owner.id:
        raise ShareError("Not available.")
    if share.revoked_at is None:
        share.revoked_at = timezone.now()
        share.save(update_fields=["revoked_at"])
        record_access(share.item, owner, EvidenceAccessEvent.Action.REVOKE)
        audit.record(owner, "evidence.share_revoked", share.item)
    return share


def shares_visible_to(user):
    """Active shares a signed-in trusted contact may open. Nothing else is visible."""
    now = timezone.now()
    return (
        EvidenceShare.objects.filter(
            shared_with__linked_user=user,
            shared_with__removed_at__isnull=True,
            revoked_at__isnull=True,
            item__deleted_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .select_related("item__incident__owner", "shared_with")
    )


# --------------------------------------------------------------- evidence pack

PACK_README = """LESEDI EVIDENCE PACK
====================

Generated: {generated}
Generated by: LESEDI, from records entered or uploaded by the account holder.

WHAT THIS PACK IS
- A copy of the incident notes and files the account holder chose to include.
- A timeline that puts those notes and files in date order.
- A manifest (manifest.json) listing each file with its size and SHA-256 hash.

WHERE THE INFORMATION COMES FROM
- "Occurred" times are what the account holder entered. LESEDI cannot check them.
- "Recorded by LESEDI" times are when LESEDI's server saved the note or file.
- File contents are exactly what was uploaded. LESEDI does not edit originals.

LIMITATIONS (please read)
- A SHA-256 hash lets anyone detect whether a file has changed since it was
  hashed. It does NOT prove the file or its contents are genuine, that the
  date it claims is accurate, who created it, or that a court or any other body
  will accept it.
- LESEDI does not claim this pack is tamper-proof or certified for legal use.
- No legal conclusions are made or implied. Speak to a qualified legal
  practitioner about how to use these records.
- No malware scanning was performed by LESEDI. Open files with care.
"""


def build_pack(user, incident, entries, items):
    """Return (zip_bytes, filename). `entries` and `items` must already belong to
    `incident`, which must belong to `user` (the view guarantees this)."""
    now = timezone.now()
    buffer = io.BytesIO()
    manifest_items = []
    timeline = []
    for entry in entries:
        timeline.append((entry.occurred_at, f"Note: {entry.note}", entry.created_at))
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
        for index, item in enumerate(items, start=1):
            record = {
                "file": None,
                "display_name": item.display_name,
                "content_type": item.content_type,
                "size_bytes": item.size_bytes,
                "sha256_at_upload": item.sha256,
                "recorded_by_lesedi_at": item.uploaded_at.isoformat(),
                "scan_status": item.scan_status,
            }
            data, ok = open_item(item)
            record["sha256_matches_upload"] = ok
            if data is None:
                record["note"] = "The stored file could not be read, so it is not included."
            else:
                arcname = f"files/{index:03d}_{item.display_name}"
                pack.writestr(arcname, data)
                record["file"] = arcname
                if not ok:
                    record["note"] = "The file's hash no longer matches the hash recorded at upload."
            manifest_items.append(record)
            timeline.append((item.uploaded_at, f"File recorded: {item.display_name}", item.uploaded_at))
            record_access(item, user, EvidenceAccessEvent.Action.EXPORT)
        timeline.sort(key=lambda row: (row[0], row[2]))
        lines = ["TIMELINE (oldest first)", "=" * 23, ""]
        for when, text, _ in timeline:
            lines.append(f"{timezone.localtime(when):%Y-%m-%d %H:%M}  {text}")
        pack.writestr("timeline.txt", "\n".join(lines) + "\n")
        manifest = {
            "generated_at": now.isoformat(),
            "generator": "LESEDI evidence pack v1",
            "incident": {
                "title": incident.title,
                "occurred_at": incident.occurred_at.isoformat(),
                "description": incident.description,
            },
            "notes_included": len(entries),
            "files": manifest_items,
            "limitations": "See README.txt. Hashes detect change; they do not prove authenticity.",
        }
        pack.writestr("manifest.json", json.dumps(manifest, indent=2))
        pack.writestr("README.txt", PACK_README.format(generated=timezone.localtime(now).strftime("%Y-%m-%d %H:%M")))
    audit.record(user, "evidence.pack_exported", incident, files=len(items))
    return buffer.getvalue(), f"lesedi-evidence-pack-{timezone.localdate():%Y%m%d}.zip"
