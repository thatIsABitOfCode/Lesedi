"""Guardian Mode orchestration.

Principles enforced here:

* Only actions the survivor authorised in advance (plan + contact permissions)
  are ever taken.
* queued != submitted != delivered != seen != acknowledged != help arrived.
  Each is recorded separately and described accurately on the timeline.
* LESEDI never contacts emergency services or police and never says it has.
* State changes and notification queuing happen inside database transactions,
  serialised per user, with an idempotency key and database constraints
  preventing duplicate activations.
"""
import logging
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps import audit
from apps.accounts.models import User
from apps.notifications import services as notify
from apps.notifications.models import LIVE_STATUSES, DeliveryStatus, NotificationDelivery
from apps.safety_circle import services as circle
from apps.safety_circle.models import Permission
from apps.safety_plans.models import ResponderRole, SafetyPlan

from .models import (
    CLOSED_STATES,
    OPEN_STATES,
    ActionType,
    EmergencyAction,
    GuardianActivation,
    GuardianEvent,
    ResponderAcknowledgement,
    State,
)
from .state import allowed_next

logger = logging.getLogger(__name__)

SCOPE_NOTE = (
    "LESEDI does not contact emergency services or the police, and has not done so. "
    "If you are in immediate danger, contact your local emergency services directly."
)
SIMULATION_NOTE = (
    "SIMULATION: no real SMS, WhatsApp message, email, emergency-service call or physical response "
    "is happening. Everything below is a rehearsal."
)


class GuardianError(Exception):
    pass


class NoActivePlan(GuardianError):
    pass


class NotAuthorised(GuardianError):
    pass


class InvalidTransition(GuardianError):
    pass


class AlreadyActive(GuardianError):
    def __init__(self, activation):
        super().__init__("An activation is already open.")
        self.activation = activation


# ------------------------------------------------------------------ helpers

def _sim(activation):
    return " [Simulated: no real message was sent.]" if activation.simulated else ""


def add_event(activation, kind, message):
    return GuardianEvent.objects.create(activation=activation, kind=kind, message=message[:300])


def transition(activation, new_state, *, why=""):
    """Move to `new_state` if the state machine allows it; otherwise raise."""
    new_state = State(new_state)
    if new_state not in allowed_next(activation.state):
        raise InvalidTransition(f"{activation.state} -> {new_state.value} is not allowed")
    old = activation.state
    activation.state = new_state.value
    fields = ["state", "updated_at"]
    if new_state.value in CLOSED_STATES:
        activation.closed_at = timezone.now()
        fields.append("closed_at")
    activation.save(update_fields=fields)
    add_event(activation, "state", f"Status changed from '{State(old).label}' to '{new_state.label}'.{(' ' + why) if why else ''}")
    audit.record(activation.owner, "guardian.state_changed", activation, from_state=old, to_state=new_state.value)


def authorised_responders(plan, role):
    """Contacts on the plan in `role` whom the survivor has actually permitted to
    receive alerts (backups also need the backup permission). Returns (ok, skipped)."""
    needed = [Permission.RECEIVE_ALERT]
    if role == ResponderRole.BACKUP:
        needed.append(Permission.BACKUP_RESPONDER)
    ok, skipped = [], []
    for assignment in plan.responders.filter(role=role).select_related("contact").order_by("position", "created_at"):
        contact = assignment.contact
        if contact.removed_at is not None:
            continue
        if all(circle.has_permission(contact, p) for p in needed):
            ok.append(contact)
        else:
            skipped.append(contact)
    return ok, skipped


def _dispatch_after_commit(delivery_ids):
    if delivery_ids:
        transaction.on_commit(lambda: notify.dispatch_many(delivery_ids))


