"""Operational commands.

    python -m app.tasks doctor    # verify every integration really works

The scheduled digest and reminder jobs belonged to the application-tracker
version of this product and were removed with it.
"""

from __future__ import annotations

import sys


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
    command = args[0] if args else "doctor"
    if command != "doctor":
        print(f"Unknown task: {command}. Expected: doctor", file=sys.stderr)
        return 2

    from app import doctor

    return doctor.run()


if __name__ == "__main__":
    raise SystemExit(main())
