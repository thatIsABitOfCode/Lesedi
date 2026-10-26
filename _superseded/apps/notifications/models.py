import uuid

from django.db import models

from .channels import Channel


class DeliveryStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SUBMITTED = "submitted", "Submitted to provider"
    DELIVERED = "delivered", "Delivered"
    RETRYING = "retrying", "Retrying"
    FAILED = "failed", "Failed"


TERMINAL_STATUSES = (DeliveryStatus.SUBMITTED, DeliveryStatus.DELIVERED, DeliveryStatus.FAILED)
LIVE_STATUSES = (
    DeliveryStatus.QUEUED,
    DeliveryStatus.RETRYING,
    DeliveryStatus.SUBMITTED,
    DeliveryStatus.DELIVERED,
)

STATUS_EXPLANATIONS = {
    "queued": "Waiting to be sent. Nothing has been sent yet.",
    "submitted": "Handed to the sending service. This does not confirm it arrived or was seen.",
    "delivered": "The sending service reported delivery. This does not confirm it was seen.",
    "retrying": "A send attempt failed; LESEDI will try again a limited number of times.",
    "failed": "Could not be sent.",
}


class NotificationDelivery(models.Model):
    """One delivery attempt chain for one contact on one channel.

    Status values are kept strictly separate from responder acknowledgement
    (apps.guardian.ResponderAcknowledgement): queued != submitted != delivered
    != seen != acknowledged != help arrived.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.ForeignKey("guardian.EmergencyAction", on_delete=models.CASCADE, related_name="deliveries")
    contact = models.ForeignKey("safety_circle.TrustedContact", on_delete=models.RESTRICT, related_name="deliveries")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.QUEUED)
    simulated = models.BooleanField(default=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    # Short machine code only (never provider response bodies or message text).
    last_error = models.CharField(max_length=64, blank=True)
    provider_ref = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=100, unique=True)

    queued_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["queued_at"]
        indexes = [models.Index(fields=["status", "queued_at"])]

    @property
    def explanation(self):
        return STATUS_EXPLANATIONS[self.status]

    def __str__(self):
        return f"{self.channel}:{self.status}"
