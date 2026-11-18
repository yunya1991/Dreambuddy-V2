"""yijing_monitor 自愈方式：通过 systemctl 启动独立单元。

历史坑：yijing-monitor 是 Type=oneshot 单元，过去在单元内用 Popen 拉 polling_trader，
monitor 退出时 systemd 按 cgroup 回收子进程，导致 11 只活 2~3 秒。
现改为 systemctl start yijing-polling-trader，由 systemd（Restart=always）托管。
"""

from __future__ import annotations  # noqa: I001

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent

# 顺序很重要：仓库根必须在 memory_l4 之前，否则 `scripts` 会解析成
# scripts/memory_l4/scripts，导致 `scripts.memory_l4` 导入失败。
for _p in (str(_REPO), str(_REPO / "scripts" / "memory_l4")):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_REPO / "scripts" / "memory_l4"))
sys.path.insert(0, str(_REPO))


def _get_module():
    import yijing_monitor

    return yijing_monitor


class _Recorder:
    """记录 subprocess.run 调用并按命令返回预设结果。"""

    def __init__(self, pgrep_out="", start_rc=0, active_sequence=None):
        self.calls = []
        self.pgrep_out = pgrep_out
        self.start_rc = start_rc
        self.active_sequence = list(active_sequence or ["active"])

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if cmd[0] == "pgrep":
            return SimpleNamespace(returncode=0, stdout=self.pgrep_out, stderr="")
        if cmd[0] == "systemctl" and cmd[1] == "start":
            return SimpleNamespace(returncode=self.start_rc, stdout="", stderr="boom")
        if cmd[0] == "systemctl" and cmd[1] == "is-active":
            state = self.active_sequence.pop(0) if self.active_sequence else "failed"
            return SimpleNamespace(returncode=0, stdout=state + "\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")


def _no_sleep(_seconds):
    return None


class TestRunPollingTraderViaSystemd:
    def test_calls_systemctl_start_when_no_instance(self, monkeypatch):
        recorder = _Recorder()
        monkeypatch.setattr(subprocess, "run", recorder)
        monkeypatch.setattr(_get_module().time, "sleep", _no_sleep)

        assert _get_module().run_polling_trader() is True
        assert ["systemctl", "start", "yijing-polling-trader"] in recorder.calls

    def test_skips_when_instance_already_running(self, monkeypatch):
        recorder = _Recorder(pgrep_out="12345\n")
        monkeypatch.setattr(subprocess, "run", recorder)

        assert _get_module().run_polling_trader() is True
        assert not any(c[:2] == ["systemctl", "start"] for c in recorder.calls)

    def test_returns_false_when_systemctl_start_fails(self, monkeypatch):
        recorder = _Recorder(start_rc=1)
        monkeypatch.setattr(subprocess, "run", recorder)
        monkeypatch.setattr(_get_module().time, "sleep", _no_sleep)

        assert _get_module().run_polling_trader() is False

    def test_returns_false_when_unit_never_active(self, monkeypatch):
        recorder = _Recorder(active_sequence=["activating"] * 10 + ["failed"])
        monkeypatch.setattr(subprocess, "run", recorder)
        monkeypatch.setattr(_get_module().time, "sleep", _no_sleep)

        assert _get_module().run_polling_trader() is False

    def test_returns_true_after_unit_becomes_active(self, monkeypatch):
        recorder = _Recorder(active_sequence=["activating", "active"])
        monkeypatch.setattr(subprocess, "run", recorder)
        monkeypatch.setattr(_get_module().time, "sleep", _no_sleep)

        assert _get_module().run_polling_trader() is True
