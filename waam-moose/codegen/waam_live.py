#!/usr/bin/env python3
"""
WAAM Live Residual Monitor (pyFoam-style)
=========================================
Live, in-flight monitoring of a MOOSE transient solve: nonlinear/linear
residual history, per-step convergence, thermal envelopes and solver health.

The MOOSE console already streams the exact residual information a solver
watcher needs:

    Time Step 24, time = 7.9647, dt = 0.331863
     0 Nonlinear |R| = 7.303180e+02
          0 Linear |R| = 7.303180e+02
          1 Linear |R| = 3.133440e+01
     Damping factor: 0.214089
    ...
    Nonlinear solve did not converge due to DIVERGED_MAX_IT iterations 120

This tool tails that stream (or launches the solve itself) and renders:

  * a live matplotlib dashboard -- residual history per timestep (pyFoam
    style), the per-step worst residual, and the tmin/tmax thermal envelope;
  * an ASCII fallback for headless/SSH sessions, refreshed in place, showing
    the same information in a Fluent-like table.

The thermal envelope (tmin/tmax) is read from the run's CSV output, which the
MOOSE builder writes alongside the log; it is optional -- the residual panes
work without it.

Usage
-----
    # watch a running solve (log file)
    python3 waam_live.py --log run/moose/waam_moose.log

    # launch a solve and monitor it
    python3 waam_live.py --run "/path/waam_moose-opt -i case.i" --log case.log

    # force the terminal (no GUI) renderer
    python3 waam_live.py --log case.log --ascii

    # save the parsed history as JSON for later analysis
    python3 waam_live.py --log case.log --json history.json
"""

import argparse
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Log grammar
# ---------------------------------------------------------------------------

_RE_STEP = re.compile(r"^Time Step\s+(?P<idx>\d+),\s*time\s*=\s*(?P<time>[-+0-9.eE]+)"
                      r"(?:,\s*dt\s*=\s*(?P<dt>[-+0-9.eE]+))?")
_RE_NL = re.compile(r"^\s*(?P<it>\d+)\s+Nonlinear \|R\|\s*=\s*(?P<val>[-+0-9.eE]+)")
_RE_LIN = re.compile(r"^\s*(?P<it>\d+)\s+Linear \|R\|\s*=\s*(?P<val>[-+0-9.eE]+)")
_RE_DAMP = re.compile(r"Damping factor:\s*(?P<val>[-+0-9.eE]+)")
_RE_DIVERGED = re.compile(r"did not converge due to (?P<reason>[A-Z_]+)")
_RE_CONVERGED = re.compile(r"Nonlinear solve converged due to (?P<reason>.*)")
_RE_ABORT = re.compile(r"^\*\*\* (?:ERROR|ABORT) \*\*\*")
_RE_TMIN = re.compile(r"^(?P<k>tmin|tmax|fidelity|num_failed_steps|e_injected|e_intended),")
_RE_CSV_HEADER = re.compile(r"^time,", re.IGNORECASE)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[@-Z\\-_]")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


class Step:
    """One time step's solver history."""

    __slots__ = ("index", "time", "dt", "nl", "lin", "damping", "diverged",
                 "reason", "closed")

    def __init__(self, index: int, time: float, dt: Optional[float]):
        self.index = index
        self.time = time
        self.dt = dt
        self.nl: List[float] = []
        self.lin: List[float] = []
        self.damping: List[float] = []
        self.diverged = False
        self.reason = ""
        self.closed = False

    @property
    def final_nl(self) -> float:
        return self.nl[-1] if self.nl else float("nan")

    @property
    def first_nl(self) -> float:
        return self.nl[0] if self.nl else float("nan")

    @property
    def reduction(self) -> float:
        """Residual reduction factor over the step (nan if not available)."""
        if len(self.nl) < 2 or self.first_nl <= 0.0:
            return float("nan")
        return self.first_nl / max(self.final_nl, 1e-300)


