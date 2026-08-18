from pathlib import Path
from typing import Any, Dict, Optional, Union

from workflows.memory.memory_engine.engine import MemoryEngine


PathLike = Union[str, Path]


def run_l3_longterm_maintenance(
    vector_dir: PathLike,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for longterm vector/index maintenance."""
    mem = engine or MemoryEngine()
    vector_artifacts = mem.build_vector_artifacts(Path(vector_dir))
    report = mem.check_consistency()
    score = mem.get_health_score()
    return {
        "vector_artifacts": vector_artifacts,
        "consistency_report": report,
        "health_score": score,
    }
