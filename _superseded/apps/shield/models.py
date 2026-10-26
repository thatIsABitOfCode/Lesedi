from django.conf import settings
from django.db import models


class Answer(models.TextChoices):
    YES = "yes", "Yes"
    NO = "no", "No"
    UNSURE = "unsure", "I am not sure"


class ShieldAnswers(models.Model):
    """What the person has told SHIELD about their own situation. These answers
    are *user-reported*: LESEDI cannot check them and never scans a device."""

    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shield_answers")
    shared_account_access = models.CharField(
        max_length=8,
        choices=Answer.choices,
        default=Answer.UNSURE,
        verbose_name="Could someone else sign in to your email, phone or cloud accounts?",
    )
    shared_device_access = models.CharField(
        max_length=8,
        choices=Answer.choices,
        default=Answer.UNSURE,
        verbose_name="Could someone else pick up and unlock the phone or computer you use for LESEDI?",
    )
    recovery_options_reviewed = models.BooleanField(
        default=False,
        verbose_name="I have checked that the recovery email and phone number on my important accounts are only mine",
    )
    updated_at = models.DateTimeField(auto_now=True)