class LogParser:
    """Incremental parser for a MOOSE console log."""

    def __init__(self) -> None:
        self.steps: List[Step] = []
        self.current: Optional[Step] = None
        self.error = ""
        self.fatal = False
        self.finished = False
        self.csv_rows: List[Dict[str, float]] = []
        self._in_csv = False
        self._csv_header: List[str] = []
        self._csv_fieldnames: List[str] = []
        self.csv_path = ""

    # -- CSV (thermal envelope) -------------------------------------------
    def set_csv(self, path: str) -> None:
        self.csv_path = path

    def _flush_csv(self, line: str) -> None:
        parts = [p.strip() for p in line.rstrip("\n").split(",")]
        if len(self._csv_fieldnames) and len(parts) == len(self._csv_fieldnames):
            try:
                row = {k: float(v) for k, v in zip(self._csv_fieldnames, parts)}
            except ValueError:
                return
            self.csv_rows.append(row)

    def read_csv(self) -> None:
        """Re-read the CSV from disk (it grows during the run)."""
        if not self.csv_path or not os.path.exists(self.csv_path):
            return
        rows: List[Dict[str, float]] = []
        with open(self.csv_path, "r", errors="ignore") as handle:
            lines = handle.readlines()
        if not lines:
            return
        header = [h.strip() for h in lines[0].split(",")]
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != len(header):
                continue
            try:
                rows.append({k: float(v) for k, v in zip(header, parts)})
            except ValueError:
                continue
        self.csv_rows = rows

    # -- main feed ---------------------------------------------------------
    def feed(self, line: str) -> Optional[Step]:
        """Consume one raw log line; returns the step if one just started."""
        text = _strip_ansi(line).rstrip("\n")
        if not text:
            return None

        if _RE_CSV_HEADER.match(text) and text.count(",") >= 2:
            self._in_csv = True
            self._csv_fieldnames = [h.strip() for h in text.split(",")]
            return None
        if self._in_csv:
            self._flush_csv(text)
            if not re.match(r"^[-+0-9.eE]", text):
                self._in_csv = False
            return None

        match = _RE_STEP.match(text.strip())
        if match:
            if self.current is not None:
                self.current.closed = True
            dt = match.group("dt")
            self.current = Step(int(match.group("idx")),
                                float(match.group("time")),
                                float(dt) if dt else None)
            self.steps.append(self.current)
            return self.current

        if self.current is not None:
            m = _RE_NL.match(text)
            if m:
                self.current.nl.append(float(m.group("val")))
                return None
            m = _RE_LIN.match(text)
            if m:
                self.current.lin.append(float(m.group("val")))
                return None
            m = _RE_DAMP.search(text)
            if m:
                self.current.damping.append(float(m.group("val")))
                return None
            m = _RE_DIVERGED.search(text)
            if m:
                self.current.diverged = True
                self.current.reason = m.group("reason")
                return None
            m = _RE_CONVERGED.search(text)
            if m:
                self.current.reason = m.group("reason").strip()
                return None

        if _RE_ABORT.match(text):
            self.fatal = True
            self.error = text.strip()
        if "Finished Executing" in text:
            self.finished = True
        return None


# ---------------------------------------------------------------------------
# ASCII renderer (Fluent-like in-place table)
# ---------------------------------------------------------------------------

