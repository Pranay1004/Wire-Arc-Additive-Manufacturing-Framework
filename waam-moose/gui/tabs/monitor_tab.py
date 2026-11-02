"""
gui/tabs/monitor_tab.py — Live residual monitor integration.

Wires `codegen/waam_live.py` (pyFoam-style live residual plotter) into the GUI:

  * Select a MOOSE console log.
  * Launch `waam_live.py --log <log> --plot` in a subprocess → opens a
    matplotlib dashboard (residual history per timestep, worst-residual per
    step, tmin/tmax thermal envelope).
  * Launch in ASCII mode for a live terminal-style table.
  * Show the last step / time / residual parsed from the log.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    from theme import (
        FONT_BTN, FONT_CONSOLE, FONT_ENTRY, FONT_LABEL, FONT_MONO_SM,
        FONT_SECTION, FONT_SMALL, FONT_TAB,
    )
except ImportError:
    from gui.theme import (
        FONT_BTN, FONT_CONSOLE, FONT_ENTRY, FONT_LABEL, FONT_MONO_SM,
        FONT_SECTION, FONT_SMALL, FONT_TAB,
    )

RE_STEP = re.compile(
    r"Time Step\s+(\d+),\s*time\s*=\s*([0-9.eE+\-]+)"
    r"(?:,\s*dt\s*=\s*([0-9.eE+\-]+))?"
)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[@-Z\\-_]", "", text)


class MonitorTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._proc = None
        self._build_ui()
        self._refresh_colors()
        self._poll_id = None
        self._start_poll()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ---- Log selection ----
        card = ttk.LabelFrame(self, text="Live residual monitor",
                              style="Card.TLabelframe")
        card.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="MOOSE console log", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.log_var = tk.StringVar(value="")
        log_row = ttk.Frame(card)
        log_row.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 4))
        log_row.columnconfigure(0, weight=1)
        self.log_entry = ttk.Entry(log_row, textvariable=self.log_var,
                                   font=FONT_ENTRY)
        self.log_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(log_row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_log).pack(side="left", padx=(6, 0))
        ttk.Button(log_row, text="Use run dir log",
                   style="Ghost.TButton",
                   command=self._use_run_log).pack(side="left", padx=(6, 0))

        # ---- Actions ----
        bar = ttk.Frame(card)
        bar.grid(row=1, column=1, sticky="e", padx=10, pady=(4, 10))
        self.plot_btn = ttk.Button(bar, text="📊 Open live plot window",
                                   style="TButton", command=self._launch_plot,
                                   width=22)
        self.plot_btn.pack(side="left", padx=(0, 6))
        self.ascii_btn = ttk.Button(bar, text="🖥  ASCII live table",
                                    style="Ghost.TButton",
                                    command=self._launch_ascii, width=18)
        self.ascii_btn.pack(side="left")

        # ---- Status ----
        self.status_var = tk.StringVar(value="No log selected")
        ttk.Label(card, textvariable=self.status_var, style="Status.TLabel",
                  anchor="w").grid(row=2, column=0, columnspan=2,
                                   sticky="ew", padx=10, pady=(0, 10))

        # ---- Live output (small console) ----
        ttk.Label(self, text="Monitor output", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=(6, 2))
        self.console = scrolledtext.ScrolledText(
            self, wrap="none", font=FONT_CONSOLE, height=14,
            padx=8, pady=6, state="disabled"
        )
        self.console.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 10))

    def _refresh_colors(self):
        colors = self.app.colors
        self.console.configure(
            background=colors["canvas"], foreground=colors["ink"],
            insertbackground=colors["ink"], selectbackground=colors["accent"],
            selectforeground="white")

    # ------------------------------------------------------------------ #
    # Log selection
    # ------------------------------------------------------------------ #
    def _browse_log(self):
        path = filedialog.askopenfilename(
            title="Select MOOSE console log",
            filetypes=[("Log files", "*.log"), ("All files", "*")])
        if path:
            self.log_var.set(path)

    def _use_run_log(self):
        # Prefer an explicit path from an active run, then the run dir.
        candidates = []
        if self.app.log_path:
            candidates.append(Path(self.app.log_path))
        if self.app.active_run_dir:
            candidates.append(Path(self.app.active_run_dir) / "waam_moose.log")
        run_dir = getattr(self.app.run_tab, "dir_var", None)
        if run_dir is not None and run_dir.get().strip():
            candidates.append(Path(run_dir.get().strip()) / "waam_moose.log")
        for p in candidates:
            if p.exists():
                self.log_var.set(str(p))
                return
        messagebox.showinfo("No log",
                            "No run directory log found. Browse for one.")

    # ------------------------------------------------------------------ #
    # Launch monitor
    # ------------------------------------------------------------------ #
    def _resolve_waam_live(self) -> str | None:
        # codegen/waam_live.py relative to this file's repo root
        here = Path(__file__).resolve()
        repo_root = here.parent.parent.parent  # gui/tabs/ -> repo root
        cand = repo_root / "codegen" / "waam_live.py"
        if cand.exists():
            return str(cand)
        # fallback: sibling of framework
        cand2 = Path.home() / "Desktop" / "WAAM" / "WAAM-Framework" / "codegen" / "waam_live.py"
        if cand2.exists():
            return str(cand2)
        return None

    def _launch(self, extra_args):
        log = self.log_var.get().strip()
        if not log or not Path(log).exists():
            messagebox.showerror("No log", "Select an existing console log.")
            return
        waam_live = self._resolve_waam_live()
        if not waam_live:
            messagebox.showerror("Not found",
                                 "codegen/waam_live.py not found.")
            return
        exe = sys.executable
        cmd = [exe, waam_live, "--log", log, *extra_args]
        self._append_console(f"$ {' '.join(cmd)}\n\n")
        self._set_buttons(running=True)

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, cwd=str(Path(waam_live).parent.parent)
                )
                self._proc = proc
                for raw in proc.stdout:
                    clean = _strip_ansi(raw.replace("\r", ""))
                    while clean and ord(clean[0]) < 32 and clean[0] not in "\n\t":
                        clean = clean[1:]
                    if clean:
                        self.app.root.after(0, self._append_console, clean)
                proc.wait()
            except Exception as exc:  # pragma: no cover
                self.app.root.after(0, lambda: messagebox.showerror("Launch failed", str(exc)))
            finally:
                self.app.root.after(0, self._set_buttons, False)
                self._proc = None

        threading.Thread(target=worker, daemon=True).start()

    def _launch_plot(self):
        self._launch(["--plot"])

    def _launch_ascii(self):
        self._launch(["--ascii"])

    def _set_buttons(self, running: bool):
        state = "disabled" if running else "normal"
        self.plot_btn.configure(state=state)
        self.ascii_btn.configure(state=state)

    def _stop_monitor(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._set_buttons(False)

    # ------------------------------------------------------------------ #
    # Poll for live status (step / time / residual)
    # ------------------------------------------------------------------ #
    def _start_poll(self):
        self._poll_status()
        self._poll_id = self.after(1500, self._start_poll)

    def _poll_status(self):
        log = self.log_var.get().strip()
        if not log or not Path(log).exists():
            return
        try:
            text = Path(log).read_text(errors="ignore")
        except Exception:
            return
        lines = text.splitlines()
        step = time_ = dt = None
        for line in reversed(lines[-200:]):
            m = RE_STEP.search(line)
            if m:
                step = int(m.group(1))
                time_ = float(m.group(2))
                dt = float(m.group(3)) if m.group(3) else 0.0
                break
        if step is not None:
            self.status_var.set(
                f"Step {step}  t = {time_:.6f} s  dt = {dt:.6f} s  (log: {Path(log).name})"
            )
        else:
            self.status_var.set(f"Waiting for first step…  ({Path(log).name})")

    def _append_console(self, text: str):
        self.console.configure(state="normal")
        self.console.insert("end", text)
        self.console.see("end")
        self.console.configure(state="disabled")

    def destroy(self):
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
        self._stop_monitor()
        super().destroy()
