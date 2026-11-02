#!/usr/bin/env python3
"""scripts/agent/log_reload_bench.py — F4.2 largest sim.log reload timing."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import tkinter as tk
from gui.tabs.sim_log_tab import log_reload

root = tk.Tk()
root.withdraw()

waam_out = Path(__file__).resolve().parents[2] / "waam_output"
logs = list(waam_out.rglob("sim.log"))
largest = max(logs, key=lambda p: p.stat().st_size) if logs else None
if not largest:
    print("No sim.log found")
    sys.exit(1)

print(f"log_reload_bench: {largest} ({largest.stat().st_size} bytes)")

class MockApp:
    def __init__(self):
        self.root = root
        self.log_text = tk.Text(root)
        self.log_text.pack()
        self._log_buffer = []
        self._log_timer = None

app = MockApp()
t0 = time.perf_counter()
log_reload(app)  # log_reload takes only app, reads from app.settings
t1 = time.perf_counter() - t0
lines = int(app.log_text.index("end-1c").split(".")[0])
print(f"  reload: {t1*1000:.1f}ms lines={lines} (target: bulk grouped <= 60ms)")
print("RESULT log_reload_bench complete")
root.destroy()
