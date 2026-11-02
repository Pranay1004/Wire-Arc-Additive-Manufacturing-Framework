"""OpenFOAM CFD (beamWeldFoam) controller for WAAM Framework."""

import glob
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from tkinter import messagebox


def collect_cfd_params(app) -> dict:
    """Collect CFD-specific parameters from the OpenFOAM tab."""
    def _f(var, default=0.0):
        try:
            txt = var.get().strip()
        except (ValueError, AttributeError):
            return default
        if txt.lower() in ("", "auto", "none", "default"):
            return default
        try:
            return float(txt)
        except ValueError:
            return default

    def _raw(var, default="auto"):
        try:
            txt = var.get().strip()
            return txt if txt else default
        except (ValueError, AttributeError):
            return default

    cfd = {}
    cfd["endTime"] = _f(app.cfd_endtime_var, 5.0e-4)
    cfd["deltaT"] = _f(app.cfd_deltat_var, 1e-7)
    cfd["writeInterval"] = _f(app.cfd_writeint_var, 5.0e-5)
    cfd["maxCo"] = _f(app.cfd_maxco_var, 0.2)
    cfd["maxAlphaCo"] = _f(app.cfd_maxalphaco_var, 0.2)
    cfd["maxDeltaT"] = _f(app.cfd_maxdeltat_var, 1e-5)
    cfd["cell_size_mm"] = _f(app.cfd_cellsize_var, 1.0)
    cfd["atmosphere_height"] = _f(app.cfd_atmoheight_var, 3.0) / 1000.0
    cfd["travel_length_mm"] = _raw(app.cfd_travel_var, "40.0")
    cfd["domain_width_mm"] = _raw(app.cfd_width_var, "auto")
    cfd["minTempCorrector"] = int(_f(app.cfd_mintcorr_var, 1))
    cfd["maxTempCorrector"] = int(_f(app.cfd_maxtcorr_var, 150))
    cfd["epsilonTolerance"] = _f(app.cfd_epstol_var, 1e-6)
    cfd["epsilonRelaxation"] = _f(app.cfd_epsrel_var, 0.95)
    cfd["damperSwitch"] = app.cfd_damper_var.get()
    cfd["oscillation_amplitude"] = _f(app.cfd_osc_amp_var, 0.0) / 1000.0
    cfd["oscillation_frequency"] = _f(app.cfd_osc_freq_var, 0.0)
    cfd["Y_R"] = _f(app.cfd_yr_var, 0.15)
    cfd["foc_shift_vel"] = _f(app.cfd_focshift_var, 0.0) / 1000.0
    cfd["tshift"] = _f(app.cfd_tshift_var, 1.0)
    cfd["deposition_cutoff"] = _f(app.cfd_cutoff_var, 0.5)

    qr_str = app.cfd_qramp_var.get().strip().lower()
    if qr_str == "auto":
        cfd["Q_ramp_rate"] = None
    else:
        try:
            cfd["Q_ramp_rate"] = float(qr_str)
        except ValueError:
            cfd["Q_ramp_rate"] = None

    return cfd


def cfd_case_subdir(run_dir: str) -> str:
    return os.path.join(run_dir, "openfoam")


def find_cfd_case_dir(run_dir: str):
    for name in ("openfoam", "openfoam_meltpool"):
        cand = os.path.join(run_dir, name)
        if os.path.exists(cand):
            return cand
    return None


def openfoam_generate_case(app):
    """Generate a beamWeldFoam case under <run_dir>/openfoam/."""
    try:
        run_dir = app._get_or_create_run_dir(is_new_run=False)
        foam_dir = cfd_case_subdir(run_dir)
        params = app._collect_params()
        cfd_params = collect_cfd_params(app)

        from core.fluid.openfoam_coupling import setup_beamweldfoam_case
        result = setup_beamweldfoam_case(foam_dir, params, cfd_params)

        def _num(x, fb=0.0):
            try:
                return float(x)
            except (TypeError, ValueError):
                return fb

        Q_arc = _num(params.get("I_weld", 200)) * _num(params.get("U_weld", 24)) * _num(params.get("eta_arc", 0.8))
        v_mms = _num(params.get("v_scan", 0.01)) * 1000.0
        app._log(f"\n{'='*55}\n")
        app._log(f"[OpenFOAM 2412] beamWeldFoam case generated\n")
        app._log(f"  Case dir:  {result}\n")
        app._log(f"  Material:  {params.get('material_dep', 'ER70S-6')}\n")
        app._log(f"  Arc Power: {Q_arc:.1f} W\n")
        app._log(f"  Scan Speed: {v_mms:.1f} mm/s\n")
        app._log(f"  End Time:  {_num(cfd_params.get('endTime', 5.0e-4)):.6g} s\n")
        app._log(f"  Cell Size: {_num(cfd_params.get('cell_size_mm', 1.0)):.2f} mm\n")
        app._log(f"{'='*55}\n")

        app.cfd_status_var.set(f"Case generated at: {foam_dir}")
        app._cfd_case_dir = foam_dir
    except Exception as e:
        app._log(f"\n[OpenFOAM] [ERROR] Case generation failed: {e}\n")
        import traceback
        app._log(traceback.format_exc())
        messagebox.showerror("OpenFOAM Case Error", str(e))


