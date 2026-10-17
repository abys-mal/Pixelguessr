from django.core.management.base import BaseCommand

from library.file_cleanup import drain_file_deletions


class Command(BaseCommand):
    help = "Retry a bounded batch of post-commit private-file deletions."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = drain_file_deletions(limit=max(1, min(options["limit"], 1000)))
        self.stdout.write(
            f"Cleanup complete: {result['completed']} completed; {result['failed']} require retry."
        )