def _queue_alerts(activation, contacts, action_type):
    ids = []
    for contact in contacts:
        action, _ = EmergencyAction.objects.get_or_create(
            activation=activation, action_type=action_type, contact=contact
        )
        channel = contact.preferred_channel
        delivery, created = notify.create_delivery(action, contact, channel, f"{action.pk}:{channel}")
        if created:
            add_event(
                activation,
                "alert_queued",
                f"Alert queued for {contact.name} by {delivery.get_channel_display()}. "
                f"'Queued' means waiting to be sent; it has not been sent yet.{_sim(activation)}",
            )
            ids.append(str(delivery.pk))
    return ids


# ---------------------------------------------------------------- activation

def activate(owner, idempotency_key):
    """Start Guardian Mode. Returns (activation, created).

    Calling again with the same key returns the same activation (safe retries).
    A different key while one is open raises AlreadyActive.
    """
    key = (idempotency_key or "").strip()[:64] or uuid.uuid4().hex
    try:
        with transaction.atomic():
            # Serialise concurrent requests from the same person.
            User.objects.select_for_update().get(pk=owner.pk)
            existing = GuardianActivation.objects.filter(owner=owner, idempotency_key=key).first()
            if existing is not None:
                return existing, False
            open_activation = GuardianActivation.objects.filter(owner=owner, state__in=OPEN_STATES).first()
            if open_activation is not None:
                raise AlreadyActive(open_activation)
            plan = SafetyPlan.objects.filter(owner=owner, is_active=True).first()
            if plan is None:
                raise NoActivePlan("You need an active safety plan before Guardian Mode can help.")

            from django.conf import settings

            activation = GuardianActivation.objects.create(
                owner=owner,
                plan=plan,
                plan_version=plan.version,
                state=State.ACTIVATED,
                idempotency_key=key,
                simulated=settings.NOTIFICATIONS_MODE == "simulation",
                ack_timeout_seconds=plan.ack_timeout_seconds,
                auto_escalate_authorised=plan.auto_escalate_to_backup,
            )
            audit.record(owner, "guardian.activated", activation, simulated=activation.simulated)
            add_event(activation, "activated", "Guardian Mode was activated by you, using your saved plan.")
            if activation.simulated:
                add_event(activation, "simulation", SIMULATION_NOTE)
            add_event(activation, "scope", SCOPE_NOTE)

            primaries, skipped = authorised_responders(plan, ResponderRole.PRIMARY)
            for contact in skipped:
                add_event(
                    activation,
                    "not_authorised",
                    f"{contact.name} is on your plan but is not currently permitted to receive alerts, so they were not contacted.",
                )
            if primaries:
                transition(activation, State.ALERTS_PENDING)
                _dispatch_after_commit(_queue_alerts(activation, primaries, ActionType.NOTIFY_PRIMARY))
            else:
                add_event(
                    activation,
                    "no_responder",
                    "No primary responder is currently able to receive alerts. LESEDI has not contacted anyone.",
                )
                transition(activation, State.ESCALATION_REQUIRED)
                _escalate_to_backup(activation, manual=False)
            return activation, True
    except IntegrityError:
        # A concurrent request won the race at the database level.
        existing = GuardianActivation.objects.filter(owner=owner, idempotency_key=key).first()
        if existing is not None:
            return existing, False
        open_activation = GuardianActivation.objects.filter(owner=owner, state__in=OPEN_STATES).first()
        if open_activation is not None:
            raise AlreadyActive(open_activation)
        raise


# --------------------------------------------------------------- escalation

