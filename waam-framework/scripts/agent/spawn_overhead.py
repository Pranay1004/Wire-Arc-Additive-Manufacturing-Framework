#!/usr/bin/env python3
"""scripts/agent/spawn_overhead.py — F6.2 subprocess spawn cost."""
import sys, time, subprocess, statistics

times = []
for i in range(20):
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
    times.append(time.perf_counter() - t0)

print(f"spawn_overhead: mean={statistics.mean(times)*1000:.1f}ms p95={sorted(times)[int(len(times)*0.95)]*1000:.1f}ms (target <80ms)")
print("RESULT spawn_overhead complete")
