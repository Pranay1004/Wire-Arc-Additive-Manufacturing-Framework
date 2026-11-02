#!/usr/bin/env python3
"""scripts/agent/tk_latency.py — Tk event-loop latency probe (F4.1/F7.2)."""
import sys, time, subprocess

child = r'''
import sys, time, tkinter as tk

root = tk.Tk()
root.withdraw()
latencies = []

deadline = time.perf_counter() + 5
while time.perf_counter() < deadline:
    t0 = time.perf_counter()
    root.update_idletasks()
    root.update()
    latencies.append((time.perf_counter() - t0) * 1000)
    time.sleep(0.001)

if latencies:
    latencies.sort()
    p50 = latencies[len(latencies)//2]
    p95 = latencies[int(len(latencies)*0.95)]
    p99 = latencies[int(len(latencies)*0.99)]
    print(f"tk_latency: p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms n={len(latencies)}")
    print(f"RESULT tk_latency p50_ms={p50:.2f} p95_ms={p95:.2f} p99_ms={p99:.2f}")
else:
    print("tk_latency: no samples")
root.destroy()
'''

proc = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=15)
print(proc.stdout)
if proc.stderr:
    print("stderr:", proc.stderr[:300])