class AsciiRenderer:
    """Live in-place terminal dashboard."""

    COLS = 96

    def __init__(self) -> None:
        self._lines_drawn = 0
        self._last = ""

    @staticmethod
    def _spark(value: float, lo: float, hi: float, width: int = 12) -> str:
        if value != value:  # nan
            return " " * width
        if hi <= lo or value <= 0.0:
            return "*" * width
        # log-scaled so decades are visible
        lfrac = (math.log10(max(value, 1e-300)) - math.log10(max(lo, 1e-300))) / \
                max(1e-12, (math.log10(max(hi, 1e-300)) - math.log10(max(lo, 1e-300))))
        lfrac = max(0.0, min(1.0, lfrac))
        blocks = " .:-=+*#%@"
        n = int(lfrac * (width - 1))
        if n <= 0:
            return " " * width
        return (blocks[min(n, len(blocks) - 1)] * n).ljust(width)[:width]

    def render(self, parser: LogParser, elapsed: float) -> str:
        cur = parser.current or (parser.steps[-1] if parser.steps else None)
        out: List[str] = []
        bar = "=" * self.COLS
        out.append(bar)
        out.append("WAAM LIVE  |  " + time.strftime("%H:%M:%S") +
                   "  |  elapsed " + self._fmt_dur(elapsed))
        out.append(bar)

        if parser.fatal:
            out.append("  !! FATAL: " + parser.error[: self.COLS - 8])
        if not parser.steps:
            out.append("  waiting for the first time step ...")
        else:
            steps = parser.steps
            done = len([s for s in steps if s.closed])
            divg = len([s for s in steps if s.diverged])
            # A retried step repeats its time with a smaller dt, so the number
            # of repeated times is the number of cutbacks.
            cutbacks = len(steps) - len(set(round(s.time, 9) for s in steps))
            worst = max((s.final_nl for s in steps if s.final_nl == s.final_nl), default=0.0)
            out.append("  steps: %d attempted, %d completed, %d divergent, %d cutbacks"
                       % (len(steps), done, divg, cutbacks))
            out.append("  worst final |R|: %.4e" % worst)
            out.append("")
            out.append("  %-5s %-12s %-11s %-6s %-13s %-12s" %
                       ("step", "time[s]", "dt[s]", "nl_it", "|R|", "trend"))
            recent = steps[-8:]
            allres = [r for s in steps for r in s.nl if r > 0]
            lo = min(allres) if allres else 1e-30
            hi = max(allres) if allres else 1.0
            for s in recent:
                dtxt = ("%.4f" % s.dt) if s.dt else "-"
                flag = " !" if s.diverged else ""
                out.append("  %-5d %-12.5f %-11s %-6d %-13.4e %-12s%s" %
                           (s.index, s.time, dtxt, len(s.nl), s.final_nl,
                            self._spark(s.final_nl, lo, hi), flag))

        # thermal envelope from the CSV
        if parser.csv_rows:
            lastrow = parser.csv_rows[-1]
            out.append("")
            tmin = lastrow.get("tmin")
            tmax = lastrow.get("tmax")
            fails = lastrow.get("num_failed_steps")
            parts = []
            if tmin is not None:
                parts.append("tmin %.1f C" % tmin)
            if tmax is not None:
                parts.append("tmax %.1f C" % tmax)
            if fails is not None:
                parts.append("failed steps %d" % int(fails))
            if parts:
                out.append("  " + "  |  ".join(parts))

        if cur and cur.nl:
            res = cur.nl[-1]
            if len(cur.nl) > 1 and cur.nl[0] > 0:
                rate = (math.log10(cur.nl[0]) - math.log10(max(res, 1e-300))) / \
                       max(1, len(cur.nl) - 1)
                out.append("  current step %d: %d NL iters, |R| %.4e (%.2f decades/iter)"
                           % (cur.index, len(cur.nl), res, rate))
        return "\n".join(out)

    @staticmethod
    def _fmt_dur(seconds: float) -> str:
        seconds = int(seconds)
        return "%02d:%02d:%02d" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)

    def draw(self, parser: LogParser, elapsed: float) -> None:
        text = self.render(parser, elapsed)
        # The header clock changes every second; compare everything else so we
        # only repaint when there is real news.
        key = text.split("\n", 3)[-1]
        if key == self._last:
            return
        self._last = key
        if self._lines_drawn:
            sys.stdout.write("\x1b[%dA\x1b[J" % self._lines_drawn)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        self._lines_drawn = text.count("\n") + 1


# ---------------------------------------------------------------------------
# Matplotlib renderer
# ---------------------------------------------------------------------------

