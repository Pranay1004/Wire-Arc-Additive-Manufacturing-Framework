#!/usr/bin/env python3
"""scripts/agent/pipe_pulse.py — unbuffered pipe pulse test (B2.3)."""
import subprocess, sys, time, os

child_code = """
import sys, time
time.sleep(1.0)
for i in range(200):
    print(f"PULSE line {i}")
    sys.stdout.flush()
"""

# Use -u flag for unbuffered
cmd = [sys.executable, "-u", "-c", child_code]

t0 = time.perf_counter()
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
first_line = None
while True:
    line = proc.stdout.readline()
    if not line:
        break
    if first_line is None:
        first_line = time.perf_counter() - t0
        print(f"First chunk latency: {first_line:.3f}s")
        if first_line > 2.0:
            print("  FAIL: first chunk > 2s (Windows buffering issue)")
            break
proc.wait()
elapsed = time.perf_counter() - t0
print(f"pipe_pulse: total={elapsed:.3f}s first_chunk={first_line:.3f}s")
print(f"RESULT pipe_pulse first_chunk_s={first_line:.3f}")
