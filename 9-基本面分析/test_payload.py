import sys
from pathlib import Path
sys.path.insert(0, str(Path("ops/nanoclaw/core_task1/narrative/scripts").resolve()))
import narrative_analyzer as na

analyzer = na.NarrativeAnalyzer()
c, e = analyzer._build_structured_payload([], [], 0.0, 0.0, "2026-04-12")
print("Contract keys:", list(c.keys()))
print("Extended keys:", list(e.keys()))
