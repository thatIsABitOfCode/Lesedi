"""Safety plan services: saving with version history, responders, health check."""
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps import audit

from .models import CheckinMethod, ResponderAssignment, ResponderRole, SafetyPlan, SafetyPlanVersion

PLAN_FIELDS = [
    "title",
    "emergency_instructions",
    "safe_destination",
    "transport_arrangement",
    "transport_confirmed",
    "essential_documents",
    "alternative_arrangements",
    "comms_failure_plan",
    "checkin_method",
    "checkin_time",
    "ack_timeout_seconds",
    "auto_escalate_to_backup",
    "review_due",
]


class ResponderError(Exception):
    pass


def snapshot(plan):
    data = {}
    for name in PLAN_FIELDS:
        value = getattr(plan, name)
        data[name] = value.isoformat() if hasattr(value, "isoformat") else value
    data["responders"] = [
        {"contact_id": str(a.contact_id), "contact": a.contact.name, "role": a.role}
        for a in plan.responders.select_related("contact")
    ]
    return data


def _record_version(plan, user, note):
    SafetyPlanVersion.objects.create(plan=plan, version=plan.version, snapshot=snapshot(plan), change_note=note[:200], changed_by=user)


@transaction.atomic
def get_or_create_active_plan(user):
    plan = SafetyPlan.objects.select_for_update().filter(owner=user, is_active=True).first()
    return plan


@transaction.atomic
def save_plan(user, plan, cleaned_data):
    """Create (plan is None) or update a plan, always writing a version snapshot."""
    if plan is None:
        plan = SafetyPlan(owner=user)
        note = "Plan created"
    else:
        plan = SafetyPlan.objects.select_for_update().get(pk=plan.pk, owner=user)
        plan.version += 1
        note = "Plan edited"
    for name in PLAN_FIELDS:
        if name in cleaned_data:
            setattr(plan, name, cleaned_data[name])
    plan.is_active = True
    plan.save()
    _record_version(plan, user, note)
    audit.record(user, "plan.saved", plan, version=plan.version)
    return plan


@transaction.atomic
def mark_reviewed(user, plan):
    plan = SafetyPlan.objects.select_for_update().get(pk=plan.pk, owner=user)
    plan.version += 1
    plan.last_reviewed_at = timezone.now()
    plan.review_due = timezone.localdate() + timedelta(days=90)
    plan.save()
    _record_version(plan, user, "Plan reviewed")
    audit.record(user, "plan.reviewed", plan, version=plan.version)
    return plan


@transaction.atomic
def deactivate(user, plan):
    plan = SafetyPlan.objects.select_for_update().get(pk=plan.pk, owner=user)
    plan.version += 1
    plan.is_active = False
    plan.save()
    _record_version(plan, user, "Plan deactivated")
    audit.record(user, "plan.deactivated", plan)
    return plan


@transaction.atomic
def assign_responder(user, plan, contact, role):
    plan = SafetyPlan.objects.select_for_update().get(pk=plan.pk, owner=user)
    if contact.owner_id != user.id or contact.removed_at is not None:
        raise ResponderError("That contact is not available.")
    if ResponderAssignment.objects.filter(plan=plan, contact=contact).exists():
        raise ResponderError(f"{contact.name} is already on this plan. Remove them first to change their role.")
    if role == ResponderRole.PRIMARY and plan.responders.filter(role=ResponderRole.PRIMARY).exists():
        raise ResponderError("You already have a primary responder. Remove them first to choose someone else.")
    position = plan.responders.filter(role=role).count()
    try:
        with transaction.atomic():
            assignment = ResponderAssignment.objects.create(plan=plan, contact=contact, role=role, position=position)
    except IntegrityError as exc:
        raise ResponderError("That arrangement could not be saved.") from exc
    plan.version += 1
    plan.save(update_fields=["version", "updated_at"])
    _record_version(plan, user, f"{ResponderRole(role).label} added")
    audit.record(user, "plan.responder_added", plan, role=role)
    return assignment


@transaction.atomic
def remove_responder(user, plan, assignment):
    plan = SafetyPlan.objects.select_for_update().get(pk=plan.pk, owner=user)
    role = assignment.role
    assignment.delete()
    plan.version += 1
    plan.save(update_fields=["version", "updated_at"])
    _record_version(plan, user, f"{ResponderRole(role).label} removed")
    audit.record(user, "plan.responder_removed", plan, role=role)


def remove_contact_from_plans(contact, actor):
    """Called when a contact is removed from the Safety Circle."""
    for assignment in list(ResponderAssignment.objects.select_related("plan").filter(contact=contact)):
        plan = assignment.plan
        assignment.delete()
        plan.version += 1
        plan.save(update_fields=["version", "updated_at"])
        _record_version(plan, actor, "A contact was removed from the plan")


# ---------------------------------------------------------------- health check

@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    detail: str
    severity: str  # "attention" (worth fixing soon) or "suggestion" (would help)
    provenance: str  # "user_entered" or "system_checked"
    action_label: str = ""
    action_url: str = ""

    @property
    def provenance_label(self):
        return {
            "user_entered": "Based on what you entered",
            "system_checked": "Checked by LESEDI from your settings",
        }[self.provenance]


