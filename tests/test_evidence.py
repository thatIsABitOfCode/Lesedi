"""Evidence Vault: validation, encrypted private storage, hashing, export, sharing and access control."""
import hashlib
import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from evidence import services
from evidence.models import EvidenceAccessEvent, EvidenceItem, EvidenceShare, Incident
from tests.factories import PASSWORD, PNG_BYTES, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_user()


@pytest.fixture
def incident(owner):
    return Incident.objects.create(owner=owner, title="Demo incident", description="Fictional.")


def png(name="photo.png", data=PNG_BYTES):
    return SimpleUploadedFile(name, data, content_type="image/png")


def stored_files(settings):
    root = Path(settings.EVIDENCE_STORAGE_DIR)
    return sorted(p.name for p in root.glob("*")) if root.exists() else []


# ----------------------------------------------------------------- notes and files
def test_a_note_is_stored_with_a_hash_of_its_text(owner, incident):
    item = services.add_note(incident=incident, user=owner, text="He shouted at me.", title="Tuesday")
    assert item.sha256 == hashlib.sha256(b"He shouted at me.").hexdigest()
    assert item.uploaded_by == owner and item.uploaded_at is not None
    assert EvidenceAccessEvent.objects.filter(item=item, action="note").exists()


def test_an_empty_note_is_refused(owner, incident):
    with pytest.raises(services.EvidenceError):
        services.add_note(incident=incident, user=owner, text="   ")


def test_a_file_is_hashed_encrypted_and_never_stored_in_the_clear(owner, incident, settings):
    item = services.add_file(incident=incident, user=owner, upload=png(), title="Photo")
    assert item.sha256 == hashlib.sha256(PNG_BYTES).hexdigest()
    assert item.size_bytes == len(PNG_BYTES) and item.content_type == "image/png"
    on_disk = Path(settings.EVIDENCE_STORAGE_DIR) / item.storage_key
    assert PNG_BYTES not in on_disk.read_bytes()      # encrypted at rest
    assert services.read_bytes(item) == PNG_BYTES     # and recoverable by the owner's code path
    assert on_disk.stat().st_mode & 0o077 == 0         # not readable by other local users
    assert Path(settings.EVIDENCE_STORAGE_DIR).stat().st_mode & 0o077 == 0


def test_storage_keys_are_random_and_never_use_the_uploaded_name(owner, incident):
    item = services.add_file(incident=incident, user=owner, upload=png("../../etc/passwd.png"))
    assert services.KEY_RE.match(item.storage_key)
    assert "passwd" not in item.storage_key and "/" not in item.original_filename


@pytest.mark.parametrize("name", ["run.exe", "page.html", "image.svg", "script.php", "noextension", "photo.png.exe", "a.js"])
def test_disallowed_file_types_are_refused(owner, incident, settings, name):
    with pytest.raises(services.EvidenceError):
        services.add_file(incident=incident, user=owner, upload=SimpleUploadedFile(name, PNG_BYTES))
    assert not EvidenceItem.objects.exists() and stored_files(settings) == []


def test_a_file_whose_contents_do_not_match_its_extension_is_refused(owner, incident, settings):
    with pytest.raises(services.EvidenceError):
        services.add_file(incident=incident, user=owner, upload=png("fake.png", b"<script>alert(1)</script>"))
    with pytest.raises(services.EvidenceError):
        services.add_file(incident=incident, user=owner, upload=SimpleUploadedFile("fake.pdf", b"not a pdf"))
    assert stored_files(settings) == []


def test_size_limits_and_empty_files_are_enforced(owner, incident, settings):
    settings.EVIDENCE_MAX_BYTES = 10
    with pytest.raises(services.EvidenceError, match="too large"):
        services.add_file(incident=incident, user=owner, upload=SimpleUploadedFile("big.txt", b"A" * 11))
    with pytest.raises(services.EvidenceError, match="empty"):
        services.add_file(incident=incident, user=owner, upload=SimpleUploadedFile("none.txt", b""))
    services.add_file(incident=incident, user=owner, upload=SimpleUploadedFile("ok.txt", b"A" * 10))  # exactly at the limit


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd.png", "passwd.png"), ("..\\..\\win\\x.pdf", "x.pdf"), ("a b<c>.png", "a b_c.png"), ("", "file")])
def test_filenames_are_made_safe(raw, expected):
    assert services.sanitise_filename(raw) == expected


@pytest.mark.parametrize("key", ["../x.enc", "/etc/passwd", "a" * 32, "0" * 32 + ".exe", "", None])
def test_storage_keys_cannot_escape_the_vault(key):
    with pytest.raises(services.EvidenceError):
        services._path(key)


