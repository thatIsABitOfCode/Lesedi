"""The flagship demonstration, driven through the real URLs, database and services (no frontend-only state).

Naledi (account owner) names Faith as primary responder and Mapaseka as backup. All three are fictional and every
notification is simulated: no message is sent, nobody is called, and nobody is on their way."""
import io
import json
import zipfile
from datetime import date, timedelta
from urllib.parse import urlparse

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounts.models import User
from evidence.models import EvidenceItem, Incident
from guardian.models import GuardianActivation
from notifications.models import DeliveryStatus, NotificationDelivery
from safety import services as safety
from safety.health import assess_plan
from safety.models import ContactStatus, Permission, TrustedContact
from tests.factories import PASSWORD, PNG_BYTES, SENTINEL_DESTINATION, SENTINEL_INSTRUCTION

pytestmark = pytest.mark.django_db


def post_json(client, name, data=None, args=None):
    return client.post(reverse(name, args=args), data=json.dumps(data or {}), content_type="application/json")


def invite_and_accept(naledi, name, phone, email, channel):
    """Naledi adds a person, creates an invitation link, and that person (not logged in) accepts it."""
    added = naledi.post(reverse("safety:contact_add"), {
        "name": name, "relationship": "Friend", "phone": phone, "email": email, "preferred_channel": channel})
    assert added.status_code == 302
    contact = TrustedContact.objects.get(name=name)
    assert contact.status == ContactStatus.PENDING  # nothing is shared until they agree

    invited = naledi.post(reverse("safety:contact", args=[contact.pk]), {"action": "invite"})
    path = urlparse(invited.context["invite_link"]).path
    assert Client().post(path, {"decision": "accept"}).status_code == 200
    contact.refresh_from_db()
    assert contact.status == ContactStatus.ACTIVE and contact.consented_at is not None
    return contact


def set_permissions(naledi, contact, *permissions):
    response = naledi.post(reverse("safety:contact", args=[contact.pk]),
                           {"action": "permissions", "permissions": [p.value for p in permissions]})
    assert response.status_code == 302


