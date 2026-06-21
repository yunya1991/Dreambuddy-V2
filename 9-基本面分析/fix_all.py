import os
import json
import glob
from pathlib import Path

# Remove old json and md files to ensure fresh reads
flows_dir = Path("ops/nanoclaw/core_task1/flow/outputs")
for p in flows_dir.glob("*"):
    if p.name.startswith("flow_regime_") or p.name.startswith("flow_analysis_"):
        p.unlink()

print("Cleaned up old files.")