def _escalate_to_backup(activation, *, manual):
    """Notify backup responders if (and only if) the survivor authorised it.
    `manual=True` means the survivor asked for it just now."""
    if activation.backup_contacted_at is not None:
        add_event(activation, "no_more_backup", "Your backup responder has already been contacted.")
        return False
    if not manual and not activation.auto_escalate_authorised:
        add_event(
            activation,
            "escalation_not_authorised",
            "Your plan does not authorise automatic escalation, so LESEDI has not contacted your backup. "
            "You can choose to notify your backup yourself below.",
        )
        return False
    backups, skipped = authorised_responders(activation.plan, ResponderRole.BACKUP)
    for contact in skipped:
        add_event(
            activation,
            "not_authorised",
            f"{contact.name} is a backup on your plan but is not currently permitted to receive alerts, so they were not contacted.",
        )
    if not backups:
        add_event(activation, "no_backup", "No authorised backup responder is available to contact.")
        return False
    now = timezone.now()
    activation.backup_contacted_at = now
    activation.ack_deadline = now + timedelta(seconds=activation.ack_timeout_seconds)
    activation.save(update_fields=["backup_contacted_at", "ack_deadline", "updated_at"])
    ids = _queue_alerts(activation, backups, ActionType.NOTIFY_BACKUP)
    add_event(
        activation,
        "escalation",
        "You asked LESEDI to notify your backup responder."
        if manual
        else "Escalation: you authorised LESEDI in advance to notify your backup responder if your primary did not acknowledge.",
    )
    transition(activation, State.BACKUP_CONTACTED)
    _dispatch_after_commit(ids)
    return True


def process_timeouts(now=None):
    """Apply acknowledgement timeouts. Run every few seconds by Celery beat."""
    now = now or timezone.now()
    due = list(
        GuardianActivation.objects.filter(
            state__in=[State.AWAITING_ACKNOWLEDGEMENT, State.BACKUP_CONTACTED], ack_deadline__lte=now
        ).values_list("pk", flat=True)
    )
    for row in GuardianActivation.objects.filter(state=State.ALERTS_PENDING).only("pk", "created_at", "ack_timeout_seconds"):
        if row.created_at + timedelta(seconds=row.ack_timeout_seconds) <= now:
            due.append(row.pk)
    handled = 0
    for pk in due:
        if _process_one(pk, now):
            handled += 1
    return handled


def _process_one(pk, now):
    with transaction.atomic():
        activation = GuardianActivation.objects.select_for_update().select_related("plan", "owner").get(pk=pk)
        if activation.state == State.AWAITING_ACKNOWLEDGEMENT and activation.ack_deadline and activation.ack_deadline <= now:
            add_event(
                activation,
                "timeout",
                f"No acknowledgement was received within {activation.ack_timeout_seconds} seconds.",
            )
            activation.ack_deadline = None
            activation.save(update_fields=["ack_deadline", "updated_at"])
            transition(activation, State.ESCALATION_REQUIRED)
            _escalate_to_backup(activation, manual=False)
            return True
        if activation.state == State.BACKUP_CONTACTED and activation.ack_deadline and activation.ack_deadline <= now:
            add_event(activation, "timeout", "Your backup responder did not acknowledge in time.")
            activation.ack_deadline = None
            activation.save(update_fields=["ack_deadline", "updated_at"])
            transition(activation, State.ESCALATION_REQUIRED)
            add_event(
                activation,
                "exhausted",
                "Everyone you authorised has been tried. LESEDI will take no further automatic action. "
                "Please contact someone you trust or your local emergency services directly.",
            )
            return True
        if (
            activation.state == State.ALERTS_PENDING
            and activation.created_at + timedelta(seconds=activation.ack_timeout_seconds) <= now
        ):
            add_event(activation, "timeout", "The alerts could not be sent in time.")
            transition(activation, State.ESCALATION_REQUIRED)
            _escalate_to_backup(activation, manual=False)
            return True
    return False


def manual_escalate(activation_id, owner):
    """The survivor chooses to notify their backup now (also covers 'alternatives
    when the primary or its channel failed')."""
    with transaction.atomic():
        activation = (
            GuardianActivation.objects.select_for_update().select_related("plan", "owner").get(pk=activation_id, owner=owner)
        )
        if not activation.is_open:
            raise InvalidTransition("This activation has ended.")
        if activation.state in (State.ALERTS_PENDING, State.AWAITING_ACKNOWLEDGEMENT):
            activation.ack_deadline = None
            activation.save(update_fields=["ack_deadline", "updated_at"])
            transition(activation, State.ESCALATION_REQUIRED, why="You chose to escalate without waiting.")
        if activation.state != State.ESCALATION_REQUIRED:
            raise InvalidTransition("Escalation is not available in this state.")
        return _escalate_to_backup(activation, manual=True)


