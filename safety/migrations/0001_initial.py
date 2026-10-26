import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

CHANNEL_CHOICES = [
    ("sms", "SMS"),
    ("whatsapp", "WhatsApp"),
    ("email", "Email"),
    ("push", "Push notification"),
    ("in_app", "In-app"),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SafetyPlan",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(default="My safety plan", max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "emergency_instructions",
                    models.TextField(
                        blank=True,
                        help_text="What you want an acknowledged responder to know. Only shared with contacts you allow.",
                    ),
                ),
                (
                    "safe_destination",
                    models.TextField(blank=True, help_text="Stored privately. Never included in notifications."),
                ),
                ("transport_notes", models.TextField(blank=True)),
                (
                    "transport_confirmed",
                    models.BooleanField(
                        default=False,
                        help_text="Tick when you have checked this arrangement is really available.",
                    ),
                ),
                ("essential_documents", models.TextField(blank=True)),
                ("checkin_method", models.CharField(blank=True, max_length=120)),
                ("checkin_time", models.TimeField(blank=True, null=True)),
                (
                    "ack_timeout_seconds",
                    models.PositiveIntegerField(
                        default=300,
                        help_text="How long to wait for an acknowledgement before trying the next responder (10-3600 seconds).",
                        validators=[
                            django.core.validators.MinValueValidator(10),
                            django.core.validators.MaxValueValidator(3600),
                        ],
                    ),
                ),
                (
                    "comms_failure_contingency",
                    models.TextField(
                        blank=True, help_text="What should happen if a phone or channel does not work?"
                    ),
                ),
                ("review_date", models.DateField(blank=True, null=True)),
                ("version", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="safety_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="SafetyPlanVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField()),
                ("snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="safety.safetyplan",
                    ),
                ),
            ],
            options={
                "ordering": ["-version"],
            },
        ),
        migrations.CreateModel(
            name="TrustedContact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80)),
                ("relationship", models.CharField(blank=True, max_length=60)),
                ("phone", models.CharField(blank=True, max_length=32)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("preferred_channel", models.CharField(choices=CHANNEL_CHOICES, default="sms", max_length=16)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Added, not yet invited"),
                            ("invited", "Invited"),
                            ("active", "Accepted"),
                            ("revoked", "Removed or declined"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("consented_at", models.DateTimeField(blank=True, null=True)),
                ("owner_confirmed_details", models.BooleanField(default=False)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="trusted_contacts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ContactInvitation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("declined_at", models.DateTimeField(blank=True, null=True)),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invitations",
                        to="safety.trustedcontact",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ResponderAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "rank",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(5),
                        ]
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="safety.trustedcontact",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="responders",
                        to="safety.safetyplan",
                    ),
                ),
            ],
            options={
                "ordering": ["rank"],
            },
        ),
        migrations.CreateModel(
            name="SafetyPlanPermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "permission",
                    models.CharField(
                        choices=[
                            ("receive_alert", "Receive an emergency alert from me"),
                            ("acknowledge_alert", "Acknowledge an alert (confirm they saw it)"),
                            ("receive_instruction", "See the emergency instruction I wrote for them"),
                        ],
                        max_length=32,
                    ),
                ),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="permissions",
                        to="safety.trustedcontact",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="permissions",
                        to="safety.safetyplan",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="safetyplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)), fields=("owner",), name="one_active_plan_per_owner"
            ),
        ),
        migrations.AddConstraint(
            model_name="safetyplanversion",
            constraint=models.UniqueConstraint(fields=("plan", "version"), name="unique_plan_version"),
        ),
        migrations.AddConstraint(
            model_name="responderassignment",
            constraint=models.UniqueConstraint(fields=("plan", "rank"), name="unique_responder_rank"),
        ),
        migrations.AddConstraint(
            model_name="responderassignment",
            constraint=models.UniqueConstraint(fields=("plan", "contact"), name="unique_responder_contact"),
        ),
        migrations.AddIndex(
            model_name="safetyplanpermission",
            index=models.Index(fields=["plan", "contact", "revoked_at"], name="safety_safe_plan_id_e6a5f9_idx"),
        ),
        migrations.AddConstraint(
            model_name="safetyplanpermission",
            constraint=models.UniqueConstraint(
                condition=models.Q(("revoked_at__isnull", True)),
                fields=("plan", "contact", "permission"),
                name="one_active_grant_per_permission",
            ),
        ),
    ]
