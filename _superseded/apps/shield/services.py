"""SHIELD: a privacy and exposure check.

What it is: a checklist built from (a) what the person tells us, (b) their
LESEDI settings and (c) simple inferences from their plan and permissions. Each
finding says which of the three it rests on.

What it is NOT: it does not scan devices, detect spyware or stalkerware, find
hidden cameras or trackers, or monitor anything. It cannot tell whether someone
is watching a device. It must never be described as doing so.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.safety_circle.models import ContactPermission, Permission, TrustedContact
from apps.safety_plans.models import ResponderRole, SafetyPlan

from .models import Answer, ShieldAnswers

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
BASIS_LABELS = {
    "user_reported": "You told us this",
    "inferred": "Inferred from your plan and permissions",
    "verified": "Checked by LESEDI against its own records",
}
STALE_AFTER = timedelta(days=90)
BROAD_PERMISSION_COUNT = 5

LIMITATIONS = [
    "SHIELD does not scan your phone or computer and cannot detect spyware, stalkerware, hidden cameras or location trackers.",
    "SHIELD cannot tell whether someone else can see your screen, your messages or this app.",
    "LESEDI cannot be made invisible or undiscoverable. Quick exit changes what is on screen; it cannot erase browser history, "
    "operating-system records, network logs or monitoring software.",
    "Findings are prompts to think about your situation, not a guarantee of safety. Only you know what is safe for you.",
]


@dataclass(frozen=True)
class ShieldFinding:
    code: str
    risk: str
    why: str
    severity: str  # high | medium | low
    mitigation: str
    basis: str  # user_reported | inferred | verified
    action_label: str = ""
    action_url: str = ""

    @property
    def basis_label(self):
        return BASIS_LABELS[self.basis]


def get_answers(user):
    answers, _ = ShieldAnswers.objects.get_or_create(owner=user)
    return answers


def assess(user):
    """Return findings for `user`, most serious first."""
    answers = get_answers(user)
    findings = []
    settings_url = reverse("accounts:settings")
    circle_url = reverse("circle:list")

    for field, subject in (
        ("shared_account_access", "accounts"),
        ("shared_device_access", "device"),
    ):
        value = getattr(answers, field)
        if value == Answer.NO:
            continue
        if subject == "accounts":
            risk = "Someone else may be able to sign in to your accounts"
            why = (
                "If another person can open your email, phone or cloud account, they may be able to see "
                "messages, reset passwords or find out about your plans."
            )
            mitigation = (
                "When it is safe to do so, change passwords from a device they cannot access, check each "
                "account's recovery email and phone, and review signed-in devices."
            )
        else:
            risk = "Someone else may be able to use the device you use for LESEDI"
            why = "Anyone who can unlock the device may be able to open LESEDI while you are signed in."
            mitigation = (
                "Consider signing out when you finish, using a device only you control (a trusted friend's or a "
                "library computer), and using 'Sign out everywhere' if you suspect access."
            )
        severity = "high" if value == Answer.YES else "medium"
        if value == Answer.UNSURE:
            risk += " (you are not sure)"
        findings.append(ShieldFinding(f"shared_{subject}", risk, why, severity, mitigation, "user_reported",
                                      "Update my answers", reverse("shield:assess")))

    if not user.neutral_notifications:
        findings.append(ShieldFinding(
            "previews_not_neutral",
            "Alerts to your contacts include your name",
            "Messages to your contacts show your name. If someone else sees a contact's lock screen, they may learn "
            "that you asked for help.",
            "medium",
            "Turn on neutral alerts so messages say only that something is waiting in LESEDI.",
            "verified", "Change notification setting", settings_url))

    findings.append(ShieldFinding(
        "no_two_step_sign_in",
        "Two-step sign-in is not available yet",
        "Without a second step, anyone who learns your password can sign in as you.",
        "medium",
        "Use a long password you use nowhere else, and use 'Sign out everywhere' after changing it.",
        "verified", "Account security", reverse("accounts:security")))

    contacts = list(
        TrustedContact.objects.filter(owner=user, removed_at__isnull=True).prefetch_related("permissions")
    )
    for contact in contacts:
        active = [p for p in contact.permissions.all() if p.revoked_at is None]
        codes = {p.permission for p in active}
        if Permission.RECEIVE_LOCATION in codes:
            findings.append(ShieldFinding(
                f"location_{contact.pk}",
                f"{contact.name} is allowed to receive a location share",
                "Location sharing is not active in this build, but the permission is saved and would apply when it exists.",
                "low",
                "Remove this permission unless you are sure you want them to be able to receive your location.",
                "inferred", "Review permissions", reverse("circle:contact_permissions", args=[contact.pk])))
        if len(active) >= BROAD_PERMISSION_COUNT:
            findings.append(ShieldFinding(
                f"broad_{contact.pk}",
                f"{contact.name} has many permissions ({len(active)})",
                "The more a person is allowed to do, the more damage it could cause if that person's account or "
                "phone is compromised, or if the relationship changes.",
                "medium",
                "Keep only the permissions this person really needs.",
                "inferred", "Review permissions", reverse("circle:contact_permissions", args=[contact.pk])))

    cutoff = timezone.now() - STALE_AFTER
    stale = ContactPermission.objects.filter(
        contact__owner=user, contact__removed_at__isnull=True, revoked_at__isnull=True, granted_at__lt=cutoff
    ).count()
    if stale:
        findings.append(ShieldFinding(
            "stale_permissions",
            f"{stale} permission(s) have not been reviewed for over 90 days",
            "Relationships and safety needs change. Old permissions can outlive the reason they were given.",
            "low",
            "Open your Safety Circle and confirm each permission is still wanted.",
            "inferred", "Open Safety Circle", circle_url))

    plan = SafetyPlan.objects.filter(owner=user, is_active=True).first()
    if plan is not None:
        destination = plan.safe_destination.strip().casefold()
        if len(destination) >= 4 and destination in plan.emergency_instructions.casefold():
            findings.append(ShieldFinding(
                "destination_in_instructions",
                "Your instructions for responders seem to include your safe destination",
                "Instructions can be seen by contacts you allow. Your safe destination is meant to stay private.",
                "high",
                "Remove the destination from the instructions and keep it in the private field only.",
                "inferred", "Edit plan", reverse("plans:edit")))
        if not plan.responders.filter(role=ResponderRole.BACKUP).exists():
            findings.append(ShieldFinding(
                "no_backup",
                "You have no backup responder",
                "If your first responder cannot be reached, nobody else is arranged to be contacted.",
                "medium",
                "Add a backup from your Safety Circle.",
                "verified", "Choose a backup", reverse("plans:responders")))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.code))
    return findings


def summarise(findings):
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        counts[finding.severity] += 1
    return counts
