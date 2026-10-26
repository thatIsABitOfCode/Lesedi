from django.core.management.base import BaseCommand

from apps.guardian import services


class Command(BaseCommand):
    help = "Apply acknowledgement timeouts once (useful without Celery beat)."

    def handle(self, *args, **options):
        handled = services.process_timeouts()
        self.stdout.write(f"Processed {handled} activation(s).")