# ------------------------------------------------------- delivery callbacks

def handle_delivery_update(delivery_id):
    """Called by the notification service whenever a delivery changes status."""
    with transaction.atomic():
        delivery = NotificationDelivery.objects.select_related("contact", "action").get(pk=delivery_id)
        activation = (
            GuardianActivation.objects.select_for_update()
            .select_related("plan", "owner")
            .get(pk=delivery.action.activation_id)
        )
        if activation.state in CLOSED_STATES:
            return
        name = delivery.contact.name
        channel = delivery.get_channel_display()
        sim = _sim(activation) if delivery.simulated else ""
        if delivery.status == DeliveryStatus.SUBMITTED:
            add_event(
                activation,
                "delivery_submitted",
                f"Alert for {name} submitted to the {channel} service.{sim} "
                "Submitted does not mean delivered, and delivered does not mean seen.",
            )
            if activation.state == State.ALERTS_PENDING:
                activation.ack_deadline = timezone.now() + timedelta(seconds=activation.ack_timeout_seconds)
                activation.save(update_fields=["ack_deadline", "updated_at"])
                transition(activation, State.AWAITING_ACKNOWLEDGEMENT)
        elif delivery.status == DeliveryStatus.DELIVERED:
            add_event(
                activation,
                "delivery_delivered",
                f"The {channel} service reported the alert for {name} as delivered.{sim} This does not confirm it was seen.",
            )
        elif delivery.status == DeliveryStatus.RETRYING:
            add_event(
                activation,
                "delivery_retrying",
                f"Sending to {name} by {channel} hit a problem ({delivery.last_error}). Trying again "
                f"(attempt {delivery.attempts} of {delivery.max_attempts}).{sim}",
            )
        elif delivery.status == DeliveryStatus.FAILED:
            add_event(
                activation,
                "delivery_failed",
                f"Alert for {name} by {channel} could not be sent ({delivery.last_error}).{sim}",
            )
            fallback_started = _try_fallback_channel(activation, delivery)
            if not fallback_started:
                _check_exhausted(activation, delivery.action.action_type)


def _try_fallback_channel(activation, delivery):
    contact = delivery.contact
    fallback = contact.fallback_channel
    if not fallback or fallback == delivery.channel:
        return False
    if NotificationDelivery.objects.filter(action=delivery.action, channel=fallback).exists():
        return False
    new_delivery, created = notify.create_delivery(
        delivery.action, contact, fallback, f"{delivery.action_id}:{fallback}"
    )
    if created:
        add_event(
            activation,
            "fallback_channel",
            f"{contact.name} could not be reached by {delivery.get_channel_display()}, so LESEDI queued "
            f"{new_delivery.get_channel_display()} instead, a second way you set up in advance.{_sim(activation)}",
        )
        _dispatch_after_commit([str(new_delivery.pk)])
    return created


def _check_exhausted(activation, action_type):
    still_possible = NotificationDelivery.objects.filter(
        action__activation=activation, action__action_type=action_type, status__in=LIVE_STATUSES
    ).exists()
    if still_possible:
        return
    if action_type == ActionType.NOTIFY_PRIMARY and activation.state in (
        State.ALERTS_PENDING,
        State.AWAITING_ACKNOWLEDGEMENT,
    ):
        add_event(activation, "primary_failed", "None of the alerts to your primary responder could be sent.")
        activation.ack_deadline = None
        activation.save(update_fields=["ack_deadline", "updated_at"])
        transition(activation, State.ESCALATION_REQUIRED)
        _escalate_to_backup(activation, manual=False)
    elif action_type == ActionType.NOTIFY_BACKUP and activation.state == State.BACKUP_CONTACTED:
        add_event(
            activation,
            "backup_failed",
            "None of the alerts to your backup responder could be sent. LESEDI has no further authorised "
            "contacts to try. Please contact someone you trust or your local emergency services directly.",
        )
        activation.ack_deadline = None
        activation.save(update_fields=["ack_deadline", "updated_at"])
        transition(activation, State.ESCALATION_REQUIRED)


