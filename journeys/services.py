"""Journey safety rules. Views, tasks and tests all go through these functions.

What this module promises, and what it does not:
- Location is shared only with people the owner picked for THIS journey, only after the owner presses Start, and only
  until share_until. Ending, expiring or revoking erases the stored fix.
- Only the latest fix is stored. There is no location history.
- A recipient is told whether a location is current or last-known. A stale fix is never presented as current.
- Notices are neutral and, in this build, simulated. Nothing here contacts emergency services, and nothing here
  knows whether anyone is on the way."""
import math
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from audit.services import record
from notifications import services as notify
from safety.models import ContactStatus

from .models import Journey, JourneyEvent, JourneyRecipient, JourneyStatus

VIEW_SALT = "lesedi.journey.view"
ASSISTANCE_RESEND_SECONDS = 300

LIMITS_NOTICE = (
    "LESEDI cannot guarantee location updates. Your browser or phone may pause them when the screen is off, "
    "the signal drops, or permission is withdrawn. A location marked 'last known' is not where you are now. "
    "LESEDI does not contact emergency services and cannot tell whether anyone is on the way."
)


class JourneyError(ValueError):
    """A user-correctable problem with a requested change."""


class InvalidLink(Exception):
    """The viewing link is bad, expired, or no longer allowed. Deliberately gives no further detail."""


# ---- helpers ---------------------------------------------------------------------------------------------------

def _now(now):
    return now or timezone.now()


def _event(journey, kind, detail=""):
    JourneyEvent.objects.create(journey=journey, kind=kind, detail=detail[:200])


def _locked(journey_id):
    return Journey.objects.select_for_update().get(pk=journey_id)


def is_sharing(journey, now=None) -> bool:
    now = _now(now)
    return journey.status == JourneyStatus.ACTIVE and journey.share_until is not None and journey.share_until > now


def active_recipients(journey):
    """Recipients not revoked for this journey AND still accepted in the owner's circle."""
    return list(
        journey.recipients.filter(revoked_at__isnull=True, contact__status=ContactStatus.ACTIVE).select_related("contact")
    )


def make_view_token(journey, recipient) -> str:
    return signing.dumps({"j": str(journey.id), "r": str(recipient.id)}, salt=VIEW_SALT)


def view_path(token) -> str:
    return reverse("journeys:view", args=[token])


def _max_link_age() -> int:
    return settings.JOURNEY_MAX_MINUTES * 60 + 3600


def _notify(journey, kind, now):
    """Send a neutral notice to each active recipient and record the REAL status each one got."""
    results = []
    for rec in active_recipients(journey):
        link = settings.LESEDI_PUBLIC_BASE_URL + view_path(make_view_token(journey, rec))
        delivery = notify.send(
            activation=None, contact=rec.contact, channel=rec.contact.preferred_channel, link=link, kind=kind)
        tag = " (simulated)" if delivery.is_simulated else ""
        _event(journey, "notice", f"{kind}: {rec.contact.name}: {delivery.get_status_display()}{tag}")
        results.append(delivery)
    return results


# ---- creating and starting -------------------------------------------------------------------------------------

@transaction.atomic
def create_journey(owner, *, destination_label, duration_minutes, contacts, checkin_minutes=None) -> Journey:
    label = (destination_label or "").strip()
    if not label:
        raise JourneyError("Please give the journey a short private label.")
    if len(label) > 120:
        raise JourneyError("The label is too long.")
    if not (settings.JOURNEY_MIN_MINUTES <= int(duration_minutes) <= settings.JOURNEY_MAX_MINUTES):
        raise JourneyError(
            f"Sharing can last between {settings.JOURNEY_MIN_MINUTES} minutes and {settings.JOURNEY_MAX_MINUTES // 60} hours.")
    if checkin_minutes is not None and not (1 <= int(checkin_minutes) < int(duration_minutes)):
        raise JourneyError("The check-in time must be before sharing ends.")
    unique = {c.pk: c for c in contacts}
    if not unique:
        raise JourneyError("Choose at least one person to share with.")
    for c in unique.values():
        if c.owner_id != owner.pk:
            raise JourneyError("That person is not in your circle.")
        if c.status != ContactStatus.ACTIVE:
            raise JourneyError(f"{c.name} has not accepted your invitation yet, so they cannot be chosen.")

    journey = Journey.objects.create(
        owner=owner, destination_label=label, duration_minutes=int(duration_minutes),
        checkin_minutes=int(checkin_minutes) if checkin_minutes is not None else None)
    for c in unique.values():
        JourneyRecipient.objects.create(journey=journey, contact=c)
    _event(journey, "created", "Planned. Nothing is shared until you press Start.")
    record("journey.created", actor=owner, obj=journey, metadata={"count": len(unique)})
    return journey


