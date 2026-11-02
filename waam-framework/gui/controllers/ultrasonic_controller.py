"""Ultrasonic tab zones and multi-material zone controller for WAAM Framework."""

import tkinter as tk
from tkinter import ttk
from gui.fonts import FONT_SMALL, FONT_SMALL_BOLD, FONT_MONO_SM


def add_us_zone(app, layers: int = None, material: str = None):
    """Add a new configurable material zone row in the Ultrasonic tab."""
    mat_options = ["SS308L", "SS316L", "Ti-6Al-4V", "Pure Al (Al1xxx)"]

    if layers is None:
        try:
            tot_req = int(app.us_layers_var.get())
        except Exception:
            tot_req = 10
        cur_sum = 0
        for e in getattr(app, "us_zone_entries", []):
            val = e["layers_var"].get().strip()
            if val.isdigit():
                cur_sum += int(val)
        rem = tot_req - cur_sum
        layers = rem if rem > 0 else 5

    if material is None:
        idx = len(getattr(app, "us_zone_entries", []))
        material = mat_options[idx % len(mat_options)]

    row_frame = tk.Frame(app.us_zones_container, pady=3)
    row_frame.pack(fill=tk.X)
    app._reg(row_frame, "card_frame")

    lbl_zone = tk.Label(row_frame, text=f"Zone {len(app.us_zone_entries) + 1}:", font=FONT_SMALL_BOLD, width=9, anchor=tk.W)
    lbl_zone.pack(side=tk.LEFT, padx=(2, 6))
    app._reg(lbl_zone, "label")

    tk.Label(row_frame, text="Layers:", font=FONT_SMALL).pack(side=tk.LEFT, padx=(2, 2))
    layers_var = tk.StringVar(value=str(layers))
    entry_layers = ttk.Entry(row_frame, textvariable=layers_var, width=6)
    entry_layers.pack(side=tk.LEFT, padx=(0, 8))

    tk.Label(row_frame, text="Material:", font=FONT_SMALL).pack(side=tk.LEFT, padx=(4, 2))
    mat_var = tk.StringVar(value=material)
    combo_mat = ttk.Combobox(row_frame, textvariable=mat_var, values=mat_options, state="readonly", width=12)
    combo_mat.pack(side=tk.LEFT, padx=(0, 8))

    lbl_range = tk.Label(row_frame, text="", font=FONT_MONO_SM, fg="#4b5563")
    lbl_range.pack(side=tk.LEFT, padx=(4, 8))
    app._reg(lbl_range, "label")

    del_btn = tk.Button(
        row_frame, text="✕", font=("TkDefaultFont", 9, "bold"),
        fg="#dc2626", relief=tk.FLAT, padx=4, pady=0, cursor="hand2",
        command=lambda rf=row_frame: remove_us_zone(app, rf)
    )
    del_btn.pack(side=tk.LEFT)
    app._reg(del_btn, "button")

    entry_dict = {
        "frame": row_frame,
        "lbl_zone": lbl_zone,
        "layers_var": layers_var,
        "mat_var": mat_var,
        "mat_combo": combo_mat,
        "lbl_range": lbl_range,
        "del_btn": del_btn
    }
    app.us_zone_entries.append(entry_dict)

    try:
        layers_var.trace_add("write", lambda *args: refresh_us_zones(app))
        mat_var.trace_add("write", lambda *args: refresh_us_zones(app))
    except Exception:
        pass
    refresh_us_zones(app)


def remove_us_zone(app, row_frame: tk.Frame):
    """Remove a zone row if more than 1 zone remains."""
    if len(app.us_zone_entries) <= 1:
        return
    idx_to_remove = None
    for i, entry in enumerate(app.us_zone_entries):
        if entry["frame"] == row_frame:
            idx_to_remove = i
            break
    if idx_to_remove is not None:
        entry = app.us_zone_entries.pop(idx_to_remove)
        entry["frame"].destroy()
        refresh_us_zones(app)


