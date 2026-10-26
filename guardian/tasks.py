from celery import shared_task

from . import services


@shared_task(name="guardian.process_due_actions")
def process_due_actions():
    """Run by Celery beat every 15 seconds. Escalates activations whose acknowledgement deadline passed."""
    return services.process_due()