def openfoam_run(app):
    """Run beamWeldFoam solver on the generated case."""
    foam_dir = getattr(app, "_cfd_case_dir", None)
    if not foam_dir or not os.path.exists(foam_dir):
        openfoam_generate_case(app)
        foam_dir = getattr(app, "_cfd_case_dir", None)
        if not foam_dir:
            found = find_cfd_case_dir(app._get_active_or_latest_run_dir())
            if found:
                foam_dir = found
                app._cfd_case_dir = found
            else:
                return

    allrun = os.path.join(foam_dir, "Allrun")
    if not os.path.exists(allrun):
        app._log(f"[OpenFOAM] [ERROR] Allrun script not found: {allrun}\n")
        return

    app._log(f"\n{'='*55}\nSTARTING beamWeldFoam SOLVER...\n{'='*55}\n")
    app.cfd_status_var.set("Running beamWeldFoam...")
    app.status_var.set("Status: beamWeldFoam Running...")

    def run_foam_thread():
        try:
            log_path = os.path.join(foam_dir, "sim_openfoam.log")
            _use_script = shutil.which("script") is not None
            if _use_script:
                cmd = ["script", "-q", "/dev/null", "bash", allrun]
            else:
                cmd = ["bash", allrun]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=foam_dir,
                bufsize=1
            )

            with open(log_path, "w", encoding="utf-8") as log_f:
                log_f.write(f"beamWeldFoam Solver Log\nCase: {foam_dir}\n\n")
                _pending = []
                _last_flush = 0.0
                _last_time_line = None
                _last_status = 0.0

                def _flush(force=False):
                    nonlocal _last_flush
                    now = time.monotonic()
                    if _pending and (force or now - _last_flush >= 0.25):
                        chunk = "".join(_pending)
                        del _pending[:]
                        _last_flush = now
                        app.root.after(0, app._log, chunk)

                for line in proc.stdout:
                    line = line.replace("\r", "")
                    while line and ord(line[0]) < 32:
                        line = line[1:]
                    log_f.write(line)
                    log_f.flush()
                    # "Time =" / "Courant" fire every timestep: forwarding one
                    # Tk after() callback per line saturated the event loop.
                    # They now go through the same 0.25 s batched flush, and
                    # only the newest timestep line updates the status label.
                    _pending.append(line)
                    if "Time =" in line:
                        _last_time_line = line.strip()
                    now = time.monotonic()
                    if _last_time_line and now - _last_status >= 0.25:
                        app.root.after(0, lambda m=_last_time_line: (
                            app.cfd_status_var.set(f"Solving: {m}")))
                        _last_time_line = None
                        _last_status = now
                    if len(_pending) > 400:
                        _flush(force=True)
                    else:
                        _flush()
                _flush(force=True)

                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as _lf:
                        _tail = [ln.strip() for ln in _lf if "Time =" in ln]
                    if _tail:
                        app.root.after(0, lambda m=_tail[-1]: (app.cfd_status_var.set(f"Solving: {m}")))
                except Exception:
                    pass

            proc.wait()
            rc = proc.returncode
            if rc == 0:
                app.root.after(0, app._log, f"\n[OpenFOAM] [OK] beamWeldFoam completed successfully.\n")
                app.root.after(0, app.status_var.set, "Status: beamWeldFoam Complete")
                app.root.after(0, app.cfd_status_var.set, "Solver completed. Postprocessing...")
                try:
                    post = subprocess.run(
                        [sys.executable, os.path.join(foam_dir, "postprocess_cfd.py"), foam_dir],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=foam_dir, timeout=180)
                    out = (post.stdout or "") + (post.stderr or "")
                    tail = "\n".join(out.strip().splitlines()[-25:])
                    app.root.after(0, app._log, f"\n[CFD-POST] postprocess_cfd.py finished:\n{tail}\n")
                except Exception as pe:
                    app.root.after(0, app._log, f"\n[CFD-POST] [WARNING] Postprocess note: {pe}\n")
                try:
                    from core.postprocess.output_manager import generate_cfd_html_report
                    cfd_rep = generate_cfd_html_report(foam_dir)
                    case_top = os.path.dirname(os.path.abspath(foam_dir))
                    import shutil as _sh2
                    top_cfd = os.path.join(case_top, "cfd_report.html")
                    _sh2.copy2(cfd_rep, top_cfd)
                    app.root.after(0, app._log, f"[CFD-REPORT] HTML dossier ready: {cfd_rep}\n")
                    app.root.after(0, app._log, f"[CFD-REPORT] Published to case folder: {top_cfd}\n")
                except Exception as re_:
                    app.root.after(0, app._log, f"\n[CFD-REPORT] [WARNING] Report note: {re_}\n")
                app.root.after(0, app.cfd_status_var.set, "Solver completed. Open results in ParaView.")
            else:
                app.root.after(0, app._log, f"\n[OpenFOAM] [ERROR] beamWeldFoam exited with code {rc}\n")
                app.root.after(0, app.status_var.set, f"Status: beamWeldFoam Error (Exit {rc})")
                app.root.after(0, app.cfd_status_var.set, f"Error: solver exit code {rc}. Check log.")
        except Exception as e:
            app.root.after(0, app._log, f"\n[OpenFOAM] [ERROR] Launch failed: {e}\n")
            app.root.after(0, app.status_var.set, "Status: beamWeldFoam Error")

    threading.Thread(target=run_foam_thread, daemon=True).start()


