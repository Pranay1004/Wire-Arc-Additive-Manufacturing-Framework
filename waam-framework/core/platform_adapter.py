#!/usr/bin/env python3
"""
WAAM Multi-Physics Simulator — Cross-Computer & Cross-Architecture Platform Adapter

Provides unified, robust abstraction for:
  1. CPU Architecture & Operating System detection (Apple Silicon arm64, x86_64, aarch64, Linux, macOS, Windows/WSL2).
  2. Solver Binary Discovery (FreeFem++, ff-mpirun, FreeFem++-mpi, Gmsh, ParaView, OpenFOAM).
  3. Linear Algebra & Threading Environment Configuration (Apple Accelerate/vecLib, Intel MKL, OpenBLAS, OpenMP).
  4. Cross-Platform Path Normalization (forward-slash normalization for FreeFEM C++ scripts on Windows).
  5. Unbuffered Process Spawning without POSIX 'script' command dependency on Windows.
  6. Native OS File Manager & Browser Integration.
"""

import glob
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Absolute repo root (WAAM-Framework/), independent of the process cwd.
# The GUI may be launched from a .app bundle, a desktop shortcut, or any
# other directory, so all framework-relative paths must anchor here instead
# of the cwd (P-09).
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent


def framework_path(*parts: str) -> str:
    """Absolute path under the WAAM-Framework repo root."""
    return str(FRAMEWORK_ROOT.joinpath(*parts))


def default_output_dir() -> str:
    """Absolute path of the canonical waam_output/ directory."""
    return str(FRAMEWORK_ROOT / "waam_output")


def default_stl_dir() -> str:
    """Absolute path of the canonical stl/ asset directory."""
    return str(FRAMEWORK_ROOT / "stl")


def resolve_output_dir(value: Optional[str] = None) -> str:
    """Resolve an output_dir value to an absolute path, cwd-independently.

    Empty/None or any cwd-relative default (./waam_output) resolves to the
    framework's waam_output/; other relative values resolve against the repo
    root so results never depend on where the process was launched.
    """
    v = str(value or "").strip()
    if not v or v in ("./waam_output", "./waam_output/", "waam_output", "waam_output/"):
        return default_output_dir()
    p = Path(v)
    if not p.is_absolute():
        p = FRAMEWORK_ROOT / v
    return str(p.resolve())


@dataclass(frozen=True)
class SystemArchitecture:
    """Hardware and operating system profile of the host machine."""
    os_name: str           # "darwin", "linux", "win32"
    machine: str           # "arm64", "x86_64", "aarch64", "AMD64"
    is_apple_silicon: bool # True if Apple M1/M2/M3/M4 macOS
    is_macos: bool
    is_linux: bool
    is_windows: bool
    is_wsl: bool
    cpu_count: int
    python_version: str


def detect_system() -> SystemArchitecture:
    """Detect and return complete host system architecture profile."""
    os_name = sys.platform
    machine = platform.machine()
    is_macos = (os_name == "darwin")
    is_linux = (os_name.startswith("linux"))
    is_windows = (os_name == "win32")
    is_apple_silicon = bool(is_macos and machine in ("arm64", "aarch64"))
    
    # Check for Windows Subsystem for Linux (WSL)
    is_wsl = False
    if is_linux:
        try:
            with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
                if "microsoft" in f.read().lower():
                    is_wsl = True
        except Exception:
            pass

    cpu_count = os.cpu_count() or 4

    return SystemArchitecture(
        os_name=os_name,
        machine=machine,
        is_apple_silicon=is_apple_silicon,
        is_macos=is_macos,
        is_linux=is_linux,
        is_windows=is_windows,
        is_wsl=is_wsl,
        cpu_count=cpu_count,
        python_version=platform.python_version()
    )


# Global singleton
HOST_ARCH = detect_system()


# -----------------------------------------------------------------------------
# Solver & Executable Discovery
# -----------------------------------------------------------------------------