# ------------------------------------------------------------- acknowledgement

def acknowledge(activation_id, user):
    """A trusted contact says they have seen the alert.

    Requires: the contact was actually alerted for this activation, belongs to
    `user`, and still holds BOTH receive-alert and acknowledge permissions.
    """
    with transaction.atomic():
        try:
            activation = GuardianActivation.objects.select_for_update().select_related("owner").get(pk=activation_id)
        except GuardianActivation.DoesNotExist:
            raise NotAuthorised("Not available.")
        if not activation.is_open:
            raise GuardianError("This alert has ended.")
        action = (
            EmergencyAction.objects.filter(
                activation=activation, contact__linked_user=user, contact__removed_at__isnull=True
            )
            .select_related("contact")
            .first()
        )
        if action is None:
            raise NotAuthorised("Not available.")
        contact = action.contact
        if not (
            circle.has_permission(contact, Permission.RECEIVE_ALERT)
            and circle.has_permission(contact, Permission.ACKNOWLEDGE_ALERT)
        ):
            raise NotAuthorised("Not available.")
        _, created = ResponderAcknowledgement.objects.get_or_create(
            activation=activation, contact=contact, defaults={"acknowledged_by": user}
        )
        if created:
            add_event(
                activation,
                "acknowledged",
                f"{contact.name} acknowledged the alert. This means they have seen it. It does not confirm "
                "that anyone is on their way or has arrived.",
            )
            audit.record(user, "guardian.acknowledged", activation)
        if activation.state != State.ACKNOWLEDGED and State.ACKNOWLEDGED in allowed_next(activation.state):
            activation.ack_deadline = None
            activation.save(update_fields=["ack_deadline", "updated_at"])
            transition(activation, State.ACKNOWLEDGED)
        return created


# ------------------------------------------------------------------- closing

def close_activation(activation_id, owner, new_state, note=""):
    if State(new_state).value not in CLOSED_STATES:
        raise InvalidTransition("Only 'resolved' or 'cancelled' end an activation.")
    with transaction.atomic():
        activation = GuardianActivation.objects.select_for_update().select_related("owner").get(
            pk=activation_id, owner=owner
        )
        activation.ack_deadline = None
        activation.outcome_note = note[:200]
        activation.save(update_fields=["ack_deadline", "outcome_note", "updated_at"])
        transition(activation, new_state, why="Ended by you.")
        add_event(
            activation,
            "closed",
            "Alerts that had not been sent yet will not be sent. LESEDI does not tell your contacts that "
            "you ended this, so you may want to let them know yourself.",
        )
        return activation


# ------------------------------------------------------- simulation controls

def simulate_time_passing(activation_id, owner):
    """Rehearsal helper: skip the wait for an acknowledgement. Simulation only."""
    with transaction.atomic():
        activation = GuardianActivation.objects.select_for_update().get(pk=activation_id, owner=owner)
        if not activation.simulated:
            raise GuardianError("Only available in simulation.")
        if activation.state not in (State.AWAITING_ACKNOWLEDGEMENT, State.BACKUP_CONTACTED):
            raise GuardianError("There is no acknowledgement wait to skip right now.")
        activation.ack_deadline = timezone.now() - timedelta(seconds=1)
        activation.save(update_fields=["ack_deadline", "updated_at"])
        add_event(activation, "simulation", "Simulation: the wait for an acknowledgement was skipped ahead.")
    return process_timeouts()


def simulate_delivery_receipts(activation_id, owner):
    activation = GuardianActivation.objects.get(pk=activation_id, owner=owner)
    if not activation.simulated:
        raise GuardianError("Only available in simulation.")
    ids = list(
        NotificationDelivery.objects.filter(
            action__activation=activation, simulated=True, status=DeliveryStatus.SUBMITTED
        ).values_list("pk", flat=True)
    )
    for delivery_id in ids:
        notify.record_simulated_receipt(delivery_id)
    return len(ids)
