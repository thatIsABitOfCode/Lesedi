from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.models import Role
from evidence.models import Incident
from guardian.models import GuardianActivation
from guardian.states import OPEN_STATES
from safety.health import assess_plan
from safety.models import ContactStatus
from safety.services import get_or_create_plan
from shield.services import assess as shield_assess


def landing(request):
    return render(request, "core/landing.html")


@login_required
def dashboard(request):
    ctx = {"is_survivor": request.user.role == Role.SURVIVOR,
           "is_moderator": request.user.role in (Role.MODERATOR, Role.ADMIN)}
    if ctx["is_survivor"]:
        plan = get_or_create_plan(request.user)
        health = assess_plan(plan)
        shield = shield_assess(request.user)
        ctx.update({
            "plan": plan,
            "health_high": sum(1 for f in health if f.severity == "high"),
            "health_total": len(health),
            "shield_high": sum(1 for f in shield if f.severity == "high"),
            "shield_total": len(shield),
            "contact_count": request.user.trusted_contacts.exclude(status=ContactStatus.REVOKED).count(),
            "responder_count": plan.responders.count(),
            "incident_count": Incident.objects.filter(owner=request.user).count(),
            "open_activation": GuardianActivation.objects.filter(
                owner=request.user, state__in=[s.value for s in OPEN_STATES]).first(),
        })
    return render(request, "core/dashboard.html", ctx)


def resources(request):
    return render(request, "core/resources.html")


def offline(request):
    return render(request, "core/offline.html")


def healthz(request):
    """Liveness/readiness. Reveals no secrets, versions or configuration."""
    db_ok = True
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        db_ok = False
    return JsonResponse({"status": "ok" if db_ok else "degraded", "database": db_ok}, status=200 if db_ok else 503)


def service_worker(request):
    """Served from the site root so its scope covers the whole app."""
    body = (settings.BASE_DIR / "static" / "js" / "sw.js").read_text(encoding="utf-8")
    resp = HttpResponse(body, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp
