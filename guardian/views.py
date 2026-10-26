from django.http import HttpResponse
from django.shortcuts import render, redirect

from core.decorators import survivor_required
from core.ratelimit import client_ip, hit
from safety.models import Permission
from safety.services import get_or_create_plan, has_permission

from . import services
from .states import TERMINAL_STATES


@survivor_required
def guardian_page(request):
    plan = get_or_create_plan(request.user)
    responders = list(plan.responders.select_related("contact"))
    return render(request, "guardian/guardian.html", {
        "plan": plan, "responders": responders, "sim_notice": services.SIM_NOTICE, "limits": services.LIMITS_NOTICE})


def sos_page(request):
    """Dedicated SOS screen; activation uses the existing authenticated Guardian API."""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    plan = get_or_create_plan(request.user)
    responders = list(plan.responders.select_related("contact"))
    return render(request, "guardian/sos.html", {
        "plan": plan, "responders": responders, "sim_notice": services.SIM_NOTICE,
        "limits": services.LIMITS_NOTICE})


def ack_page(request, token):
    """Public page opened from the notification link. Shows the minimum a responder needs."""
    if not hit(f"ack:{client_ip(request)}", limit=60, window=3600):
        return HttpResponse("Too many requests.", status=429)
    try:
        activation, contact = services.resolve_token(token)
    except services.InvalidToken:
        return render(request, "guardian/ack_invalid.html", status=404)

    if activation.state in TERMINAL_STATES:
        return render(request, "guardian/ack_ended.html")

    ctx = {"activation": activation, "contact": contact, "inviter": activation.owner.display_name,
           "is_simulation": activation.is_simulation, "token": token, "done": False, "error": ""}
    if request.method == "POST":
        try:
            _, _, created = services.acknowledge(token)
            ctx["done"] = True
        except services.NotPermitted as exc:
            ctx["error"] = str(exc)
        except services.InvalidToken:
            return render(request, "guardian/ack_invalid.html", status=404)
    # Location is revealed only to an active, authorised alert recipient.
    if has_permission(activation.plan, contact, Permission.RECEIVE_ALERT):
        if activation.location_latitude is not None and activation.location_longitude is not None:
            ctx["shared_location"] = {
                "latitude": activation.location_latitude, "longitude": activation.location_longitude,
                "accuracy_m": activation.location_accuracy_m, "captured_at": activation.location_captured_at,
                "map_url": f"https://www.openstreetmap.org/?mlat={activation.location_latitude}&mlon={activation.location_longitude}#map=16/{activation.location_latitude}/{activation.location_longitude}",
            }
    # The instruction is only shown when the owner granted this exact permission.
    if has_permission(activation.plan, contact, Permission.RECEIVE_INSTRUCTION):
        ctx["instruction"] = activation.plan.emergency_instructions
    return render(request, "guardian/ack.html", ctx)
