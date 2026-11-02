"""
gui/tabs/run_tab.py — Configure and launch `waam_moose-opt`.

Features:
  * Pick the generated `.i` input and the run directory.
  * Auto-discover the `waam_moose-opt` executable (WAAM_MOOSE_HOME or
    sibling of the framework checkout).
  * Launch with a live, unbuffered console stream teed to a log file
    (pty/`script` trick on macOS/Linux to defeat block buffering).
  * Parse `Time Step N, time = T, dt = D` for live progress.
  * Run / Stop, clear console, open log / run folder.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    from theme import (
        FONT_BTN, FONT_BTN_RUN, FONT_CONSOLE, FONT_ENTRY, FONT_LABEL,
        FONT_MONO_SM, FONT_SECTION, FONT_SMALL, FONT_SMALL_BOLD, FONT_TAB,
        FONT_UNIT, get_theme,
    )
except ImportError:
    from gui.theme import (
        FONT_BTN, FONT_BTN_RUN, FONT_CONSOLE, FONT_ENTRY, FONT_LABEL,
        FONT_MONO_SM, FONT_SECTION, FONT_SMALL, FONT_SMALL_BOLD, FONT_TAB,
        FONT_UNIT, get_theme,
    )


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[@-Z\\-_]", "", text)


class RunTab(ttk.Frame):
    """Configure + execute tab."""

    STEP_RE = re.compile(r"Time Step\s+(\d+),\s*time\s*=\s*([0-9.eE+\-]+)"
                         r"(?:,\s*dt\s*=\s*([0-9.eE+\-]+))?")
    END_RE = re.compile(r"Finished Executing")

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()
        self._discover_executable()
        self._refresh_colors()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # ---- Autonomous STL Pipeline Card ----
        card_stl = ttk.LabelFrame(self, text="Autonomous CAD / STL Pipeline (End-to-End)", style="Card.TLabelframe")
        card_stl.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        card_stl.columnconfigure(1, weight=1)

        ttk.Label(card_stl, text="CAD STL / STEP", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.stl_var = tk.StringVar(value="")
        repo_root = Path(__file__).resolve().parent.parent.parent
        default_stl = repo_root / "test_stl" / "z.stl"
        if default_stl.exists():
            self.stl_var.set(str(default_stl))
        stl_row = ttk.Frame(card_stl)
        stl_row.grid(row=0, column=1, sticky="ew", padx=10, pady=(8, 4))
        stl_row.columnconfigure(0, weight=1)
        self.stl_entry = ttk.Entry(stl_row, textvariable=self.stl_var, font=FONT_ENTRY)
        self.stl_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(stl_row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_stl).pack(side="left", padx=(6, 0))

        # Parameters & Toggles row
        param_row = ttk.Frame(card_stl)
        param_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 8))
        
        ttk.Label(param_row, text="Layer [mm]:", style="Card.TLabel").pack(side="left", padx=(0, 4))
        self.lh_var = tk.StringVar(value="3.0")
        ttk.Entry(param_row, textvariable=self.lh_var, width=5, font=FONT_ENTRY).pack(side="left", padx=(0, 10))

        ttk.Label(param_row, text="Bead [mm]:", style="Card.TLabel").pack(side="left", padx=(0, 4))
        self.bw_var = tk.StringVar(value="8.0")
        ttk.Entry(param_row, textvariable=self.bw_var, width=5, font=FONT_ENTRY).pack(side="left", padx=(0, 10))

        ttk.Label(param_row, text="Substrate [mm]:", style="Card.TLabel").pack(side="left", padx=(0, 4))
        self.hz_var = tk.StringVar(value="5.0")
        ttk.Entry(param_row, textvariable=self.hz_var, width=5, font=FONT_ENTRY).pack(side="left", padx=(0, 14))

        self.mech_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(param_row, text="J2 Mechanics", variable=self.mech_var,
                        style="TCheckbutton").pack(side="left", padx=(0, 10))

        self.uva_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(param_row, text="Ultrasonic UVA", variable=self.uva_var,
                        style="TCheckbutton").pack(side="left", padx=(0, 14))

        self.stl_run_btn = ttk.Button(param_row, text="🚀  Run STL Build",
                                      style="TButton", command=self._run_stl_pipeline)
        self.stl_run_btn.pack(side="right")

        # ---- Configuration card ----
        card = ttk.LabelFrame(self, text="Manual Input Deck (.i) Runner", style="Card.TLabelframe")
        card.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 8))
        card.columnconfigure(1, weight=1)

        # App binary
        ttk.Label(card, text="Application", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(6, 4))
        self.app_var = tk.StringVar(value="")
        app_row = ttk.Frame(card)
        app_row.grid(row=0, column=1, sticky="ew", padx=10, pady=(6, 4))
        app_row.columnconfigure(0, weight=1)
        self.app_entry = ttk.Entry(app_row, textvariable=self.app_var,
                                   font=FONT_ENTRY)
        self.app_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(app_row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_app).pack(side="left", padx=(6, 0))

        # Input .i
        ttk.Label(card, text="Input file (.i)", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=10, pady=4)
        self.i_var = tk.StringVar(value="")
        i_row = ttk.Frame(card)
        i_row.grid(row=1, column=1, sticky="ew", padx=10, pady=4)
        i_row.columnconfigure(0, weight=1)
        self.i_entry = ttk.Entry(i_row, textvariable=self.i_var,
                                 font=FONT_ENTRY)
        self.i_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(i_row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_i).pack(side="left", padx=(6, 0))

        # Run directory
        ttk.Label(card, text="Run directory", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=10, pady=(4, 6))
        self.dir_var = tk.StringVar(value="")
        d_row = ttk.Frame(card)
        d_row.grid(row=2, column=1, sticky="ew", padx=10, pady=(4, 6))
        d_row.columnconfigure(0, weight=1)
        self.dir_entry = ttk.Entry(d_row, textvariable=self.dir_var,
                                   font=FONT_ENTRY)
        self.dir_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(d_row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_dir).pack(side="left", padx=(6, 0))

        # ---- Action bar ----
        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        actions.columnconfigure(1, weight=1)

        self.recover_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="Recover from checkpoint",
                        variable=self.recover_var,
                        style="TCheckbutton").pack(side="left", padx=(0, 12))
        self.run_btn = ttk.Button(actions, text="▶  Run Solver",
                                  style="TButton", command=self._run_simulation,
                                  width=14)
        self.run_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(actions, text="⏹  Stop",
                                   style="Ghost.TButton",
                                   command=self._stop_simulation,
                                   width=14, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="🗑  Clear console",
                   style="Ghost.TButton", command=self._clear_console,
                   width=14).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="📂 Open run folder",
                   style="Ghost.TButton", command=self._open_run_folder,
                   width=14).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="📄 Open log file",
                   style="Ghost.TButton", command=self._open_log,
                   width=14).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="📑 View Report",
                   style="Ghost.TButton", command=self._view_report,
                   width=14).pack(side="left")

        # ---- Console ----
        ttk.Label(self, text="Console output", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", padx=12, pady=(4, 2))
        self.console = scrolledtext.ScrolledText(
            self, wrap="none", font=FONT_CONSOLE,
            height=20, padx=8, pady=6, state="disabled"
        )
        self.console.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 10))

    def _refresh_colors(self):
        colors = self.app.colors
        self.console.configure(
            background=colors["canvas"], foreground=colors["ink"],
            insertbackground=colors["ink"], selectbackground=colors["accent"],
            selectforeground="white"
        )

    # ------------------------------------------------------------------ #
    # Discovery / browse
    # ------------------------------------------------------------------ #
    def _discover_executable(self):
        # Priority: explicit WAAM_MOOSE_HOME, then sibling of this checkout.
        home = os.environ.get("WAAM_MOOSE_HOME")
        candidates = []
        if home:
            candidates.append(Path(home) / "waam_moose" / "waam_moose-opt")
        # this file: <repo>/waam_moose/gui/tabs/run_tab.py -> <repo>
        repo_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(repo_root / "waam_moose" / "waam_moose-opt")
        candidates.append(repo_root / "waam_moose" / "waam_moose")
        for c in candidates:
            if c.exists() and os.access(str(c), os.X_OK):
                self.app_var.set(str(c))
                return
        # leave blank; user can browse

    def _browse_app(self):
        path = filedialog.askopenfilename(
            title="Select waam_moose executable",
            filetypes=[("Executable", "*waam_moose*"), ("All files", "*")]
        )
        if path:
            self.app_var.set(path)

    def _browse_i(self):
        path = filedialog.askopenfilename(
            title="Select MOOSE input file",
            filetypes=[("MOOSE input", "*.i"), ("All files", "*")]
        )
        if path:
            self.i_var.set(path)
            # Derive run directory from the input's parent
            p = Path(path)
            if not self.dir_var.get():
                self.dir_var.set(str(p.parent))

    def _browse_dir(self):
        path = filedialog.askdirectory(title="Select run directory")
        if path:
            self.dir_var.set(path)

    def _browse_stl(self):
        path = filedialog.askopenfilename(
            title="Select CAD STL / STEP file",
            filetypes=[("CAD files", "*.stl *.step *.stp"), ("All files", "*")]
        )
        if path:
            self.stl_var.set(path)

    def _view_report(self):
        d_str = self.dir_var.get().strip() or self.app.active_run_dir
        if not d_str or not Path(d_str).exists():
            messagebox.showerror("No run dir", "Select or run a simulation first.")
            return
        d = Path(d_str)
        report = d / "report.html"
        if not report.exists():
            report = d.parent / "report.html"
        if not report.exists():
            report = d / "moose" / "report.html"
        if not report.exists():
            try:
                from postprocess.report_generator import generate_report
                report = generate_report(d)
            except Exception as ex:
                messagebox.showerror("Report Error", f"Could not generate report: {ex}")
                return
        if report and report.exists():
            import webbrowser
            webbrowser.open(report.as_uri())

    def _run_stl_pipeline(self):
        if self.app.is_running():
            return
        stl_path = self.stl_var.get().strip()
        if not stl_path or not Path(stl_path).exists():
            messagebox.showerror("Invalid STL", "Select a valid CAD STL/STEP file.")
            return

        lh = float(self.lh_var.get().strip() or 3.0)
        bw = float(self.bw_var.get().strip() or 8.0)
        hz = float(self.hz_var.get().strip() or 5.0)
        mech = bool(self.mech_var.get())
        uva = bool(self.uva_var.get())

        repo_root = Path(__file__).resolve().parent.parent.parent
        run_py = repo_root / "run.py"

        cmd = [sys.executable, str(run_py), "--stl", str(stl_path),
               "--layer-height", str(lh), "--bead-width", str(bw),
               "--hz-base-mm", str(hz)]
        if mech:
            cmd.append("--mechanical")
        if uva:
            cmd.append("--ultrasonic")

        self.running = True
        self.app.running = True
        self.run_btn.configure(state="disabled")
        self.stl_run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.app.set_status("Running Autonomous STL Build…")
        self.app.set_progress(0.0, "Slicing & Meshing")
        self._append_console(f"$ {' '.join(cmd)}\n\n")

        def worker():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True,
                                       bufsize=1)
                self.app.process = proc
                for raw in proc.stdout:
                    clean = _strip_ansi(raw.replace("\r", ""))
                    while clean and ord(clean[0]) < 32 and clean[0] not in "\n\t":
                        clean = clean[1:]
                    if clean:
                        self.app.root.after(0, self._append_console, clean)
                        self.app.root.after(0, self._parse_line, clean)
                proc.wait()
            except Exception as exc:
                self.app.root.after(0, self._append_console, f"\nERROR: {exc}\n")
            finally:
                self.app.root.after(0, self._finish_stl_run)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_stl_run(self):
        self.running = False
        self.app.running = False
        self.run_btn.configure(state="normal")
        self.stl_run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.app.set_status("Build Finished")
        self.app.set_progress(100.0, "Finished")
        self._append_console("\n[Autonomous STL Build Completed]\n")

    # ------------------------------------------------------------------ #
    # Run / stop
    # ------------------------------------------------------------------ #
    def _run_simulation(self):
        if self.app.is_running():
            return

        app_bin = self.app_var.get().strip()
        i_file = self.i_var.get().strip()
        run_dir = self.dir_var.get().strip()

        if not app_bin or not Path(app_bin).exists():
            messagebox.showerror("Invalid application",
                                 "Point to a valid waam_moose executable.")
            return
        if not i_file or not Path(i_file).exists():
            messagebox.showerror("Invalid input file",
                                 "Select a valid .i input file.")
            return
        if not run_dir:
            run_dir = str(Path(i_file).parent)
            self.dir_var.set(run_dir)
        Path(run_dir).mkdir(parents=True, exist_ok=True)

        self.app.active_i_path = i_file
        self.app.active_run_dir = run_dir
        self.app.log_path = str(Path(run_dir) / "waam_moose.log")
        self.app.csv_path = str(Path(run_dir) / "waam_moose_out.csv")
        self._recover = bool(self.recover_var.get())

        self.running = True
        self.app.running = True
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.app.set_status("Running…")
        self.app.set_progress(0.0, "Starting")
        self._append_console(f"$ {app_bin} -i {i_file}\n  cwd: {run_dir}\n\n")

        thread = threading.Thread(target=self._run_thread, daemon=True)
        thread.start()
        self.app.process_thread = thread

    def _run_thread(self):
        app_bin = self.app_var.get().strip()
        i_file = self.i_var.get().strip()
        run_dir = self.dir_var.get().strip()

        Path(run_dir).mkdir(parents=True, exist_ok=True)
        log_path = self.app.log_path

        # Build the command; use `script` pty on macOS/Linux for unbuffered tee.
        raw_cmd = [str(app_bin), "-i", str(i_file)]
        if getattr(self, "_recover", False):
            raw_cmd = raw_cmd + ["--recover"]
        cmd = raw_cmd
        use_script = (shutil.which("script") is not None
                      and sys.platform != "win32")
        if use_script:
            if sys.platform == "darwin":
                exec_cmd = ["script", "-q", "/dev/null"] + [str(c) for c in cmd]
            else:
                joined = " ".join(
                    f'"{c}"' if " " in str(c) else str(c) for c in cmd
                )
                exec_cmd = ["script", "-q", "-c", joined, "/dev/null"]
        else:
            exec_cmd = [str(c) for c in cmd]

        try:
            self.app.process = subprocess.Popen(
                exec_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=run_dir,
                bufsize=1,
            )
        except Exception as exc:  # pragma: no cover
            self.app.root.after(0, lambda: messagebox.showerror(
                "Launch failed", str(exc)))
            self._finish_run()
            return

        # Mirror to log file and console.
        with open(log_path, "w", encoding="utf-8", errors="ignore") as log_f:
            log_f.write(f"{'='*72}\n")
            log_f.write(f"EXECUTION: {' '.join(str(c) for c in exec_cmd)}\n")
            log_f.write(f"CWD:       {run_dir}\n")
            log_f.write(f"{'='*72}\n\n")
            log_f.flush()

            try:
                for raw in self.app.process.stdout:
                    clean = _strip_ansi(raw.replace("\r", ""))
                    # Strip leading control chars except newline/tab
                    while clean and ord(clean[0]) < 32 and clean[0] not in "\n\t":
                        clean = clean[1:]
                    if clean:
                        self.app.root.after(0, self._append_console, clean)
                        self.app.root.after(0, self._parse_line, clean)
                        log_f.write(clean)
                        log_f.flush()
            except Exception:
                pass

            self.app.process.wait()

        self.app.root.after(0, self._finish_run)

    def _parse_line(self, line: str):
        m = self.STEP_RE.search(line)
        if m:
            step = int(m.group(1))
            t = float(m.group(2))
            dt = float(m.group(3)) if m.group(3) else 0.0
            self.app.set_status(f"Step {step}  t = {t:.6f} s  dt = {dt:.6f} s")
            self.app.set_progress(0.0,
                                  f"Step {step}  t = {t:.4f} s  dt = {dt:.4f} s")
        if self.END_RE.search(line):
            self.app.set_status("Finished")
            self.app.set_progress(100.0, "Finished")

    def _finish_run(self):
        self.running = False
        self.app.running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.app.set_status("Finished")
        self.app.set_progress(100.0, "Finished")
        self._append_console("\n[Process exited]\n")

    def _stop_simulation(self):
        self.app.stop_process()

    # ------------------------------------------------------------------ #
    # Console helpers
    # ------------------------------------------------------------------ #
    def _append_console(self, text: str):
        self.console.configure(state="normal")
        self.console.insert("end", text)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _open_run_folder(self):
        d = self.dir_var.get().strip() or self.app.active_run_dir
        if d and Path(d).exists():
            if sys.platform == "darwin":
                subprocess.Popen(["open", d])
            elif sys.platform == "win32":
                os.startfile(d)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", d])

    def _open_log(self):
        p = self.app.log_path or str(Path(self.dir_var.get() or ".") / "waam_moose.log")
        if Path(p).exists():
            if sys.platform == "darwin":
                subprocess.Popen(["open", p])
            elif sys.platform == "win32":
                os.startfile(p)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", p])
