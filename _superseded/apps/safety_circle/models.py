import uuid

from django.conf import settings
from django.db import models

from apps.notifications.channels import Channel


class Permission(models.TextChoices):
    RECEIVE_CHECKIN = "receive_checkin", "Receive a check-in request"
    RECEIVE_ALERT = "receive_alert", "Receive an emergency alert"
    ACKNOWLEDGE_ALERT = "acknowledge_alert", "Acknowledge an alert"
    RECEIVE_INSTRUCTION = "receive_instruction", "See the instruction I have approved for responders"
    BACKUP_RESPONDER = "backup_responder", "Act as a backup responder"
    RECEIVE_LOCATION = "receive_location", "Receive a temporary location share (not active yet)"
    COMMUNITY_RESPONSE = "community_response", "Take part in an authorised community response (not active yet)"


# Permissions that have working behaviour in this build.
ACTIVE_PERMISSIONS = {
    Permission.RECEIVE_ALERT,
    Permission.ACKNOWLEDGE_ALERT,
    Permission.RECEIVE_INSTRUCTION,
    Permission.BACKUP_RESPONDER,
}


class SimulationBehaviour(models.TextChoices):
    NORMAL = "normal", "Normal (accepts messages, never acknowledges on its own)"
    FAIL_PREFERRED = "fail_preferred", "Preferred channel fails; other channels work"
    FAIL_ALL = "fail_all", "All channels fail"
    FLAKY = "flaky", "Temporary errors (exercises retries)"


class TrustedContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trusted_contacts")
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    preferred_channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.SMS)
    fallback_channel = models.CharField(max_length=16, choices=Channel.choices, blank=True)

    # Set when the person accepts an invitation with their own LESEDI account.
    # This is the only thing LESEDI treats as "verified": that this person
    # controls the account the invitation was accepted from. It says nothing
    # about whether they are trustworthy.
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="contact_links"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    # Development/demo only: controls how the simulated adapter behaves.
    simulation_behaviour = models.CharField(
        max_length=16, choices=SimulationBehaviour.choices, default=SimulationBehaviour.NORMAL
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "created_at"]

    @property
    def is_verified(self):
        return self.verified_at is not None

    def __str__(self):
        return self.name


class ContactPermission(models.Model):
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="permissions")
    permission = models.CharField(max_length=32, choices=Permission.choices)
    granted_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["contact", "permission"], name="unique_contact_permission")]

    @property
    def is_active(self):
        return self.revoked_at is None


class ContactInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="invitations")
    token_hash = models.CharField(max_length=64, unique=True)  # only the hash is stored
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
