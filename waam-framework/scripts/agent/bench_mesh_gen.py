#!/usr/bin/env python3
"""scripts/agent/bench_mesh_gen.py — F1.4 mesh gen bench (off Tk thread)."""
import sys, time, threading, queue
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gui.controllers.mesh_controller import generate_waam_mesh

# Test targets
targets = [
    {"nx": 20, "ny": 8, "nz": 8, "label": "~5k"},
    {"nx": 60, "ny": 20, "nz": 20, "label": "~50k"},
]

def run_gen(params, q):
    try:
        t0 = time.perf_counter()
        result = generate_waam_mesh(params)
        t1 = time.perf_counter() - t0
        q.put(("ok", result, t1))
    except Exception as e:
        q.put(("err", str(e), 0))

for t in targets:
    q = queue.Queue()
    th = threading.Thread(target=run_gen, args=(t, q))
    th.start()
    th.join(timeout=120)
    status, result, elapsed = q.get()
    if status == "ok":
        nodes = result.get("n_nodes", 0)
        print(f"  {t['label']}: {elapsed:.1f}s nodes={nodes}")
    else:
        print(f"  {t['label']}: FAIL {result}")
print("RESULT bench_mesh_gen complete")
