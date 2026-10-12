import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from games.parties import clock_tick


class Command(BaseCommand):
    help = "Advance durable party deadlines and presence, including when all clients disconnect."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        try:
            while True:
                close_old_connections()
                clock_tick()
                if options["once"]:
                    return
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Party clock stopped.")
