import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def default_review_due():
    return timezone.localdate() + timedelta(days=90)


class CheckinMethod(models.TextChoices):
    NONE = "none", "No check-in arranged yet"
    INAPP = "inapp", "In-app reminder"
    SMS = "sms", "Text message"
    CALL = "call", "A phone call from someone I trust"


class ResponderRole(models.TextChoices):
    PRIMARY = "primary", "Primary responder"
    BACKUP = "backup", "Backup responder"


class SafetyPlan(models.Model):
    """A person's Living Safety Protocol. Private to the owner: nothing here is
    shared unless the owner grants a specific permission to a specific contact."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="safety_plans")
    title = models.CharField(max_length=120, default="My safety plan")

    emergency_instructions = models.TextField(
        blank=True,
        help_text="What you would like an approved responder to do. Only contacts you give the "
        "'instruction' permission can see this, and only during an active alert.",
    )
    safe_destination = models.TextField(
        blank=True, help_text="Stored privately. Never included in messages or shown to contacts."
    )
    transport_arrangement = models.CharField(max_length=200, blank=True)
    transport_confirmed = models.BooleanField(default=False, verbose_name="I have confirmed this transport arrangement")
    essential_documents = models.TextField(blank=True, help_text="A reminder list for yourself.")
    alternative_arrangements = models.TextField(blank=True, help_text="What happens if a responder is unavailable.")
    comms_failure_plan = models.TextField(blank=True, help_text="What you will do if phones or data are not working.")

    checkin_method = models.CharField(max_length=16, choices=CheckinMethod.choices, default=CheckinMethod.NONE)
    checkin_time = models.TimeField(null=True, blank=True)

    ack_timeout_seconds = models.PositiveIntegerField(
        default=300,
        validators=[MinValueValidator(10), MaxValueValidator(3600)],
        verbose_name="Seconds to wait for an acknowledgement",
    )
    auto_escalate_to_backup = models.BooleanField(
        default=False,
        verbose_name="If my primary responder does not acknowledge in time, notify my backup responder automatically",
    )

    review_due = models.DateField(default=default_review_due)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner"], condition=models.Q(is_active=True), name="one_active_plan_per_owner"
            )
        ]

    def __str__(self):
        return self.title


class ResponderAssignment(models.Model):
    plan = models.ForeignKey(SafetyPlan, on_delete=models.CASCADE, related_name="responders")
    contact = models.ForeignKey("safety_circle.TrustedContact", on_delete=models.CASCADE, related_name="assignments")
    role = models.CharField(max_length=16, choices=ResponderRole.choices)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "contact"], name="unique_responder_per_plan"),
            models.UniqueConstraint(
                fields=["plan"], condition=models.Q(role="primary"), name="one_primary_per_plan"
            ),
        ]
        ordering = ["role", "position", "created_at"]


class SafetyPlanVersion(models.Model):
    plan = models.ForeignKey(SafetyPlan, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    change_note = models.CharField(max_length=200, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["plan", "version"], name="unique_plan_version")]
