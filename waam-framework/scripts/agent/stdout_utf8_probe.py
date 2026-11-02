#!/usr/bin/env python3
"""scripts/agent/stdout_utf8_probe.py — child emits UTF-8; test decode paths."""
import subprocess, sys

# Child that prints UTF-8 chars (θ, °, µ, Erreur)
child = """
import sys
sys.stdout.write("θ=0.6° Ça marche\\n")
sys.stdout.write("µ=1.2e-6 Erreur de test\\n")
sys.stdout.flush()
"""

for label, kwargs in [
    ("default", {"text": True}),
    ("utf8_replace", {"text": True, "encoding": "utf-8", "errors": "replace"}),
    ("utf8_ignore", {"text": True, "encoding": "utf-8", "errors": "ignore"}),
]:
    try:
        proc = subprocess.run([sys.executable, "-c", child], capture_output=True, **kwargs)
        print(f"{label}: OK stdout={proc.stdout[:80]!r} stderr={proc.stderr[:80]!r}")
    except Exception as e:
        print(f"{label}: FAIL {e}")

print("RESULT stdout_utf8_probe complete")