def open_cfd_report(app):
    """Open CFD HTML report."""
    foam_dir = getattr(app, "_cfd_case_dir", None)
    if not foam_dir or not os.path.exists(foam_dir):
        foam_dir = find_cfd_case_dir(app._get_active_or_latest_run_dir())
    if not foam_dir or not os.path.exists(foam_dir):
        messagebox.showinfo("No CFD Case", "No OpenFOAM case directory found.\nGenerate and run a case first.")
        return
    rep = os.path.join(foam_dir, "cfd_report.html")
    hist = os.path.join(foam_dir, "cfd_history.csv")
    stale = (not os.path.exists(rep) or
             (os.path.exists(hist) and os.path.getmtime(hist) > os.path.getmtime(rep)))
    if stale:
        try:
            from core.postprocess.output_manager import generate_cfd_html_report
            rep = generate_cfd_html_report(foam_dir)
            import shutil as _sh3
            _sh3.copy2(rep, os.path.join(os.path.dirname(os.path.abspath(foam_dir)), "cfd_report.html"))
        except Exception as e:
            messagebox.showinfo("CFD Report", f"Could not generate report: {e}")
            return
    webbrowser.open(f"file://{os.path.abspath(rep)}")
    app._log(f"[CFD-REPORT] Opened CFD dossier: {os.path.abspath(rep)}\n")


def openfoam_paraview(app):
    """Open OpenFOAM results in ParaView."""
    foam_dir = getattr(app, "_cfd_case_dir", None)
    if not foam_dir or not os.path.isdir(str(foam_dir)):
        resolved = find_cfd_case_dir(app._get_active_or_latest_run_dir())
        foam_dir = str(resolved) if resolved else None

    if not foam_dir or not os.path.isdir(foam_dir):
        messagebox.showinfo("No CFD Case", "No OpenFOAM case directory found.\nGenerate and run a case first.")
        return

    foam_file = os.path.join(foam_dir, "case.foam")
    if not os.path.exists(foam_file):
        with open(foam_file, "w") as f:
            f.write("")

    candidates = [
        shutil.which("paraview"),
        os.environ.get("PARAVIEW_BIN"),
        os.path.expanduser("~/bin/paraview"),
        "/Applications/ParaView-5.13.3.app/Contents/MacOS/paraview",
        "/opt/homebrew/bin/paraview",
    ] + glob.glob("/Applications/ParaView*.app/Contents/MacOS/paraview")

    pv_bin = None
    for c in candidates:
        if c and os.path.exists(c):
            pv_bin = c
            break

    if pv_bin:
        try:
            subprocess.Popen([pv_bin, foam_file])
            app._log(f"[PARAVIEW] [OK] Opening OpenFOAM case: {foam_file}\n")
        except Exception as e:
            app._log(f"[PARAVIEW] [ERROR] {e}\n")
    elif sys.platform == "darwin":
        pv_apps = glob.glob("/Applications/ParaView*.app")
        if pv_apps:
            subprocess.Popen(["open", "-a", pv_apps[0], foam_file])
            app._log(f"[PARAVIEW] [OK] Opening via {pv_apps[0]}\n")
        else:
            subprocess.Popen(["open", foam_dir])
            app._log(f"[PARAVIEW] ParaView not found. Opened case directory.\n")
    else:
        subprocess.Popen(["open", foam_dir])
