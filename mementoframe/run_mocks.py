import subprocess
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))

procs = []

try:
    procs.append(
        subprocess.Popen([sys.executable, "mock_app.py"], cwd=BASE)
    )

    procs.append(
        subprocess.Popen([sys.executable, "mock_api_service.py"], cwd=BASE)
    )

    print()
    print("MementoFrame mock environment running")
    print("Admin dashboard : http://localhost:5000")
    print("Frontend API    : http://localhost:5001")
    print()
    print("Press CTRL+C to stop")

    for p in procs:
        p.wait()

except KeyboardInterrupt:
    print("\nStopping mocks...")

    for p in procs:
        p.terminate()