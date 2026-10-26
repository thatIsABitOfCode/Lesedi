from django.conf import settings
from django.db import models

class ListenerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='amani_listener')
    available = models.BooleanField(default=False)
    trained = models.BooleanField(default=False, help_text='Must be approved by a moderator before matching.')
    created_at = models.DateTimeField(auto_now_add=True)

class SupportConnection(models.Model):
    seeker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='amani_support')
    listener = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='amani_listening')
    status = models.CharField(max_length=16, choices=[('pending','Pending'),('active','Active'),('closed','Closed')], default='pending')
    primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['seeker','listener'], name='amani_unique_pair')]

class SupportMessage(models.Model):
    connection = models.ForeignKey(SupportConnection, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField(max_length=2500)
    created_at = models.DateTimeField(auto_now_add=True)

class StorySummary(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='amani_story')
    text = models.TextField(max_length=3000, blank=True)
    share_primary = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
