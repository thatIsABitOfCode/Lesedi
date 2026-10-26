import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Incident(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="incidents")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class EvidenceKind(models.TextChoices):
    NOTE = "note", "Note"
    FILE = "file", "File"


class EvidenceItem(models.Model):
    """A note or an uploaded file. File bytes live ENCRYPTED in private storage, never in a public directory.

    sha256 is of the original bytes (or note text) at upload. It can show later changes to the stored copy;
    it does not prove the content is authentic, that timestamps are accurate, or that a court will accept it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="items")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="evidence_items")
    kind = models.CharField(max_length=8, choices=EvidenceKind.choices)
    title = models.CharField(max_length=120, blank=True)
    note_text = models.TextField(blank=True)
    original_filename = models.CharField(max_length=120, blank=True)
    content_type = models.CharField(max_length=64, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=64, blank=True)
    event_time = models.DateTimeField(default=timezone.now, help_text="When it happened (as you entered it)")
    uploaded_at = models.DateTimeField(auto_now_add=True, help_text="When LESEDI stored it (server clock)")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")

    class Meta:
        ordering = ["event_time", "uploaded_at"]
        indexes = [models.Index(fields=["incident", "event_time"])]


class EvidenceAccessEvent(models.Model):
    """Who touched which item and how. Contains no file contents."""

    item = models.ForeignKey(EvidenceItem, null=True, on_delete=models.SET_NULL, related_name="access_events")
    item_label = models.CharField(max_length=140, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=24)  # upload | note | download | export | share_create | share_revoke | share_download | delete
    via = models.CharField(max_length=16, default="owner")  # owner | share
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class EvidenceShare(models.Model):
    """A revocable, expiring link to ONE item. Only a hash of the token is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(EvidenceItem, on_delete=models.CASCADE, related_name="shares")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    recipient_label = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveIntegerField(default=0)
    last_accessed_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()
