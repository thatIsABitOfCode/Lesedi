from django.db import models


class Channel(models.TextChoices):
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    PUSH = "push", "Push notification"
    INAPP = "inapp", "In-app alert"


# Channels that need a phone number / an email address on the contact.
NEEDS_PHONE = {Channel.SMS.value, Channel.WHATSAPP.value}
NEEDS_EMAIL = {Channel.EMAIL.value}
