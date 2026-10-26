from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from audit.services import record

from .models import (
    ContactInvitation, ContactStatus, Permission, ResponderAssignment, SafetyPlan,
    SafetyPlanPermission, SafetyPlanVersion, TrustedContact,
)

INVITE_SALT = "lesedi.invite"
SNAPSHOT_FIELDS = [
    "title", "emergency_instructions", "safe_destination", "transport_notes", "transport_confirmed",
    "essential_documents", "checkin_method", "comms_failure_contingency", "ack_timeout_seconds",
]


class SafetyError(ValueError):
    """A user-correctable problem with a requested change."""


def get_or_create_plan(owner) -> SafetyPlan:
    plan = SafetyPlan.objects.filter(owner=owner, is_active=True).first()
    if plan is None:
        with transaction.atomic():
            plan = SafetyPlan.objects.create(owner=owner)
            _snapshot(plan)
    return plan


def _snapshot(plan: SafetyPlan) -> None:
    data = {f: getattr(plan, f) for f in SNAPSHOT_FIELDS}
    data["checkin_time"] = plan.checkin_time.isoformat() if plan.checkin_time else None
    data["review_date"] = plan.review_date.isoformat() if plan.review_date else None
    data["responders"] = [{"rank": r.rank, "contact": r.contact.name} for r in plan.responders.select_related("contact")]
    plan.version += 1
    plan.save(update_fields=["version", "updated_at"])
    SafetyPlanVersion.objects.create(plan=plan, version=plan.version, snapshot=data)


@transaction.atomic
def save_plan(plan: SafetyPlan) -> SafetyPlan:
    """Persist edits and write a new immutable version entry."""
    plan.save()
    _snapshot(plan)
    record("plan.saved", actor=plan.owner, obj=plan)
    return plan


def active_permissions(plan, contact) -> set:
    return set(
        SafetyPlanPermission.objects.filter(plan=plan, contact=contact, revoked_at__isnull=True)
        .values_list("permission", flat=True)
    )


def has_permission(plan, contact, permission) -> bool:
    return SafetyPlanPermission.objects.filter(
        plan=plan, contact=contact, permission=permission, revoked_at__isnull=True
    ).exists()


@transaction.atomic
def set_permissions(plan, contact, wanted) -> None:
    if contact.owner_id != plan.owner_id:
        raise SafetyError("That contact does not belong to this plan.")
    valid = {p.value for p in Permission}
    wanted = set(wanted) & valid
    current = active_permissions(plan, contact)
    now = timezone.now()
    for perm in wanted - current:
        SafetyPlanPermission.objects.create(plan=plan, contact=contact, permission=perm)
        record("permission.granted", actor=plan.owner, obj=contact, metadata={"permission": perm})
    for perm in current - wanted:
        SafetyPlanPermission.objects.filter(
            plan=plan, contact=contact, permission=perm, revoked_at__isnull=True
        ).update(revoked_at=now)
        record("permission.revoked", actor=plan.owner, obj=contact, metadata={"permission": perm})


@transaction.atomic
def assign_responder(plan, contact, rank, *, grant_alert_permissions=False) -> ResponderAssignment:
    if contact.owner_id != plan.owner_id:
        raise SafetyError("That contact does not belong to this plan.")
    if contact.status != ContactStatus.ACTIVE:
        raise SafetyError("This person has not accepted your invitation yet, so they cannot be a responder.")
    existing = ResponderAssignment.objects.filter(plan=plan, rank=rank).exclude(contact=contact).first()
    if existing:
        raise SafetyError(f"Position {rank} is already held by {existing.contact.name}. Remove them first.")
    ResponderAssignment.objects.filter(plan=plan, contact=contact).delete()
    assignment = ResponderAssignment.objects.create(plan=plan, contact=contact, rank=rank)
    if grant_alert_permissions:
        set_permissions(plan, contact, active_permissions(plan, contact) | {Permission.RECEIVE_ALERT, Permission.ACKNOWLEDGE_ALERT})
    record("responder.assigned", actor=plan.owner, obj=contact, metadata={"rank": rank})
    return assignment


@transaction.atomic
def remove_responder(plan, contact) -> None:
    ResponderAssignment.objects.filter(plan=plan, contact=contact).delete()
    record("responder.removed", actor=plan.owner, obj=contact)


@transaction.atomic
def revoke_contact(contact: TrustedContact) -> None:
    """Remove a contact entirely: all permissions revoked, all responder slots freed."""
    now = timezone.now()
    SafetyPlanPermission.objects.filter(contact=contact, revoked_at__isnull=True).update(revoked_at=now)
    ResponderAssignment.objects.filter(contact=contact).delete()
    contact.status = ContactStatus.REVOKED
    contact.revoked_at = now
    contact.save(update_fields=["status", "revoked_at"])
    record("contact.revoked", actor=contact.owner, obj=contact)


@transaction.atomic
def create_invitation(contact: TrustedContact):
    """Returns (invitation, token). The token is shown to the owner (simulation) - delivery is not implemented."""
    if contact.status == ContactStatus.REVOKED:
        raise SafetyError("This contact was removed. Add them again to invite them.")
    invitation = ContactInvitation.objects.create(contact=contact)
    if contact.status == ContactStatus.PENDING:
        contact.status = ContactStatus.INVITED
        contact.save(update_fields=["status"])
    record("contact.invited", actor=contact.owner, obj=contact)
    return invitation, signing.dumps(str(invitation.id), salt=INVITE_SALT)


def load_invitation(token):
    """Return the open invitation for a token, or None if invalid, expired or already used."""
    try:
        invitation_id = signing.loads(token, salt=INVITE_SALT, max_age=settings.INVITATION_MAX_AGE)
    except signing.BadSignature:
        return None
    invitation = ContactInvitation.objects.select_related("contact", "contact__owner").filter(pk=invitation_id).first()
    if invitation is None or invitation.accepted_at or invitation.declined_at:
        return None
    if invitation.contact.status == ContactStatus.REVOKED:
        return None
    return invitation


@transaction.atomic
def respond_to_invitation(invitation: ContactInvitation, accept: bool) -> None:
    now = timezone.now()
    contact = invitation.contact
    if accept:
        invitation.accepted_at = now
        contact.status = ContactStatus.ACTIVE
        contact.consented_at = now
        contact.save(update_fields=["status", "consented_at"])
        record("invitation.accepted", obj=contact)
    else:
        invitation.declined_at = now
        record("invitation.declined", obj=contact)
    invitation.save()
    if not accept:
        revoke_contact(contact)