def find_freefem_serial() -> str:
    """
    Locates the serial FreeFEM++ binary across all major OS and installation layouts.
    Returns absolute path or empty string if not found.
    """
    # 1. User explicit environment variable
    env_bin = os.environ.get("FREEFEM_BIN", "").strip()
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return os.path.abspath(env_bin)

    # 2. PATH resolution
    found = shutil.which("FreeFem++") or shutil.which("ff")
    if found:
        return os.path.abspath(found)

    # 3. macOS Application & Homebrew paths
    if HOST_ARCH.is_macos:
        candidates = [
            "/Applications/FreeFem++.app/Contents/ff-4.15/bin/FreeFem++",
            "/Applications/FreeFem++.app/Contents/Resources/bin/FreeFem++",
            "/opt/homebrew/bin/FreeFem++",       # Apple Silicon Homebrew
            "/usr/local/bin/FreeFem++",          # Intel Mac Homebrew
            os.path.expanduser("~/Applications/FreeFem++.app/Contents/ff-4.15/bin/FreeFem++"),
        ]
        # Check dynamic version paths like ff-4.14, ff-4.16, etc.
        dyn_apps = glob.glob("/Applications/FreeFem++.app/Contents/ff-*/bin/FreeFem++")
        candidates = dyn_apps + candidates
        for cand in candidates:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return os.path.abspath(cand)

    # 4. Linux standard packaging paths / WSL2 interop (solver on Windows host)
    elif HOST_ARCH.is_linux:
        if HOST_ARCH.is_wsl:
            # WSL2: FreeFEM is a Windows binary mounted under /mnt/c.
            # Probe the common installer layouts (verified on this host:
            # C:\\Program Files (x86)\\FreeFem++\\FreeFem++.exe).
            wsl_candidates = [
                "/mnt/c/Program Files (x86)/FreeFem++/FreeFem++.exe",
                "/mnt/c/Program Files/FreeFem++/FreeFem++.exe",
                "/mnt/c/Program Files (x86)/FreeFem++/bin/FreeFem++.exe",
                "/mnt/c/Program Files/FreeFem++/bin/FreeFem++.exe",
                "/mnt/c/FreeFem++/FreeFem++.exe",
                "/mnt/c/FreeFem++/bin/FreeFem++.exe",
            ]
            wsl_candidates += glob.glob("/mnt/c/Program Files*/FreeFem++/**/FreeFem++.exe", recursive=True)
            wsl_candidates += glob.glob("/mnt/c/FreeFem++/**/FreeFem++.exe", recursive=True)
            for cand in wsl_candidates:
                if os.path.isfile(cand):
                    return os.path.abspath(cand)
            # fall through to native-Linux candidates below (in case a Linux
            # FreeFEM was also installed inside WSL)
        candidates = [
            "/usr/bin/FreeFem++",
            "/usr/local/bin/FreeFem++",
            "/opt/freefem/bin/FreeFem++",
            "/opt/freefem++/bin/FreeFem++",
            "/usr/lib/freefem++/bin/FreeFem++",
            os.path.expanduser("~/.local/bin/FreeFem++"),
        ]
        for cand in candidates:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return os.path.abspath(cand)

    # 5. Windows standard installer paths
    elif HOST_ARCH.is_windows:
        candidates = [
            r"C:\Program Files\FreeFem++\bin\FreeFem++.exe",
            r"C:\Program Files\FreeFem++\FreeFem++.exe",
            r"C:\Program Files (x86)\FreeFem++\bin\FreeFem++.exe",
            r"C:\Program Files (x86)\FreeFem++\FreeFem++.exe",
            r"C:\FreeFem++\bin\FreeFem++.exe",
            r"C:\FreeFem++\FreeFem++.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeFem++\FreeFem++.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\FreeFem++\bin\FreeFem++.exe"),
            os.path.expandvars(r"%PROGRAMFILES(x86)%\FreeFem++\FreeFem++.exe"),
        ]
        for cand in candidates:
            if os.path.isfile(cand):
                return os.path.abspath(cand)

    return ""


