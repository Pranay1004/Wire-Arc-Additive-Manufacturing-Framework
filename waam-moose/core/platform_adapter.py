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

    # 4. Linux standard packaging paths
    elif HOST_ARCH.is_linux:
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
            r"C:\FreeFem++\bin\FreeFem++.exe",
            r"C:\FreeFem++\FreeFem++.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeFem++\FreeFem++.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\FreeFem++\bin\FreeFem++.exe"),
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

    # 4. Linux candidate locations
    elif HOST_ARCH.is_linux:
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
            r"C:\FreeFem++\bin",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\FreeFem++\bin")
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

def to_solver_path(filepath: str) -> str:
    """
    Normalizes any file path into a format safe for embedding in FreeFEM++ (.edp)
    and OpenFOAM dictionary files.
    
    Converts Windows backslashes ('\\') to forward slashes ('/').
    FreeFEM C++ string literals interpret '\\' as escape characters (e.g., '\\n', '\\t'),
    which corrupts paths on Windows if not normalized.
    """
    if not filepath:
        return ""
    p = os.path.abspath(filepath)
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

    script_bin = shutil.which("script")
    if not script_bin:
        return cmd, False

    if HOST_ARCH.is_macos:
        # macOS syntax: script -q /dev/null cmd arg1 arg2 ...
        return [script_bin, "-q", "/dev/null"] + cmd, True
    elif HOST_ARCH.is_linux:
        # Linux util-linux syntax: script -q -c "cmd arg1 arg2 ..." /dev/null
        import shlex
        escaped_cmd = " ".join(shlex.quote(c) for c in cmd)
        return [script_bin, "-q", "-c", escaped_cmd, "/dev/null"], True

    return cmd, False
