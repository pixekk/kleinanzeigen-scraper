import os
import sys
import time
from pathlib import Path

path = Path(os.getenv("HEARTBEAT_PATH", "data/heartbeat"))
max_age = int(os.getenv("HEARTBEAT_MAX_AGE", "600"))

if not path.exists():
    sys.exit(1)

age = time.time() - float(path.read_text(encoding="utf-8").strip())
sys.exit(0 if age < max_age else 1)
