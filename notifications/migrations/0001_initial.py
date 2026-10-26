import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("guardian", "0001_initial"),
        ("safety", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("sms", "SMS"),
                            ("whatsapp", "WhatsApp"),
                            ("email", "Email"),
                            ("push", "Push notification"),
                            ("in_app", "In-app"),
                        ],
                        max_length=16,
                    ),
                ),
                ("kind", models.CharField(default="guardian_alert", max_length=32)),
                ("attempt", models.PositiveSmallIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("submitted", "Submitted to provider"),
                            ("delivered", "Delivered (provider-confirmed)"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("is_simulated", models.BooleanField(default=True)),
                ("provider", models.CharField(default="simulation", max_length=32)),
                ("provider_message_id", models.CharField(blank=True, max_length=80)),
                ("error", models.CharField(blank=True, max_length=200)),
                ("body_preview", models.TextField(blank=True)),
                ("queued_at", models.DateTimeField(auto_now_add=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "activation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="guardian.guardianactivation",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="safety.trustedcontact",
                    ),
                ),
            ],
            options={
                "ordering": ["queued_at"],
            },
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(fields=["activation", "contact"], name="notificatio_activat_04dcdf_idx"),
        ),
    ]
