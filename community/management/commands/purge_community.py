from django.core.management.base import BaseCommand

from community import services


class Command(BaseCommand):
    help = ("Delete rejected or resolved community reports and closed Witness concerns whose retention period "
            "(COMMUNITY_RETENTION_DAYS, default 90) has passed. Run it on a schedule.")

    def handle(self, *args, **options):
        result = services.purge_expired()
        self.stdout.write(self.style.SUCCESS(
            f"Removed {result['reports_and_related']} report-related and {result['concerns']} concern-related records."))
