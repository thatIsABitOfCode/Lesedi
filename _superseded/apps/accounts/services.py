"""Account services: data export and deletion."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps import audit

DELETION_GRACE_DAYS = 14


def export_user_data(user):
    """Return everything LESEDI holds about the user as a JSON-serialisable dict.

    Evidence file contents are not included here (only metadata); download
    files from the Evidence Vault or export an evidence pack.
    """
    from apps.evidence.models import Incident
    from apps.guardian.models import GuardianActivation
    from apps.safety_circle.models import TrustedContact
    from apps.safety_plans.models import SafetyPlan

    data = {
        "exported_at": timezone.now().isoformat(),
        "profile": {
            "email": user.email,
            "display_name": user.display_name,
            "phone": user.phone,
            "language": user.language,
            "low_data_mode": user.low_data_mode,
            "neutral_notifications": user.neutral_notifications,
            "role": user.role,
            "joined": user.date_joined.isoformat(),
        },
        "safety_plans": [],
        "trusted_contacts": [],
        "incidents": [],
        "guardian_activations": [],
    }
    for plan in SafetyPlan.objects.filter(owner=user).prefetch_related("versions"):
        data["safety_plans"].append(
            {
                "title": plan.title,
                "active": plan.is_active,
                "version": plan.version,
                "emergency_instructions": plan.emergency_instructions,
                "safe_destination": plan.safe_destination,
                "transport_arrangement": plan.transport_arrangement,
                "essential_documents": plan.essential_documents,
                "versions": [v.snapshot | {"version": v.version} for v in plan.versions.all()],
            }
        )
    for contact in TrustedContact.objects.filter(owner=user).prefetch_related("permissions"):
        data["trusted_contacts"].append(
            {
                "name": contact.name,
                "preferred_channel": contact.preferred_channel,
                "fallback_channel": contact.fallback_channel,
                "removed": contact.removed_at is not None,
                "verified_by_invitation": contact.verified_at is not None,
                "permissions": [
                    {"permission": p.permission, "active": p.revoked_at is None}
                    for p in contact.permissions.all()
                ],
            }
        )
    for incident in Incident.objects.filter(owner=user).prefetch_related("entries", "items"):
        data["incidents"].append(
            {
                "title": incident.title,
                "description": incident.description,
                "occurred_at": incident.occurred_at.isoformat(),
                "timeline": [
                    {"occurred_at": e.occurred_at.isoformat(), "note": e.note} for e in incident.entries.all()
                ],
                "files": [
                    {
                        "name": i.display_name,
                        "sha256_at_upload": i.sha256,
                        "size_bytes": i.size_bytes,
                        "uploaded_at": i.uploaded_at.isoformat(),
                        "deleted": i.deleted_at is not None,
                    }
                    for i in incident.items.all()
                ],
            }
        )
    for activation in GuardianActivation.objects.filter(owner=user).prefetch_related("events"):
        data["guardian_activations"].append(
            {
                "created_at": activation.created_at.isoformat(),
                "state": activation.state,
                "simulated": activation.simulated,
                "events": [{"at": e.created_at.isoformat(), "message": e.message} for e in activation.events.all()],
            }
        )
    audit.record(user, "account.data_exported")
    return data


@transaction.atomic
def request_deletion(user):
    from .models import DataDeletionRequest

    existing = DataDeletionRequest.objects.filter(user=user, status="pending").first()
    if existing:
        return existing
    req = DataDeletionRequest.objects.create(
        user=user, execute_after=timezone.now() + timedelta(days=DELETION_GRACE_DAYS)
    )
    audit.record(user, "account.deletion_requested")
    return req


def cancel_deletion(user):
    from .models import DataDeletionRequest

    count = DataDeletionRequest.objects.filter(user=user, status="pending").update(status="cancelled")
    if count:
        audit.record(user, "account.deletion_cancelled")
    return count


def process_due_deletions(now=None):
    """Permanently delete accounts whose grace period has ended. Returns count.

    Evidence files are removed from storage first. Audit events are kept with
    the actor reference cleared (see docs/POLICY_DRAFTS.md for retention notes
    that need legal review).
    """
    from apps.evidence import storage
    from apps.evidence.models import EvidenceItem

    from .models import DataDeletionRequest

    now = now or timezone.now()
    done = 0
    for req in DataDeletionRequest.objects.filter(status="pending", execute_after__lte=now).select_related("user"):
        user = req.user
        for item in EvidenceItem.objects.filter(incident__owner=user):
            storage.remove(item.storage_key)
        audit.record(None, "account.deleted", None, reason="user_request")
        user.delete()
        done += 1
    return done
