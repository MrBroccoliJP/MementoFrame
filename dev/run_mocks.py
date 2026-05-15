#!/usr/bin/env python3
"""Run both updated MementoFrame mock services."""
from __future__ import annotations

import os
import signal
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SERVICES = ["mock_config_portal_service.py", "mock_display_service.py"]
procs: list[subprocess.Popen] = []

try:
    for script in SERVICES:
        procs.append(subprocess.Popen([sys.executable, script], cwd=BASE))
    print()
    print("MementoFrame mock environment running")
    print("Config portal : http://localhost:5000")
    print("Display UI    : http://localhost:5001")
    print("Mock controls : http://localhost:5001/mock")
    print("Forced time   : http://localhost:5001/mock/time.json")
    print()
    print("Press CTRL+C to stop")
    for proc in procs:
        proc.wait()
except KeyboardInterrupt:
    print("\nStopping mocks...")
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
