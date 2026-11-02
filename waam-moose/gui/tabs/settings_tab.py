"""
gui/tabs/settings_tab.py — Persistent settings.

Stores app paths, theme preference, and console options in
`~/.waam_moose_gui.json` and applies them on startup.
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from theme import (
        FONT_BTN, FONT_LABEL, FONT_MONO_SM, FONT_SECTION, FONT_SMALL,
        FONT_SMALL_BOLD, FONT_TAB, THEMES,
    )
except ImportError:
    from gui.theme import (
        FONT_BTN, FONT_LABEL, FONT_MONO_SM, FONT_SECTION, FONT_SMALL,
        FONT_SMALL_BOLD, FONT_TAB, THEMES,
    )

SETTINGS_PATH = Path.home() / ".waam_moose_gui.json"


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.data: dict = {}
        self._build_ui()
        self.load()
        self._refresh_colors()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def load(self):
        try:
            if SETTINGS_PATH.exists():
                self.data = json.loads(SETTINGS_PATH.read_text())
        except Exception:
            self.data = {}
        self.app_var.set(self.data.get("app_bin", ""))
        self.live_var.set(self.data.get("waam_live", ""))
        self.theme_var.set(self.data.get("theme", "light"))
        self.autoscroll_var.set(bool(self.data.get("autoscroll", True)))
        self.confirm_stop_var.set(bool(self.data.get("confirm_stop", True)))
        # Auto-detect paths when not yet configured
        if not self.app_var.get().strip() or not self.live_var.get().strip():
            self._autodetect()
        # push into app
        self.app.current_theme = self.theme_var.get()
        self.app.colors = THEMES.get(self.theme_var.get(), THEMES["light"])
        self.app.autoscroll = self.autoscroll_var.get()
        self.app.confirm_stop = self.confirm_stop_var.get()

    def save(self):
        self.data = {
            "app_bin": self.app_var.get().strip(),
            "waam_live": self.live_var.get().strip(),
            "theme": self.theme_var.get(),
            "autoscroll": self.autoscroll_var.get(),
            "confirm_stop": self.confirm_stop_var.get(),
        }
        try:
            SETTINGS_PATH.write_text(json.dumps(self.data, indent=2))
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Save failed", str(exc))

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        # --- Paths card ---
        card = ttk.LabelFrame(self, text="Paths", style="Card.TLabelframe")
        card.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="waam_moose-opt", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.app_var = tk.StringVar(value="")
        row = ttk.Frame(card)
        row.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 4))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.app_var,
                  font=FONT_MONO_SM).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_app).pack(side="left", padx=(6, 0))

        ttk.Label(card, text="waam_live.py", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=10, pady=4)
        self.live_var = tk.StringVar(value="")
        row2 = ttk.Frame(card)
        row2.grid(row=1, column=1, sticky="ew", padx=10, pady=4)
        row2.columnconfigure(0, weight=1)
        ttk.Entry(row2, textvariable=self.live_var,
                  font=FONT_MONO_SM).pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="Browse…", style="Ghost.TButton",
                   command=self._browse_live).pack(side="left", padx=(6, 0))

        ttk.Button(card, text="Auto-detect", style="Ghost.TButton",
                   command=self._autodetect).grid(
            row=2, column=1, sticky="e", padx=10, pady=(4, 10))

        # --- Appearance card ---
        card2 = ttk.LabelFrame(self, text="Appearance",
                               style="Card.TLabelframe")
        card2.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        card2.columnconfigure(1, weight=1)

        ttk.Label(card2, text="Theme", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.theme_var = tk.StringVar(value="light")
        theme_row = ttk.Frame(card2)
        theme_row.grid(row=0, column=1, sticky="w", padx=10, pady=(10, 4))
        for name, label in (("light", "☀  Light"), ("dark", "☾  Dark")):
            ttk.Radiobutton(
                theme_row, text=label, value=name,
                variable=self.theme_var, style="TRadiobutton",
                command=self._on_theme_change
            ).pack(side="left", padx=(0, 14))

        ttk.Label(card2, text="Console", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=10, pady=4)
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card2, text="Auto-scroll console",
                        variable=self.autoscroll_var,
                        style="TCheckbutton").grid(
            row=1, column=1, sticky="w", padx=10, pady=4)

        ttk.Label(card2, text="Safety", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=10, pady=(4, 10))
        self.confirm_stop_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card2, text="Confirm before stopping a run",
                        variable=self.confirm_stop_var,
                        style="TCheckbutton").grid(
            row=2, column=1, sticky="w", padx=10, pady=(4, 10))

        # --- Actions ---
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="e", padx=12, pady=(0, 8))
        ttk.Button(bar, text="💾 Save settings", style="TButton",
                   command=self._save_and_apply, width=16).pack(
            side="left", padx=(0, 6))
        ttk.Button(bar, text="↺ Reset", style="Ghost.TButton",
                   command=self._reset, width=10).pack(side="left")

        # --- About ---
        card3 = ttk.LabelFrame(self, text="About", style="Card.TLabelframe")
        card3.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        about = (
            "WAAM MOOSE — Thermal Backend\n"
            "Goldak moving heat source • FreeFEM-parity corrector • "
            "CALPHAD Scheil solidification\n"
            f"Python {sys.version.split()[0]}  •  Tk {tk.TkVersion}  •  "
            f"Platform {sys.platform}"
        )
        ttk.Label(card3, text=about, style="Card.TLabel",
                  justify="left").grid(row=0, column=0, sticky="w",
                                       padx=10, pady=10)

        # --- Hint ---
        hint = ttk.Label(
            self,
            text="Settings are stored in ~/.waam_moose_gui.json and applied "
                 "on every launch.",
            style="Hint.TLabel")
        hint.grid(row=4, column=0, sticky="w", padx=12, pady=(0, 10))

    def _refresh_colors(self):
        colors = self.app.colors
        # ttk widgets restyle via app._apply_theme; nothing widget-specific here.

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def _browse_app(self):
        path = filedialog.askopenfilename(
            title="Select waam_moose executable",
            filetypes=[("Executable", "*waam_moose*"), ("All files", "*")])
        if path:
            self.app_var.set(path)

    def _browse_live(self):
        path = filedialog.askopenfilename(
            title="Select waam_live.py",
            filetypes=[("Python", "*.py"), ("All files", "*")])
        if path:
            self.live_var.set(path)

    def _autodetect(self):
        home = os.environ.get("WAAM_MOOSE_HOME")
        repo_root = Path(__file__).resolve().parent.parent.parent
        candidates = []
        if home:
            candidates.append(Path(home) / "waam_moose" / "waam_moose-opt")
        candidates.append(repo_root / "waam_moose" / "waam_moose-opt")
        candidates.append(repo_root / "waam_moose" / "waam_moose")
        for c in candidates:
            if c.exists() and os.access(str(c), os.X_OK):
                self.app_var.set(str(c))
                break
        live_cands = [
            repo_root / "codegen" / "waam_live.py",
            Path.home() / "Desktop" / "WAAM" / "WAAM-Framework" / "codegen" / "waam_live.py",
        ]
        for c in live_cands:
            if c.exists():
                self.live_var.set(str(c))
                break

    def _on_theme_change(self):
        self.app.current_theme = self.theme_var.get()
        self.app.colors = THEMES.get(self.theme_var.get(), THEMES["light"])
        self.app._apply_theme()
        self.app.run_tab._refresh_colors()
        self.app.monitor_tab._refresh_colors()
        self.app.outputs_tab._refresh_colors()
        self._refresh_colors()

    def _save_and_apply(self):
        self.save()
        # push paths into run tab
        if self.app_var.get().strip():
            self.app.run_tab.app_var.set(self.app_var.get().strip())
        if self.live_var.get().strip():
            self.app.waam_live_path = self.live_var.get().strip()
        self._on_theme_change()
        messagebox.showinfo("Saved", "Settings saved to ~/.waam_moose_gui.json")

    def _reset(self):
        if messagebox.askyesno("Reset", "Reset all settings to defaults?"):
            try:
                if SETTINGS_PATH.exists():
                    SETTINGS_PATH.unlink()
            except Exception:
                pass
            self.data = {}
            self.app_var.set("")
            self.live_var.set("")
            self.theme_var.set("light")
            self.autoscroll_var.set(True)
            self.confirm_stop_var.set(True)
            self._on_theme_change()
