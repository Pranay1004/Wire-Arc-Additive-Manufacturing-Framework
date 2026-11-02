"""
gui/tabs/outputs_tab.py — Browse run outputs.

Lists the artifacts produced by a MOOSE run (input, log, CSV ledger,
Exodus field output, checkpoints, calphad.json) and lets the user open
any of them.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    from theme import (
        FONT_BTN, FONT_LABEL, FONT_MONO_SM, FONT_SECTION, FONT_SMALL,
        get_theme,
    )
except ImportError:
    from gui.theme import (
        FONT_BTN, FONT_LABEL, FONT_MONO_SM, FONT_SECTION, FONT_SMALL,
        get_theme,
    )


def _append(widget, text):
    widget.configure(state="normal")
    widget.insert("end", text)
    widget.see("end")
    widget.configure(state="disabled")


class OutputsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
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

        card = ttk.LabelFrame(self, text="Run outputs",
                              style="Card.TLabelframe")
        card.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="Run directory", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.dir_var = tk.StringVar(value="")
        d_row = ttk.Frame(card)
        d_row.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 4))
        d_row.columnconfigure(0, weight=1)
        self.dir_entry = ttk.Entry(d_row, textvariable=self.dir_var,
                                   font=FONT_MONO_SM)
        self.dir_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(d_row, text="Browse…", style="Ghost.TButton",
                   command=self._browse_dir).pack(side="left", padx=(6, 0))
        ttk.Button(d_row, text="Use run dir",
                   style="Ghost.TButton",
                   command=self._use_run_dir).pack(side="left", padx=(6, 0))

        btn_row = ttk.Frame(card)
        btn_row.grid(row=1, column=1, sticky="e", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="🔄 Refresh", style="Ghost.TButton",
                   command=self._refresh).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="📊 Run audit", style="Ghost.TButton",
                   command=self._run_audit).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="📈 Plots", style="Ghost.TButton",
                   command=self._run_plots).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="📑 View Report (HTML)", style="TButton",
                   command=self._view_report).pack(side="left")

        # ---- File list ----
        ttk.Label(self, text="Artifacts", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=12, pady=(6, 2))

        cols = ("file", "size", "type")
        self.tree = ttk.Treeview(self, columns=cols, show="headings",
                                 height=12, selectmode="browse")
        self.tree.heading("file", text="File")
        self.tree.heading("size", text="Size")
        self.tree.heading("type", text="Type")
        self.tree.column("file", width=260, anchor="w")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("type", width=120, anchor="w")
        self.tree.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 6))

        vsb = ttk.Scrollbar(self, orient="vertical",
                            command=self.tree.yview)
        vsb.grid(row=2, column=1, sticky="ns", pady=(0, 6))
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.bind("<Double-1>", self._on_open)
        self.tree.bind("<Return>", self._on_open)

        # Hint
        hint = ttk.Label(
            self,
            text="Double-click a file to open it. Exodus (.e) opens in your "
                 "default application; CSV/text opens in a viewer.",
            style="Hint.TLabel")
        hint.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 10))

    def _refresh_colors(self):
        colors = self.app.colors
        style = ttk.Style()
        style.configure("Treeview", background=colors["surface"],
                        foreground=colors["text"], fieldbackground=colors["surface"],
                        bordercolor=colors["border"])
        style.configure("Treeview.Heading", background=colors["panel"],
                        foreground=colors["text"])

    # ------------------------------------------------------------------ #
    # Directory selection
    # ------------------------------------------------------------------ #
    def _browse_dir(self):
        path = filedialog.askdirectory(title="Select run directory")
        if path:
            self.dir_var.set(path)
            self._refresh()

    def _use_run_dir(self):
        d = self.app.active_run_dir
        if d and Path(d).exists():
            self.dir_var.set(d)
            self._refresh()
        self._refresh()
        self._poll_id = self.after(2000, self._start_poll)

    def _refresh(self):
        d = Path(self.dir_var.get().strip()) if self.dir_var.get().strip() else None
        if not d or not d.exists():
            self._set_rows([])
            return

        known_ext = {
            ".i": "MOOSE input",
            ".log": "Console log",
            ".csv": "CSV ledger",
            ".e": "Exodus field output",
            ".exo": "Exodus mesh/output",
            ".json": "JSON artifact",
            ".meta": "Metadata",
        }
        rows = []
        for p in sorted(d.iterdir()):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            ftype = known_ext.get(ext, "File")
            size = p.stat().st_size
            rows.append((p.name, size, ftype, str(p)))
        # Sort: .i and .log first, then by name
        rows.sort(key=lambda r: (r[2] != "MOOSE input", r[2] != "Console log", r[0]))
        self._set_rows(rows[:200])

    def _set_rows(self, rows):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for name, size, ftype, full in rows:
            size_str = self._fmt_size(size)
            self.tree.insert("", "end", values=(name, size_str, ftype),
                             tags=(full,))

    @staticmethod
    def _fmt_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
            n /= 1024
        return f"{n:.2f} TB"

    def _poll_status(self):
        self._refresh()

    def _start_poll(self):
        self._refresh()
        self._poll_id = self.after(2000, self._start_poll)

    def _poll_status(self):
        self._refresh()

    def destroy(self):
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
        super().destroy()

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _view_report(self):
        d_str = self.dir_var.get().strip()
        if not d_str or not Path(d_str).exists():
            messagebox.showerror("No run dir", "Select a run directory first.")
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

    def _run_audit(self):
        d = self.dir_var.get().strip()
        if not d or not Path(d).exists():
            messagebox.showerror("No run dir", "Select a run directory first.")
            return
        # resolve moose_audit.py
        repo_root = Path(__file__).resolve().parent.parent.parent
        audit_py = repo_root / "codegen" / "moose_audit.py"
        if not audit_py.exists():
            messagebox.showerror("Not found", "codegen/moose_audit.py not found.")
            return
        cmd = [sys.executable, str(audit_py), "--run-dir", d]
        # also try freefem baseline
        ff_candidate = Path(d).parent / "FreeFEM"
        if ff_candidate.is_dir():
            cmd += ["--freefem-run-dir", str(Path(d).parent)]
        win = tk.Toplevel(self.app.root)
        win.title("Audit output")
        win.geometry("720x480")
        txt = scrolledtext.ScrolledText(win, wrap="none", font=FONT_MONO_SM)
        txt.pack(fill="both", expand=True)
        txt.insert("end", "$ " + " ".join(cmd) + "\n\n")
        txt.configure(state="disabled")

        def worker():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True,
                                       bufsize=1)
                for raw in proc.stdout:
                    self.app.root.after(0, lambda t=raw: _append(txt, t))
                proc.wait()
                self.app.root.after(0, lambda: _append(
                    txt, f"\n[exit code {proc.returncode}]\n"))
            except Exception as exc:
                self.app.root.after(0, lambda: _append(txt, f"\nERROR: {exc}\n"))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Plots
    # ------------------------------------------------------------------ #
    def _run_plots(self):
        d = self.dir_var.get().strip()
        if not d or not Path(d).exists():
            messagebox.showerror("No run dir", "Select a run directory first.")
            return
        repo_root = Path(__file__).resolve().parent.parent.parent
        plots_py = repo_root / "codegen" / "moose_plots.py"
        if not plots_py.exists():
            messagebox.showerror("Not found", "codegen/moose_plots.py not found.")
            return
        cmd = [sys.executable, str(plots_py), "--run-dir", d]
        win = tk.Toplevel(self.app.root)
        win.title("Plot output")
        win.geometry("720x480")
        txt = scrolledtext.ScrolledText(win, wrap="none", font=FONT_MONO_SM)
        txt.pack(fill="both", expand=True)
        txt.insert("end", "$ " + " ".join(cmd) + "\n\n")
        txt.configure(state="disabled")

        def worker():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True,
                                       bufsize=1)
                for raw in proc.stdout:
                    self.app.root.after(0, lambda t=raw: _append(txt, t))
                proc.wait()
                self.app.root.after(0, lambda: _append(
                    txt, f"\n[exit code {proc.returncode}]\n"))
                # refresh file list
                self.app.root.after(0, self._refresh)
            except Exception as exc:
                self.app.root.after(0, lambda: _append(txt, f"\nERROR: {exc}\n"))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Open
    # ------------------------------------------------------------------ #
    def _on_open(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        full = item["tags"][0] if item.get("tags") else None
        if not full:
            return
        p = Path(full)
        if not p.exists():
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            elif sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Open failed", str(exc))
