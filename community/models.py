"""Community safety feed, comments, flags, moderation records and Witness Mode concerns.

Design rules (see docs/LIMITATIONS.md):
* Nothing here links to a private incident, safety plan, contact, location or Guardian activation.
* The public never sees what a reporter wrote. They see `public_summary`, written or approved by a moderator.
* There is no "confirmed" status. LESEDI has no verification process, so it never labels an allegation as confirmed.
* Witness concerns are private to moderators and the person who sent them. Nobody is notified about the person
  the concern is about.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Category(models.TextChoices):
    UNSAFE_AREA = "unsafe_area", "Unsafe area or place"
    SUSPECTED_ABUSE = "suspected_abuse", "Concern about possible abuse"
    HARASSMENT = "harassment", "Harassment or stalking"
    CHILD_CONCERN = "child_concern", "Concern for a child"
    OLDER_PERSON_CONCERN = "older_person_concern", "Concern for an older person"
    OTHER = "other", "Something else"


# Reports in these categories can describe a specific person. Their raw text is never shown publicly and
# comments are closed on them.
SENSITIVE_CATEGORIES = {
    Category.SUSPECTED_ABUSE.value,
    Category.HARASSMENT.value,
    Category.CHILD_CONCERN.value,
    Category.OLDER_PERSON_CONCERN.value,
}


class ReportStatus(models.TextChoices):
    UNREVIEWED = "unreviewed", "Unreviewed"
    UNDER_REVIEW = "under_review", "Under review"
    PUBLISHED = "published", "Published after moderator review (not verified)"
    RESOLVED = "resolved", "Resolved"
    REJECTED = "rejected", "Rejected"


PUBLIC_STATUSES = (ReportStatus.PUBLISHED.value, ReportStatus.RESOLVED.value)


class CommunityReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="community_reports")
    category = models.CharField(max_length=32, choices=Category.choices)
    area = models.CharField(max_length=120, help_text="Suburb, town or ward only.")
    incident_date = models.DateField()
    description = models.TextField(max_length=2000)  # private: reporter and moderators only
    public_summary = models.TextField(blank=True)  # the only text shown to other users
    status = models.CharField(max_length=16, choices=ReportStatus.choices, default=ReportStatus.UNREVIEWED,
                              db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)  # shown to the reporter when a report is rejected
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    possible_duplicate_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                              related_name="possible_duplicates")
    appeal_text = models.TextField(blank=True)
    appealed_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "published_at"])]

    def __str__(self):
        return f"{self.get_category_display()} in {self.area} ({self.status})"

    @property
    def is_sensitive(self):
        return self.category in SENSITIVE_CATEGORIES

    @property
    def is_public(self):
        return self.status in PUBLIC_STATUSES and self.published_at is not None


class ReportUpdate(models.Model):
    """A moderator's public update or correction on a published report."""

    class Kind(models.TextChoices):
        UPDATE = "update", "Update"
        CORRECTION = "correction", "Correction"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(CommunityReport, on_delete=models.CASCADE, related_name="updates")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.UPDATE)
    body = models.TextField(max_length=1000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class CommunityComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(CommunityReport, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="community_comments")
    body = models.TextField(max_length=500)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class ContentFlag(models.Model):
    """A user's request for moderator attention on a report or a comment. Flags never remove content by themselves."""

    class Reason(models.TextChoices):
        PRIVACY = "privacy", "Shows personal details"
        HARASSMENT = "harassment", "Harassing, threatening or abusive"
        FALSE = "false", "Looks false or misleading"
        OTHER = "other", "Something else"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    flagged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    report = models.ForeignKey(CommunityReport, null=True, blank=True, on_delete=models.CASCADE, related_name="flags")
    comment = models.ForeignKey(CommunityComment, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="flags")
    reason = models.CharField(max_length=16, choices=Reason.choices)
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(report__isnull=False, comment__isnull=True) | Q(report__isnull=True, comment__isnull=False)),
                name="community_flag_exactly_one_target"),
            models.UniqueConstraint(fields=["flagged_by", "report"], condition=Q(report__isnull=False),
                                    name="community_flag_once_per_report"),
            models.UniqueConstraint(fields=["flagged_by", "comment"], condition=Q(comment__isnull=False),
                                    name="community_flag_once_per_comment"),
        ]


class ModerationAction(models.Model):
    """Record of what a moderator did. Notes are internal; never put personal details in them."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    moderator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="+")
    report = models.ForeignKey(CommunityReport, on_delete=models.CASCADE, related_name="moderation_actions")
    action = models.CharField(max_length=32)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class WitnessConcern(models.Model):
    """A private concern about someone else. It is never public, links to no account, location or evidence of the
    person it is about, and triggers no message to anyone."""

    class About(models.TextChoices):
        ADULT = "adult", "An adult"
        CHILD = "child", "A child"
        OLDER_PERSON = "older_person", "An older person"
        UNSURE = "unsure", "Not sure"

    class Status(models.TextChoices):
        NEW = "new", "Received"
        REVIEWED = "reviewed", "Reviewed by a moderator"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="witness_concerns")
    about = models.CharField(max_length=16, choices=About.choices)
    area = models.CharField(max_length=120, blank=True)
    what_seen = models.TextField(max_length=2000)
    seems_urgent = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    moderator_note = models.TextField(blank=True)  # shown to the person who sent the concern
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    purge_after = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