def test_deleting_an_item_removes_the_encrypted_file_and_keeps_the_audit_trail(owner, incident, settings):
    item = services.add_file(incident=incident, user=owner, upload=png())
    assert len(stored_files(settings)) == 1
    services.delete_item(item, owner)
    assert stored_files(settings) == [] and not EvidenceItem.objects.exists()
    assert EvidenceAccessEvent.objects.filter(action="delete", item__isnull=True, item_label="photo.png").exists()


def test_nobody_else_can_add_to_or_delete_my_records(owner, incident):
    stranger = make_user("other@example.test", "Other")
    with pytest.raises(PermissionDenied):
        services.add_note(incident=incident, user=stranger, text="planting a note")
    with pytest.raises(PermissionDenied):
        services.add_file(incident=incident, user=stranger, upload=png())
    item = services.add_note(incident=incident, user=owner, text="mine")
    with pytest.raises(PermissionDenied):
        services.delete_item(item, stranger)


# ----------------------------------------------------------------- evidence pack
def _open_pack(blob):
    return zipfile.ZipFile(io.BytesIO(blob))


def test_the_evidence_pack_has_a_timeline_hashes_and_honest_limitations(owner, incident):
    earlier = timezone.now() - timedelta(days=2)
    note = services.add_note(incident=incident, user=owner, text="Note text", event_time=earlier)
    photo = services.add_file(incident=incident, user=owner, upload=png(), title="Photo")
    z = _open_pack(services.build_pack(user=owner, incident=incident, items=[photo, note]))
    names = z.namelist()
    assert {"README_limitations.txt", "timeline.csv", "manifest.json"} <= set(names)
    assert "files/002_photo.png" in names  # numbered by position in the timeline (the note came first)

    manifest = json.loads(z.read("manifest.json"))
    assert manifest["item_count"] == 2
    assert [e["kind"] for e in manifest["items"]] == ["note", "file"]  # chronological, not selection order
    assert all(e["integrity_check"] == "match" for e in manifest["items"])
    assert {e["sha256_at_upload"] for e in manifest["items"]} == {note.sha256, photo.sha256}

    readme = z.read("README_limitations.txt").decode()
    assert "does NOT prove" in readme and "not legal advice" in readme
    assert "sha256" in z.read("timeline.csv").decode().splitlines()[0]


def test_the_pack_detects_a_changed_stored_file(owner, incident):
    photo = services.add_file(incident=incident, user=owner, upload=png())
    services._write_blob(photo.storage_key, services._fernet().encrypt(b"\x89PNG\r\n\x1a\nCHANGED"))
    manifest = json.loads(_open_pack(services.build_pack(user=owner, incident=incident, items=[photo])).read("manifest.json"))
    assert manifest["items"][0]["integrity_check"] == "MISMATCH"


def test_spreadsheet_formulas_in_notes_cannot_run_from_the_exported_csv(owner, incident):
    note = services.add_note(incident=incident, user=owner, text='=HYPERLINK("http://evil.example","click")')
    csv_text = _open_pack(services.build_pack(user=owner, incident=incident, items=[note])).read("timeline.csv").decode()
    assert "'=HYPERLINK" in csv_text


def test_a_pack_cannot_include_someone_elses_records(owner, incident):
    stranger = make_user("other@example.test", "Other")
    theirs = Incident.objects.create(owner=stranger, title="Theirs")
    their_note = services.add_note(incident=theirs, user=stranger, text="private")
    with pytest.raises(PermissionDenied):
        services.build_pack(user=owner, incident=incident, items=[their_note])
    with pytest.raises(PermissionDenied):
        services.build_pack(user=stranger, incident=incident, items=[])


# ----------------------------------------------------------------- sharing
def test_a_share_link_stores_only_a_hash_and_can_be_revoked_or_expire(owner, incident):
    item = services.add_note(incident=incident, user=owner, text="share me")
    share, token = services.create_share(item=item, user=owner, label="Counsellor", hours=2)
    assert token not in share.token_hash and share.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert services.find_active_share(token).pk == share.pk
    assert services.find_active_share(token + "x") is None

    EvidenceShare.objects.filter(pk=share.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert services.find_active_share(token) is None  # expired

    share2, token2 = services.create_share(item=item, user=owner, label="Lawyer", hours=2)
    services.revoke_share(share2, owner)
    assert services.find_active_share(token2) is None  # revoked immediately


def test_share_duration_is_capped_and_only_the_owner_can_share(owner, incident):
    item = services.add_note(incident=incident, user=owner, text="x")
    share, _ = services.create_share(item=item, user=owner, label="Anyone", hours=100000)
    assert share.expires_at <= timezone.now() + timedelta(days=14, minutes=1)
    with pytest.raises(PermissionDenied):
        services.create_share(item=item, user=make_user("other@example.test", "Other"), label="x", hours=1)


# ----------------------------------------------------------------- over HTTP
def test_the_owner_can_download_and_each_download_is_logged(client, owner, incident):
    item = services.add_file(incident=incident, user=owner, upload=png())
    client.force_login(owner)
    response = client.get(reverse("evidence:download", args=[item.pk]))
    assert response.status_code == 200 and b"".join(response.streaming_content) == PNG_BYTES
    assert "attachment" in response["Content-Disposition"] and response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]
    assert EvidenceAccessEvent.objects.filter(item=item, action="download", actor=owner).exists()


