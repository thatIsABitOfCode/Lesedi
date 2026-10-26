from django.conf import settings
from django.db import models


class ShieldSelfReport(models.Model):
    """The user's own answers. LESEDI cannot check whether they are true or complete."""

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shield_report")
    shared_account_access = models.BooleanField(default=False, verbose_name="Someone else knows or can reset my email, phone or app passwords")
    shared_device = models.BooleanField(default=False, verbose_name="Someone else can unlock or use the phone or computer I use for LESEDI")
    previews_visible = models.BooleanField(default=False, verbose_name="Message previews show on my lock screen")
    location_always_shared = models.BooleanField(default=False, verbose_name="I share my location with people all the time (for example a family-sharing app)")
    suspects_monitoring = models.BooleanField(default=False, verbose_name="I suspect my phone or accounts may be monitored")
    updated_at = models.DateTimeField(auto_now=True)
