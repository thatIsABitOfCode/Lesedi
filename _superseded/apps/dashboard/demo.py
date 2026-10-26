"""Fictional demonstration data: Naledi, Faith and Mapaseka.

Everything here is invented. Phone numbers and addresses are placeholders. It
runs through the real services (invitations, permissions, plan versions), so the
demo exercises the same code paths as real use. Used by the `seed_demo`
management command and by the tests.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import Role, User
from apps.notifications.channels import Channel
from apps.safety_circle import services as circle
from apps.safety_circle.models import Permission, TrustedContact
from apps.safety_plans import services as plans
from apps.safety_plans.models import CheckinMethod, ResponderRole

DEMO_DOMAIN = "demo.lesedi.example"


@dataclass
class DemoWorld:
    naledi: User
    faith_user: User
    mapaseka_user: User
    faith: TrustedContact
    mapaseka: TrustedContact
    plan: object
    password: str


def _contact(owner, linked_user, name, phone, email):
    contact = TrustedContact.objects.create(
        owner=owner,
        name=name,
        phone=phone,
        email=email,
        preferred_channel=Channel.SMS,
        fallback_channel=Channel.EMAIL,
    )
    token = circle.create_invitation(contact, owner)
    circle.accept_invitation(token, linked_user)  # the contact accepts from their own account
    contact.refresh_from_db()
    return contact


def build_demo_world(password, ack_timeout_seconds=30):
    naledi = User.objects.create_user(f"naledi@{DEMO_DOMAIN}", password, display_name="Naledi (demo)")
    faith_user = User.objects.create_user(
        f"faith@{DEMO_DOMAIN}", password, display_name="Faith (demo)", role=Role.TRUSTED_CONTACT
    )
    mapaseka_user = User.objects.create_user(
        f"mapaseka@{DEMO_DOMAIN}", password, display_name="Mapaseka (demo)", role=Role.TRUSTED_CONTACT
    )

    faith = _contact(naledi, faith_user, "Faith (demo)", "+27000000001", f"faith.contact@{DEMO_DOMAIN}")
    mapaseka = _contact(naledi, mapaseka_user, "Mapaseka (demo)", "+27000000002", f"mapaseka.contact@{DEMO_DOMAIN}")

    # What Naledi chooses to allow each person. Nothing else is shared.
    circle.set_permissions(
        faith, [Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT, Permission.RECEIVE_INSTRUCTION], naledi
    )
    circle.set_permissions(
        mapaseka, [Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT, Permission.BACKUP_RESPONDER], naledi
    )

    plan = plans.save_plan(
        naledi,
        None,
        {
            "title": "Naledi's plan (demo)",
            "emergency_instructions": "Please phone me first. If I do not answer, check on me only if it is safe for you.",
            "safe_destination": "Fictional safe place: 1 Example Street, Demo Town",
            "transport_arrangement": "Mapaseka can drive (demo)",
            "transport_confirmed": True,
            "essential_documents": "ID, spare keys, phone charger (demo reminder list)",
            "alternative_arrangements": "If Faith cannot respond, Mapaseka is the backup.",
            "comms_failure_plan": "Code word with a neighbour (demo).",
            "checkin_method": CheckinMethod.INAPP,
            "checkin_time": None,
            "ack_timeout_seconds": ack_timeout_seconds,
            "auto_escalate_to_backup": True,
            "review_due": timezone.localdate() + timedelta(days=90),
        },
    )
    plans.assign_responder(naledi, plan, faith, ResponderRole.PRIMARY)
    plans.assign_responder(naledi, plan, mapaseka, ResponderRole.BACKUP)
    plan.refresh_from_db()
    return DemoWorld(naledi, faith_user, mapaseka_user, faith, mapaseka, plan, password)
