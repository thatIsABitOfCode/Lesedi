from celery import shared_task

from . import services


@shared_task(name="guardian.process_timeouts")
def process_timeouts():
    return services.process_timeouts()
