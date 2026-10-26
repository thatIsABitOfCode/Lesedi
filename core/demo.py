"""Fictional demonstration data: Naledi (account owner), Faith (primary responder), Mapaseka (backup).

Every name, email (reserved .test domain) and phone number here is invented. Nobody is ever contacted."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.channels import Channel
from safety import services as safety
from safety.models import ContactStatus, Permission, TrustedContact
from shield.models import ShieldSelfReport

DEMO_EMAIL = "naledi@example.test"


def _contact(owner, name, relationship, phone, email, channel):
    contact, _ = TrustedContact.objects.get_or_create(
        owner=owner, name=name,
        defaults={"relationship": relationship, "phone": phone, "email": email, "preferred_channel": channel})
    if contact.status != ContactStatus.ACTIVE:
        contact.status = ContactStatus.ACTIVE
        contact.consented_at = timezone.now()
        contact.save(update_fields=["status", "consented_at"])
    return contact


def seed_naledi(password: str) -> dict:
    User = get_user_model()
    naledi, _ = User.objects.get_or_create(email=DEMO_EMAIL, defaults={"display_name": "Naledi"})
    naledi.set_password(password)
    naledi.save()

    plan = safety.get_or_create_plan(naledi)
    plan.title = "Naledi's safety plan (demo)"
    plan.emergency_instructions = "Please call me from a safe place. If I do not answer, check on me in person."
    plan.safe_destination = "Fictional demo destination - not a real place."
    plan.transport_notes = "Demo: a neighbour could drive me."
    plan.essential_documents = "Demo: ID copy, spare keys."
    plan.checkin_method = "Evening message to Faith"
    plan.comms_failure_contingency = "If my phone is off, Faith visits at 19:00."
    plan.ack_timeout_seconds = 60
    plan.review_date = date.today() + timedelta(days=30)
    safety.save_plan(plan)

    faith = _contact(naledi, "Faith", "Friend", "+27 00 000 0001", "faith@example.test", Channel.SMS)
    mapaseka = _contact(naledi, "Mapaseka", "Cousin", "+27 00 000 0002", "mapaseka@example.test", Channel.WHATSAPP)

    for contact, rank, perms in (
        (faith, 1, {Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT, Permission.RECEIVE_INSTRUCTION}),
        (mapaseka, 2, {Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT}),
    ):
        safety.assign_responder(plan, contact, rank)
        safety.set_permissions(plan, contact, perms)

    # SHIELD scenario: the user reports that someone else can get into one of her accounts.
    ShieldSelfReport.objects.update_or_create(owner=naledi, defaults={"shared_account_access": True})
    return {"naledi": naledi, "faith": faith, "mapaseka": mapaseka, "plan": plan}
