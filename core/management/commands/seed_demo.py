import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.demo import DEMO_EMAIL, seed_naledi


class Command(BaseCommand):
    help = "Create the fictional Naledi / Faith / Mapaseka demo data (simulation mode only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for the demo account (random if omitted).")

    def handle(self, *args, **opts):
        if settings.LESEDI_NOTIFICATION_MODE != "simulation":
            raise CommandError("Demo data can only be created in simulation mode.")
        if not settings.DEBUG:
            raise CommandError("Demo data can only be created with DJANGO_DEBUG=1 (development).")
        password = opts["password"] or secrets.token_urlsafe(12)
        seed_naledi(password)
        self.stdout.write(self.style.SUCCESS("Demo data ready (fictional people, simulation only)."))
        self.stdout.write(f"Log in at /accounts/login/ as {DEMO_EMAIL}\nPassword: {password}")