def auto_balance_us_zones(app):
    """Evenly distribute total layers across all defined zones."""
    if not getattr(app, "us_zone_entries", []):
        return
    try:
        total_req = int(app.us_layers_var.get())
    except Exception:
        total_req = 10
    n_zones = len(app.us_zone_entries)
    if n_zones <= 0:
        return
    base_per_zone = max(1, total_req // n_zones)
    rem = total_req - base_per_zone * n_zones
    for i, entry in enumerate(app.us_zone_entries):
        extra = 1 if i < rem else 0
        entry["layers_var"].set(str(base_per_zone + extra))
    refresh_us_zones(app)


def refresh_us_zones(app):
    """Update zone labels, Z-height ranges, delete button states, and summary bar."""
    if not hasattr(app, "us_zone_entries"):
        return
    try:
        tot_req = int(app.us_layers_var.get())
    except Exception:
        tot_req = 10
    try:
        h_bead_first = float(app.us_height_var.get())
    except Exception:
        h_bead_first = 4.0
    try:
        remelt_pct = float(app.us_remelt_var.get())
        remelt_ratio = (remelt_pct / 100.0) if remelt_pct > 1.0 else remelt_pct
    except Exception:
        remelt_ratio = 0.80

    h_bead_subseq = h_bead_first * remelt_ratio
    if hasattr(app, "us_fusion_info_lbl"):
        app.us_fusion_info_lbl.config(
            text=f"Subsequent: {h_bead_subseq:.2f} mm ({remelt_ratio*100.0:.0f}% fusion)"
        )

    def calc_z(n):
        if n <= 0:
            return 0.0
        elif n == 1:
            return h_bead_first
        else:
            return h_bead_first + (n - 1) * h_bead_subseq

    cum_l = 0
    can_delete = len(app.us_zone_entries) > 1

    for i, entry in enumerate(app.us_zone_entries):
        entry["lbl_zone"].config(text=f"Zone {i + 1}:")
        val_str = entry["layers_var"].get().strip()
        l_count = int(val_str) if val_str.isdigit() else 0

        start_l = cum_l + 1 if l_count > 0 else cum_l
        end_l = cum_l + l_count
        start_z = calc_z(cum_l)
        end_z = calc_z(cum_l + l_count)
        cum_l += l_count

        if l_count > 0:
            entry["lbl_range"].config(text=f"Layers {start_l}–{end_l} (Z: {start_z:.1f}–{end_z:.1f} mm)")
        else:
            entry["lbl_range"].config(text="0 layers")

        if can_delete:
            entry["del_btn"].config(state=tk.NORMAL)
        else:
            entry["del_btn"].config(state=tk.DISABLED)

    total_alloc_z = calc_z(cum_l)
    if hasattr(app, "us_zones_summary_lbl"):
        if cum_l == tot_req:
            app.us_zones_summary_lbl.config(
                text=f"✓ All Layers Allocated: {cum_l} / {tot_req} layers  |  Total Build Height: {total_alloc_z:.1f} mm",
                fg="#16a34a"
            )
        elif cum_l < tot_req:
            app.us_zones_summary_lbl.config(
                text=f"⚠ Under-allocated: {cum_l} / {tot_req} layers ({tot_req - cum_l} layers remaining)  |  Height: {total_alloc_z:.1f} mm",
                fg="#d97706"
            )
        else:
            app.us_zones_summary_lbl.config(
                text=f"⚠ Over-allocated: {cum_l} / {tot_req} layers ({cum_l - tot_req} extra layers)  |  Height: {total_alloc_z:.1f} mm",
                fg="#dc2626"
            )


def sync_geometry_to_ultrasonic(app):
    """Keep Ultrasonic tab parameters in sync with Geometry tab."""
    if not hasattr(app, "_param_vars") or getattr(app, "_syncing_geom_us", False):
        return
    app._syncing_geom_us = True
    try:
        if hasattr(app, "us_layers_var") and "n_layers" in app._param_vars:
            nl_val = app._param_vars["n_layers"][0].get().strip()
            if nl_val and app.us_layers_var.get() != nl_val:
                app.us_layers_var.set(nl_val)
                if hasattr(app, "_auto_balance_us_zones"):
                    app._auto_balance_us_zones()
        if hasattr(app, "us_width_var") and "ty_dep" in app._param_vars:
            w_val = app._param_vars["ty_dep"][0].get().strip()
            if w_val and app.us_width_var.get() != w_val:
                app.us_width_var.set(w_val)
        if hasattr(app, "us_height_var") and "h_bead" in app._param_vars:
            h_val = app._param_vars["h_bead"][0].get().strip()
            if h_val and app.us_height_var.get() != h_val:
                app.us_height_var.set(h_val)
        if hasattr(app, "us_remelt_var") and "remelt_ratio" in app._param_vars:
            r_raw = app._param_vars["remelt_ratio"][0].get().strip()
            try:
                r_flt = float(r_raw)
                r_pct = str(round(r_flt * 100.0, 1)) if r_flt <= 1.0 else str(round(r_flt, 1))
                if app.us_remelt_var.get() != r_pct:
                    app.us_remelt_var.set(r_pct)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        app._syncing_geom_us = False


def sync_ultrasonic_to_geometry(app):
    """Keep Geometry tab in sync if Ultrasonic tab entries are edited."""
    if not hasattr(app, "_param_vars") or getattr(app, "_syncing_geom_us", False):
        return
    is_us = getattr(app, "enable_ultrasonic_var", None)
    if is_us is not None and not is_us.get():
        return
    app._syncing_geom_us = True
    try:
        if hasattr(app, "us_layers_var") and "n_layers" in app._param_vars:
            u_nl = app.us_layers_var.get().strip()
            if u_nl and app._param_vars["n_layers"][0].get() != u_nl:
                app._param_vars["n_layers"][0].set(u_nl)
        if hasattr(app, "us_width_var") and "ty_dep" in app._param_vars:
            u_w = app.us_width_var.get().strip()
            if u_w and app._param_vars["ty_dep"][0].get() != u_w:
                app._param_vars["ty_dep"][0].set(u_w)
        if hasattr(app, "us_height_var") and "h_bead" in app._param_vars:
            u_h = app.us_height_var.get().strip()
            if u_h and app._param_vars["h_bead"][0].get() != u_h:
                app._param_vars["h_bead"][0].set(u_h)
        if hasattr(app, "us_remelt_var") and "remelt_ratio" in app._param_vars:
            u_r = app.us_remelt_var.get().strip()
            try:
                r_flt = float(u_r)
                ratio_str = str(round(r_flt / 100.0, 3)) if r_flt > 1.0 else str(round(r_flt, 3))
                if app._param_vars["remelt_ratio"][0].get() != ratio_str:
                    app._param_vars["remelt_ratio"][0].set(ratio_str)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        app._syncing_geom_us = False