def test_other_people_and_anonymous_visitors_cannot_reach_my_evidence(client, owner, incident):
    item = services.add_file(incident=incident, user=owner, upload=png())
    urls = [reverse("evidence:download", args=[item.pk]), reverse("evidence:incident", args=[incident.pk])]
    for url in urls:
        anonymous = client.get(url)
        assert anonymous.status_code == 302 and "/accounts/login/" in anonymous.url
    client.force_login(make_user("other@example.test", "Other"))
    for url in urls:
        assert client.get(url).status_code == 404  # not even confirmation that it exists
    assert client.post(reverse("evidence:delete", args=[item.pk])).status_code == 404
    assert client.post(reverse("evidence:export", args=[incident.pk]), {"item": [str(item.pk)]}).status_code == 404
    assert EvidenceItem.objects.filter(pk=item.pk).exists()


def test_the_vault_pages_work_end_to_end(client, owner):
    client.force_login(owner)
    created = client.post(reverse("evidence:incident_new"), {"title": "Fictional incident", "description": "Demo"})
    assert created.status_code == 302
    incident = Incident.objects.get(owner=owner)
    note_url, upload_url = reverse("evidence:note", args=[incident.pk]), reverse("evidence:upload", args=[incident.pk])
    assert client.post(note_url, {"note_text": "Something happened.", "title": "Note"}).status_code == 302
    assert client.post(upload_url, {"file": png(), "title": "Photo"}).status_code == 302
    assert client.post(upload_url, {"file": SimpleUploadedFile("evil.exe", b"MZ"), "title": "Bad"}).status_code == 302
    assert incident.items.count() == 2  # the .exe was refused

    page = client.get(reverse("evidence:incident", args=[incident.pk])).content.decode()
    assert "Something happened." in page and "Photo" in page

    ids = [str(i.pk) for i in incident.items.all()]
    pack = client.post(reverse("evidence:export", args=[incident.pk]), {"item": ids})
    assert pack.status_code == 200 and pack["Content-Type"] == "application/zip"
    assert "manifest.json" in _open_pack(pack.content).namelist()
    assert client.post(reverse("evidence:export", args=[incident.pk]), {}).status_code == 302  # nothing ticked

    search = client.get(reverse("evidence:incidents"), {"q": "Something happened"}).content.decode()
    assert "Fictional incident" in search
    assert "Fictional incident" not in client.get(reverse("evidence:incidents"), {"q": "zzz-no-match"}).content.decode()


def test_a_share_link_works_without_login_until_it_is_revoked_then_stops(client, owner, incident):
    item = services.add_file(incident=incident, user=owner, upload=png())
    client.force_login(owner)
    shared = client.post(reverse("evidence:share", args=[item.pk]), {"recipient_label": "Counsellor", "hours": 1})
    assert shared.status_code == 302
    share = EvidenceShare.objects.get(item=item)
    token, anonymous = services.create_share(item=item, user=owner, label="Direct", hours=1)[1], Client()

    url = reverse("evidence:shared", args=[token])
    response = anonymous.get(url)
    assert response.status_code == 200 and b"".join(response.streaming_content) == PNG_BYTES
    assert EvidenceAccessEvent.objects.filter(item=item, action="share_download", via="share", actor=None).exists()

    assert client.post(reverse("evidence:share_revoke", args=[share.pk])).status_code == 302
    direct = EvidenceShare.objects.get(token_hash=hashlib.sha256(token.encode()).hexdigest())
    assert client.post(reverse("evidence:share_revoke", args=[direct.pk])).status_code == 302
    assert anonymous.get(url).status_code == 404
    assert Client().get(reverse("evidence:shared", args=["not-a-token"])).status_code == 404


def test_only_the_owner_can_revoke_a_share(client, owner, incident):
    item = services.add_note(incident=incident, user=owner, text="x")
    share, token = services.create_share(item=item, user=owner, label="Someone", hours=1)
    client.force_login(make_user("other@example.test", "Other"))
    assert client.post(reverse("evidence:share_revoke", args=[share.pk])).status_code == 404
    assert services.find_active_share(token) is not None


def test_deleting_an_account_removes_the_encrypted_files(client, owner, incident, settings):
    services.add_file(incident=incident, user=owner, upload=png())
    assert len(stored_files(settings)) == 1
    client.force_login(owner)
    client.post(reverse("accounts:delete"), {"password": PASSWORD, "confirm": "on"})
    assert not User.objects.filter(pk=owner.pk).exists()
    assert stored_files(settings) == []
