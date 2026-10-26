import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from .states import OPEN_STATES, State


class GuardianActivation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activations")
    plan = models.ForeignKey("safety.SafetyPlan", on_delete=models.RESTRICT, related_name="activations")
    plan_version = models.PositiveIntegerField()
    state = models.CharField(max_length=32, choices=State.choices, default=State.ACTIVATED)
    idempotency_key = models.CharField(max_length=64, blank=True)
    is_simulation = models.BooleanField(default=True)
    simulate_primary_failure = models.BooleanField(default=False)
    ack_timeout_seconds = models.PositiveIntegerField()
    ack_deadline = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    # Optional device location supplied at SOS activation; private to this activation.
    location_latitude = models.FloatField(null=True, blank=True)
    location_longitude = models.FloatField(null=True, blank=True)
    location_accuracy_m = models.FloatField(null=True, blank=True)
    location_captured_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-activated_at"]
        constraints = [
            # Database-level guarantee: at most ONE open activation per person, even under concurrent requests.
            models.UniqueConstraint(
                fields=["owner"], condition=Q(state__in=[s.value for s in OPEN_STATES]),
                name="one_open_activation_per_owner"),
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"], condition=~Q(idempotency_key=""),
                name="unique_activation_idempotency_key"),
        ]
        indexes = [models.Index(fields=["state", "ack_deadline"])]


class ActionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DONE = "done", "Notification submitted"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class EmergencyAction(models.Model):
    """One planned step: notify the responder at `rank`. Re-checked against permissions when executed."""

    activation = models.ForeignKey(GuardianActivation, on_delete=models.CASCADE, related_name="actions")
    contact = models.ForeignKey("safety.TrustedContact", on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=ActionStatus.choices, default=ActionStatus.PENDING)
    detail = models.CharField(max_length=200, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rank"]
        constraints = [models.UniqueConstraint(fields=["activation", "rank"], name="unique_action_rank")]


class ResponderAcknowledgement(models.Model):
    """The responder saying "I saw this". Separate from delivery, and NOT proof of physical help."""

    activation = models.ForeignKey(GuardianActivation, on_delete=models.CASCADE, related_name="acknowledgements")
    contact = models.ForeignKey("safety.TrustedContact", on_delete=models.CASCADE, related_name="+")
    acknowledged_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["activation", "contact"], name="one_ack_per_contact")]


class GuardianEvent(models.Model):
    """User-visible timeline. Messages state only what actually happened."""

    activation = models.ForeignKey(GuardianActivation, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=40)
    message = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
