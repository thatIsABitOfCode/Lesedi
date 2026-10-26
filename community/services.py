"""Rules for the community feed and Witness Mode. Views stay thin; every rule is enforced here, on the server."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from audit.services import record as audit_record

from . import screening
from .models import (PUBLIC_STATUSES, CommunityComment, CommunityReport, ContentFlag, ModerationAction,
                     ReportStatus, ReportUpdate, WitnessConcern)
from .permissions import is_moderator

DAILY_LIMITS = {"report": 5, "witness": 3, "comment": 20, "flag": 10}
REJECTION_LOCKOUT = 3          # rejected reports in 30 days before new reports are paused
DUPLICATE_WINDOW_DAYS = 14

S = ReportStatus
ALLOWED = {
    S.UNREVIEWED.value: {S.UNDER_REVIEW.value, S.REJECTED.value},
    S.UNDER_REVIEW.value: {S.PUBLISHED.value, S.REJECTED.value},
    S.PUBLISHED.value: {S.RESOLVED.value, S.REJECTED.value, S.UNDER_REVIEW.value},
    S.REJECTED.value: {S.UNDER_REVIEW.value},   # only to re-examine, for example after an appeal
    S.RESOLVED.value: set(),
}


class CommunityError(Exception):
    """A rule was not met. The message is written to be shown to the person."""


def _retention():
    return timedelta(days=getattr(settings, "COMMUNITY_RETENTION_DAYS", 90))


def _day_ago():
    return timezone.now() - timedelta(days=1)


def _need_moderator(user):
    if not is_moderator(user):
        raise CommunityError("Only moderators can do this.")


# --- visibility ------------------------------------------------------------------------------------------------

def public_reports():
    return CommunityReport.objects.filter(status__in=PUBLIC_STATUSES, published_at__isnull=False)


def can_view(user, report) -> bool:
    return report.is_public or report.author_id == user.pk or is_moderator(user)


def commenting_open(report) -> bool:
    return report.is_public and not report.is_sensitive


# --- reports ---------------------------------------------------------------------------------------------------

def submit_report(user, *, category, area, incident_date, description):
    if CommunityReport.objects.filter(author=user, created_at__gte=_day_ago()).count() >= DAILY_LIMITS["report"]:
        raise CommunityError("You have reached today's limit for reports. Please try again tomorrow.")
    recent_rejections = CommunityReport.objects.filter(
        author=user, status=S.REJECTED.value, decided_at__gte=timezone.now() - timedelta(days=30)).count()
    if recent_rejections >= REJECTION_LOCKOUT:
        raise CommunityError("New reports are paused on your account because several recent reports were "
                             "rejected. You can appeal a rejected report from its page.")
    with transaction.atomic():
        earlier = (CommunityReport.objects
                   .filter(category=category, area__iexact=area.strip(),
                           created_at__gte=timezone.now() - timedelta(days=DUPLICATE_WINDOW_DAYS))
                   .exclude(status=S.REJECTED.value).order_by("created_at").first())
        report = CommunityReport.objects.create(
            author=user, category=category, area=area.strip(), incident_date=incident_date,
            description=description.strip(), possible_duplicate_of=earlier)
        audit_record("community.report_submitted", actor=user, obj=report, metadata={"kind": category})
    return report


def transition(report, to, moderator, *, note="", public_summary=""):
    """Move a report to a new status. Valid moves only; publishing needs a screened public summary."""
    _need_moderator(moderator)
    with transaction.atomic():
        r = CommunityReport.objects.select_for_update().get(pk=report.pk)
        if r.author_id == moderator.pk:
            raise CommunityError("You cannot moderate your own report. Another moderator must review it.")
        if to not in ALLOWED.get(r.status, set()):
            raise CommunityError(f"A report that is {r.get_status_display().lower()} cannot be moved to "
                                 f"{S(to).label.lower()}.")
        now = timezone.now()
        if to == S.PUBLISHED.value:
            summary = public_summary.strip()
            if not summary:
                raise CommunityError("Write a public summary before publishing. Do not copy private details.")
            problems = screening.screen_text(summary)
            if problems:
                raise CommunityError(f"The public summary must not include {problems[0]}.")
            if r.is_sensitive and " ".join(summary.split()).lower() == " ".join(r.description.split()).lower():
                raise CommunityError("For this kind of report the public summary must be rewritten, not copied.")
            r.public_summary = summary
            r.published_at = r.published_at or now
        if to == S.REJECTED.value:
            if not note.strip():
                raise CommunityError("Give a short reason. The person who sent the report will see it.")
            r.decision_note = note.strip()
        if to == S.RESOLVED.value:
            r.resolved_at = now
        r.purge_after = now + _retention() if to in (S.REJECTED.value, S.RESOLVED.value) else None
        r.status, r.reviewed_by, r.decided_at = to, moderator, now
        r.save()
        ModerationAction.objects.create(moderator=moderator, report=r, action=f"status:{to}", note=note.strip())
        audit_record("community.report_status", actor=moderator, obj=r, metadata={"to_state": to})
    return r


def add_update(report, moderator, body, kind):
    _need_moderator(moderator)
    if not report.is_public:
        raise CommunityError("Updates can only be added to a report that is published.")
    body = body.strip()
    problems = screening.screen_text(body)
    if problems:
        raise CommunityError(f"The update must not include {problems[0]}.")
    with transaction.atomic():
        update = ReportUpdate.objects.create(report=report, kind=kind, body=body, created_by=moderator)
        ModerationAction.objects.create(moderator=moderator, report=report, action=kind)
        audit_record("community.report_update", actor=moderator, obj=report, metadata={"kind": kind})
    return update


def appeal(report, user, text):
    if report.author_id != user.pk:
        raise CommunityError("Only the person who sent a report can appeal it.")
    if report.status != S.REJECTED.value:
        raise CommunityError("Only a rejected report can be appealed.")
    if report.appealed_at is not None:
        raise CommunityError("This report has already been appealed. A moderator will look at it.")
    if not text.strip():
        raise CommunityError("Please say why you think the decision should be looked at again.")
    report.appeal_text, report.appealed_at = text.strip(), timezone.now()
    report.save(update_fields=["appeal_text", "appealed_at"])
    audit_record("community.report_appealed", actor=user, obj=report)
    return report


# --- comments and flags ----------------------------------------------------------------------------------------

def add_comment(user, report, body):
    if not commenting_open(report):
        raise CommunityError("Comments are not open on this report.")
    if CommunityComment.objects.filter(author=user, created_at__gte=_day_ago()).count() >= DAILY_LIMITS["comment"]:
        raise CommunityError("You have reached today's limit for comments.")
    problems = screening.screen_text(body)
    if problems:
        raise CommunityError(f"Please remove {problems[0]} from your comment.")
    comment = CommunityComment.objects.create(report=report, author=user, body=body.strip())
    audit_record("community.comment_added", actor=user, obj=comment)
    return comment


def flag(user, reason, *, report=None, comment=None):
    """Ask moderators to look at something. Returns False if this person already flagged it."""
    if (report is None) == (comment is None):
        raise CommunityError("Choose one thing to flag.")
    target_report = report or comment.report
    if not target_report.is_public or (comment is not None and comment.is_hidden):
        raise CommunityError("That cannot be flagged.")
    if ContentFlag.objects.filter(flagged_by=user, created_at__gte=_day_ago()).count() >= DAILY_LIMITS["flag"]:
        raise CommunityError("You have reached today's limit for flags.")
    _, created = ContentFlag.objects.get_or_create(flagged_by=user, report=report, comment=comment,
                                                   defaults={"reason": reason})
    if created:
        audit_record("community.flagged", actor=user, metadata={"kind": "comment" if comment else "report"})
    return created


def hide_comment(comment, moderator, note=""):
    _need_moderator(moderator)
    with transaction.atomic():
        comment.is_hidden = True
        comment.save(update_fields=["is_hidden"])
        comment.flags.filter(resolved_at__isnull=True).update(resolved_at=timezone.now())
        ModerationAction.objects.create(moderator=moderator, report=comment.report, action="hide_comment",
                                        note=note.strip())
        audit_record("community.comment_hidden", actor=moderator, obj=comment)


def dismiss_flags(report, moderator):
    _need_moderator(moderator)
    now = timezone.now()
    with transaction.atomic():
        ContentFlag.objects.filter(Q(report=report) | Q(comment__report=report), resolved_at__isnull=True).update(
            resolved_at=now)
        ModerationAction.objects.create(moderator=moderator, report=report, action="dismiss_flags")


def moderation_queue():
    """Reports a moderator needs to act on, oldest first, and published reports with open flags."""
    open_flags = Count("flags", filter=Q(flags__resolved_at__isnull=True), distinct=True)
    needs_action = (CommunityReport.objects
                    .filter(Q(status__in=[S.UNREVIEWED.value, S.UNDER_REVIEW.value])
                            | Q(status=S.REJECTED.value, appealed_at__isnull=False))
                    .annotate(open_flags=open_flags).order_by("created_at"))
    flagged = (CommunityReport.objects.filter(status__in=PUBLIC_STATUSES)
               .annotate(open_flags=open_flags,
                         open_comment_flags=Count("comments__flags", filter=Q(comments__flags__resolved_at__isnull=True),
                                                  distinct=True))
               .filter(Q(open_flags__gt=0) | Q(open_comment_flags__gt=0)).order_by("created_at"))
    return needs_action, flagged


# --- Witness Mode ----------------------------------------------------------------------------------------------

def submit_witness(user, *, about, area, what_seen, seems_urgent):
    if WitnessConcern.objects.filter(author=user, created_at__gte=_day_ago()).count() >= DAILY_LIMITS["witness"]:
        raise CommunityError("You have reached today's limit for concerns. Please try again tomorrow.")
    concern = WitnessConcern.objects.create(author=user, about=about, area=area.strip(),
                                            what_seen=what_seen.strip(), seems_urgent=seems_urgent)
    audit_record("community.witness_submitted", actor=user, obj=concern, metadata={"kind": about})
    return concern


def review_witness(concern, moderator, status, note=""):
    _need_moderator(moderator)
    if status not in (WitnessConcern.Status.REVIEWED.value, WitnessConcern.Status.CLOSED.value):
        raise CommunityError("Choose reviewed or closed.")
    if concern.author_id == moderator.pk:
        raise CommunityError("You cannot review your own concern. Another moderator must do it.")
    now = timezone.now()
    concern.status, concern.moderator_note = status, note.strip()
    concern.reviewed_by, concern.reviewed_at = moderator, now
    concern.purge_after = now + _retention() if status == WitnessConcern.Status.CLOSED.value else None
    concern.save()
    audit_record("community.witness_reviewed", actor=moderator, obj=concern, metadata={"status": status})
    return concern


# --- retention ---------------------------------------------------------------------------------------------------

def purge_expired(now=None):
    """Delete rejected/resolved reports and closed concerns whose retention period has passed."""
    now = now or timezone.now()
    reports, _ = CommunityReport.objects.filter(purge_after__lte=now).delete()
    concerns, _ = WitnessConcern.objects.filter(purge_after__lte=now).delete()
    return {"reports_and_related": reports, "concerns": concerns}