def find_freefem_mpi() -> Tuple[str, str]:
    """
    Locates the MPI runner wrapper and FreeFEM++-mpi executable.
    Returns (ff_mpirun_path, freefem_mpi_path).
    """
    # 1. Environment variables
    mpirun_env = os.environ.get("FF_MPIRUN", "").strip()
    mpibin_env = os.environ.get("FREEFEM_MPI", "").strip()

    mpirun = mpirun_env if (mpirun_env and os.path.isfile(mpirun_env)) else ""
    mpibin = mpibin_env if (mpibin_env and os.path.isfile(mpibin_env)) else ""

    # 2. PATH resolution
    if not mpirun:
        mpirun = shutil.which("ff-mpirun") or ""
    if not mpibin:
        mpibin = shutil.which("FreeFem++-mpi") or ""

    # 3. macOS candidate locations
    if HOST_ARCH.is_macos:
        app_dirs = glob.glob("/Applications/FreeFem++.app/Contents/ff-*/bin")
        if not app_dirs:
            app_dirs = ["/Applications/FreeFem++.app/Contents/ff-4.15/bin"]
        for bdir in app_dirs:
            if not mpirun:
                p = os.path.join(bdir, "ff-mpirun")
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    mpirun = p
            if not mpibin:
                p = os.path.join(bdir, "FreeFem++-mpi")
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    mpibin = p

        # Fallback Homebrew paths
        brew_prefix = "/opt/homebrew/bin" if HOST_ARCH.is_apple_silicon else "/usr/local/bin"
        if not mpirun:
            p = os.path.join(brew_prefix, "ff-mpirun")
            if os.path.isfile(p):
                mpirun = p
        if not mpibin:
            p = os.path.join(brew_prefix, "FreeFem++-mpi")
            if os.path.isfile(p):
                mpibin = p

    # 4. Linux candidate locations / WSL2 interop
    elif HOST_ARCH.is_linux:
        if HOST_ARCH.is_wsl:
            # WSL2: MPI runner + solver are Windows binaries under /mnt/c.
            win_mpi_dirs = [
                r"/mnt/c/Program Files (x86)/FreeFem++/bin",
                r"/mnt/c/Program Files/FreeFem++/bin",
                r"/mnt/c/Program Files (x86)/FreeFem++",
                r"/mnt/c/Program Files/FreeFem++",
            ]
            for bdir in win_mpi_dirs:
                if not mpirun:
                    for name in ("ff-mpirun.bat", "ff-mpirun.exe", "ff-mpirun"):
                        p = os.path.join(bdir, name)
                        if os.path.isfile(p):
                            mpirun = p
                            break
                if not mpibin:
                    p = os.path.join(bdir, "FreeFem++-mpi.exe")
                    if os.path.isfile(p):
                        mpibin = p
            # also discover any nested install
            if not mpibin:
                for p in glob.glob("/mnt/c/Program Files*/FreeFem++/**/FreeFem++-mpi.exe", recursive=True):
                    mpibin = p
                    break
            if not mpirun:
                for p in glob.glob("/mnt/c/Program Files*/FreeFem++/**/ff-mpirun*", recursive=True):
                    mpirun = p
                    break
            # fall through to native-Linux candidates below
        linux_dirs = ["/usr/bin", "/usr/local/bin", "/opt/freefem/bin", "/usr/lib64/openmpi/bin"]
        for bdir in linux_dirs:
            if not mpirun:
                p = os.path.join(bdir, "ff-mpirun")
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    mpirun = p
            if not mpibin:
                p = os.path.join(bdir, "FreeFem++-mpi")
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    mpibin = p
    # 5. Windows candidate locations
    elif HOST_ARCH.is_windows:
        win_dirs = [
            r"C:\Program Files\FreeFem++\bin",
            r"C:\Program Files\FreeFem++",
            r"C:\Program Files (x86)\FreeFem++\bin",
            r"C:\Program Files (x86)\FreeFem++",
            r"C:\FreeFem++\bin",
            r"C:\FreeFem++",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeFem++\bin"),
        ]
        for bdir in win_dirs:
            if not mpirun:
                p = os.path.join(bdir, "ff-mpirun.bat")
                if not os.path.isfile(p):
                    p = os.path.join(bdir, "ff-mpirun.exe")
                if os.path.isfile(p):
                    mpirun = p
            if not mpibin:
                p = os.path.join(bdir, "FreeFem++-mpi.exe")
                if os.path.isfile(p):
                    mpibin = p

    return mpirun, mpibin


