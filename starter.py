#!/usr/bin/env python3
import subprocess
import os
from pathlib import Path

# ŚCIEŻKI
BASE_DIR = Path("/home/smart/Desktop/Smart_Mirror")
PYTHON = BASE_DIR / ".venv2" / "bin" / "python"
PIR_SCRIPT = BASE_DIR / "Czujniki" / "movement_PIR.py"
START_DESKTOP = BASE_DIR / "start_desktop.sh"

# OBSŁUGA PIR
# True -> startuje movement_PIR.py, który sam odpala aplikację przy ruchu
# False -> pomijamy PIR, od razu odpalamy start_desktop.sh
PIR_ENABLED = True


def main():
    os.chdir(BASE_DIR)

    if PIR_ENABLED:
        print("[STARTER] PIR_ENABLED = True -> uruchamiam movement_PIR.py")
        proc = subprocess.Popen([str(PYTHON), str(PIR_SCRIPT)])
    else:
        print("[STARTER] PIR_ENABLED = False -> uruchamiam start_desktop.sh bez PIR")
        proc = subprocess.Popen(["/bin/bash", str(START_DESKTOP)])

    # czekanie aż proces główny się skończy
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
