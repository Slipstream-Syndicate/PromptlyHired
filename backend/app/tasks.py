"""Scheduled jobs and operational commands.

Run from the host scheduler (Render/Railway cron):

    python -m app.tasks digest              # polls upstream, then emails
    python -m app.tasks digest --dry-run    # emails from stored jobs, 0 API calls
    python -m app.tasks reminders           # nudges stale applications, 0 API calls
    python -m app.tasks doctor              # verify every integration really works
    python -m app.tasks doctor --email you@example.com   # ...and send a test email

The digest costs one upstream API call per followed company, so schedule it
weekly on the free plan - not daily.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.db import SessionLocal
from app.services.notifications import run_digest
from app.services.reminders import send_reminders

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

COMMANDS = {"digest", "reminders", "doctor"}


def _flag_value(name: str) -> str | None:
    """Read `--name value` or `--name=value` from argv."""
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    command = args[0] if args else "digest"
    if command not in COMMANDS:
        print(f"Unknown task: {command}. Expected one of: {', '.join(sorted(COMMANDS))}",
              file=sys.stderr)
        return 2

    if command == "doctor":
        from app import doctor

        return doctor.run(send_to=_flag_value("--email"))

    dry_run = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        if command == "reminders":
            # Purely local - reads stored applications, costs no API quota.
            result = send_reminders(db)
        else:
            result = asyncio.run(run_digest(db, dry_run=dry_run))
    finally:
        db.close()

    logger.info("%s complete: %s", command.capitalize(), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
