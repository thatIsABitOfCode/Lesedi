"""SHIELD privacy assessment.

What it does: turns the user's own answers and LESEDI's stored settings into plain findings, each labelled
with where it came from. What it does NOT do: detect spyware, stalkerware, hidden cameras, trackers or a
compromised device, and it never monitors the user's device. It says so on every report."""
from datetime import timedelta

from django.utils import timezone

from core.findings import INFERRED, SYSTEM_CHECKED, USER_REPORTED, Finding, sort_findings
from safety.models import ContactStatus, SafetyPlanPermission
from safety.services import get_or_create_plan

from .models import ShieldSelfReport

LIMITS = ("SHIELD only reflects what you told us and what is stored in LESEDI. It cannot detect spyware, hidden "
          "apps, trackers, cameras or a compromised phone, and it does not watch your device.")
STALE_AFTER = timedelta(days=90)


def get_report(user) -> ShieldSelfReport:
    return ShieldSelfReport.objects.get_or_create(owner=user)[0]


def assess(user, now=None) -> list:
    now = now or timezone.now()
    report = get_report(user)
    plan = get_or_create_plan(user)
    f = []

    if report.shared_account_access:
        f.append(Finding(
            "SHARED_ACCOUNT", "Someone else may be able to get into your accounts",
            "If another person can read your email or texts, they may see messages about your safety plan.",
            "From a device and network the other person cannot access, change passwords and recovery options for your "
            "email and phone account first. Consider a new email address used only for LESEDI.", "high", USER_REPORTED))
    if report.shared_device:
        f.append(Finding(
            "SHARED_DEVICE", "The device you use may not be private",
            "Anything open on a shared device, including this page, could be seen by that person.",
            "Use a device only you control where possible, log out when you finish, and use Quick Exit. "
            "Quick Exit cannot erase browser history or hide that you visited.", "high", USER_REPORTED))
    if report.suspects_monitoring:
        f.append(Finding(
            "SUSPECTED_MONITORING", "You suspect your phone or accounts are monitored",
            "LESEDI cannot confirm or rule this out.",
            "Trust your instinct. Avoid researching or changing things on the device you suspect. A trained "
            "support organisation can help you check safely.", "high", USER_REPORTED))
    if report.previews_visible:
        f.append(Finding(
            "PREVIEWS_VISIBLE", "Message previews appear on your lock screen",
            "LESEDI keeps its own notification wording neutral, but previews from other apps may still reveal things.",
            "Turn off lock-screen previews in your phone settings.", "medium", USER_REPORTED))
    if report.location_always_shared:
        f.append(Finding(
            "LOCATION_SHARED", "You share your location all the time",
            "Someone with access to that sharing could see where you go, including a safe destination.",
            "Review who can see your location in that app and pause sharing if it is safe to do so.", "medium", USER_REPORTED))

    contacts = list(user.trusted_contacts.exclude(status=ContactStatus.REVOKED))
    for c in contacts:
        grants = SafetyPlanPermission.objects.filter(plan=plan, contact=c, revoked_at__isnull=True)
        count = grants.count()
        if count >= 3 and not plan.responders.filter(contact=c).exists():
            f.append(Finding(
                f"BROAD_NO_ROLE:{c.id}", f"{c.name} holds every permission but is not a responder",
                "Wide permissions are easier to misuse and easier to forget.",
                "Remove permissions they do not need.", "medium", INFERRED))
        old = grants.filter(granted_at__lte=now - STALE_AFTER).count()
        if old:
            f.append(Finding(
                f"STALE_PERMISSIONS:{c.id}", f"{c.name}'s permissions have not been reviewed in 90 days",
                "People and circumstances change.", "Open their page and confirm each permission is still wanted.",
                "low", SYSTEM_CHECKED))

    if plan.responders.count() < 2:
        f.append(Finding(
            "NO_BACKUP", "Only one way to get help (or none)",
            "A single point of failure means one unreachable person can stop the plan.",
            "Add a backup responder in your Safety Circle.", "medium", SYSTEM_CHECKED))
    if plan.safe_destination.strip():
        f.append(Finding(
            "DESTINATION_STORED", "A safe destination is written in your plan",
            "It is stored privately and never put in notifications, but anyone who can log in as you could read it.",
            "Use a strong, unique password and log out on shared devices.", "low", SYSTEM_CHECKED))
    f.append(Finding(
        "NO_MFA", "Multi-factor sign-in is not available yet",
        "This version of LESEDI only protects your account with a password.",
        "Use a long, unique password. Multi-factor authentication is planned but not built.", "medium", SYSTEM_CHECKED))
    return sort_findings(f)