def start(journey, *, now=None) -> Journey:
    """The explicit consent step. Sharing begins here and not before."""
    now = _now(now)
    with transaction.atomic():
        j = _locked(journey.pk)
        if j.status != JourneyStatus.PLANNED:
            raise JourneyError("This journey has already started or ended.")
        if not active_recipients(j):
            raise JourneyError("Nobody can receive this journey. Choose someone who has accepted your invitation.")
        j.status = JourneyStatus.ACTIVE
        j.started_at = now
        j.share_until = now + timedelta(minutes=j.duration_minutes)
        if j.checkin_minutes:
            j.checkin_due_at = now + timedelta(minutes=j.checkin_minutes)
        j.save()
        _event(j, "started", f"Sharing until {timezone.localtime(j.share_until):%H:%M}.")
        record("journey.started", actor=j.owner, obj=j, metadata={"count": len(active_recipients(j))})
    _notify(j, "journey_started", now)
    return j


# ---- during the journey ----------------------------------------------------------------------------------------

def update_location(journey, *, lat, lng, accuracy=None, now=None) -> Journey:
    now = _now(now)
    try:
        lat, lng = float(lat), float(lng)
        accuracy = None if accuracy is None else float(accuracy)
    except (TypeError, ValueError):
        raise JourneyError("That location could not be read.")
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise JourneyError("That location is not valid.")
    if accuracy is not None and not (math.isfinite(accuracy) and 0 <= accuracy <= 100000):
        raise JourneyError("That location accuracy is not valid.")
    with transaction.atomic():
        j = _locked(journey.pk)
        if j.status == JourneyStatus.ACTIVE and j.share_until and j.share_until <= now:
            _end(j, "expired", now)
        if not is_sharing(j, now):
            raise JourneyError("Location is not being shared right now.")
        j.last_lat, j.last_lng, j.last_accuracy_m, j.last_fix_at = lat, lng, accuracy, now
        j.save(update_fields=["last_lat", "last_lng", "last_accuracy_m", "last_fix_at"])
    return j


def confirm_checkin(journey, *, now=None) -> Journey:
    now = _now(now)
    with transaction.atomic():
        j = _locked(journey.pk)
        if not is_sharing(j, now):
            raise JourneyError("This journey is not being shared.")
        j.checkin_confirmed_at = now
        j.save(update_fields=["checkin_confirmed_at"])
        _event(j, "checkin_confirmed", "You confirmed you are OK.")
    return j


def confirm_arrival(journey, *, now=None) -> Journey:
    now = _now(now)
    with transaction.atomic():
        j = _locked(journey.pk)
        if j.status != JourneyStatus.ACTIVE:
            raise JourneyError("This journey is not being shared.")
        _end(j, "arrived", now)
    return j


def end_sharing(journey, *, now=None) -> Journey:
    """Owner stops sharing. Safe to call twice."""
    now = _now(now)
    with transaction.atomic():
        j = _locked(journey.pk)
        if j.status == JourneyStatus.ENDED:
            return j
        _end(j, "ended_by_owner", now)
    return j


def _end(j, reason, now):
    """Caller holds the row lock. Erases the stored location."""
    j.status = JourneyStatus.ENDED
    j.ended_at = now
    j.end_reason = reason
    j.last_lat = j.last_lng = j.last_accuracy_m = j.last_fix_at = None
    j.save()
    _event(j, "ended", {
        "arrived": "You confirmed you arrived. Sharing stopped and the stored location was erased.",
        "ended_by_owner": "You stopped sharing. The stored location was erased.",
        "expired": "The time you chose ran out. Sharing stopped and the stored location was erased.",
        "revoked": "Everyone was removed. Sharing stopped and the stored location was erased.",
    }.get(reason, "Sharing stopped."))
    record("journey.ended", actor=j.owner, obj=j, metadata={"status": reason})


