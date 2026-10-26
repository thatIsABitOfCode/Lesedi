import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Incident(models.Model):
    """A private incident record. Never shared as a whole; only individual items
    can be shared, and only with a contact the owner chooses."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="incidents")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    occurred_at = models.DateTimeField(help_text="When it happened, as best you remember.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["owner", "occurred_at"])]

    def __str__(self):
        return self.title


class TimelineEntry(models.Model):
    """A dated note. `occurred_at` is what the user says; `created_at` is when
    LESEDI's server recorded it. The two are kept apart on purpose."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="entries")
    occurred_at = models.DateTimeField()
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "created_at"]


class EvidenceItem(models.Model):
    """An uploaded file. The bytes live encrypted in private storage (see
    apps.evidence.storage); this row holds only metadata."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="items")
    entry = models.ForeignKey(
        TimelineEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="items"
    )
    # Sanitised label shown to people. Never used as a path.
    display_name = models.CharField(max_length=120)
    # Random server-generated key. Never derived from user input.
    storage_key = models.CharField(max_length=64, blank=True)
    # Decided by the server from the extension + file signature, not by the browser.
    content_type = models.CharField(max_length=60)
    size_bytes = models.PositiveBigIntegerField()
    # SHA-256 of the original bytes at upload time. See docs/LIMITATIONS.md for
    # what a hash does and does not prove.
    sha256 = models.CharField(max_length=64)
    # No malware scanner is integrated in this build; this says so honestly.
    scan_status = models.CharField(max_length=20, default="not_scanned")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["uploaded_at"]

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class EvidenceShare(models.Model):
    """The owner chose to let one linked trusted contact see one item."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(EvidenceItem, on_delete=models.CASCADE, related_name="shares")
    shared_with = models.ForeignKey(
        "safety_circle.TrustedContact", on_delete=models.CASCADE, related_name="evidence_shares"
    )
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "shared_with"],
                condition=models.Q(revoked_at__isnull=True),
                name="one_active_share_per_item_contact",
            )
        ]

    @property
    def is_active(self):
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


class EvidenceAccessEvent(models.Model):
    """Who touched which item, and how. Holds no file contents or names."""

    class Action(models.TextChoices):
        DOWNLOAD = "download", "Downloaded"
        EXPORT = "export", "Included in an evidence pack"
        SHARED_DOWNLOAD = "shared_download", "Downloaded by a contact it was shared with"
        SHARE = "share", "Shared"
        REVOKE = "revoke", "Share revoked"
        DELETE = "delete", "Deleted"

    item = models.ForeignKey(EvidenceItem, null=True, on_delete=models.SET_NULL, related_name="access_events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=20, choices=Action.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
