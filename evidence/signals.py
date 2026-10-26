from django.db.models.signals import post_delete
from django.dispatch import receiver

from . import services
from .models import EvidenceItem


@receiver(post_delete, sender=EvidenceItem)
def delete_blob_with_item(sender, instance, **kwargs):
    if instance.storage_key:
        services.delete_blob(instance.storage_key)
