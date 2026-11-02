"""
tests/conftest.py - Pytest configuration for WAAM-MOOSE
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOOSE_ROOT = HERE.parent
if str(MOOSE_ROOT) not in sys.path:
    sys.path.insert(0, str(MOOSE_ROOT))
