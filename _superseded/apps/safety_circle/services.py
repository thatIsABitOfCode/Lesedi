"""Safety Circle services: granular permissions, invitations, removal."""
import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps import audit

from .models import ContactInvitation, ContactPermission, Permission

INVITE_TTL = timedelta(days=7)


class InvitationError(Exception):
    """Deliberately vague so a bad token reveals nothing."""


def has_permission(contact, permission):
    """True only while the contact is not removed and the permission is not revoked."""
    return ContactPermission.objects.filter(
        contact=contact,
        permission=permission,
        revoked_at__isnull=True,
        contact__removed_at__isnull=True,
    ).exists()


def active_permissions(contact):
    return list(
        contact.permissions.filter(revoked_at__isnull=True).values_list("permission", flat=True)
    )


@transaction.atomic
def set_permissions(contact, wanted, actor):
    """Make the contact's active permissions exactly `wanted` (an iterable of values)."""
    wanted = set(wanted) & set(Permission.values)
    now = timezone.now()
    existing = {row.permission: row for row in contact.permissions.all()}
    for perm in Permission.values:
        row = existing.get(perm)
        if perm in wanted:
            if row is None:
                ContactPermission.objects.create(contact=contact, permission=perm, granted_at=now)
                audit.record(actor, "circle.permission_granted", contact, permission=perm)
            elif row.revoked_at is not None:
                row.revoked_at = None
                row.granted_at = now
                row.save(update_fields=["revoked_at", "granted_at"])
                audit.record(actor, "circle.permission_granted", contact, permission=perm)
        elif row is not None and row.revoked_at is None:
            row.revoked_at = now
            row.save(update_fields=["revoked_at"])
            audit.record(actor, "circle.permission_revoked", contact, permission=perm)


@transaction.atomic
def revoke_permission(contact, permission, actor):
    now = timezone.now()
    updated = ContactPermission.objects.filter(
        contact=contact, permission=permission, revoked_at__isnull=True
    ).update(revoked_at=now)
    if updated:
        audit.record(actor, "circle.permission_revoked", contact, permission=permission)
    return updated


def create_invitation(contact, actor):
    """Returns the one-time token. Only its hash is stored, so it cannot be shown again."""
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        contact.invitations.filter(status=ContactInvitation.Status.PENDING).update(
            status=ContactInvitation.Status.REVOKED
        )
        ContactInvitation.objects.create(
            contact=contact,
            token_hash=hash_token(token),
            expires_at=timezone.now() + INVITE_TTL,
        )
        audit.record(actor, "circle.invitation_created", contact)
    return token


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def get_valid_invitation(token):
    invitation = (
        ContactInvitation.objects.select_related("contact__owner").filter(token_hash=hash_token(token)).first()
    )
    if (
        invitation is None
        or invitation.status != ContactInvitation.Status.PENDING
        or invitation.expires_at <= timezone.now()
        or invitation.contact.removed_at is not None
    ):
        raise InvitationError("invalid")
    return invitation


@transaction.atomic
def accept_invitation(token, user):
    invitation = get_valid_invitation(token)
    invitation = ContactInvitation.objects.select_for_update().select_related("contact").get(pk=invitation.pk)
    if invitation.status != ContactInvitation.Status.PENDING:
        raise InvitationError("invalid")
    contact = invitation.contact
    if contact.owner_id == user.id:
        raise InvitationError("invalid")
    now = timezone.now()
    contact.linked_user = user
    contact.verified_at = now
    contact.save(update_fields=["linked_user", "verified_at"])
    invitation.status = ContactInvitation.Status.ACCEPTED
    invitation.accepted_at = now
    invitation.save(update_fields=["status", "accepted_at"])
    audit.record(user, "circle.invitation_accepted", contact)
    return contact


@transaction.atomic
def remove_contact(contact, actor):
    """Soft-remove: revoke every permission and share, drop plan assignments and
    pending invitations. The row is kept so past alert history stays intact."""
    from apps.evidence.models import EvidenceShare
    from apps.safety_plans import services as plan_services

    now = timezone.now()
    contact.permissions.filter(revoked_at__isnull=True).update(revoked_at=now)
    contact.invitations.filter(status=ContactInvitation.Status.PENDING).update(
        status=ContactInvitation.Status.REVOKED
    )
    EvidenceShare.objects.filter(shared_with=contact, revoked_at__isnull=True).update(revoked_at=now)
    plan_services.remove_contact_from_plans(contact, actor)
    contact.removed_at = now
    contact.save(update_fields=["removed_at"])
    audit.record(actor, "circle.contact_removed", contact)
