#!/usr/bin/env python3
"""Development CLI script to create an administrator (ADMIN) account.

Can be run directly from repository root:
    python scripts/create_admin.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "Backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.create_admin import main

if __name__ == "__main__":
    sys.exit(main())
