"""Helpers that build fictional people and plans through the real service layer. Nobody here is a real person."""
from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.channels import Channel
from safety import services as safety
from safety.models import ContactStatus, Permission, TrustedContact

PASSWORD = "Correct-Horse-Battery-9"
SENTINEL_DESTINATION = "FICTIONAL-DESTINATION-XYZ"
SENTINEL_INSTRUCTION = "Please call me from a safe place."
ALERT = {Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT}

# A tiny but valid PNG header plus filler: enough for the vault's content check.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fictional-image-bytes" * 4


def make_user(email="naledi@example.test", name="Naledi", role="survivor"):
    return get_user_model().objects.create_user(email, PASSWORD, display_name=name, role=role)


def make_contact(owner, name, *, channel=Channel.SMS, active=True, confirmed=True, phone=None, email=None):
    number = {"Faith": "+27 00 000 0001", "Mapaseka": "+27 00 000 0002"}.get(name, "+27 00 000 0009")
    return TrustedContact.objects.create(
        owner=owner, name=name, relationship="Friend", phone=number if phone is None else phone,
        email=f"{name.lower()}@example.test" if email is None else email, preferred_channel=channel,
        status=ContactStatus.ACTIVE if active else ContactStatus.INVITED,
        consented_at=timezone.now() if active else None, owner_confirmed_details=confirmed)


def complete_plan(plan):
    plan.emergency_instructions = SENTINEL_INSTRUCTION
    plan.safe_destination = SENTINEL_DESTINATION
    plan.transport_notes = "A neighbour can drive."
    plan.transport_confirmed = True
    plan.essential_documents = "ID copy"
    plan.checkin_method = "Evening message"
    plan.comms_failure_contingency = "Visit at 19:00"
    plan.ack_timeout_seconds = 60
    plan.review_date = date.today() + timedelta(days=30)
    return safety.save_plan(plan)


def make_circle(owner=None):
    """Naledi with a complete plan, Faith (primary, SMS) and Mapaseka (backup, WhatsApp), both already accepted."""
    owner = owner or make_user()
    plan = complete_plan(safety.get_or_create_plan(owner))
    faith = make_contact(owner, "Faith", channel=Channel.SMS)
    mapaseka = make_contact(owner, "Mapaseka", channel=Channel.WHATSAPP)
    safety.assign_responder(plan, faith, 1)
    safety.assign_responder(plan, mapaseka, 2)
    safety.set_permissions(plan, faith, ALERT | {Permission.RECEIVE_INSTRUCTION})
    safety.set_permissions(plan, mapaseka, ALERT)
    return SimpleNamespace(owner=owner, plan=plan, faith=faith, mapaseka=mapaseka)
