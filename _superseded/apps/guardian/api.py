"""JSON API for Guardian Mode. Session-authenticated and CSRF-protected (DRF
SessionAuthentication). Every query is scoped to the signed-in user."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import NotificationDelivery

from . import services
from .models import GuardianActivation


def serialise(activation, *, detail=False):
    data = {
        "id": str(activation.pk),
        "state": activation.state,
        "simulated": activation.simulated,
        "created_at": activation.created_at.isoformat(),
        "closed_at": activation.closed_at.isoformat() if activation.closed_at else None,
        "ack_deadline": activation.ack_deadline.isoformat() if activation.ack_deadline else None,
        "notice": services.SIMULATION_NOTE if activation.simulated else services.SCOPE_NOTE,
    }
    if detail:
        data["events"] = [{"at": e.created_at.isoformat(), "kind": e.kind, "message": e.message} for e in activation.events.all()]
        deliveries = NotificationDelivery.objects.filter(action__activation=activation).select_related("contact")
        data["deliveries"] = [
            {
                "contact": d.contact.name,
                "channel": d.channel,
                "status": d.status,
                "simulated": d.simulated,
                "attempts": d.attempts,
                "explanation": d.explanation,
            }
            for d in deliveries
        ]
        data["acknowledgements"] = [
            {"contact": a.contact.name, "at": a.created_at.isoformat()} for a in activation.acknowledgements.select_related("contact")
        ]
    return data


class ActivationListCreateAPI(APIView):
    def get(self, request):
        activations = GuardianActivation.objects.filter(owner=request.user)[:50]
        return Response({"results": [serialise(a) for a in activations]})

    def post(self, request):
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return Response(
                {"detail": "Send an Idempotency-Key header so a retried request cannot create a second activation."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            activation, created = services.activate(request.user, key)
        except services.AlreadyActive as exc:
            return Response(
                {"detail": "Guardian Mode is already active.", "activation": serialise(exc.activation)},
                status=status.HTTP_409_CONFLICT,
            )
        except services.NoActivePlan as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            serialise(activation, detail=True),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ActivationDetailAPI(APIView):
    def get(self, request, pk):
        try:
            activation = GuardianActivation.objects.get(pk=pk, owner=request.user)
        except GuardianActivation.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialise(activation, detail=True))
