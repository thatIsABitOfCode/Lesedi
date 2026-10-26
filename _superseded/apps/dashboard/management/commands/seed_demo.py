import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.dashboard import demo
from apps.shield.models import Answer, ShieldAnswers


class Command(BaseCommand):
    help = "Create fictional demo data (Naledi, Faith, Mapaseka). Simulation mode only."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for the three demo accounts (default: random, printed once).")
        parser.add_argument("--ack-timeout", type=int, default=30, help="Seconds Guardian Mode waits for an acknowledgement.")

    def handle(self, *args, **options):
        if settings.NOTIFICATIONS_MODE != "simulation":
            raise CommandError("Demo data can only be created while NOTIFICATIONS_MODE=simulation.")
        if User.objects.filter(email=f"naledi@{demo.DEMO_DOMAIN}").exists():
            self.stdout.write("Demo data already exists. Nothing changed.")
            return
        password = options["password"] or secrets.token_urlsafe(12)
        world = demo.build_demo_world(password, ack_timeout_seconds=options["ack_timeout"])
        # A hypothetical shared-account risk for SHIELD to find (user-reported).
        ShieldAnswers.objects.update_or_create(
            owner=world.naledi,
            defaults={"shared_account_access": Answer.YES, "shared_device_access": Answer.NO},
        )
        self.stdout.write(self.style.SUCCESS("Fictional demo data created. Nothing real is involved."))
        self.stdout.write(f"  Survivor:        {world.naledi.email}")
        self.stdout.write(f"  Primary contact: {world.faith_user.email}")
        self.stdout.write(f"  Backup contact:  {world.mapaseka_user.email}")
        self.stdout.write(f"  Password (all three): {password}")
        self.stdout.write("Sign in as Naledi, open Guardian Mode, and activate it. Notifications are simulated.")
