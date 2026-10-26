from celery import shared_task

from . import services


@shared_task(name="community.purge_expired")
def purge_expired():
    """Run daily by Celery beat. Deletes rejected/resolved reports and closed concerns past their retention date."""
    return services.purge_expired()
