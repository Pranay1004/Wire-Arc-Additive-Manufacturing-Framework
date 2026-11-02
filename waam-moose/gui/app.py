"""
gui/app.py — WAAM MOOSE professional front-end.

Standalone Tkinter GUI for the WAAM-MOOSE thermal backend. Responsibilities:

  * Configure and launch `waam_moose-opt -i <input.i>` with a live, teed
    console stream (same `script`-based unbuffered tee as the framework).
  * Live residual / thermal monitoring (wires `codegen/waam_live.py`).
  * Browse Exodus / CSV outputs and the generated `.i` / `calphad.json`.
  * Light / dark themes, persistent settings.

Self-contained: imports nothing from the FreeFEM framework GUI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

_GUI_DIR = Path(__file__).resolve().parent
if str(_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(_GUI_DIR))

try:
    import tkinter.font as tkfont
except Exception:  # pragma: no cover
    tkfont = None  # type: ignore

try:
    from theme import (
        FONT_TITLE, FONT_SUBTITLE, FONT_SECTION, FONT_LABEL, FONT_ENTRY,
        FONT_CONSOLE, FONT_STATUS, FONT_BTN_RUN, FONT_BTN, FONT_TAB,
        FONT_MONO_SM, FONT_SMALL, FONT_SMALL_BOLD, FONT_UNIT,
        FONT_MONO, FONT_INFO, FONT_TINY, FONT_COMBO,
        apply_os_typography, get_theme, THEMES,
    )
    from tabs.run_tab import RunTab
    from tabs.monitor_tab import MonitorTab
    from tabs.outputs_tab import OutputsTab
    from tabs.settings_tab import SettingsTab
except ImportError:
    from gui.theme import (
        FONT_TITLE, FONT_SUBTITLE, FONT_SECTION, FONT_LABEL, FONT_ENTRY,
        FONT_CONSOLE, FONT_STATUS, FONT_BTN_RUN, FONT_BTN, FONT_TAB,
        FONT_MONO_SM, FONT_SMALL, FONT_SMALL_BOLD, FONT_UNIT,
        FONT_MONO, FONT_INFO, FONT_TINY, FONT_COMBO,
        apply_os_typography, get_theme, THEMES,
    )
    from gui.tabs.run_tab import RunTab
    from gui.tabs.monitor_tab import MonitorTab
    from gui.tabs.outputs_tab import OutputsTab
    from gui.tabs.settings_tab import SettingsTab

APP_TITLE = "WAAM MOOSE — Thermal Backend"
APP_SUBTITLE = "Wire Arc Additive Manufacturing • Goldak heat source • PETSc SNES"


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[@-Z\\-_]", "", text)


class WAAMApp:
    """Main application window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.minsize(1000, 640)

        # OS-aware typography
        self.font_info = apply_os_typography(self.root)

        # Theme state
        self.current_theme = "light"
        self.colors = get_theme(self.current_theme)

        # Runtime state
        self.process: subprocess.Popen | None = None
        self.process_thread: threading.Thread | None = None
        self.running = False
        self.active_run_dir: str | None = None
        self.active_i_path: str | None = None
        self.log_path: str | None = None
        self.csv_path: str | None = None

        # Build UI
        self._build_ui()
        self._apply_theme()
        self._bind_shortcuts()

        # Kick off a settings refresh
        self.root.after(100, self._refresh_from_settings)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        # --- Header ---
        header = ttk.Frame(self.root, style="Header.TFrame")
        header.pack(side="top", fill="x")

        title = ttk.Label(header, text=APP_TITLE, style="Title.TLabel")
        title.pack(side="left", padx=16, pady=(10, 2))
        subtitle = ttk.Label(header, text=APP_SUBTITLE, style="Subtitle.TLabel")
        subtitle.pack(side="left", padx=0, pady=(10, 2))

        # Theme toggle + status pill on right
        right = ttk.Frame(header, style="Header.TFrame")
        right.pack(side="right", padx=16, pady=8)
        self.theme_btn = ttk.Button(
            right, text="☀  Light", style="Ghost.TButton",
            command=self._toggle_theme, width=10
        )
        self.theme_btn.pack(side="right", padx=4)

        self.status_var = tk.StringVar(value="Idle")
        status_pill = ttk.Label(
            right, textvariable=self.status_var, style="Status.TLabel",
            anchor="e", width=14
        )
        status_pill.pack(side="right", padx=4)

        # --- Notebook ---
        self.notebook = ttk.Notebook(self.root, style="TNotebook")
        self.notebook.pack(side="top", fill="both", expand=True)

        self.run_tab = RunTab(self.notebook, self)
        self.monitor_tab = MonitorTab(self.notebook, self)
        self.outputs_tab = OutputsTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)

        self.notebook.add(self.run_tab, text="  Run  ")
        self.notebook.add(self.monitor_tab, text="  Monitor  ")
        self.notebook.add(self.outputs_tab, text="  Outputs  ")
        self.notebook.add(self.settings_tab, text="  Settings  ")

        # --- Bottom status bar ---
        self._build_status_bar()

    def _build_status_bar(self):
        bar = ttk.Frame(self.root, style="StatusBar.TFrame")
        bar.pack(side="bottom", fill="x")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(
            bar, variable=self.progress_var, maximum=100, length=200,
            style="Status.Horizontal.TProgressbar"
        )
        self.progress.pack(side="right", padx=12, pady=6)
        self.progress_label = ttk.Label(
            bar, text="", style="Status.TLabel", anchor="e", width=22
        )
        self.progress_label.pack(side="right", padx=8, pady=6)
        self.msg_var = tk.StringVar(value="Ready")
        ttk.Label(
            bar, textvariable=self.msg_var, style="Status.TLabel", anchor="w"
        ).pack(side="left", padx=12, pady=6)

    # ------------------------------------------------------------------ #
    # Theme
    # ------------------------------------------------------------------ #
    def _apply_theme(self):
        colors = self.colors
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Frame / label styles
        style.configure(".", background=colors["bg"], foreground=colors["text"])
        style.configure("TFrame", background=colors["bg"])
        style.configure("Header.TFrame", background=colors["surface"])
        style.configure("StatusBar.TFrame", background=colors["panel"])

        style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
        style.configure("Title.TLabel", background=colors["surface"],
                        foreground=colors["text"])
        style.configure("Subtitle.TLabel", background=colors["surface"],
                        foreground=colors["text_secondary"])
        style.configure("Status.TLabel", background=colors["panel"],
                        foreground=colors["text"])
        style.configure("StatusBar.TFrame", background=colors["panel"])

        # Buttons
        style.configure("TButton", background=colors["accent"],
                        foreground="white", font=FONT_BTN)
        style.map("TButton",
                  background=[("active", colors["accent_hover"])])
        style.configure("Ghost.TButton", background=colors["panel"],
                        foreground=colors["text"])
        style.map("Ghost.TButton",
                  background=[("active", colors["border"])])

        # Notebook
        style.configure("TNotebook", background=colors["bg"],
                        bordercolor=colors["border"])
        style.configure("TNotebook.Tab", background=colors["panel"],
                        foreground=colors["text_secondary"],
                        font=FONT_TAB, padding=[14, 8])
        style.map("TNotebook.Tab",
                  background=[("selected", colors["surface"])],
                  foreground=[("selected", colors["accent"])])

        # Progressbar
        style.configure("Status.Horizontal.TProgressbar",
                        troughcolor=colors["panel"],
                        background=colors["accent"],
                        bordercolor=colors["border"],
                        lightcolor=colors["accent"],
                        darkcolor=colors["accent"])

        # Console / text widget styling handled per-widget
        self.root.configure(bg=colors["bg"])

        self.theme_btn.configure(text=("☀  Light" if self.current_theme == "light"
                                       else "☾  Dark"))

        # Refresh per-tab canvas/console colors (tabs may not exist yet on
        # the first call from __init__).
        for attr in ("run_tab", "monitor_tab", "outputs_tab"):
            tab = getattr(self, attr, None)
            if tab is not None:
                tab._refresh_colors()

    def _toggle_theme(self):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.colors = get_theme(self.current_theme)
        self._apply_theme()
        self.run_tab._refresh_colors()
        self.monitor_tab._refresh_colors()
        self.outputs_tab._refresh_colors()

    def _bind_shortcuts(self):
        try:
            self.root.bind_all("<Control-Return>", lambda e: self.run_tab._run_simulation())
            self.root.bind_all("<Command-Return>", lambda e: self.run_tab._run_simulation())
            self.root.bind_all("<Escape>", lambda e: self.run_tab._stop_simulation())
        except Exception:
            pass

    def _refresh_from_settings(self):
        # Placeholder for loading persisted settings
        pass

    # ------------------------------------------------------------------ #
    # Process helpers
    # ------------------------------------------------------------------ #
    def set_status(self, text: str):
        self.status_var.set(text)
        self.msg_var.set(text)

    def set_progress(self, value: float, label: str = ""):
        self.progress_var.set(max(0.0, min(100.0, value)))
        if label:
            self.progress_label.set(label)

    def is_running(self) -> bool:
        return self.running and self.process is not None and \
            self.process.poll() is None

    def stop_process(self):
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.running = False
        self.process = None
        self.set_status("Stopped")
        self.set_progress(0.0, "")


def main():
    root = tk.Tk()
    app = WAAMApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
