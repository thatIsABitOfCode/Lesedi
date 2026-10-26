from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from . import services
from .models import DeliveryStatus, NotificationDelivery


@shared_task(name="notifications.send_delivery")
def send_delivery(delivery_id):
    services.attempt_delivery(delivery_id)


@shared_task(name="notifications.requeue_stuck")
def requeue_stuck():
    """Re-dispatch deliveries that were queued while the broker was down, or whose
    retry time has passed. attempt_delivery is idempotent, so duplicates are harmless."""
    now = timezone.now()
    stuck = NotificationDelivery.objects.filter(
        Q(status=DeliveryStatus.QUEUED, queued_at__lte=now - timedelta(seconds=60))
        | Q(status=DeliveryStatus.RETRYING, next_retry_at__lte=now)
    ).values_list("pk", flat=True)[:200]
    for delivery_id in list(stuck):
        services.dispatch(delivery_id)