def find_paraview() -> str:
    """Locate ParaView executable across macOS, Linux, and Windows."""
    env_pv = os.environ.get("PARAVIEW_BIN", "").strip()
    if env_pv and os.path.isfile(env_pv):
        return env_pv

    found = shutil.which("paraview")
    if found:
        return found

    if HOST_ARCH.is_macos:
        mac_cands = glob.glob("/Applications/ParaView*.app/Contents/MacOS/paraview")
        if mac_cands:
            return max(mac_cands)  # pick latest version
        if HOST_ARCH.is_apple_silicon and os.path.isfile("/opt/homebrew/bin/paraview"):
            return "/opt/homebrew/bin/paraview"

    elif HOST_ARCH.is_windows:
        win_cands = glob.glob(r"C:\Program Files\ParaView*\bin\paraview.exe")
        if win_cands:
            return max(win_cands)

    return ""


def find_gmsh() -> str:
    """Locate Gmsh mesh generator executable."""
    env_gmsh = os.environ.get("GMSH_BIN", "").strip()
    if env_gmsh and os.path.isfile(env_gmsh):
        return env_gmsh

    found = shutil.which("gmsh")
    if found:
        return found

    if HOST_ARCH.is_macos:
        mac_cands = [
            "/Applications/Gmsh.app/Contents/MacOS/gmsh",
            "/opt/homebrew/bin/gmsh",
            "/usr/local/bin/gmsh",
        ]
        for cand in mac_cands:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand

    elif HOST_ARCH.is_windows:
        win_cands = [
            r"C:\Program Files\gmsh\gmsh.exe",
            r"C:\gmsh\gmsh.exe",
        ]
        for cand in win_cands:
            if os.path.isfile(cand):
                return cand

    return ""


# -----------------------------------------------------------------------------
# Cross-Architecture Parallel Environment Tuning
# -----------------------------------------------------------------------------

def configure_parallel_environment(n_threads: Optional[int] = None, solver: str = "MUMPS") -> Dict[str, str]:
    """
    Constructs optimal OS/CPU-tailored environment variables for shared-memory multithreading.
    Automatically accounts for Apple Accelerate, Intel MKL, and OpenBLAS/OpenMP backends.
    """
    total_cores = HOST_ARCH.cpu_count
    if n_threads is None or n_threads <= 0:
        # Default: leave 1 core for OS/GUI, saturate remaining cores
        n_threads = max(1, total_cores - 1)
    else:
        n_threads = min(n_threads, total_cores)

    env = os.environ.copy()
    str_threads = str(n_threads)

    # 1. Standard OpenMP
    env["OMP_NUM_THREADS"] = str_threads

    # 2. Architecture & Library specific tuning
    if HOST_ARCH.is_apple_silicon:
        # macOS Apple Accelerate / vecLib framework
        env["VECLIB_MAXIMUM_THREADS"] = str_threads
        env["NUMEXPR_NUM_THREADS"] = str_threads
        env["OPENBLAS_NUM_THREADS"] = str_threads
    else:
        # x86_64 / Linux / Windows
        env["MKL_NUM_THREADS"] = str_threads
        env["OPENBLAS_NUM_THREADS"] = str_threads
        env["NUMEXPR_NUM_THREADS"] = str_threads

    # 3. MUMPS library thread configuration
    if solver.upper() == "MUMPS":
        env["MUMPS_NUM_THREADS"] = str_threads

    return env


