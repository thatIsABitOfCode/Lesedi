"""Guardian Mode orchestration.

Honest-status rules enforced here:
  * a notification being queued/submitted is NOT delivery, and delivery is NOT the person seeing it;
  * an acknowledgement means "I saw this", NOT "help is on the way";
  * LESEDI never contacts emergency services or police - there is no such integration.

Concurrency: a partial unique index allows one open activation per owner; every state change happens
inside a transaction holding a row lock on the activation."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from audit.services import record
from notifications import services as notify
from notifications.channels import Channel
from notifications.models import DeliveryStatus
from safety.models import ContactStatus, Permission, ResponderAssignment, SafetyPlan, TrustedContact
from safety.services import has_permission

from .models import ActionStatus, EmergencyAction, GuardianActivation, GuardianEvent, ResponderAcknowledgement
from .states import OPEN_STATES, TERMINAL_STATES, WAITING_STATES, State, can_transition

log = logging.getLogger(__name__)
ACK_SALT = "lesedi.guardian.ack"
SIM_NOTICE = ("SIMULATION: no real SMS, WhatsApp message or call was made, no emergency service was "
              "contacted, and nobody is on their way.")
LIMITS_NOTICE = ("LESEDI does not contact emergency services. An acknowledgement means someone saw the alert - "
                 "not that help is on the way. If you are in danger, contact your local emergency services directly.")
OPEN_VALUES = [s.value for s in OPEN_STATES]


class GuardianError(Exception):
    pass


class NoActivePlan(GuardianError):
    pass


class InvalidTransition(GuardianError):
    pass


class InvalidToken(GuardianError):
    pass


class NotPermitted(GuardianError):
    pass


# ---------------------------------------------------------------- helpers
def _event(a, kind, message, simulated=False):
    prefix = "[SIMULATION] " if (simulated and a.is_simulation) else ""
    return GuardianEvent.objects.create(activation=a, kind=kind, message=(prefix + message)[:300])


def _transition(a, new, now=None):
    if not can_transition(a.state, new):
        raise InvalidTransition(f"{a.state} -> {new}")
    old = a.state
    a.state = new
    if new in TERMINAL_STATES:
        a.closed_at = now or timezone.now()
    a.save()
    record("guardian.transition", actor=a.owner, obj=a, metadata={"from_state": old, "to_state": str(new)})


def _open_for(owner):
    return GuardianActivation.objects.filter(owner=owner, state__in=OPEN_VALUES).first()


def make_ack_token(activation, contact) -> str:
    return signing.dumps({"a": str(activation.id), "c": str(contact.id)}, salt=ACK_SALT)


def ack_path(token) -> str:
    return reverse("guardian:ack", args=[token])


def _hhmmss(dt):
    return timezone.localtime(dt).strftime("%H:%M:%S")


def _channel_label(value):
    return dict(Channel.choices).get(value, value)


# ---------------------------------------------------------------- activation
def activate(owner, *, idempotency_key="", simulate_primary_failure=False, now=None):
    """Start Guardian Mode. Returns (activation, created). Safe to call repeatedly or concurrently."""
    now = now or timezone.now()
    idempotency_key = (idempotency_key or "")[:64]

    if idempotency_key:
        same = GuardianActivation.objects.filter(owner=owner, idempotency_key=idempotency_key).first()
        if same:
            return same, False

    existing = _open_for(owner)
    if existing and existing.state == State.ESCALATION_EXHAUSTED:
        # Nobody acknowledged last time; let the person try again rather than blocking them.
        close(owner, existing.pk, outcome=State.CANCELLED, note="Replaced by a new activation.")
        existing = None
    if existing:
        return existing, False

    plan = SafetyPlan.objects.filter(owner=owner, is_active=True).first()
    if plan is None:
        raise NoActivePlan("Create a safety plan first so Guardian Mode knows what you have authorised.")

    simulation = settings.LESEDI_NOTIFICATION_MODE == "simulation"
    try:
        with transaction.atomic():
            a = GuardianActivation.objects.create(
                owner=owner, plan=plan, plan_version=plan.version, state=State.ACTIVATED,
                idempotency_key=idempotency_key, is_simulation=simulation,
                simulate_primary_failure=bool(simulate_primary_failure and simulation),
                ack_timeout_seconds=plan.ack_timeout_seconds, activated_at=now)
            _event(a, "activated", "Guardian Mode was activated by you.")
            responders = list(plan.responders.select_related("contact").order_by("rank"))
            for r in responders:
                EmergencyAction.objects.create(activation=a, contact=r.contact, rank=r.rank)
            _event(a, "plan_loaded", f"Loaded safety plan version {plan.version} with {len(responders)} responder step(s). "
                                     "Only actions you authorised will be attempted.")
            _transition(a, State.ALERTS_PENDING, now)
            record("guardian.activated", actor=owner, obj=a, metadata={"mode": "simulation" if simulation else "live"})
    except IntegrityError:
        # A concurrent request won the race: hand back the activation it created.
        winner = _open_for(owner)
        if winner is None and idempotency_key:
            winner = GuardianActivation.objects.filter(owner=owner, idempotency_key=idempotency_key).first()
        if winner is not None:
            return winner, False
        raise

    with transaction.atomic():
        locked = GuardianActivation.objects.select_for_update().get(pk=a.pk)
        _dispatch_pending(locked, now)
    return GuardianActivation.objects.get(pk=a.pk), True


# ---------------------------------------------------------------- escalation engine
def _dispatch_pending(a, now):
    """Execute pending steps in rank order until one is submitted, or none remain. Caller holds the lock."""
    while True:
        action = a.actions.select_related("contact").filter(status=ActionStatus.PENDING).order_by("rank").first()
        if action is None:
            _exhaust(a, now)
            return
        if _execute_action(a, action, now):
            return
        if a.state != State.ESCALATION_REQUIRED:
            _transition(a, State.ESCALATION_REQUIRED, now)


def _exhaust(a, now):
    if a.state != State.ESCALATION_REQUIRED:
        _transition(a, State.ESCALATION_REQUIRED, now)
    a.ack_deadline = None
    _transition(a, State.ESCALATION_EXHAUSTED, now)
    _event(a, "exhausted", "No responder could be notified or acknowledged. LESEDI has not contacted emergency "
                           "services and cannot. If you are in danger, contact your local emergency services directly.")


def _execute_action(a, action, now) -> bool:
    """Returns True when a notification was submitted. Permissions are re-checked at execution time."""
    contact, plan = action.contact, a.plan
    reason = ""
    if contact.status != ContactStatus.ACTIVE:
        reason = "has not accepted, or was removed"
    elif not ResponderAssignment.objects.filter(plan=plan, contact=contact).exists():
        reason = "is no longer in your responder order"
    elif not has_permission(plan, contact, Permission.RECEIVE_ALERT):
        reason = "is not currently allowed to receive alerts"
    if reason:
        action.status, action.detail, action.executed_at = ActionStatus.SKIPPED, f"Skipped: {reason}"[:200], now
        action.save()
        _event(a, "action_skipped", f"Step {action.rank}: {contact.name} was skipped - {reason}.")
        return False

    link = settings.LESEDI_PUBLIC_BASE_URL + ack_path(make_ack_token(a, contact))
    label = _channel_label(contact.preferred_channel)
    last_error = ""
    for attempt in range(1, settings.GUARDIAN_MAX_SEND_ATTEMPTS + 1):
        force_fail = a.simulate_primary_failure and action.rank == 1
        delivery = notify.send(activation=a, contact=contact, channel=contact.preferred_channel, link=link,
                               attempt=attempt, force_fail=force_fail)
        if delivery.status == DeliveryStatus.SUBMITTED:
            action.status, action.executed_at = ActionStatus.DONE, now
            action.detail = f"Submitted via {label}"
            action.save()
            a.ack_deadline = now + timedelta(seconds=a.ack_timeout_seconds)
            _transition(a, State.AWAITING_ACKNOWLEDGEMENT if a.state == State.ALERTS_PENDING else State.BACKUP_CONTACTED, now)
            _event(a, "notification_submitted",
                   f"Step {action.rank}: a notification for {contact.name} was submitted via {label}"
                   f"{' (no real message was sent)' if delivery.is_simulated else ''}. Delivery is not confirmed. "
                   f"Waiting for {contact.name} to acknowledge until {_hhmmss(a.ack_deadline)}.", simulated=True)
            return True
        last_error = delivery.error
        _event(a, "notification_failed",
               f"Step {action.rank}: attempt {attempt} to notify {contact.name} via {label} failed: {delivery.error}",
               simulated=delivery.is_simulated)

    action.status, action.detail, action.executed_at = ActionStatus.FAILED, f"Failed: {last_error}"[:200], now
    action.save()
    _event(a, "action_failed", f"Step {action.rank}: {contact.name} could not be notified after "
                               f"{settings.GUARDIAN_MAX_SEND_ATTEMPTS} attempt(s). Moving to the next responder.")
    return False


def _expire(a, now):
    _event(a, "ack_timeout", f"No acknowledgement within {a.ack_timeout_seconds} seconds.")
    a.ack_deadline = None
    _transition(a, State.ESCALATION_REQUIRED, now)
    _dispatch_pending(a, now)


def process_due(now=None) -> int:
    """Escalate every activation whose acknowledgement deadline has passed. Called by Celery beat; also
    callable directly with a fake `now` so tests need no real waiting. Idempotent and lock-protected."""
    now = now or timezone.now()
    handled = 0
    due = list(GuardianActivation.objects.filter(state__in=[s.value for s in WAITING_STATES], ack_deadline__lte=now)
               .values_list("pk", flat=True))
    stuck = list(GuardianActivation.objects.filter(
        state__in=[State.ALERTS_PENDING.value, State.ESCALATION_REQUIRED.value], updated_at__lte=now - timedelta(seconds=60))
        .values_list("pk", flat=True))
    for pk in due:
        with transaction.atomic():
            a = GuardianActivation.objects.select_for_update().get(pk=pk)
            if a.state in WAITING_STATES and a.ack_deadline and a.ack_deadline <= now:
                _expire(a, now)
                handled += 1
    for pk in stuck:  # recovery: a crash mid-dispatch must not strand a person
        with transaction.atomic():
            a = GuardianActivation.objects.select_for_update().get(pk=pk)
            if a.state in (State.ALERTS_PENDING, State.ESCALATION_REQUIRED):
                _dispatch_pending(a, now)
                handled += 1
    return handled


# ---------------------------------------------------------------- acknowledgement
def read_token(token):
    try:
        return signing.loads(token, salt=ACK_SALT, max_age=settings.GUARDIAN_ACK_TOKEN_MAX_AGE)
    except signing.BadSignature as exc:  # includes SignatureExpired
        raise InvalidToken("This link is not valid any more.") from exc


def resolve_token(token):
    """Return (activation, contact) for a valid token, else raise InvalidToken."""
    data = read_token(token)
    a = GuardianActivation.objects.filter(pk=data["a"]).first()
    contact = TrustedContact.objects.filter(pk=data["c"]).first()
    if a is None or contact is None or contact.owner_id != a.owner_id:
        raise InvalidToken("This link is not valid any more.")
    return a, contact


def acknowledge(token, *, now=None):
    """Record that a responder saw the alert. Returns (activation, contact, newly_recorded)."""
    now = now or timezone.now()
    data = read_token(token)
    with transaction.atomic():
        a = GuardianActivation.objects.select_for_update().filter(pk=data["a"]).first()
        contact = TrustedContact.objects.filter(pk=data["c"]).first()
        if a is None or contact is None or contact.owner_id != a.owner_id:
            raise InvalidToken("This link is not valid any more.")
        if a.state in TERMINAL_STATES:
            return a, contact, False
        plan = a.plan
        if not has_permission(plan, contact, Permission.ACKNOWLEDGE_ALERT):
            raise NotPermitted("You are not currently allowed to acknowledge this.")
        if not a.actions.filter(contact=contact, status=ActionStatus.DONE).exists():
            raise NotPermitted("This alert was not sent to you.")
        _, created = ResponderAcknowledgement.objects.get_or_create(
            activation=a, contact=contact, defaults={"acknowledged_at": now})
        if created:
            _event(a, "acknowledged", f"{contact.name} acknowledged the alert. This confirms they saw it. It does "
                                      "not confirm that anyone is travelling to you or has arrived.")
            record("guardian.acknowledged", obj=a)
            if a.state in WAITING_STATES or a.state == State.ESCALATION_EXHAUSTED:
                a.ack_deadline = None
                _transition(a, State.ACKNOWLEDGED, now)
        return a, contact, created


# ---------------------------------------------------------------- closing and demo helpers
def close(owner, activation_id, *, outcome, note=None, now=None):
    """Owner ends the activation (RESOLVED or CANCELLED). Already-submitted notifications cannot be recalled."""
    now = now or timezone.now()
    with transaction.atomic():
        a = GuardianActivation.objects.select_for_update().get(pk=activation_id, owner=owner)
        if a.state in TERMINAL_STATES:
            return a
        a.ack_deadline = None
        a.actions.filter(status=ActionStatus.PENDING).update(status=ActionStatus.SKIPPED, detail="Skipped: activation ended")
        _transition(a, outcome, now)
        if outcome == State.RESOLVED:
            _event(a, "resolved", note or "You marked this as resolved.")
        else:
            _event(a, "cancelled", note or "You cancelled Guardian Mode. No further notifications will be attempted; "
                                           "notifications already submitted cannot be recalled.")
        return a


def demo_force_timeout(owner, activation_id, *, now=None):
    """SIMULATION ONLY: pretend the acknowledgement deadline has passed, then run the real escalation code."""
    now = now or timezone.now()
    with transaction.atomic():
        a = GuardianActivation.objects.select_for_update().get(pk=activation_id, owner=owner)
        if not a.is_simulation:
            raise GuardianError("Time can only be advanced in simulation mode.")
        if a.state not in WAITING_STATES:
            raise GuardianError("There is nothing waiting for an acknowledgement.")
        a.ack_deadline = now - timedelta(seconds=1)
        a.save(update_fields=["ack_deadline", "updated_at"])
        _event(a, "demo_clock", "Demo control: the waiting time was skipped ahead.", simulated=True)
    process_due(now)
    return GuardianActivation.objects.get(pk=activation_id)
