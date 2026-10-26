import uuid

from django.conf import settings
from django.db import models


class State(models.TextChoices):
    ACTIVATED = "activated", "Activated"
    ALERTS_PENDING = "alerts_pending", "Alerts being sent"
    AWAITING_ACKNOWLEDGEMENT = "awaiting_acknowledgement", "Waiting for someone to acknowledge"
    ESCALATION_REQUIRED = "escalation_required", "Escalation needed"
    BACKUP_CONTACTED = "backup_contacted", "Backup responder contacted"
    ACKNOWLEDGED = "acknowledged", "A responder acknowledged"
    RESOLVED = "resolved", "Resolved"
    CANCELLED = "cancelled", "Cancelled"


OPEN_STATES = [
    State.ACTIVATED.value,
    State.ALERTS_PENDING.value,
    State.AWAITING_ACKNOWLEDGEMENT.value,
    State.ESCALATION_REQUIRED.value,
    State.BACKUP_CONTACTED.value,
    State.ACKNOWLEDGED.value,
]
CLOSED_STATES = [State.RESOLVED.value, State.CANCELLED.value]


class GuardianActivation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activations")
    # RESTRICT (not PROTECT): the plan may be deleted together with its owner's
    # account, but never on its own while activations reference it.
    plan = models.ForeignKey("safety_plans.SafetyPlan", on_delete=models.RESTRICT, related_name="activations")
    plan_version = models.PositiveIntegerField()
    state = models.CharField(max_length=32, choices=State.choices, default=State.ACTIVATED)
    idempotency_key = models.CharField(max_length=64)
    simulated = models.BooleanField(default=True)

    # Snapshots of what the survivor authorised at the moment of activation.
    ack_timeout_seconds = models.PositiveIntegerField()
    auto_escalate_authorised = models.BooleanField(default=False)

    ack_deadline = models.DateTimeField(null=True, blank=True)
    backup_contacted_at = models.DateTimeField(null=True, blank=True)
    outcome_note = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Retried or concurrent requests with the same key can never create two activations.
            models.UniqueConstraint(fields=["owner", "idempotency_key"], name="unique_activation_key_per_owner"),
            # At most one open activation per person, enforced by the database itself.
            models.UniqueConstraint(
                fields=["owner"],
                condition=models.Q(state__in=OPEN_STATES),
                name="one_open_activation_per_owner",
            ),
        ]
        indexes = [models.Index(fields=["state", "ack_deadline"])]

    @property
    def is_open(self):
        return self.state in OPEN_STATES

    def __str__(self):
        return f"Activation {self.pk} ({self.state})"


class ActionType(models.TextChoices):
    NOTIFY_PRIMARY = "notify_primary", "Notify primary responder"
    NOTIFY_BACKUP = "notify_backup", "Notify backup responder"


class EmergencyAction(models.Model):
    """An action the survivor authorised in advance and LESEDI carried out."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activation = models.ForeignKey(GuardianActivation, on_delete=models.CASCADE, related_name="actions")
    action_type = models.CharField(max_length=24, choices=ActionType.choices)
    contact = models.ForeignKey("safety_circle.TrustedContact", on_delete=models.RESTRICT, related_name="actions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["activation", "action_type", "contact"], name="unique_action_per_contact"
            )
        ]


class ResponderAcknowledgement(models.Model):
    """A trusted contact saying "I have seen this alert". It does NOT mean that
    anyone is travelling, has arrived, or has been able to help."""

    activation = models.ForeignKey(GuardianActivation, on_delete=models.CASCADE, related_name="acknowledgements")
    contact = models.ForeignKey("safety_circle.TrustedContact", on_delete=models.RESTRICT, related_name="acknowledgements")
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["activation", "contact"], name="one_ack_per_contact")
        ]


class GuardianEvent(models.Model):
    """The visible timeline. Each line states what actually happened, no more."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activation = models.ForeignKey(GuardianActivation, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=40)
    message = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
