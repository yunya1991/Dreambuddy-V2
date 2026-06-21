import os
import glob
from pathlib import Path

flows_dir = Path("ops/nanoclaw/core_task1/narrative/outputs")
for p in flows_dir.glob("*"):
    if p.name.startswith("narrative_") and not p.name.startswith("narrative_20260412"):
        p.unlink()
print("Cleaned up old narrative outputs.")
