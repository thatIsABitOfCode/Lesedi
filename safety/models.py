import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from notifications.channels import Channel


class Permission(models.TextChoices):
    """Granular, individually revocable permissions. Nothing is granted by default."""

    RECEIVE_ALERT = "receive_alert", "Receive an emergency alert from me"
    ACKNOWLEDGE_ALERT = "acknowledge_alert", "Acknowledge an alert (confirm they saw it)"
    RECEIVE_INSTRUCTION = "receive_instruction", "See the emergency instruction I wrote for them"


class SafetyPlan(models.Model):
    """The Living Safety Protocol. Private to its owner unless a permission says otherwise."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="safety_plans")
    title = models.CharField(max_length=120, default="My safety plan")
    is_active = models.BooleanField(default=True)
    emergency_instructions = models.TextField(blank=True, help_text="What you want an acknowledged responder to know. Only shared with contacts you allow.")
    safe_destination = models.TextField(blank=True, help_text="Stored privately. Never included in notifications.")
    transport_notes = models.TextField(blank=True)
    transport_confirmed = models.BooleanField(default=False, help_text="Tick when you have checked this arrangement is really available.")
    essential_documents = models.TextField(blank=True)
    checkin_method = models.CharField(max_length=120, blank=True)
    checkin_time = models.TimeField(null=True, blank=True)
    ack_timeout_seconds = models.PositiveIntegerField(
        default=300, validators=[MinValueValidator(10), MaxValueValidator(3600)],
        help_text="How long to wait for an acknowledgement before trying the next responder (10-3600 seconds).")
    comms_failure_contingency = models.TextField(blank=True, help_text="What should happen if a phone or channel does not work?")
    review_date = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner"], condition=Q(is_active=True), name="one_active_plan_per_owner"),
        ]

    def __str__(self):
        return f"{self.title} (v{self.version})"


class SafetyPlanVersion(models.Model):
    plan = models.ForeignKey(SafetyPlan, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["plan", "version"], name="unique_plan_version")]


class ContactStatus(models.TextChoices):
    PENDING = "pending", "Added, not yet invited"
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Accepted"
    REVOKED = "revoked", "Removed or declined"


class TrustedContact(models.Model):
    """A person the owner chose. Details are what the OWNER entered; LESEDI has not verified them."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trusted_contacts")
    name = models.CharField(max_length=80)
    relationship = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    preferred_channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.SMS)
    status = models.CharField(max_length=16, choices=ContactStatus.choices, default=ContactStatus.PENDING)
    consented_at = models.DateTimeField(null=True, blank=True)
    # The owner's own statement that they confirmed these details (for example by phoning the person).
    owner_confirmed_details = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ContactInvitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="invitations")
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)


class ResponderAssignment(models.Model):
    """rank 1 = primary responder, 2 = first backup, and so on."""

    plan = models.ForeignKey(SafetyPlan, on_delete=models.CASCADE, related_name="responders")
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="assignments")
    rank = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "rank"], name="unique_responder_rank"),
            models.UniqueConstraint(fields=["plan", "contact"], name="unique_responder_contact"),
        ]


class SafetyPlanPermission(models.Model):
    plan = models.ForeignKey(SafetyPlan, on_delete=models.CASCADE, related_name="permissions")
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="permissions")
    permission = models.CharField(max_length=32, choices=Permission.choices)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "contact", "permission"], condition=Q(revoked_at__isnull=True),
                name="one_active_grant_per_permission"),
        ]
        indexes = [models.Index(fields=["plan", "contact", "revoked_at"])]
