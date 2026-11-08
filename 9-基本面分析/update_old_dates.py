from pathlib import Path

flows_dir = Path("ops/nanoclaw/core_task1/flow/outputs")
for p in flows_dir.glob("*.json"):
    print("Found:", p)

from datetime import datetime, timezone  # noqa: E402

print(datetime.now(timezone.utc).strftime("%Y%m%d_%H%M"))
