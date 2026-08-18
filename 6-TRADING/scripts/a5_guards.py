import os
from dataclasses import dataclass
from pathlib import Path

import fcntl


@dataclass(frozen=True)
class LiveGateError(RuntimeError):
    reason: str

    def __str__(self) -> str:
        return self.reason


def require_live_gate(expected_profile: str) -> None:
    if os.environ.get("LIVE_AUTOMATION_ENABLED") != "1":
        raise LiveGateError("GATE_LIVE_DISABLED")
    if os.environ.get("OKX_PROFILE") != expected_profile:
        raise LiveGateError("GATE_PROFILE_MISMATCH")


def acquire_single_instance_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise LiveGateError("GATE_SINGLE_INSTANCE_LOCKED")
    return fh

