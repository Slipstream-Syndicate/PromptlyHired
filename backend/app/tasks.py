"""Operational commands.

    python -m app.tasks doctor    # verify every integration really works

The scheduled digest and reminder jobs belonged to the application-tracker
version of this product and were removed with it.
"""

from __future__ import annotations

import sys


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    command = args[0] if args else "doctor"
    if command != "doctor":
        print(f"Unknown task: {command}. Expected: doctor", file=sys.stderr)
        return 2

    from app import doctor

    return doctor.run()


if __name__ == "__main__":
    raise SystemExit(main())
