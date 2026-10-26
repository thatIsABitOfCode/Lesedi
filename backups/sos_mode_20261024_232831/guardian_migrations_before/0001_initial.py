import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATE_CHOICES = [
    ("activated", "Activated"),
    ("alerts_pending", "Preparing alerts"),
    ("awaiting_acknowledgement", "Waiting for acknowledgement"),
    ("escalation_required", "Trying the next responder"),
    ("backup_contacted", "Backup responder notified - waiting"),
    ("acknowledged", "A responder acknowledged"),
    ("escalation_exhausted", "No responder acknowledged"),
    ("resolved", "Resolved"),
    ("cancelled", "Cancelled"),
]

OPEN_STATE_VALUES = [
    "activated",
    "alerts_pending",
    "awaiting_acknowledgement",
    "escalation_required",
    "backup_contacted",
    "acknowledged",
    "escalation_exhausted",
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("safety", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GuardianActivation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("plan_version", models.PositiveIntegerField()),
                ("state", models.CharField(choices=STATE_CHOICES, default="activated", max_length=32)),
                ("idempotency_key", models.CharField(blank=True, max_length=64)),
                ("is_simulation", models.BooleanField(default=True)),
                ("simulate_primary_failure", models.BooleanField(default=False)),
                ("ack_timeout_seconds", models.PositiveIntegerField()),
                ("ack_deadline", models.DateTimeField(blank=True, null=True)),
                ("activated_at", models.DateTimeField()),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="activations",
                        to="safety.safetyplan",
                    ),
                ),
            ],
            options={
                "ordering": ["-activated_at"],
            },
        ),
        migrations.CreateModel(
            name="EmergencyAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rank", models.PositiveSmallIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("done", "Notification submitted"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("detail", models.CharField(blank=True, max_length=200)),
                ("executed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "activation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="actions",
                        to="guardian.guardianactivation",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="safety.trustedcontact",
                    ),
                ),
            ],
            options={
                "ordering": ["rank"],
            },
        ),
        migrations.CreateModel(
            name="ResponderAcknowledgement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("acknowledged_at", models.DateTimeField()),
                (
                    "activation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="acknowledgements",
                        to="guardian.guardianactivation",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="safety.trustedcontact",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="GuardianEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=40)),
                ("message", models.CharField(max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "activation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="guardian.guardianactivation",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="guardianactivation",
            index=models.Index(fields=["state", "ack_deadline"], name="guardian_gu_state_495409_idx"),
        ),
        migrations.AddConstraint(
            model_name="guardianactivation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("state__in", OPEN_STATE_VALUES)),
                fields=("owner",),
                name="one_open_activation_per_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="guardianactivation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("idempotency_key", ""), _negated=True),
                fields=("owner", "idempotency_key"),
                name="unique_activation_idempotency_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="emergencyaction",
            constraint=models.UniqueConstraint(fields=("activation", "rank"), name="unique_action_rank"),
        ),
        migrations.AddConstraint(
            model_name="responderacknowledgement",
            constraint=models.UniqueConstraint(fields=("activation", "contact"), name="one_ack_per_contact"),
        ),
    ]
