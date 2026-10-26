from django.core.management.base import BaseCommand

from apps.accounts import services


class Command(BaseCommand):
    help = "Permanently delete accounts whose deletion grace period has ended."

    def handle(self, *args, **options):
        count = services.process_due_deletions()
        self.stdout.write(f"Deleted {count} account(s).")
