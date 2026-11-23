#!/usr/bin/env python3
"""Development CLI script to create a staff (STAFF) account.

Usage:
    python scripts/create_staff.py
    python scripts/create_staff.py --name "Staff Member" --email "staff@example.com"
    python scripts/create_staff.py --name "Staff Member" --email "staff@example.com" --password "securePass123!"
"""

import sys
from pathlib import Path

# Add Backend directory to sys.path so app and scripts packages resolve
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.user import UserRole
from scripts.seed_user import run_seed_cli


def main(argv: list[str] | None = None) -> int:
    return run_seed_cli(role=UserRole.STAFF, role_display="Staff", argv=argv)


if __name__ == "__main__":
    sys.exit(main())
