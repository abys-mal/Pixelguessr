"""Create a local .env with a random secret; preserve any existing configuration."""

import argparse
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--lite",
    action="store_true",
    help="Use SQLite and in-memory services for local development",
)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
destination = root / ".env"
if destination.exists():
    parser.exit(
        message=".env already exists; preserved. Edit USE_SQLITE and LOCAL_SERVICES if needed.\n"
    )
content = (root / ".env.example").read_text(encoding="utf-8")
content = content.replace(
    "dev-replace-with-a-random-secret-before-deployment", secrets.token_urlsafe(64)
)
if args.lite:
    content = content.replace("USE_SQLITE=False", "USE_SQLITE=True").replace(
        "LOCAL_SERVICES=False", "LOCAL_SERVICES=True"
    )
destination.write_text(content, encoding="utf-8", newline="\n")
print("Created .env for local development. Never commit this file.")
