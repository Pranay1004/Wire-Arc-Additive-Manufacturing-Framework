"""
gui/tabs package initialization.
"""

from __future__ import annotations

import sys
from pathlib import Path

_GUI_DIR = Path(__file__).resolve().parent.parent
if str(_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(_GUI_DIR))
