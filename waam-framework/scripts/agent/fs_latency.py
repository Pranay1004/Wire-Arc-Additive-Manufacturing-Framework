#!/usr/bin/env python3
"""scripts/agent/fs_latency.py — 1000x1KB append+fsync benchmark."""
import os, time, tempfile

N = 1000
SIZE = 1024
data = b"x" * SIZE

with tempfile.TemporaryDirectory() as td:
    fpath = os.path.join(td, "bench.log")
    t0 = time.perf_counter()
    for i in range(N):
        with open(fpath, "ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    elapsed = time.perf_counter() - t0
    per_ms = (elapsed / N) * 1000
    print(f"fs_latency: N={N} size={SIZE}B elapsed={elapsed:.3f}s per_op={per_ms:.3f}ms")
    if per_ms > 1.0:
        print("  WARNING: >1ms/op — possible AV/sync interference (S0-adjacent)")
    print(f"RESULT fs_latency per_op_ms={per_ms:.3f}")