def assess_plan_health(plan):
    """Gentle, actionable review. It never judges whether a person is trustworthy:
    'verified' only ever means a contact accepted an invitation from their own account."""
    from apps.safety_circle import services as circle
    from apps.safety_circle.models import Permission

    findings = []
    circle_url = reverse("circle:list")
    responders_url = reverse("plans:responders")
    plan_url = reverse("plans:edit")

    assignments = list(plan.responders.select_related("contact"))
    primaries = [a for a in assignments if a.role == ResponderRole.PRIMARY]
    backups = [a for a in assignments if a.role == ResponderRole.BACKUP]

    if not primaries:
        findings.append(Finding(
            "no_primary", "No primary responder yet",
            "Guardian Mode needs at least one person to contact first. Choose someone from your Safety Circle.",
            "attention", "system_checked", "Choose a responder", responders_url))
    if not backups:
        findings.append(Finding(
            "no_backup", "No backup responder yet",
            "If your primary responder cannot be reached, there is nobody for LESEDI to try next.",
            "attention", "system_checked", "Add a backup", responders_url))

    for a in assignments:
        contact = a.contact
        who = contact.name
        if not circle.has_permission(contact, Permission.RECEIVE_ALERT):
            findings.append(Finding(
                f"not_authorised_{contact.pk}", f"{who} cannot receive alerts yet",
                f"{who} is on your plan, but you have not given them permission to receive an alert, so LESEDI would not contact them.",
                "attention", "system_checked", "Review permissions", reverse("circle:contact_permissions", args=[contact.pk])))
        if a.role == ResponderRole.BACKUP and not circle.has_permission(contact, Permission.BACKUP_RESPONDER):
            findings.append(Finding(
                f"backup_not_authorised_{contact.pk}", f"{who} is not yet allowed to act as your backup",
                "Backups need the 'backup responder' permission before LESEDI will contact them.",
                "attention", "system_checked", "Review permissions", reverse("circle:contact_permissions", args=[contact.pk])))
        if not contact.is_verified:
            findings.append(Finding(
                f"unverified_{contact.pk}", f"LESEDI has not confirmed {who}'s details",
                f"The contact details for {who} are what you typed in. Inviting them lets them confirm with their own account. "
                "This confirms the account, not anything else about the person.",
                "suggestion", "system_checked", "Send an invitation", circle_url))
        if not contact.fallback_channel:
            findings.append(Finding(
                f"no_fallback_{contact.pk}", f"No second way to reach {who}",
                "If the first channel fails, LESEDI has no other way to try them.",
                "suggestion", "system_checked", "Add a backup channel", reverse("circle:contact_edit", args=[contact.pk])))

    if not plan.transport_arrangement:
        findings.append(Finding(
            "no_transport", "No transport arrangement noted",
            "Thinking about how you would get somewhere safe can help, if and when it feels right.",
            "suggestion", "user_entered", "Add transport details", plan_url))
    elif not plan.transport_confirmed:
        findings.append(Finding(
            "transport_unconfirmed", "Transport arrangement not confirmed",
            "You noted an arrangement but have not marked it as confirmed with whoever is helping.",
            "suggestion", "user_entered", "Update plan", plan_url))
    if plan.checkin_method == CheckinMethod.NONE:
        findings.append(Finding(
            "no_checkin", "No check-in method chosen",
            "A regular check-in can help someone notice if something is wrong. LESEDI stores your preference "
            "but does not yet send scheduled check-ins itself.",
            "suggestion", "user_entered", "Choose a method", plan_url))
    if not plan.emergency_instructions.strip():
        findings.append(Finding(
            "no_instructions", "No instructions for responders",
            "Responders you approve can see short instructions during an alert. Without them, they will not know what you would like.",
            "suggestion", "user_entered", "Write instructions", plan_url))
    if not plan.comms_failure_plan.strip():
        findings.append(Finding(
            "no_comms_plan", "No plan for when phones or data are unavailable",
            "LESEDI cannot send an alert from a device that is off or offline. A fallback can be as simple as a neighbour or a code word.",
            "suggestion", "user_entered", "Add a fallback", plan_url))
    if backups and not plan.auto_escalate_to_backup:
        findings.append(Finding(
            "auto_escalation_off", "Backup will not be contacted automatically",
            "If your primary responder does not acknowledge, LESEDI will wait for you to decide. "
            "You can authorise automatic escalation in your plan if you would like that.",
            "suggestion", "user_entered", "Review escalation", plan_url))

    today = timezone.localdate()
    if plan.review_due < today:
        findings.append(Finding(
            "review_overdue", "Your plan is due for a review",
            "Arrangements change. A quick review keeps the plan reliable.",
            "attention", "system_checked", "Review now", reverse("plans:health")))
    elif plan.review_due <= today + timedelta(days=14):
        findings.append(Finding(
            "review_soon", "Your plan review is coming up", f"Review due {plan.review_due:%d %B %Y}.",
            "suggestion", "system_checked", "Review now", reverse("plans:health")))
    return findings