class PlotRenderer:
    """Live pyFoam-style dashboard."""

    def __init__(self) -> None:
        import tempfile
        _mpl_dir = os.path.join(tempfile.gettempdir(),
                                 "matplotlib_waam_%s" % (os.getuid() if hasattr(os, "getuid") else "0"))
        try:
            os.makedirs(_mpl_dir, exist_ok=True)
            os.environ.setdefault("MPLCONFIGDIR", _mpl_dir)
        except Exception:
            pass
        import matplotlib
        matplotlib.use("TkAgg", force=False)
        import matplotlib.pyplot as plt
        self.plt = plt
        self.fig, axes = plt.subplots(1, 3, figsize=(17, 5.5))
        self.fig.suptitle("WAAM live residual monitor")
        self.ax_hist, self.ax_worst, self.ax_therm = axes
        self.ax_hist.set_xlabel("nonlinear iteration")
        self.ax_hist.set_ylabel("residual |R|")
        self.ax_hist.set_yscale("log")
        self.ax_hist.set_title("residual history per time step")
        self.ax_hist.grid(True, which="both", ls="--", alpha=0.4)
        self.ax_worst.set_xlabel("time step")
        self.ax_worst.set_ylabel("final |R| per step")
        self.ax_worst.set_yscale("log")
        self.ax_worst.set_title("worst residual per step")
        self.ax_worst.grid(True, which="both", ls="--", alpha=0.4)
        self.ax_therm.set_xlabel("time [s]")
        self.ax_therm.set_ylabel("temperature [C]")
        self.ax_therm.set_title("thermal envelope")
        self.ax_therm.grid(True, ls="--", alpha=0.4)
        self._first = True

    def update(self, parser: LogParser) -> None:
        plt = self.plt
        self.ax_hist.clear()
        self.ax_worst.clear()
        self.ax_therm.clear()
        self.ax_hist.set_yscale("log")
        self.ax_worst.set_yscale("log")

        steps = [s for s in parser.steps if s.nl]
        if steps:
            cmap = plt.get_cmap("turbo")
            n = max(1, len(steps) - 1)
            for i, s in enumerate(steps):
                colour = cmap(i / n)
                alpha = 1.0 if i >= len(steps) - 12 else 0.25
                self.ax_hist.plot(range(len(s.nl)), s.nl, color=colour, alpha=alpha, lw=1.1)
            worst = [max(s.nl) for s in steps]
            times = [s.time for s in steps]
            self.ax_worst.plot(range(len(worst)), worst, ".-", color="#c0392b", ms=4, lw=0.9)
            self.ax_worst.set_xticks(range(0, len(worst), max(1, len(worst) // 10)))
            self.ax_worst.set_xticklabels(["%d" % steps[i].index
                                           for i in range(0, len(worst), max(1, len(worst) // 10))],
                                          rotation=45, fontsize=8)
            div = [s.index for s in steps if s.diverged]
            if div:
                for i, s in enumerate(steps):
                    if s.diverged:
                        self.ax_worst.axvline(i, color="#e67e22", alpha=0.35, lw=0.8)
        self.ax_hist.set_xlabel("nonlinear iteration")
        self.ax_hist.set_ylabel("residual |R|")
        self.ax_hist.set_title("residual history per time step")
        self.ax_hist.grid(True, which="both", ls="--", alpha=0.4)
        self.ax_worst.set_xlabel("time step")
        self.ax_worst.set_ylabel("max |R| per step")
        self.ax_worst.set_title("worst residual per step")
        self.ax_worst.grid(True, which="both", ls="--", alpha=0.4)

        if parser.csv_rows:
            t = [r.get("time", 0.0) for r in parser.csv_rows]
            tmin = [r.get("tmin") for r in parser.csv_rows]
            tmax = [r.get("tmax") for r in parser.csv_rows]
            if any(v is not None for v in tmin):
                self.ax_therm.plot(t, [v if v is not None else float("nan") for v in tmin],
                                   label="tmin", color="#2c81c9", lw=1.3)
            if any(v is not None for v in tmax):
                self.ax_therm.plot(t, [v if v is not None else float("nan") for v in tmax],
                                   label="tmax", color="#c0392b", lw=1.3)
            self.ax_therm.legend(loc="best", fontsize=9)
        self.ax_therm.set_xlabel("time [s]")
        self.ax_therm.set_ylabel("temperature [C]")
        self.ax_therm.set_title("thermal envelope")
        self.ax_therm.grid(True, ls="--", alpha=0.4)

        cur = parser.current
        if cur is not None:
            self.fig.suptitle("WAAM live residual monitor   |   step %d   t = %.4f s   |R| = %.3e"
                               % (cur.index, cur.time,
                                  cur.nl[-1] if cur.nl else float("nan")))
        if self._first:
            plt.tight_layout()
            self._first = False
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _guess_csv(log_path: str) -> str:
    base = os.path.splitext(log_path)[0]
    for cand in (base + ".csv", base + "_out.csv", base + "_out.e"):
        if cand.endswith(".csv") and os.path.exists(cand):
            return cand
    return ""


def _has_display() -> bool:
    if os.environ.get("WAAM_LIVE_ASCII"):
        return False
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY"))


def monitor(log_path: str, run_cmd: str = "", csv_path: str = "",
            ascii_mode: bool = False, json_out: str = "",
            refresh: float = 0.4, idle_timeout: float = 30.0) -> int:
    """Monitor a MOOSE run until it finishes. Returns a process exit code."""
    parser = LogParser()
    if not csv_path:
        csv_path = _guess_csv(log_path)
    if csv_path:
        parser.set_csv(csv_path)
        print("[waam_live] thermal envelope CSV: %s" % csv_path)

    proc: Optional[subprocess.Popen] = None
    log_handle = None
    writer = None
    if run_cmd:
        # The child writes to a PIPE and we own the log file. Sharing one file
        # descriptor between the reader and the writer corrupts the file (both
        # advance the same offset), and a file-backed stdout is block-buffered
        # so the residual stream would arrive in 4 KB lumps.
        proc = subprocess.Popen(run_cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        writer = open(log_path, "w", errors="ignore")
        print("[waam_live] launched: %s" % run_cmd)
    else:
        log_handle = open(log_path, "r", errors="ignore")
        # Attach mode: follow a live run from the tail. If the log already
        # holds a finished solve, replay it from the start instead.
        replay = False
        try:
            with open(log_path, "r", errors="ignore") as probe:
                probe.seek(0, os.SEEK_END)
                size = probe.tell()
                probe.seek(max(0, size - 65536))
                tail = probe.read()
            if "Finished Executing" in tail:
                log_handle.seek(0)
                replay = True
                print("[waam_live] replaying the completed log %s" % log_path)
            else:
                log_handle.seek(0, os.SEEK_END)
        except OSError:
            log_handle.seek(0, os.SEEK_END)

    renderer = None
    ascii_renderer = None
    if not ascii_mode and _has_display():
        try:
            renderer = PlotRenderer()
        except Exception as exc:  # pragma: no cover - GUI availability
            print("[waam_live] no GUI (%s); falling back to the terminal view" % exc)
            renderer = None
    if renderer is None:
        ascii_renderer = AsciiRenderer()

    parser.read_csv()

    start = time.time()
    partial = ""
    last_csv = 0.0
    last_render = 0.0

    # Pipe mode: a dedicated reader thread drains stdout at full speed into a
    # queue. Rendering EVERY line re-plots the whole residual history in
    # matplotlib, which cannot keep up with MOOSE's ~700 lines per solver
    # iteration — the pipe then fills and the solver blocks in write() at 0%
    # CPU (observed 24 Oct 2026: 7 min of monitor CPU vs 4.5 s of solver CPU
    # after 8 min). The main loop therefore drains the queue completely first
    # and only redraws at the --refresh cadence.
    line_queue: "queue.Queue[Optional[str]]" = queue.Queue()
    reader_done = threading.Event()

    def _reader() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line_queue.put(line)
        except Exception:
            pass
        finally:
            reader_done.set()
            line_queue.put(None)

    if proc is not None:
        threading.Thread(target=_reader, daemon=True, name="waam_live_reader").start()

    try:
        while True:
            if proc is not None:
                # Drain every buffered line BEFORE considering a render.
                got_any = False
                while True:
                    try:
                        line = line_queue.get_nowait()
                    except queue.Empty:
                        break
                    if line is None:
                        continue
                    got_any = True
                    writer.write(line)
                    parser.feed(line)
                if got_any:
                    writer.flush()
                elif reader_done.is_set() and line_queue.empty():
                    break
                else:
                    time.sleep(0.02)
            else:
                chunk = log_handle.read()
                if chunk:
                    partial += chunk
                    while "\n" in partial:
                        raw, partial = partial.split("\n", 1)
                        parser.feed(raw)
                else:
                    if replay:
                        # the log is complete: nothing more will be written
                        break
                    if not os.path.exists(log_path):
                        break
                    # Attaching to a run that is not actually progressing: if the
                    # log has not grown for idle_timeout seconds, stop waiting.
                    try:
                        if time.time() - os.path.getmtime(log_path) > idle_timeout:
                            print("[waam_live] the log has not changed for %.0f s; "
                                  "stopping" % idle_timeout)
                            break
                    except OSError:
                        break
                    time.sleep(0.05)

            now = time.time()
            if now - last_csv >= max(1.0, refresh * 5):
                last_csv = now
                parser.read_csv()

            # Throttled redraw: at most one render per --refresh seconds.
            if now - last_render >= refresh:
                last_render = now
                if renderer is not None:
                    renderer.update(parser)
                    plt_pause = getattr(renderer, "plt", None)
                    if plt_pause is not None:
                        plt_pause.pause(0.01)
                elif ascii_renderer is not None:
                    ascii_renderer.draw(parser, now - start)

            if parser.finished:
                break
    except KeyboardInterrupt:
        print("\n[waam_live] interrupted")
        if proc is not None:
            proc.terminate()
        return 130
    finally:
        if log_handle is not None:
            log_handle.close()
        if writer is not None:
            writer.close()

    if renderer is not None:
        try:
            renderer.fig.savefig(os.path.splitext(log_path)[0] + "_live.png", dpi=110)
            print("[waam_live] wrote %s_live.png" % os.path.splitext(log_path)[0])
        except Exception:
            pass
    else:
        # Final summary (the live view is already on screen; this is the
        # scroll-back copy).
        print()
        print(ascii_renderer.render(parser, time.time() - start))

    if json_out:
        payload = {
            "steps": [
                {
                    "index": s.index, "time": s.time, "dt": s.dt,
                    "nl": s.nl, "lin": s.lin, "damping": s.damping,
                    "diverged": s.diverged, "reason": s.reason,
                }
                for s in parser.steps
            ],
            "csv": parser.csv_rows,
            "finished": parser.finished,
            "fatal": parser.fatal,
            "error": parser.error,
        }
        Path(json_out).write_text(json.dumps(payload, indent=1))
        print("[waam_live] wrote %s" % json_out)

    if parser.fatal:
        print("[waam_live] the solve FAILED: %s" % parser.error)
        return 1
    if proc is not None:
        return proc.returncode or 0
    return 0


def _resolve_case(case_dir: str) -> Tuple[str, str, str]:
    """Resolve (app, input_file, log_path) for a WAAM run directory.

    The run layout is <case>/moose/waam_moose.i; the executable lives in the
    MOOSE app checkout ($WAAM_MOOSE_HOME/waam_moose/waam_moose-opt).
    """
    case = Path(case_dir).resolve()
    moose_dir = case / "moose" if (case / "moose").is_dir() else case
    inputs = sorted(moose_dir.glob("*.i"))
    if not inputs:
        raise SystemExit("[waam_live] no .i input found under %s" % moose_dir)
    input_file = str(inputs[0])

    home = Path(os.environ.get("WAAM_MOOSE_HOME", case.parent.parent / "WAAM-MOOSE"))
    candidates = [
        home / "waam_moose" / "waam_moose-opt",
        home / "waam_moose" / "waam_moose",
        Path(__file__).resolve().parent.parent.parent / "WAAM-MOOSE" / "waam_moose" / "waam_moose-opt",
    ]
    app = ""
    for cand in candidates:
        if cand.exists() and os.access(str(cand), os.X_OK):
            app = str(cand)
            break
    if not app:
        raise SystemExit("[waam_live] waam_moose executable not found; set WAAM_MOOSE_HOME")
    log_path = str(moose_dir / (Path(input_file).stem + ".log"))
    return app, input_file, log_path


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="WAAM live residual monitor (pyFoam-style)")
    ap.add_argument("--log", help="MOOSE console log to tail")
    ap.add_argument("--run", help="command to launch (the log is written to --log)")
    ap.add_argument("--case", help="WAAM run directory: resolves the .i, the app and the log")
    ap.add_argument("--csv", help="run CSV (tmin/tmax envelope); auto-detected by default")
    ap.add_argument("--ascii", action="store_true", help="force the terminal renderer")
    ap.add_argument("--json", help="write the parsed history to this JSON file")
    ap.add_argument("--refresh", type=float, default=0.4, help="screen refresh interval [s]")
    ap.add_argument("--idle-timeout", type=float, default=30.0,
                    help="stop waiting after this many seconds without new log output [s]")
    args = ap.parse_args(argv)

    if not args.log and not args.run and not args.case:
        ap.error("give --log <file>, --run <command> and/or --case <run_dir>")

    if args.case:
        app, input_file, log_path = _resolve_case(args.case)
        args.log = args.log or log_path
        args.run = args.run or ('"%s" -i "%s"' % (app, input_file))
        print("[waam_live] case: %s" % input_file)
        print("[waam_live] app:   %s" % app)

    log_path = args.log or "waam_live.log"
    return monitor(log_path, run_cmd=args.run or "", csv_path=args.csv or "",
                   ascii_mode=args.ascii, json_out=args.json or "",
                   refresh=args.refresh, idle_timeout=args.idle_timeout)


if __name__ == "__main__":
    sys.exit(main())
