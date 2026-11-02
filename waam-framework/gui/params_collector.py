"""GUI Parameter Collector for WAAM Simulation Framework.

Extracts Tkinter variable values, enforces units, dimensions, materials,
and multi-physics configurations for EDP synthesis.
"""

import math
import tkinter as tk
from codegen.edp_builder import EDPBuilder
from gui.presets import MM_DIMENSION_KEYS, MM_SPEED_KEYS


def collect_params(app) -> dict:
    """Collect and validate parameters from the GUI state."""
    params = EDPBuilder.default_params()
    for key, (var, type_) in app._param_vars.items():
        try:
            val_str = var.get().strip()
            if not val_str or val_str.lower() in ("none", "null", "auto"):
                params[key] = None
                continue
            if type_ == "str":
                params[key] = val_str
            else:
                import re
                clean_str = re.sub(r"[^\d.eE+-]", "", val_str)
                if not clean_str:
                    params[key] = None
                    continue
                if type_ == "int":
                    params[key] = int(float(clean_str))
                else:
                    params[key] = float(clean_str)
            warned = getattr(app, "_warned_invalid_keys", None)
            if warned is not None:
                warned.discard(key)
        except Exception as e:
            warned = getattr(app, "_warned_invalid_keys", None)
            if warned is None:
                warned = set()
                app._warned_invalid_keys = warned
            if key not in warned:
                warned.add(key)
                try:
                    app._log(f"[PARAM] [WARNING] Invalid entry for '{key}': {e}. Keeping {params.get(key)}.\n")
                except Exception:
                    pass

    try:
        from mesh.units import dim_to_m
    except Exception:
        dim_to_m = None

    def _convert(key, kind):
        if key not in params or params[key] is None or dim_to_m is None:
            return
        try:
            before = float(params[key])
        except (ValueError, TypeError):
            return
        try:
            after = dim_to_m(params[key], key)
        except ValueError:
            return
        if after != before:
            params[key] = after

    for _k in MM_DIMENSION_KEYS:
        _convert(_k, "millimetres")
    for _k in MM_SPEED_KEYS:
        _convert(_k, "mm/s")

    params["heat_source"] = app.source_var.get()
    if params["heat_source"] in ("p48_surface", "p48_gmaw", "p48"):
        for _k in ("af", "ar", "bG", "cG", "ff", "fr"):
            params[_k] = None
        if "eta_drop" not in params or params["eta_drop"] is None:
            params["eta_drop"] = 0.25
        if "T_drop" not in params or params["T_drop"] is None:
            params["T_drop"] = 1627.0
    elif params["heat_source"] != "goldak":
        for _k in ("af", "ar", "bG", "cG", "ff", "fr"):
            params[_k] = None

    params["material_base"] = app.material_base_var.get()
    params["material_dep"] = app.material_dep_var.get()
    params["material"] = app.material_dep_var.get()
    params["mesh_source"] = app.mesh_source_var.get()
    params["mesh_file"] = app.mesh_file_var.get()

    if hasattr(app, "loaded_mesh_path") and app.loaded_mesh_path and (not params["mesh_file"] or not params["mesh_file"].lower().endswith(('.mesh', '.mesh3', '.msh'))):
        params["mesh_file"] = app.loaded_mesh_path
    if hasattr(app, "loaded_gcode_path") and app.loaded_gcode_path:
        params["gcode_file"] = app.loaded_gcode_path
    elif params.get("mesh_file") and params["mesh_file"].lower().endswith((".gcode", ".nc")):
        params["gcode_file"] = params["mesh_file"]

    stl_p = getattr(app, "loaded_stl_path", "")
    if not stl_p and params["mesh_file"] and params["mesh_file"].lower().endswith((".stl", ".ply", ".obj")):
        stl_p = params["mesh_file"]
    params["stl_file"] = stl_p

    params["enable_radiation"] = app.rad_var.get()
    params["enable_latent"] = app.latent_var.get()
    params["enable_mechanical"] = app.mech_var.get()
    params["enable_microstructure"] = app.micro_var.get()
    params["enable_p48_buoyancy"] = getattr(app, "p48_buoyancy_var", tk.BooleanVar(value=True)).get()
    params["enable_p48_droplets"] = getattr(app, "p48_droplet_var", tk.BooleanVar(value=True)).get()
    params["enable_openfoam"] = app.foam_var.get()
    params["enable_ultrasonic"] = getattr(app, "enable_ultrasonic_var", tk.BooleanVar(value=False)).get()

    # --- UVA physics parameters ---
    if hasattr(app, "us_freq_var"):
        try:
            params["ultrasonic_frequency"] = float(app.us_freq_var.get())
        except Exception:
            params["ultrasonic_frequency"] = 20000.0
    if hasattr(app, "us_amp_var"):
        try:
            params["ultrasonic_amplitude"] = float(app.us_amp_var.get()) * 1.0e-6
        except Exception:
            params["ultrasonic_amplitude"] = 15.0e-6
    if hasattr(app, "us_coupling_var"):
        try:
            params["ultrasonic_coupling_eff"] = float(app.us_coupling_var.get())
        except Exception:
            params["ultrasonic_coupling_eff"] = 0.15
    if hasattr(app, "us_attenuation_var"):
        try:
            params["ultrasonic_attenuation"] = float(app.us_attenuation_var.get())
        except Exception:
            params["ultrasonic_attenuation"] = 0.12
    if hasattr(app, "us_csound_var"):
        try:
            params["ultrasonic_c_sound"] = float(app.us_csound_var.get())
        except Exception:
            params["ultrasonic_c_sound"] = 5790.0
    if hasattr(app, "us_kstream_var"):
        try:
            params["ultrasonic_k_stream"] = float(app.us_kstream_var.get())
        except Exception:
            params["ultrasonic_k_stream"] = 45.0
    if hasattr(app, "us_cavthresh_var"):
        try:
            params["ultrasonic_cav_threshold"] = float(app.us_cavthresh_var.get()) * 1.0e6
        except Exception:
            params["ultrasonic_cav_threshold"] = 1.0e6
    if hasattr(app, "us_streaming_var"):
        params["ultrasonic_streaming"] = bool(app.us_streaming_var.get())
    if hasattr(app, "us_heatgen_var"):
        params["ultrasonic_heat_gen"] = bool(app.us_heatgen_var.get())
    if hasattr(app, "us_cavitation_var"):
        params["ultrasonic_cavitation"] = bool(app.us_cavitation_var.get())
    if hasattr(app, "us_momentum_var"):
        params["ultrasonic_momentum"] = bool(app.us_momentum_var.get())

    # Wire Feedstock & Mass Deposition Aliases and Physical Quantities
    d_wire_m = params.get("d_wire", 1.2e-3)
    if d_wire_m is None or d_wire_m <= 0:
        d_wire_m = 1.2e-3
    params["d_wire"] = d_wire_m
    params["wire_diameter"] = d_wire_m
    params["wire_diameter_mm"] = d_wire_m * 1000.0

    v_wire_m_min = params.get("v_wire", 5.0)
    if v_wire_m_min is None or v_wire_m_min <= 0:
        v_wire_m_min = 5.0
    params["v_wire"] = v_wire_m_min
    params["wire_feed_speed"] = v_wire_m_min
    params["wire_feed_speed_m_min"] = v_wire_m_min
    params["wire_feed_speed_m_s"] = v_wire_m_min / 60.0

    wire_area_m2 = (math.pi * (d_wire_m ** 2)) / 4.0
    params["wire_area_m2"] = wire_area_m2
    params["wire_area_mm2"] = wire_area_m2 * 1e6

    vol_rate_m3_s = wire_area_m2 * params["wire_feed_speed_m_s"]
    params["wire_vol_rate_m3_s"] = vol_rate_m3_s

    rho_dep = float(params.get("rho", 7850.0))
    m_dep_kg_s = rho_dep * vol_rate_m3_s
    params["wire_mass_rate_kg_s"] = m_dep_kg_s
    params["wire_mass_rate_kg_h"] = m_dep_kg_s * 3600.0

    v_scan_m_s = params.get("v_scan", 0.010)
    params["a_bead_theo_m2"] = (vol_rate_m3_s / v_scan_m_s) if v_scan_m_s > 0 else 0.0
    params["a_bead_theo_mm2"] = params["a_bead_theo_m2"] * 1e6

    # Mechanics controls
    if hasattr(app, "mech_cadence_var"):
        params["mech_solve_cadence"] = app.mech_cadence_var.get()
    if hasattr(app, "springback_var"):
        params["springback_solve"] = bool(app.springback_var.get())
        params["dynamic_clamping"] = bool(app.springback_var.get())

    if hasattr(app, "adaptive_dt_var"):
        params["adaptive_dt"] = app.adaptive_dt_var.get()

    def _parse_probe_block(textbox, label):
        try:
            raw_lines = textbox.get("1.0", "end").splitlines()
        except Exception:
            return []
        out = []
        for ln in raw_lines:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if "#" in ln:
                ln = ln.split("#", 1)[0].strip()
            try:
                vals = [float(v) for v in ln.replace(";", ",").split(",") if v.strip()]
            except ValueError:
                continue
            if len(vals) % 3 or len(vals) < 3:
                continue
            out.append([v / 1000.0 for v in vals])
        return out

    if hasattr(app, "probe_points_text"):
        pts = _parse_probe_block(app.probe_points_text, "probe point")
        if not pts:
            try:
                _lx = float(params.get("lx", 0.15))
                _ly = float(params.get("ly_base", 0.15))
                _hz = float(params.get("hz_base", 0.005))
                _h_build = float(params.get("H_build_actual_mm", 13.20)) / 1000.0
                xc = _lx / 2.0
                yc = _ly / 2.0
                pts = [
                    [xc, yc, _hz / 2.0],
                    [xc, yc, _hz],
                    [xc, yc, _hz + 0.20 * _h_build],
                    [xc, yc, _hz + 0.50 * _h_build],
                    [xc, yc, _hz + 1.00 * _h_build],
                ]
            except Exception:
                pass
        params["probe_points"] = pts
        if hasattr(app, "probe_paths_text"):
            paths = _parse_probe_block(app.probe_paths_text, "probe path")
            params["probe_paths"] = [q for q in paths if len(q) >= 6]

    if hasattr(app, "restart_mode_var"):
        params["restart"] = app.restart_mode_var.get()
        params["restart_resume"] = bool(app.restart_resume_var.get())

    if hasattr(app, "solver_backend_var"):
        params["solver"] = app.solver_backend_var.get()
    if hasattr(app, "parallel_mode_var"):
        params["exec_mode"] = app.parallel_mode_var.get()
    if hasattr(app, "cpu_threads_var"):
        params["cpu_threads"] = app.cpu_threads_var.get()
    if hasattr(app, "mpi_ranks_var"):
        try:
            params["mpi_ranks"] = int(app.mpi_ranks_var.get().split()[0])
        except Exception:
            params["mpi_ranks"] = 1
        if params["mpi_ranks"] > 1:
            params["mpi_safe"] = True

    if hasattr(app, "deposition_pattern_var"):
        params["deposition_pattern"] = app.deposition_pattern_var.get()
    else:
        params["deposition_pattern"] = "bidirectional"

    is_us_active = bool(params.get("enable_ultrasonic", False))
    if is_us_active and hasattr(app, "us_freq_var"):
        try:
            params["ultrasonic_frequency"] = float(app.us_freq_var.get())
        except Exception:
            params["ultrasonic_frequency"] = 20000.0
    else:
        params["ultrasonic_frequency"] = 0.0

    layer_mode = getattr(app, "_layer_mode", None)
    mode_val = layer_mode.get() if layer_mode is not None else "n_layers"
    if mode_val in ("height", "h_bead"):
        try:
            nl_eff, target_h_eff, h_actual_eff = app._effective_layer_count()
        except Exception:
            nl_eff, target_h_eff, h_actual_eff = None, None, None
        if nl_eff is not None:
            try:
                raw_entry = app._param_vars["n_layers"][0].get().strip() if "n_layers" in app._param_vars else ""
                entry_nl = int(float(raw_entry)) if raw_entry else None
            except Exception:
                entry_nl = None
            params["n_layers"] = max(1, int(nl_eff))
            params["H_build_target_mm"] = target_h_eff
            params["H_build_actual_mm"] = h_actual_eff
            if entry_nl != params["n_layers"] and "n_layers" in app._param_vars:
                try:
                    app._param_vars["n_layers"][0].set(str(params["n_layers"]))
                except Exception:
                    pass
                try:
                    app._update_geom_fusion_label()
                except Exception:
                    pass
            try:
                app._log(f"[LAYERS] H_build driver: target={target_h_eff:.2f} mm "
                         f"(h1={app._f(app._param_vars.get('h_bead', (None,))[0], 4.0) if 'h_bead' in app._param_vars else 4.0:.2f} mm) "
                         f"-> N_layer={params['n_layers']} (actual wall {h_actual_eff:.2f} mm, ceil overshoot expected). "
                         f"Solver and display now agree.\n")
            except Exception:
                pass
    else:
        try:
            raw_nl = app._param_vars["n_layers"][0].get().strip() if "n_layers" in app._param_vars else "10"
            params["n_layers"] = max(1, int(float(raw_nl)))
        except Exception:
            params["n_layers"] = 10
        try:
            _, _, h_actual_n = app._effective_layer_count()
            params["H_build_actual_mm"] = h_actual_n
            if hasattr(app, "_build_height_var"):
                app._build_height_var.set(f"{h_actual_n:.2f}")
        except Exception:
            pass

    nl = max(int(params.get("n_layers", 10)), 1)
    params["n_layers"] = nl
    params["num_layers"] = nl
    try:
        nz_user = int(float(params.get("nz_dep", nl)))
    except (TypeError, ValueError):
        nz_user = nl
    prev_nl = getattr(app, "_last_n_layers", None)
    if prev_nl is not None and nz_user != prev_nl and nz_user != nl:
        if getattr(app, "_last_logged_nz_override", None) != (nz_user, nl):
            app._last_logged_nz_override = (nz_user, nl)
            try:
                cpl = nz_user / max(nl, 1)
                app._log(f"[MESH] nz_dep={nz_user} with n_layers={nl}: "
                         f"{cpl:.2f} cells/layer (user override kept).\n")
            except Exception:
                pass
        params["nz_dep"] = max(1, nz_user)
    else:
        app._last_logged_nz_override = None
        params["nz_dep"] = nl
    app._last_n_layers = nl

    ty_dep = float(params.get("ty_dep", 0.005))
    params["ty_dep"] = ty_dep
    params["wBead"] = ty_dep

    # Populate synchronized remelt and bead dimensions
    remelt = float(params.get("remelt_ratio", 0.80))
    h1 = float(params.get("h_bead", params.get("h_bead_first", 0.004)))
    params["h_bead_first"] = h1
    params["h_bead"] = h1
    params["hBead"] = h1
    params["remelt_ratio"] = remelt

    # CAD geometry preserves true spatial height
    is_cad_mode = bool(
        params.get("mesh_source") == "cad_file" or
        params.get("stl_file") or
        getattr(app, "_cad_bbox_z", 0) > 0
    )
    params["h_bead_subseq"] = h1 if is_cad_mode else (h1 * remelt)

    # Multi-material zones
    if is_us_active and hasattr(app, "us_zone_entries") and app.us_zone_entries:
        zones_data = []
        for entry in app.us_zone_entries:
            try:
                val_str = entry["layers_var"].get().strip()
                lz = int(val_str) if val_str.isdigit() else 1
            except Exception:
                lz = 1
            mz = entry["mat_var"].get().strip()
            if lz > 0:
                zones_data.append({"layers": lz, "material": mz})
        if zones_data:
            tot_z = sum(z["layers"] for z in zones_data)
            target_nl = params["n_layers"]
            if tot_z != target_nl and tot_z > 0:
                scaled_zones = []
                cum_l = 0
                for i, z in enumerate(zones_data):
                    if i == len(zones_data) - 1:
                        l_alloc = max(1, target_nl - cum_l)
                    else:
                        l_alloc = max(1, int(round(z["layers"] * target_nl / tot_z)))
                        cum_l += l_alloc
                    scaled_zones.append({"layers": l_alloc, "material": z["material"]})
                zones_data = scaled_zones
            params["zones"] = zones_data
            params["zonea_layers"] = zones_data[0]["layers"]
            params["zonea_material"] = zones_data[0]["material"]
            if len(zones_data) > 1:
                params["zoneb_layers"] = zones_data[1]["layers"]
                params["zoneb_material"] = zones_data[1]["material"]
            params["material_dep"] = zones_data[0]["material"]
    else:
        params.pop("zones", None)
        params["zonea_layers"] = params["n_layers"]
        params["zonea_material"] = params["material_dep"]
        params["zoneb_layers"] = 0
        params["zoneb_material"] = params["material_dep"]

    bc_str = getattr(app, "mech_bc_var", None)
    if bc_str:
        val = bc_str.get()
        if "Cantilever" in val:
            params["mechanical_bc"] = "cantilever"
        elif "Clamped" in val:
            params["mechanical_bc"] = "fixture_clamped"
        else:
            params["mechanical_bc"] = "isostatic"

    # Heat input and power calculations
    I = float(params.get("I_weld", 180.0))
    U = float(params.get("U_weld", 20.0))
    eta = float(params.get("eta_arc", 0.8))
    v_m_s = float(params.get("v_scan", 0.008))
    v_mm_s = v_m_s * 1000.0
    p_gross = U * I
    p_net = eta * p_gross
    h_net_j_mm = p_net / v_mm_s if v_mm_s > 0 else 0.0
    h_gross_j_mm = p_gross / v_mm_s if v_mm_s > 0 else 0.0

    params["power_gross_W"] = round(p_gross, 2)
    params["power_net_W"] = round(p_net, 2)
    params["heat_input_net_J_per_mm"] = round(h_net_j_mm, 2)
    params["heat_input_gross_J_per_mm"] = round(h_gross_j_mm, 2)
    return params
