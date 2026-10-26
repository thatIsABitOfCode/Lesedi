"""Delivery adapters.

Only two kinds exist in this build:

* SimulatedAdapter: records that a message *would* have been submitted. Nothing
  leaves the machine. Used whenever NOTIFICATIONS_MODE == "simulation".
* InAppAdapter: makes the alert visible on the responder's own LESEDI alerts
  page (real, but only reaches people who have an account and sign in).

There is NO real SMS, WhatsApp, email or push provider implemented. In "live"
mode those channels fail safely with `provider_not_configured`.
"""
from dataclasses import dataclass

from django.conf import settings

from .channels import Channel


class AdapterError(Exception):
    transient = False

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TransientAdapterError(AdapterError):
    transient = True


class PermanentAdapterError(AdapterError):
    transient = False


@dataclass
class SendResult:
    provider_ref: str


class BaseAdapter:
    def send(self, delivery, text):  # pragma: no cover - interface
        raise NotImplementedError


class SimulatedAdapter(BaseAdapter):
    """Simulates a provider accepting (or failing) a message. Sends nothing."""

    def send(self, delivery, text):
        behaviour = delivery.contact.simulation_behaviour
        if behaviour == "fail_all":
            raise PermanentAdapterError("simulated_permanent_failure")
        if behaviour == "fail_preferred" and delivery.channel == delivery.contact.preferred_channel:
            raise PermanentAdapterError("simulated_preferred_channel_failure")
        if behaviour == "flaky":
            raise TransientAdapterError("simulated_transient_failure")
        return SendResult(provider_ref=f"SIMULATED-{delivery.pk.hex[:12]}")


class InAppAdapter(BaseAdapter):
    def send(self, delivery, text):
        if delivery.contact.linked_user_id is None:
            raise PermanentAdapterError("no_linked_account")
        return SendResult(provider_ref=f"INAPP-{delivery.pk.hex[:12]}")


class UnconfiguredLiveAdapter(BaseAdapter):
    """Placeholder for real providers. Fails safely instead of pretending to send."""

    def send(self, delivery, text):
        raise PermanentAdapterError("provider_not_configured")


def get_adapter(channel):
    if channel == Channel.INAPP:
        return InAppAdapter()
    if settings.NOTIFICATIONS_MODE == "simulation":
        return SimulatedAdapter()
    return UnconfiguredLiveAdapter()
