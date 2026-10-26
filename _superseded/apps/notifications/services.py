"""Provider-independent notification service."""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .adapters import AdapterError, TransientAdapterError, get_adapter
from .channels import Channel
from .models import DeliveryStatus, NotificationDelivery, TERMINAL_STATUSES

logger = logging.getLogger(__name__)

NEUTRAL_TEXT = "You have a new message waiting in LESEDI. Please sign in to view it."


def render_message(delivery):
    """Message text. Never contains locations, allegations or evidence content."""
    owner = delivery.action.activation.owner
    if owner.neutral_notifications:
        return NEUTRAL_TEXT
    return f"{owner.display_name} has asked LESEDI to contact you. Open LESEDI to see what to do."


def create_delivery(action, contact, channel, key):
    """Idempotent: the same key always returns the same delivery."""
    return NotificationDelivery.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "action": action,
            "contact": contact,
            "channel": channel,
            "simulated": settings.NOTIFICATIONS_MODE == "simulation" and channel != Channel.INAPP,
            "max_attempts": settings.NOTIFICATION_MAX_ATTEMPTS,
        },
    )


def dispatch(delivery_id, countdown=0):
    """Hand a delivery to Celery. If the broker is down the delivery stays QUEUED
    (honestly) and the periodic `notifications.requeue_stuck` task picks it up."""
    from kombu.exceptions import OperationalError

    from .tasks import send_delivery

    try:
        send_delivery.apply_async(args=[str(delivery_id)], countdown=countdown)
    except (OperationalError, ConnectionError, OSError):
        logger.warning("Notification dispatch deferred: task broker unavailable")


def dispatch_many(delivery_ids):
    for delivery_id in delivery_ids:
        dispatch(delivery_id)


def attempt_delivery(delivery_id):
    """Make one send attempt. Safe to call more than once for the same delivery.

    The row stays locked while the adapter runs, which prevents duplicate sends
    for the same delivery. Real network adapters should keep their timeouts short.
    """
    from apps.guardian import services as guardian_services
    from apps.guardian.models import CLOSED_STATES

    with transaction.atomic():
        delivery = (
            NotificationDelivery.objects.select_for_update()
            .select_related("contact", "action__activation__owner")
            .get(pk=delivery_id)
        )
        if delivery.status in TERMINAL_STATUSES:
            return delivery
        now = timezone.now()
        if delivery.action.activation.state in CLOSED_STATES:
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error = "activation_closed"
            delivery.failed_at = now
        else:
            delivery.attempts += 1
            try:
                result = get_adapter(delivery.channel).send(delivery, render_message(delivery))
            except TransientAdapterError as exc:
                _record_failure(delivery, exc.code, now, retry=True)
            except AdapterError as exc:
                _record_failure(delivery, exc.code, now, retry=False)
            except Exception as exc:  # unexpected adapter bug: treat as transient, log type only
                logger.error("Adapter raised %s", type(exc).__name__)
                _record_failure(delivery, "adapter_error", now, retry=True)
            else:
                delivery.status = DeliveryStatus.SUBMITTED
                delivery.submitted_at = now
                delivery.provider_ref = result.provider_ref
                delivery.last_error = ""
                delivery.next_retry_at = None
        delivery.save()

    guardian_services.handle_delivery_update(delivery.pk)
    if delivery.status == DeliveryStatus.RETRYING:
        dispatch(delivery.pk, countdown=settings.NOTIFICATION_RETRY_DELAY_SECONDS)
    return delivery


def _record_failure(delivery, code, now, *, retry):
    delivery.last_error = code
    if retry and delivery.attempts < delivery.max_attempts:
        delivery.status = DeliveryStatus.RETRYING
        delivery.next_retry_at = now + timedelta(seconds=settings.NOTIFICATION_RETRY_DELAY_SECONDS)
    else:
        delivery.status = DeliveryStatus.FAILED
        delivery.failed_at = now
        delivery.next_retry_at = None


def record_simulated_receipt(delivery_id):
    """Simulate a provider delivery receipt. Only ever applies to simulated deliveries.

    Real provider webhooks (with signature validation and replay protection)
    are NOT implemented yet.
    """
    from apps.guardian import services as guardian_services

    with transaction.atomic():
        delivery = NotificationDelivery.objects.select_for_update().get(pk=delivery_id)
        if not delivery.simulated or delivery.status != DeliveryStatus.SUBMITTED:
            return delivery
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = timezone.now()
        delivery.save(update_fields=["status", "delivered_at"])
    guardian_services.handle_delivery_update(delivery.pk)
    return delivery