def request_assistance(journey, *, now=None):
    """Ask the people chosen for this journey to check on the owner. Returns the delivery records."""
    now = _now(now)
    with transaction.atomic():
        j = _locked(journey.pk)
        if not is_sharing(j, now):
            raise JourneyError("Start sharing first, so your contacts know what this refers to.")
        if j.assistance_requested_at and (now - j.assistance_requested_at).total_seconds() < ASSISTANCE_RESEND_SECONDS:
            raise JourneyError("You asked a moment ago. Please wait a few minutes before asking again.")
        j.assistance_requested_at = now
        j.save(update_fields=["assistance_requested_at"])
        _event(j, "assistance_requested", "You asked your chosen contacts to check on you.")
        record("journey.assistance", actor=j.owner, obj=j)
    return _notify(j, "journey_assistance", now)


def revoke_recipient(journey, contact, *, now=None) -> Journey:
    now = _now(now)
    with transaction.atomic():
        j = _locked(journey.pk)
        rec = j.recipients.filter(contact=contact, revoked_at__isnull=True).first()
        if rec is None:
            raise JourneyError("That person is not receiving this journey.")
        rec.revoked_at = now
        rec.save(update_fields=["revoked_at"])
        _event(j, "recipient_revoked", f"{contact.name} can no longer see this journey.")
        record("journey.revoked", actor=j.owner, obj=j)
        if j.status == JourneyStatus.ACTIVE and not active_recipients(j):
            _end(j, "revoked", now)
    return j


# ---- scheduled work --------------------------------------------------------------------------------------------

def expire_due(now=None) -> dict:
    """Stop sharing that has run out and send one neutral notice for check-ins that were not confirmed."""
    now = _now(now)
    counts = {"expired": 0, "checkin_alerts": 0}
    for pk in list(Journey.objects.filter(status=JourneyStatus.ACTIVE, share_until__lte=now).values_list("pk", flat=True)):
        with transaction.atomic():
            j = _locked(pk)
            if j.status == JourneyStatus.ACTIVE and j.share_until and j.share_until <= now:
                _end(j, "expired", now)
                counts["expired"] += 1
    due = Journey.objects.filter(
        status=JourneyStatus.ACTIVE, checkin_due_at__lte=now,
        checkin_confirmed_at__isnull=True, checkin_alert_sent_at__isnull=True)
    for pk in list(due.values_list("pk", flat=True)):
        with transaction.atomic():
            j = _locked(pk)
            if j.status != JourneyStatus.ACTIVE or j.checkin_confirmed_at or j.checkin_alert_sent_at:
                continue
            j.checkin_alert_sent_at = now
            j.save(update_fields=["checkin_alert_sent_at"])
            _event(j, "checkin_missed", "The check-in time passed without your confirmation.")
        _notify(j, "journey_checkin_overdue", now)
        counts["checkin_alerts"] += 1
    return counts


# ---- what a recipient may see ----------------------------------------------------------------------------------

def resolve_view_token(token):
    try:
        data = signing.loads(token, salt=VIEW_SALT, max_age=_max_link_age())
        rec = JourneyRecipient.objects.select_related("journey__owner", "contact").get(pk=data["r"])
    except (signing.BadSignature, JourneyRecipient.DoesNotExist, KeyError, ValueError):
        raise InvalidLink
    if str(rec.journey_id) != data.get("j") or rec.revoked_at or rec.contact.status != ContactStatus.ACTIVE:
        raise InvalidLink
    return rec.journey, rec


def viewer_snapshot(journey, now=None) -> dict:
    """The ONLY data a recipient receives. No destination label, no history, no plan, no contacts."""
    now = _now(now)
    sharing = is_sharing(journey, now)
    location = None
    if sharing and journey.last_fix_at and journey.last_lat is not None and journey.last_lng is not None:
        age = max(0, int((now - journey.last_fix_at).total_seconds()))
        location = {
            "lat": journey.last_lat, "lng": journey.last_lng, "accuracy_m": journey.last_accuracy_m,
            "fix_at": journey.last_fix_at, "age_seconds": age, "is_stale": age > settings.JOURNEY_STALE_SECONDS,
        }
    return {
        "owner_name": journey.owner.display_name,
        "sharing": sharing,
        "ended": journey.status == JourneyStatus.ENDED,
        "share_until": journey.share_until if sharing else None,
        "location": location,
        "assistance_requested": sharing and bool(journey.assistance_requested_at),
        "checkin_overdue": sharing and bool(journey.checkin_alert_sent_at and not journey.checkin_confirmed_at),
    }
