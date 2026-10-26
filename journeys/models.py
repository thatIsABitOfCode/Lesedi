import uuid

from django.conf import settings
from django.db import models


class JourneyStatus(models.TextChoices):
    PLANNED = "planned", "Planned, not shared yet"
    ACTIVE = "active", "Sharing now"
    ENDED = "ended", "Ended"


class Journey(models.Model):
    """A trip the owner chose to share, with people the owner chose, for a time the owner chose.

    Privacy design:
    - The destination label is private to the owner. Recipients are never shown it.
    - Only the LATEST location fix is kept. There is no location history table. When sharing ends, expires or is
      revoked, even that latest fix is erased.
    - Recipients only ever see a location while status is ACTIVE and share_until is in the future."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="journeys")
    destination_label = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=JourneyStatus.choices, default=JourneyStatus.PLANNED)
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    checkin_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    share_until = models.DateTimeField(null=True, blank=True)
    checkin_due_at = models.DateTimeField(null=True, blank=True)
    checkin_confirmed_at = models.DateTimeField(null=True, blank=True)
    checkin_alert_sent_at = models.DateTimeField(null=True, blank=True)
    assistance_requested_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=24, blank=True)
    last_lat = models.FloatField(null=True, blank=True)
    last_lng = models.FloatField(null=True, blank=True)
    last_accuracy_m = models.FloatField(null=True, blank=True)
    last_fix_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "share_until"], name="journey_status_until_idx")]

    def __str__(self):
        return f"Journey {self.id}"


class JourneyRecipient(models.Model):
    """One person the owner chose to share THIS journey with. Choosing them for this journey is the consent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name="recipients")
    contact = models.ForeignKey("safety.TrustedContact", on_delete=models.CASCADE, related_name="journey_shares")
    added_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["added_at"]
        constraints = [models.UniqueConstraint(fields=["journey", "contact"], name="unique_journey_recipient")]


class JourneyEvent(models.Model):
    """What happened, in order. Never stores coordinates."""

    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32)
    detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