# -----------------------------------------------------------------------------
# Script & Path Normalization (CRITICAL for FreeFEM & OpenFOAM on Windows)
# -----------------------------------------------------------------------------

def is_windows_solver_path(path: str) -> bool:
    """True if `path` refers to a Windows-side binary (native win32 or WSL interop)."""
    if not path:
        return False
    if HOST_ARCH.is_windows:
        return True
    if HOST_ARCH.is_wsl:
        pp = str(path).replace("\\", "/")
        return pp.lower().startswith("/mnt/") or (len(pp) >= 2 and pp[1] == ":" and pp[0].isalpha())
    return False


def to_windows_path(filepath: str) -> str:
    """Translate a path to a Windows-native form (X:\\...). On WSL2 this uses
    `wslpath -w` with a pure-Python /mnt/<drive>/... fallback. Elsewhere it
    returns the (backslash-normalized) absolute path."""
    if not filepath:
        return ""
    p = str(filepath).replace("\\", "/")
    if HOST_ARCH.is_wsl:
        import subprocess as _sp
        try:
            out = _sp.run(["wslpath", "-w", p], capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            pass
        import re as _re
        mm = _re.match(r"^/mnt/([a-zA-Z])/(.*)$", p)
        if mm:
            drive = mm.group(1).upper()
            rest = mm.group(2).replace("/", "\\")
            return f"{drive}:\\{rest}"
        if len(p) >= 2 and p[1] == ":":
            return p.replace("/", "\\")
    if not os.path.isabs(p) and not (len(p) >= 2 and p[1] == ":"):
        try:
            p = os.path.abspath(p)
        except Exception:
            pass
    return p.replace("/", "\\") if HOST_ARCH.is_windows else p


import threading as _threading

_stat_cache = {}
_stat_cache_lock = _threading.Lock()


def stat_fingerprint(path, ttl_ms: float = 250.0):
    """Return (abspath, mtime_ns, size) for `path`, memoized with a short TTL.

    Use this instead of raw os.stat() in hot paths / stat-gated caches to avoid
    repeated syscalls (huge win on 9p/WSL/drive mounts). ttl_ms trades staleness
    for speed; pass 0 to disable memoization.
    """
    import time as _time
    key = str(path)
    now = _time.monotonic() * 1000.0
    with _stat_cache_lock:
        entry = _stat_cache.get(key)
        if entry is not None and ttl_ms > 0 and (now - entry[0]) < ttl_ms:
            return entry[1]
    st = os.stat(path)
    fp = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    with _stat_cache_lock:
        _stat_cache[key] = (now, fp)
    return fp


def to_solver_path(filepath: str) -> str:
    """
    Normalize a path into a form safe to embed in a FreeFEM++ (.edp) string
    literal or pass as argv to the solver.

    - Backslashes -> forward slashes (FreeFEM C++ string literals treat backslash
      as an escape character).
    - Under WSL2, drvfs paths (/mnt/<drive>/...) are translated to Windows form
      (X:/...) because the consumer is FreeFEM++.exe on the Windows host.
    - Result is always absolute.
    """
    if not filepath:
        return ""
    p = str(filepath).replace("\\", "/")
    if HOST_ARCH.is_wsl and p.lower().startswith("/mnt/"):
        p = to_windows_path(p).replace("\\", "/")
    if not (len(p) >= 2 and p[1] == ":") and not os.path.isabs(p):
        try:
            p = os.path.abspath(p)
        except Exception:
            pass
    return p.replace("\\", "/")

# -----------------------------------------------------------------------------
# Cross-Platform File Opening & UI Integration
# -----------------------------------------------------------------------------

def open_path_in_file_manager(target_path: str):
    """Opens a directory or file in the native operating system file explorer."""
    target_path = os.path.abspath(target_path)
    if not os.path.exists(target_path):
        os.makedirs(target_path, exist_ok=True)

    try:
        if HOST_ARCH.is_macos:
            subprocess.Popen(["open", target_path])
        elif HOST_ARCH.is_windows:
            os.startfile(target_path)
        else: # Linux / BSD
            subprocess.Popen(["xdg-open", target_path])
    except Exception as e:
        sys.stderr.write(f"[PLATFORM] Warning: Failed to open {target_path}: {e}\n")


def open_url_in_browser(url: str):
    """Opens a URL or local HTML file in the user's default web browser."""
    import webbrowser
    webbrowser.open(url)


# -----------------------------------------------------------------------------
# Cross-Platform Process Runner (Defeats Pipe Buffering on Windows & POSIX)
# -----------------------------------------------------------------------------

def build_unbuffered_command(cmd: List[str]) -> Tuple[List[str], bool]:
    """
    Returns (wrapped_cmd, used_script_wrapper).
    
    On macOS and Linux, the POSIX 'script' command creates a pseudo-terminal (pty)
    that forces child processes to flush stdout line-by-line rather than 4KB buffering.
    On Windows, 'script' does not exist, so the raw command must be run directly.
    """
    if HOST_ARCH.is_windows:
        return cmd, False

    # Under WSL2 the solver is a Windows .exe; wrapping it in the POSIX `script`
    # pty breaks interop/quoting, and Windows FreeFEM does not need it.
    if HOST_ARCH.is_wsl and cmd and is_windows_solver_path(str(cmd[0])):
        return list(cmd), False

    script_bin = shutil.which("script")
    if not script_bin:
        return list(cmd), False

    if HOST_ARCH.is_macos:
        # macOS syntax: script -q /dev/null cmd arg1 arg2 ...
        return [script_bin, "-q", "/dev/null"] + cmd, True
    elif HOST_ARCH.is_linux:
        # Linux util-linux syntax: script -q -c "cmd arg1 arg2 ..." /dev/null
        import shlex
        escaped_cmd = " ".join(shlex.quote(c) for c in cmd)
        return [script_bin, "-q", "-c", escaped_cmd, "/dev/null"], True

    return cmd, False


def spawn_isolation_kwargs() -> Dict:
    """
    Popen kwargs that put the solver in its OWN process group/session.

    Why this exists: on POSIX the 'script' wrapper spawns FreeFem++ as a
    grandchild; killing only the direct child leaves the real solver running
    (visible as PermissionError on the next run's file copy). On Windows,
    taskkill /T walks the child tree from the recorded PID instead.
    """
    if HOST_ARCH.is_windows:
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def kill_process_tree(proc: "subprocess.Popen") -> bool:
    """
    Terminate proc AND every descendant. Returns True if the tree was reaped.

    Replaces the old pattern where os.killpg was unreachable (the terminate()
    branch always won the retry loop) and where no session was ever created,
    so a group kill would have hit the GUI's own process group.
    """
    if proc.poll() is None:
        if HOST_ARCH.is_windows or HOST_ARCH.is_wsl:
            if HOST_ARCH.is_wsl:
                # Under WSL, proc.pid is the WSL interop stub; taskkill.exe cannot
                # resolve it (verified: "process not found"). proc.kill() DOES
                # propagate to the Windows child (verified). Escalate to an
                # image-name kill only if the stub reaping fails.
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=8)
                    return True
                except Exception:
                    pass
                # Fallback: kill every FreeFEM instance (single-user workstation).
                try:
                    subprocess.run(
                        ["taskkill.exe", "/IM", "FreeFem++.exe", "/F", "/T"],
                        capture_output=True, timeout=15,
                    )
                    subprocess.run(
                        ["taskkill.exe", "/IM", "FreeFem++-mpi.exe", "/F", "/T"],
                        capture_output=True, timeout=15,
                    )
                except Exception:
                    pass
            else:
                # Native Windows: taskkill walks the child tree from the PID.
                try:
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        capture_output=True, timeout=15,
                    )
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        else:
            # start_new_session=True was set at spawn, so getpgid() is the
            # solver's OWN group (script -> sh -> FreeFem++), never ours.
            try:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except Exception:
                    pass
    try:
        proc.wait(timeout=8)
        return True
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=4)
        except Exception:
            pass
        return False
