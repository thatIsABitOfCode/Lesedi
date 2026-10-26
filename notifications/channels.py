from django.db import models


class Channel(models.TextChoices):
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    PUSH = "push", "Push notification"
    IN_APP = "in_app", "In-app"
