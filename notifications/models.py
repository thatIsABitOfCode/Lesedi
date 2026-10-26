import uuid

from django.db import models

from .channels import Channel


class DeliveryStatus(models.TextChoices):
    """Each status means exactly what it says and no more.

    QUEUED     - LESEDI has created the delivery attempt. Nothing has left LESEDI.
    SUBMITTED  - A provider (or the simulator) accepted it. NOT proof the person received it.
    DELIVERED  - The provider confirmed delivery to the device/mailbox. NOT proof the person saw it.
    FAILED     - This attempt failed; see `error`.
    Acknowledgement is a separate record (guardian.ResponderAcknowledgement), made by the person."""

    QUEUED = "queued", "Queued"
    SUBMITTED = "submitted", "Submitted to provider"
    DELIVERED = "delivered", "Delivered (provider-confirmed)"
    FAILED = "failed", "Failed"


class NotificationDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activation = models.ForeignKey("guardian.GuardianActivation", null=True, blank=True, on_delete=models.CASCADE, related_name="deliveries")
    contact = models.ForeignKey("safety.TrustedContact", on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    kind = models.CharField(max_length=32, default="guardian_alert")
    attempt = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.QUEUED)
    is_simulated = models.BooleanField(default=True)
    provider = models.CharField(max_length=32, default="simulation")
    provider_message_id = models.CharField(max_length=80, blank=True)
    error = models.CharField(max_length=200, blank=True)
    # Stored ONLY for simulated deliveries so the demo can show what would have been sent.
    body_preview = models.TextField(blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["queued_at"]
        indexes = [models.Index(fields=["activation", "contact"])]
