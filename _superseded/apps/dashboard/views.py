import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.db import connection
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from apps.evidence.models import Incident
from apps.guardian.models import OPEN_STATES, EmergencyAction, GuardianActivation
from apps.safety_circle.models import TrustedContact
from apps.safety_plans import services as plan_services
from apps.safety_plans.models import SafetyPlan

from . import content


def landing(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    return render(request, "dashboard/landing.html")


@login_required
def home(request):
    user = request.user
    plan = SafetyPlan.objects.filter(owner=user, is_active=True).first()
    findings = plan_services.assess_plan_health(plan) if plan else []
    return render(
        request,
        "dashboard/home.html",
        {
            "plan": plan,
            "attention": [f for f in findings if f.severity == "attention"],
            "suggestion_count": len([f for f in findings if f.severity == "suggestion"]),
            "open_activation": GuardianActivation.objects.filter(owner=user, state__in=OPEN_STATES).first(),
            "contact_count": TrustedContact.objects.filter(owner=user, removed_at__isnull=True).count(),
            "incident_count": Incident.objects.filter(owner=user).count(),
            "alerts_for_me": EmergencyAction.objects.filter(
                contact__linked_user=user,
                contact__removed_at__isnull=True,
                activation__state__in=OPEN_STATES,
            ).count(),
        },
    )


def recognise(request):
    return render(
        request,
        "dashboard/recognise.html",
        {"intro": content.RECOGNISE_INTRO, "sections": content.RECOGNISE_SECTIONS, "leaving_note": content.LEAVING_NOTE,
         "disclaimer": content.DISCLAIMER},
    )


def support(request):
    return render(
        request,
        "dashboard/support.html",
        {
            "resources": content.SUPPORT_RESOURCES,
            "speak_note": content.SPEAK_NOTE,
            "heal_note": content.HEAL_NOTE,
            "disclaimer": content.DISCLAIMER,
        },
    )


def privacy(request):
    return render(request, "dashboard/privacy.html", {"disclaimer": content.DISCLAIMER})


def offline(request):
    return render(request, "dashboard/offline.html", {"guide": content.OFFLINE_GUIDE})


def healthz(request):
    """Liveness/readiness. Reveals no configuration or secrets."""
    try:
        connection.ensure_connection()
        database = True
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        database = False
    return JsonResponse(
        {"status": "ok" if database else "degraded", "database": database},
        status=200 if database else 503,
    )


@never_cache
def service_worker(request):
    """Served from the site root so its scope covers the whole site. It only
    caches static assets and the public offline page; never signed-in pages."""
    path = finders.find("js/sw.js")
    if not path:
        raise Http404
    response = FileResponse(open(path, "rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def manifest(request):
    data = {
        "name": "LESEDI",
        "short_name": "LESEDI",
        "start_url": "/home/",
        "display": "standalone",
        "background_color": "#f6f5f2",
        "theme_color": "#0f5c5c",
        "description": "Plan, prepare and coordinate authorised support.",
        "icons": [],  # NOTE: no icons are shipped yet; see docs/LIMITATIONS.md
    }
    return JsonResponse(data, content_type="application/manifest+json")
