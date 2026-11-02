"""
gui/theme.py — WAAM MOOSE GUI theme system.

Self-contained typography / colour palette for the WAAM MOOSE front-end.
Kept independent of the FreeFEM framework GUI so the MOOSE lane can run
standalone.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

try:
    import tkinter.font as tkfont
except Exception:  # pragma: no cover - tkinter always available on target
    tkfont = None  # type: ignore


OS_TYPE = sys.platform
UI_FONT_FAMILY = "Helvetica Neue"
MONO_FONT_FAMILY = "Menlo"


# Module-level font spec tuples (family, size, weight) for direct use in
# widget `font=` kwargs and for the FontCache.
(
    FONT_TITLE,
    FONT_SUBTITLE,
    FONT_SECTION,
    FONT_LABEL,
    FONT_ENTRY,
    FONT_CONSOLE,
    FONT_STATUS,
    FONT_BTN_RUN,
    FONT_BTN,
    FONT_TAB,
    FONT_MONO_SM,
    FONT_SMALL,
    FONT_SMALL_BOLD,
    FONT_UNIT,
    FONT_MONO,
    FONT_INFO,
    FONT_TINY,
    FONT_COMBO,
    FONT_DLG_TITLE,
    FONT_MONO_LG,
) = (
    (UI_FONT_FAMILY, 17, "bold"),
    (UI_FONT_FAMILY, 11),
    (UI_FONT_FAMILY, 11, "bold"),
    (UI_FONT_FAMILY, 10),
    (MONO_FONT_FAMILY, 10),
    (MONO_FONT_FAMILY, 9),
    (UI_FONT_FAMILY, 11, "bold"),
    (UI_FONT_FAMILY, 12, "bold"),
    (UI_FONT_FAMILY, 10),
    (UI_FONT_FAMILY, 10, "bold"),
    (MONO_FONT_FAMILY, 8),
    (UI_FONT_FAMILY, 9),
    (UI_FONT_FAMILY, 9, "bold"),
    (UI_FONT_FAMILY, 9),
    (MONO_FONT_FAMILY, 9),
    (MONO_FONT_FAMILY, 9),
    (MONO_FONT_FAMILY, 8),
    (UI_FONT_FAMILY, 9),
    (UI_FONT_FAMILY, 13, "bold"),
    (MONO_FONT_FAMILY, 11),
)


def apply_os_typography(root: tk.Tk, style=None, verbose: bool = False) -> dict:
    """Best-effort OS font resolution; returns a dict of fallbacks used."""
    families = {
        "darwin": ("Helvetica Neue", "Menlo"),
        "linux": ("DejaVu Sans", "DejaVu Sans Mono"),
        "win32": ("Segoe UI", "Consolas"),
    }.get(sys.platform, ("Helvetica Neue", "Menlo"))

    ui_family, mono_family = families

    scale = {
        "FONT_TITLE":   (ui_family, 17, "bold"),
        "FONT_SUBTITLE":(ui_family, 11),
        "FONT_SECTION": (ui_family, 11, "bold"),
        "FONT_LABEL":   (ui_family, 10),
        "FONT_ENTRY":   (mono_family, 10),
        "FONT_CONSOLE": (mono_family, 9),
        "FONT_STATUS":  (ui_family, 11, "bold"),
        "FONT_BTN_RUN": (ui_family, 12, "bold"),
        "FONT_BTN":     (ui_family, 10),
        "FONT_TAB":     (ui_family, 10, "bold"),
        "FONT_MONO_SM": (mono_family, 8),
        "FONT_SMALL":   (ui_family, 9),
        "FONT_SMALL_BOLD": (ui_family, 9, "bold"),
        "FONT_UNIT":    (ui_family, 9),
        "FONT_MONO":    (mono_family, 9),
        "FONT_INFO":    (mono_family, 9),
        "FONT_TINY":    (mono_family, 8),
        "FONT_COMBO":   (ui_family, 9),
        "FONT_DLG_TITLE":(ui_family, 13, "bold"),
        "FONT_MONO_LG": (mono_family, 11),
    }
    return scale


# --------------------------------------------------------------------------- #
# Colour palettes
# --------------------------------------------------------------------------- #

THEMES = {
    "light": {
        "name": "Light",
        "bg": "#f5f7fa",
        "surface": "#ffffff",
        "panel": "#eef2f6",
        "text": "#1f2937",
        "text_secondary": "#6b7280",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "danger": "#dc2626",
        "danger_hover": "#b91c1c",
        "success": "#059669",
        "success_hover": "#047857",
        "warning": "#d97706",
        "muted": "#9ca3af",
        "border": "#d1d5db",
        "canvas": "#f3f4f6",
        "ink": "#111827",
    },
    "dark": {
        "name": "Dark",
        "bg": "#0f172a",
        "surface": "#1e293b",
        "panel": "#334155",
        "text": "#f8fafc",
        "text_secondary": "#94a3b8",
        "accent": "#3b82f6",
        "accent_hover": "#60a5fa",
        "danger": "#ef4444",
        "danger_hover": "#f87171",
        "success": "#22c55e",
        "success_hover": "#4ade80",
        "warning": "#f59e0b",
        "muted": "#64748b",
        "border": "#475569",
        "canvas": "#0b1120",
        "ink": "#f1f5f9",
    },
}


def get_theme(name: str = "light") -> dict:
    return THEMES.get(name, THEMES["light"])


# --------------------------------------------------------------------------- #
# Font object cache (built once per root)
# --------------------------------------------------------------------------- #

class FontCache:
    """Holds tk.Font objects keyed by the scale keys above."""

    def __init__(self, root: tk.Tk, scale: dict):
        self._fonts: dict[str, tkfont.Font] = {}
        for key, spec in scale.items():
            family, size, *rest = spec
            weight = rest[0] if rest else "normal"
            slant = "roman"
            try:
                self._fonts[key] = tkfont.Font(
                    family=family, size=size, weight=weight, slant=slant
                )
            except Exception:
                self._fonts[key] = tkfont.Font(size=size)

    def __getitem__(self, key: str) -> tkfont.Font:
        return self._fonts[key]

    def get(self, key: str, default=None):
        return self._fonts.get(key, default)
