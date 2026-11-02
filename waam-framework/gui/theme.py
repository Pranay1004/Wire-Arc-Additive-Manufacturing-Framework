#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Unified Cross-Platform Theme System

Provides cohesive, modern visual styling across macOS, Windows 11, and Ubuntu Linux.
Eliminates inconsistent widget borders, unreadable text on colored buttons,
and mismatched platform bevels.
"""

import sys
import tkinter as tk
from tkinter import ttk

THEMES = {
    "light": {
        "bg": "#f8fafc",
        "bg_card": "#ffffff",
        "bg_input": "#ffffff",
        "fg": "#0f172a",
        "fg_dim": "#64748b",
        "accent": "#2563eb",
        "accent2": "#059669",
        "warning": "#d97706",
        "error": "#dc2626",
        "border": "#cbd5e1",
        "border_light": "#e2e8f0",
        # Action Buttons (Clean contrast, no unreadable dark text on dark colors)
        "button": "#f1f5f9",
        "button_fg": "#0f172a",
        "button_hover": "#e2e8f0",
        "button_run": "#059669",
        "button_run_fg": "#ffffff",
        "button_run_active": "#047857",
        "button_primary": "#2563eb",
        "button_primary_fg": "#ffffff",
        "button_primary_active": "#1d4ed8",
        "button_action": "#0284c7",
        "button_action_fg": "#ffffff",
        "button_action_active": "#0369a1",
        "button_violet": "#4f46e5",
        "button_violet_fg": "#ffffff",
        "button_violet_active": "#4338ca",
        "button_info": "#0284c7",
        "button_info_fg": "#ffffff",
        # Tab Styling
        "tab_selected_bg": "#2563eb",
        "tab_selected_fg": "#ffffff",
        "tab_unselected_bg": "#e2e8f0",
        "tab_unselected_fg": "#475569",
        # Live Solver Console
        "console_bg": "#0f172a",
        "console_fg": "#f8fafc",
        "console_border": "#334155"
    },
    "dark": {
        "bg": "#0f172a",
        "bg_card": "#1e293b",
        "bg_input": "#0f172a",
        "fg": "#f8fafc",
        "fg_dim": "#94a3b8",
        "accent": "#38bdf8",
        "accent2": "#34d399",
        "warning": "#fbbf24",
        "error": "#f87171",
        "border": "#334155",
        "border_light": "#1e293b",
        # Action Buttons
        "button": "#334155",
        "button_fg": "#f8fafc",
        "button_hover": "#475569",
        "button_run": "#10b981",
        "button_run_fg": "#ffffff",
        "button_run_active": "#059669",
        "button_primary": "#3b82f6",
        "button_primary_fg": "#ffffff",
        "button_primary_active": "#2563eb",
        "button_action": "#38bdf8",
        "button_action_fg": "#0f172a",
        "button_action_active": "#0284c7",
        "button_violet": "#6366f1",
        "button_violet_fg": "#ffffff",
        "button_violet_active": "#4f46e5",
        "button_info": "#38bdf8",
        "button_info_fg": "#0f172a",
        # Tab Styling
        "tab_selected_bg": "#3b82f6",
        "tab_selected_fg": "#ffffff",
        "tab_unselected_bg": "#1e293b",
        "tab_unselected_fg": "#94a3b8",
        # Live Solver Console
        "console_bg": "#090d16",
        "console_fg": "#f8fafc",
        "console_border": "#1e293b"
    }
}


def apply_theme_to_app(app):
    """
    Apply active palette to all registered widgets and ttk styling cleanly.
    Ensures identical layout metrics and contrast on macOS, Windows, and Linux.
    """
    if not hasattr(app, "colors"):
        return

    c = app.colors
    bg = c["bg"]
    card = c["bg_card"]
    fg = c["fg"]
    accent = c["accent"]
    border = c["border"]

    # Main window and top headers
    if hasattr(app, "root"):
        app.root.configure(bg=bg)
    if hasattr(app, "header"):
        app.header.configure(bg=bg)
    if hasattr(app, "title_frame"):
        app.title_frame.configure(bg=bg)
    if hasattr(app, "header_right"):
        app.header_right.configure(bg=bg)
    if hasattr(app, "title_label"):
        app.title_label.configure(bg=bg, fg=accent)
    if hasattr(app, "subtitle_label") and app.subtitle_label:
        app.subtitle_label.configure(bg=bg, fg=c["fg_dim"])
    if hasattr(app, "status_label"):
        app.status_label.configure(bg=bg, fg=c["accent2"])
    if hasattr(app, "theme_btn"):
        app.theme_btn.configure(
            bg=c["button"], fg=c["button_fg"],
            text="[ Dark Theme ]" if app.current_theme == "light" else "[ Light Theme ]",
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
    if hasattr(app, "right_panel"):
        app.right_panel.configure(bg=card)
    if hasattr(app, "btn_bar"):
        app.btn_bar.configure(bg=card)
    if hasattr(app, "main_pane"):
        app.main_pane.configure(bg=bg)
    if hasattr(app, "console_frame"):
        app.console_frame.configure(bg=card, fg=accent)
    if hasattr(app, "console_toolbar"):
        app.console_toolbar.configure(bg=card)
    if hasattr(app, "console_status_dot"):
        app.console_status_dot.configure(bg=card)
    if hasattr(app, "console_clear_btn"):
        app.console_clear_btn.configure(bg=c["button"], fg=c["button_fg"], relief=tk.FLAT, bd=0)
    if hasattr(app, "console_copy_btn"):
        app.console_copy_btn.configure(bg=c["button"], fg=c["button_fg"], relief=tk.FLAT, bd=0)
    if hasattr(app, "console"):
        app.console.configure(
            bg=c["console_bg"], fg=c["console_fg"],
            insertbackground=c["console_fg"]
        )
        if hasattr(app, "_init_console_tags"):
            app._init_console_tags()

    # Style ttk elements
    if hasattr(app, "style"):
        app.style.configure(".", background=bg, foreground=fg)
        app.style.configure("TNotebook", background=bg)
        font_tab = getattr(app, "font_tab", ("Helvetica Neue", 10, "bold"))
        app.style.configure(
            "TNotebook.Tab",
            background=c["tab_unselected_bg"],
            foreground=c["tab_unselected_fg"],
            padding=[10, 5],
            font=font_tab
        )
        app.style.map(
            "TNotebook.Tab",
            background=[("selected", c["tab_selected_bg"])],
            foreground=[("selected", c["tab_selected_fg"])]
        )

    # Standard action buttons
    _std_btns = []
    for btn_name in ("gen_btn", "out_btn", "pv_btn", "foam_btn", "pv_gpu_btn", "claude_100mm_btn", "claude_pv_btn"):
        if hasattr(app, btn_name):
            _std_btns.append(getattr(app, btn_name))

    for btn in _std_btns:
        try:
            btn.configure(
                bg=c["button"], fg=c["button_fg"],
                activebackground=border, activeforeground=c["button_fg"],
                highlightbackground=border, relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass

    # High-visibility primary action buttons
    if hasattr(app, "run_btn"):
        try:
            app.run_btn.configure(
                bg=c["button_run"], fg=c["button_run_fg"],
                activebackground=c["button_run_active"], activeforeground=c["button_run_fg"],
                relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass

    if hasattr(app, "view_results_btn"):
        try:
            app.view_results_btn.configure(
                bg=c["button_primary"], fg=c["button_primary_fg"],
                activebackground=c["button_primary_active"], activeforeground=c["button_primary_fg"],
                relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass

    if hasattr(app, "mesh3d_btn"):
        try:
            app.mesh3d_btn.configure(
                bg=c["button_info"], fg=c["button_info_fg"],
                activebackground=c["button_primary_active"], activeforeground=c["button_info_fg"],
                relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass

    if hasattr(app, "claude_btn"):
        try:
            app.claude_btn.configure(
                bg=c["button_violet"], fg=c["button_violet_fg"],
                activebackground=c["button_violet_active"], activeforeground=c["button_violet_fg"],
                relief=tk.FLAT, bd=0, highlightthickness=0
            )
        except Exception:
            pass

    # Registered widgets batch configuration
    reg_widgets = getattr(app, "registered_widgets", [])
    for item in reg_widgets:
        try:
            w, kind = item[0], item[1]
            if not w.winfo_exists():
                continue
            if kind == "card_frame":
                w.configure(bg=card)
            elif kind == "card_labelframe":
                w.configure(bg=card, fg=accent)
            elif kind == "label":
                w.configure(bg=card, fg=fg)
            elif kind == "label_bold":
                w.configure(bg=card, fg=fg)
            elif kind == "label_dim":
                w.configure(bg=card, fg=c["fg_dim"])
            elif kind == "label_accent":
                w.configure(bg=card, fg=accent)
            elif kind == "button":
                w.configure(bg=c["button"], fg=c["button_fg"], relief=tk.FLAT, bd=0)
            elif kind == "entry":
                w.configure(bg=c["bg_input"], fg=fg, insertbackground=fg)
        except Exception:
            pass
