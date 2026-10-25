"""Start the development backend, optionally listening on the LAN (PowerShell friendly)."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan", action="store_true", help="Listen on 0.0.0.0 instead of loopback")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.conf import settings
    from django.core.management import execute_from_command_line

    if not settings.DEBUG:
        parser.error("This helper requires DEBUG=True and is only for local development.")
    execute_from_command_line(
        ["manage.py", "runserver", f"{'0.0.0.0' if args.lan else '127.0.0.1'}:{args.port}"]
    )


if __name__ == "__main__":
    main()
