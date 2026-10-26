from django.utils import timezone

from .adapters import AdapterNotConfigured, get_adapter
from .models import DeliveryStatus, NotificationDelivery

NEUTRAL_BODY = (
    "LESEDI: you have a new message from someone who listed you as a trusted contact. "
    "Open this link to read it and reply: {link}"
)


def send(*, activation, contact, channel, link, attempt=1, force_fail=False, kind="guardian_alert"):
    """Create a delivery attempt, hand it to the adapter, record the true outcome.

    The body is neutral by design: no names of people at risk, no locations, no instructions.
    Detail is only visible after the recipient opens the link and only if permitted."""
    body = NEUTRAL_BODY.format(link=link)
    try:
        adapter = get_adapter()
        simulated = adapter.name == "simulation"
    except AdapterNotConfigured as exc:
        return NotificationDelivery.objects.create(
            activation=activation, contact=contact, channel=channel, kind=kind, attempt=attempt,
            status=DeliveryStatus.FAILED, is_simulated=False, provider="none", error=str(exc)[:200],
            failed_at=timezone.now())

    delivery = NotificationDelivery.objects.create(
        activation=activation, contact=contact, channel=channel, kind=kind, attempt=attempt,
        status=DeliveryStatus.QUEUED, is_simulated=simulated, provider=adapter.name,
        body_preview=body if simulated else "")
    result = adapter.send(channel=channel, contact=contact, body=body, force_fail=force_fail)
    now = timezone.now()
    if result.ok:
        delivery.status = DeliveryStatus.SUBMITTED
        delivery.submitted_at = now
        delivery.provider_message_id = result.provider_message_id
    else:
        delivery.status = DeliveryStatus.FAILED
        delivery.failed_at = now
        delivery.error = result.error[:200]
    delivery.save()
    return delivery


def simulate_delivery_receipt(delivery):
    """Demo/test only: mimic a provider delivery receipt. Refuses for real deliveries."""
    if not delivery.is_simulated:
        raise ValueError("Only simulated deliveries can be given a simulated receipt.")
    if delivery.status != DeliveryStatus.SUBMITTED:
        raise ValueError("Only a submitted delivery can receive a delivery receipt.")
    delivery.status = DeliveryStatus.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.save(update_fields=["status", "delivered_at"])
    return delivery
