from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import Role
from notifications.models import DeliveryStatus

from . import services
from .models import GuardianActivation
from .states import OPEN_STATES, State


class IsSurvivor(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.SURVIVOR)


def _iso(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def serialize(a: GuardianActivation) -> dict:
    deliveries = []
    for d in a.deliveries.select_related("contact").order_by("queued_at"):
        link = None
        if d.is_simulated and d.status in (DeliveryStatus.SUBMITTED, DeliveryStatus.DELIVERED):
            link = services.ack_path(services.make_ack_token(a, d.contact))
        deliveries.append({
            "contact": d.contact.name, "channel": d.get_channel_display(), "status": d.get_status_display(),
            "status_code": d.status, "simulated": d.is_simulated, "attempt": d.attempt, "error": d.error,
            "responder_link": link,
        })
    return {
        "id": str(a.id),
        "state": a.state,
        "state_label": a.get_state_display(),
        "is_open": a.state in [s.value for s in OPEN_STATES],
        "is_simulation": a.is_simulation,
        "notice": services.SIM_NOTICE if a.is_simulation else "",
        "limits": services.LIMITS_NOTICE,
        "activated_at": _iso(a.activated_at),
        "ack_deadline": _iso(a.ack_deadline),
        "ack_timeout_seconds": a.ack_timeout_seconds,
        "steps": [{"rank": x.rank, "name": x.contact.name, "status": x.get_status_display(), "detail": x.detail}
                  for x in a.actions.select_related("contact")],
        "deliveries": deliveries,
        "acknowledgements": [{"contact": k.contact.name, "at": _iso(k.acknowledged_at)}
                             for k in a.acknowledgements.select_related("contact")],
        "events": [{"time": _iso(e.created_at), "kind": e.kind, "message": e.message} for e in a.events.all()],
    }


class ActivateView(APIView):
    permission_classes = [IsAuthenticated, IsSurvivor]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guardian_activate"

    def post(self, request):
        key = str(request.data.get("idempotency_key", ""))[:64]
        fail = request.data.get("simulate_primary_failure") in (True, "true", "1", 1)
        try:
            a, created = services.activate(request.user, idempotency_key=key, simulate_primary_failure=fail)
        except services.NoActivePlan as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serialize(a), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CurrentView(APIView):
    permission_classes = [IsAuthenticated, IsSurvivor]

    def get(self, request):
        qs = GuardianActivation.objects.filter(owner=request.user)
        a = qs.filter(state__in=[s.value for s in OPEN_STATES]).first()
        if a is None:
            a = qs.filter(activated_at__gte=timezone.now() - timedelta(hours=24)).first()
        return Response({"activation": serialize(a) if a else None})


class DetailView(APIView):
    permission_classes = [IsAuthenticated, IsSurvivor]

    def get(self, request, pk):
        return Response(serialize(get_object_or_404(GuardianActivation, pk=pk, owner=request.user)))


class ActionView(APIView):
    """POST /api/guardian/<id>/<action>/ where action is resolve | cancel | simulate-timeout."""

    permission_classes = [IsAuthenticated, IsSurvivor]
    action = None

    def post(self, request, pk):
        a = get_object_or_404(GuardianActivation, pk=pk, owner=request.user)
        try:
            if self.action == "resolve":
                a = services.close(request.user, a.pk, outcome=State.RESOLVED)
            elif self.action == "cancel":
                a = services.close(request.user, a.pk, outcome=State.CANCELLED)
            elif self.action == "simulate-timeout":
                a = services.demo_force_timeout(request.user, a.pk)
        except services.GuardianError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(serialize(a))
