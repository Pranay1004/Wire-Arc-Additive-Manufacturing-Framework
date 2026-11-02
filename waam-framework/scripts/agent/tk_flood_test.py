#!/usr/bin/env python3
"""scripts/agent/tk_flood_test.py — F4.3 synthetic 12k lines/s into _log_batch."""
import sys, time, threading, queue
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Import the app to access _log_batch
import gui.app as app_module
import tkinter as tk

root = tk.Tk()
root.withdraw()
app = app_module.WAAMApp.__new__(app_module.WAAMApp)
app.root = root
app.log_text = tk.Text(root)
app.log_text.pack()
app._log_buffer = []
app._log_timer = None
app._log_batch_size = 350
app._log_max_lines = 6000
app._log_tags = {"info": "black", "error": "red", "warn": "orange"}

def _log_batch():
    if not app._log_buffer:
        return
    batch = app._log_buffer[:app._log_batch_size]
    app._log_buffer = app._log_buffer[app._log_batch_size:]
    for tag, msg in batch:
        app.log_text.insert("end", msg, tag)
    if int(app.log_text.index("end-1c").split(".")[0]) > app._log_max_lines:
        app.log_text.delete("1.0", f"{int(app.log_text.index('end-1c').split('.')[0]) - app._log_max_lines}.0")
    app._log_timer = root.after(25, _log_batch)

app._log = lambda msg, tag="info": app._log_buffer.append((tag, msg)) or (app._log_timer or setattr(app, '_log_timer', root.after(25, _log_batch)))

# Flood 12k lines/s for 3s
lines_per_sec = 12000
duration = 3
total = lines_per_sec * duration
interval = 1.0 / lines_per_sec

t0 = time.perf_counter()
for i in range(total):
    app._log(f"Line {i}\n")
    time.sleep(interval)
# Drain (update() fires after() timers; update_idletasks() does not)
while app._log_buffer:
    root.update()
    time.sleep(0.01)
elapsed = time.perf_counter() - t0
print(f"tk_flood_test: {total} lines in {elapsed:.1f}s ({total/elapsed:.0f} lines/s)")
print(f"  buffer capped at 6000: {len(app.log_text.get('1.0', 'end-1c').splitlines())} lines in widget")
print("RESULT tk_flood_test complete")
root.destroy()
