"""Provider adapters. ONLY the simulation adapter exists in this build.

Real SMS / WhatsApp Business / FCM / email-for-alerts adapters are NOT implemented. Setting
LESEDI_NOTIFICATION_MODE to anything but "simulation" makes every delivery fail with a clear
error rather than pretending to send."""
import uuid
from dataclasses import dataclass

from django.conf import settings


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str = ""
    error: str = ""


class AdapterNotConfigured(Exception):
    pass


class SimulationAdapter:
    """Never touches the network. Reports SUBMITTED at most - never DELIVERED."""

    name = "simulation"

    def send(self, *, channel, contact, body, force_fail=False) -> SendResult:
        if force_fail:
            return SendResult(ok=False, error="Simulated provider failure (demo)")
        return SendResult(ok=True, provider_message_id=f"sim-{uuid.uuid4().hex[:12]}")


def get_adapter():
    if settings.LESEDI_NOTIFICATION_MODE == "simulation":
        return SimulationAdapter()
    raise AdapterNotConfigured(
        "No live provider adapter is implemented in this build. Use LESEDI_NOTIFICATION_MODE=simulation.")