def test_naledi_faith_and_mapaseka_end_to_end():
    naledi = Client()

    # 1. Naledi creates an account and logs in.
    assert naledi.post(reverse("accounts:register"), {
        "email": "naledi@example.test", "display_name": "Naledi", "password1": PASSWORD, "password2": PASSWORD}).status_code == 302
    assert naledi.post(reverse("accounts:login"), {"username": "naledi@example.test", "password": PASSWORD}).status_code == 302
    user = User.objects.get(email="naledi@example.test")

    # 2. She writes a safety plan. It is private and versioned.
    plan_page = naledi.get(reverse("safety:plan"))
    assert plan_page.status_code == 200
    saved = naledi.post(reverse("safety:plan"), {
        "title": "Naledi's plan (demo)", "emergency_instructions": SENTINEL_INSTRUCTION,
        "safe_destination": SENTINEL_DESTINATION, "transport_notes": "A neighbour could drive me.",
        "transport_confirmed": "on", "essential_documents": "ID copy", "checkin_method": "Evening message",
        "checkin_time": "", "ack_timeout_seconds": 10, "comms_failure_contingency": "Faith visits at 19:00.",
        "review_date": (date.today() + timedelta(days=30)).isoformat()})
    assert saved.status_code == 302
    plan = safety.get_or_create_plan(user)
    assert plan.version == 2 and plan.versions.count() == 2

    # 3. She chooses Faith (primary) and Mapaseka (backup). Both accept; neither receives anything yet.
    faith = invite_and_accept(naledi, "Faith", "+27 00 000 0001", "faith@example.test", "sms")
    mapaseka = invite_and_accept(naledi, "Mapaseka", "+27 00 000 0002", "mapaseka@example.test", "whatsapp")
    for contact, rank in ((faith, 1), (mapaseka, 2)):
        response = naledi.post(reverse("safety:contact", args=[contact.pk]),
                               {"action": "assign", "rank": rank, "grant_alert_permissions": "on"})
        assert response.status_code == 302

    # 4. She reviews exactly what each responder may see. Only Faith may read her instruction.
    set_permissions(naledi, faith, Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT, Permission.RECEIVE_INSTRUCTION)
    assert safety.active_permissions(plan, faith) == {"receive_alert", "acknowledge_alert", "receive_instruction"}
    assert safety.active_permissions(plan, mapaseka) == {"receive_alert", "acknowledge_alert"}

    # 5. Plan health tells her, calmly, that she has not confirmed her contacts' details yet.
    assert naledi.get(reverse("safety:health")).status_code == 200
    assert {f"DETAILS_UNCONFIRMED:{faith.id}", f"DETAILS_UNCONFIRMED:{mapaseka.id}"} <= {f.code for f in assess_plan(plan)}
    for contact in (faith, mapaseka):
        naledi.post(reverse("safety:contact", args=[contact.pk]), {"action": "confirm_details", "confirmed": "on"})
    assert [f for f in assess_plan(plan) if f.severity == "high"] == []

    # 6. SHIELD: she reports that someone else can get into one of her accounts and is given a mitigation.
    assert naledi.post(reverse("shield:page"), {"shared_account_access": "on"}).status_code == 302
    shield_html = naledi.get(reverse("shield:page")).content.decode()
    assert "Someone else may be able to get into your accounts" in shield_html
    assert "change passwords and recovery options" in shield_html and "cannot detect spyware" in shield_html

    # 7. She activates Guardian Mode (simulation). Faith is notified; the status says only what is true.
    assert "SIMULATION: no real SMS" in naledi.get(reverse("guardian:page")).content.decode()
    started = post_json(naledi, "guardian_api:activate", {"idempotency_key": "demo-1"})
    assert started.status_code == 201
    activation = started.json()
    assert activation["state"] == "awaiting_acknowledgement" and activation["is_simulation"]
    assert [d["contact"] for d in activation["deliveries"]] == ["Faith"]
    assert activation["deliveries"][0]["status_code"] == "submitted"  # submitted: not delivered, not seen
    assert activation["acknowledgements"] == []

    # 8. Faith does not acknowledge in time, so the fallback she authorised runs: Mapaseka is notified.
    after = post_json(naledi, "guardian_api:simulate_timeout", args=[activation["id"]]).json()
    assert after["state"] == "backup_contacted"
    assert [(d["contact"], d["channel"], d["status_code"]) for d in after["deliveries"]] == [
        ("Faith", "SMS", "submitted"), ("Mapaseka", "WhatsApp", "submitted")]
    messages = [e["message"] for e in after["events"]]
    assert any("No acknowledgement within 10 seconds" in m for m in messages)
    assert any(m.startswith("[SIMULATION]") and "Mapaseka" in m for m in messages)  # the visible timeline

    # 9. Nothing real happened, and the records prove it.
    assert not NotificationDelivery.objects.exclude(provider="simulation").exists()
    assert not NotificationDelivery.objects.filter(is_simulated=False).exists()
    assert not NotificationDelivery.objects.filter(status=DeliveryStatus.DELIVERED).exists()
    assert "no emergency service was contacted" in after["notice"]
    for delivery in NotificationDelivery.objects.all():
        assert SENTINEL_DESTINATION not in delivery.body_preview and SENTINEL_INSTRUCTION not in delivery.body_preview

    # 10. Mapaseka opens her link (not logged in). She sees no instruction. Her acknowledgement is recorded.
    link = next(d["responder_link"] for d in after["deliveries"] if d["contact"] == "Mapaseka")
    mapaseka_view = Client().get(link).content.decode()
    assert "Naledi" in mapaseka_view and SENTINEL_INSTRUCTION not in mapaseka_view and SENTINEL_DESTINATION not in mapaseka_view
    assert Client().post(link).status_code == 200
    current = naledi.get(reverse("guardian_api:current")).json()["activation"]
    assert current["state"] == "acknowledged" and [a["contact"] for a in current["acknowledgements"]] == ["Mapaseka"]
    assert any("does not confirm that anyone is travelling" in e["message"] for e in current["events"])

    # 11. Naledi marks it resolved.
    assert post_json(naledi, "guardian_api:resolve", args=[activation["id"]]).json()["state"] == "resolved"
    assert GuardianActivation.objects.get(pk=activation["id"]).closed_at is not None

    # 12. Afterwards she records an incident, adds a note, uploads a sample file and exports a selected pack.
    assert naledi.post(reverse("evidence:incident_new"), {"title": "Demo incident", "description": "Fictional."}).status_code == 302
    incident = Incident.objects.get(owner=user)
    naledi.post(reverse("evidence:note", args=[incident.pk]), {"note_text": "Fictional note for the demo.", "title": "Note"})
    naledi.post(reverse("evidence:upload", args=[incident.pk]),
                {"file": SimpleUploadedFile("sample.png", PNG_BYTES, content_type="image/png"), "title": "Sample photo"})
    assert incident.items.count() == 2
    pack = naledi.post(reverse("evidence:export", args=[incident.pk]), {"item": [str(i.pk) for i in incident.items.all()]})
    archive = zipfile.ZipFile(io.BytesIO(pack.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["item_count"] == 2 and all(e["integrity_check"] == "match" for e in manifest["items"])
    assert "does NOT prove" in archive.read("README_limitations.txt").decode()
    stranger = Client()
    stranger.force_login(User.objects.create_user("other@example.test", PASSWORD, display_name="Other"))
    assert stranger.get(reverse("evidence:incident", args=[incident.pk])).status_code == 404

    # 13. She reviews her plan: Faith no longer needs to see the instruction, and Mapaseka is replaced as backup.
    set_permissions(naledi, faith, Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT)
    assert not safety.has_permission(plan, faith, Permission.RECEIVE_INSTRUCTION)  # revoked

    naledi.post(reverse("safety:contact", args=[mapaseka.pk]), {"action": "unassign"})
    assert f"PERMISSIONS_WITHOUT_ROLE:{mapaseka.id}" in {f.code for f in assess_plan(plan)}  # noticed
    naledi.post(reverse("safety:contact", args=[mapaseka.pk]), {"action": "permissions"})  # untick everything
    assert safety.active_permissions(plan, mapaseka) == set()
    assert f"PERMISSIONS_WITHOUT_ROLE:{mapaseka.id}" not in {f.code for f in assess_plan(plan)}

    lindiwe = invite_and_accept(naledi, "Lindiwe", "+27 00 000 0003", "lindiwe@example.test", "sms")
    naledi.post(reverse("safety:contact", args=[lindiwe.pk]), {"action": "assign", "rank": 2, "grant_alert_permissions": "on"})
    naledi.post(reverse("safety:contact", args=[lindiwe.pk]), {"action": "confirm_details", "confirmed": "on"})
    revised = dict(title="Naledi's plan (demo)", emergency_instructions=SENTINEL_INSTRUCTION,
                   safe_destination=SENTINEL_DESTINATION, transport_notes="A neighbour could drive me.",
                   transport_confirmed="on", essential_documents="ID copy", checkin_method="Evening message",
                   checkin_time="", ack_timeout_seconds=10, comms_failure_contingency="Faith or Lindiwe visit at 19:00.",
                   review_date=(date.today() + timedelta(days=60)).isoformat())
    assert naledi.post(reverse("safety:plan"), revised).status_code == 302
    plan.refresh_from_db()
    assert plan.version == 3 and plan.versions.count() == 3
    assert [r.contact.name for r in plan.responders.select_related("contact")] == ["Faith", "Lindiwe"]

    # 14. The next activation uses the updated arrangements: the removed backup is never contacted again.
    second = post_json(naledi, "guardian_api:activate", {"idempotency_key": "demo-2"}).json()
    skipped = post_json(naledi, "guardian_api:simulate_timeout", args=[second["id"]]).json()
    assert [d["contact"] for d in skipped["deliveries"]] == ["Faith", "Lindiwe"]
    assert not NotificationDelivery.objects.filter(activation_id=second["id"], contact=mapaseka).exists()
    assert EvidenceItem.objects.filter(owner=user).count() == 2  # the evidence was untouched by all of this
