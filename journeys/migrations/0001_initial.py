import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("safety", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Journey",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("destination_label", models.CharField(max_length=120)),
                ("status", models.CharField(
                    choices=[("planned", "Planned, not shared yet"), ("active", "Sharing now"), ("ended", "Ended")],
                    default="planned", max_length=16)),
                ("duration_minutes", models.PositiveSmallIntegerField(default=60)),
                ("checkin_minutes", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("share_until", models.DateTimeField(blank=True, null=True)),
                ("checkin_due_at", models.DateTimeField(blank=True, null=True)),
                ("checkin_confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("checkin_alert_sent_at", models.DateTimeField(blank=True, null=True)),
                ("assistance_requested_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("end_reason", models.CharField(blank=True, max_length=24)),
                ("last_lat", models.FloatField(blank=True, null=True)),
                ("last_lng", models.FloatField(blank=True, null=True)),
                ("last_accuracy_m", models.FloatField(blank=True, null=True)),
                ("last_fix_at", models.DateTimeField(blank=True, null=True)),
                ("owner", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="journeys", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["status", "share_until"], name="journey_status_until_idx")],
            },
        ),
        migrations.CreateModel(
            name="JourneyRecipient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("contact", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="journey_shares", to="safety.trustedcontact")),
                ("journey", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="recipients", to="journeys.journey")),
            ],
            options={
                "ordering": ["added_at"],
                "constraints": [models.UniqueConstraint(fields=("journey", "contact"), name="unique_journey_recipient")],
            },
        ),
        migrations.CreateModel(
            name="JourneyEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=32)),
                ("detail", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("journey", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="events", to="journeys.journey")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
