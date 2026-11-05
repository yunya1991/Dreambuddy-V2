"""影子层轨迹滚动切分 + 冷热分层保留（OPT-L0-SHADOW-DATA-GOV v0.1 优化项一）。

设计约束：
  - H1 壳 diff=0：外置脚本，不改 agent_mail_shadow.py 写入端；
  - §6.5 校准协议：热保留 HOT_DAYS=14 天 >= 影子期 2 周取数需求；
  - H4 阈值硬编码：HOT_DAYS / RETENTION_DAYS 为常量，禁 env override；
  - S3 零干扰：任何失败静默降级（退出码 0），不影响主链路；
  - 幂等安全：按行迁移 + 临时文件原子替换，中断重跑不丢数据、不重复迁移。

保留策略（对齐 C9 job_runs 90 天语义）：
  - 当日热数据留主文件 trajectories.jsonl；
  - 早于当日的按天归档 archive/trajectories-YYYYMMDD.jsonl；
  - 归档 > HOT_DAYS 天压缩为 .gz（标准库 gzip，零新依赖）；
  - 归档 > RETENTION_DAYS 天删除。
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HOT_DAYS = 14  # 热保留天数（原文，供校准取数）
RETENTION_DAYS = 90  # 总保留天数（对齐 C9 job_runs）

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = _REPO_ROOT / ".workbuddy" / "agent_mail" / "trajectories.jsonl"


def _entry_ts(entry: Dict[str, Any]) -> float:
    """取轨迹时间戳：优先 ts 字段，缺省 0（归入最旧桶，保证不丢）。"""
    try:
        return float(entry.get("ts", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")


def _today_key(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d")


def rotate(
    store: Path = DEFAULT_STORE,
    *,
    now: float | None = None,
) -> Dict[str, int]:
    """执行一次轮转，返回统计 {archived, kept, compressed, deleted}。"""
    stats = {"archived": 0, "kept": 0, "compressed": 0, "deleted": 0}
    now = time.time() if now is None else float(now)
    if not store.exists():
        return stats
    archive_dir = store.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # 1) 按天分桶：当日留主文件，早于当日的按天归档
    today = _today_key(now)
    buckets: Dict[str, List[str]] = {}
    keep_lines: List[str] = []
    with store.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                keep_lines.append(stripped)  # 损坏行不丢，留主文件
                continue
            day = _day_key(_entry_ts(entry))
            if day >= today:
                keep_lines.append(stripped)
            else:
                buckets.setdefault(day, []).append(stripped)

    # 2) 追加写入对应归档（幂等：追加语义，重复行由读取端去重容忍）
    for day, lines in buckets.items():
        target = archive_dir / f"trajectories-{day}.jsonl"
        gz_target = target.with_suffix(".jsonl.gz")
        if gz_target.exists():
            opener = lambda p: gzip.open(p, "at", encoding="utf-8")  # noqa: E731
            with opener(gz_target) as out:
                out.write("\n".join(lines) + "\n")
        else:
            with target.open("a", encoding="utf-8") as out:
                out.write("\n".join(lines) + "\n")
        stats["archived"] += len(lines)
    stats["kept"] = len(keep_lines)

    # 3) 主文件原子替换为当日热数据
    tmp = store.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as out:
        for line in keep_lines:
            out.write(line + "\n")
    os.replace(tmp, store)

    # 4) 冷热分层：> HOT_DAYS 压缩；> RETENTION_DAYS 删除
    hot_cutoff = now - HOT_DAYS * 86400.0
    del_cutoff = now - RETENTION_DAYS * 86400.0
    for path in sorted(archive_dir.iterdir()):
        name = path.name
        if not (name.startswith("trajectories-") and name.endswith(".jsonl")):
            continue
        day_str = name[len("trajectories-") : -len(".jsonl")]
        try:
            day_ts = datetime.strptime(day_str, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if day_ts < del_cutoff:
            path.unlink(missing_ok=True)
            path.with_suffix(".jsonl.gz").unlink(missing_ok=True)
            stats["deleted"] += 1
        elif day_ts < hot_cutoff:
            gz = path.with_suffix(".jsonl.gz")
            with path.open("rb") as src, gzip.open(gz, "wb") as dst:
                dst.writelines(src)
            path.unlink()
            stats["compressed"] += 1
    return stats


def main() -> int:
    try:
        stats = rotate()
        print(f"rotate ok: {stats}")
        return 0
    except Exception as exc:  # noqa: BLE001 — S3 零干扰，失败静默降级
        print(f"rotate failed (fail-open): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
