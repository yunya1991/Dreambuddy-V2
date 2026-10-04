"""N-P0a VerificationObserver 观测层 — 旁路记录 recall→verify 转化漏斗。

设计原则（千问二轮评估 N-P0a 落地）：
- 零行为变更：不修改 recall()/verify() 的返回值
- 独立开关：默认 OFF，开启后才记录
- FAIL-OPEN：观测异常静默，不影响主流程
- 持久化：事件写入独立 JSON 文件，可跨实例读取
- 与核心隔离：独立模块，HC-1a 合规
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# 质量等级 → 数值映射（用于 oracle gap 计算）
_QUALITY_NUMERIC: Dict[str, float] = {
    "S": 1.0,
    "A": 0.8,
    "B": 0.5,
    "C": 0.3,
    "D": 0.1,
}


def quality_to_numeric(quality: str) -> float:
    """质量等级转数值（FAIL-OPEN：未知等级返回 0.0）。"""
    return _QUALITY_NUMERIC.get(str(quality or "").upper(), 0.0)


# ---------------------------------------------------------------------------
# 事件数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecallEvent:
    """一次 recall 调用的观测记录。"""
    session_id: str
    context: str
    top_k: int
    returned_ids: List[str]
    returned_scores: List[float]
    returned_qualities: List[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class VerifyEvent:
    """一次 verify 调用的观测记录。"""
    session_id: str
    memory_id: str
    success: bool
    old_confidence: float
    new_confidence: float
    old_quality: str
    new_quality: str
    ts: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# VerificationObserver
# ---------------------------------------------------------------------------

class VerificationObserver:
    """观测层：旁路记录 recall/verify 事件，计算转化率与 oracle gap。

    所有记录操作均在 try/except 内（FAIL-OPEN），开关 OFF 时完全跳过。
    """

    _RECALL_FILE = "recall_events.jsonl"
    _VERIFY_FILE = "verify_events.jsonl"

    def __init__(self, storage_path: str, enabled: bool = False):
        self._storage = Path(storage_path)
        self._storage.mkdir(parents=True, exist_ok=True)
        self._enabled = enabled
        self._lock = threading.Lock()
        # 内存缓存（启动时加载）
        self._recall_events: List[RecallEvent] = []
        self._verify_events: List[VerifyEvent] = []
        self._load()

    # ---- 开关 ----
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    # ---- 记录 ----
    def record_recall(
        self,
        session_id: str,
        context: str,
        top_k: int,
        returned_ids: List[str],
        returned_scores: List[float],
        returned_qualities: Optional[List[str]] = None,
    ) -> None:
        """记录一次 recall 调用（旁路，不影响返回值）。"""
        if not self._enabled:
            return
        try:
            ev = RecallEvent(
                session_id=session_id,
                context=context,
                top_k=top_k,
                returned_ids=list(returned_ids or []),
                returned_scores=[float(s) for s in (returned_scores or [])],
                returned_qualities=list(returned_qualities or []),
            )
            with self._lock:
                self._recall_events.append(ev)
                self._persist_recall(ev)
        except Exception:
            # FAIL-OPEN：观测失败静默
            pass

    def record_verify(
        self,
        session_id: str,
        memory_id: str,
        success: bool,
        old_confidence: float,
        new_confidence: float,
        old_quality: str,
        new_quality: str,
    ) -> None:
        """记录一次 verify 调用（旁路，不影响返回值）。"""
        if not self._enabled:
            return
        try:
            ev = VerifyEvent(
                session_id=session_id,
                memory_id=memory_id,
                success=bool(success),
                old_confidence=float(old_confidence),
                new_confidence=float(new_confidence),
                old_quality=str(old_quality),
                new_quality=str(new_quality),
            )
            with self._lock:
                self._verify_events.append(ev)
                self._persist_verify(ev)
        except Exception:
            # FAIL-OPEN
            pass

    # ---- 查询 ----
    def get_recall_count(self) -> int:
        with self._lock:
            return len(self._recall_events)

    def get_verify_count(self) -> int:
        with self._lock:
            return len(self._verify_events)

    def get_recall_events(self) -> List[RecallEvent]:
        with self._lock:
            return list(self._recall_events)

    def get_verify_events(self) -> List[VerifyEvent]:
        with self._lock:
            return list(self._verify_events)

    def get_success_verify_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._verify_events if e.success)

    # ---- 指标 ----
    def conversion_rate(self) -> float:
        """recall→verify 转化率 = 成功 verify 数 / recall 返回记忆总数。"""
        with self._lock:
            total_returned = sum(len(e.returned_ids) for e in self._recall_events)
            if total_returned == 0:
                return 0.0
            success_verify = sum(1 for e in self._verify_events if e.success)
            return success_verify / total_returned

    def oracle_gap(self) -> float:
        """Oracle gap = 理想最优质量(1.0) - 实际 top-k 平均质量。

        衡量"如果有完美验证器，能提升多少"。gap 很小说明不值得上验证器。
        """
        with self._lock:
            if not self._recall_events:
                return 0.0
            all_qualities: List[float] = []
            for ev in self._recall_events:
                for q in ev.returned_qualities:
                    all_qualities.append(quality_to_numeric(q))
            if not all_qualities:
                # 无质量信息时用 score 近似（归一化到 [0,1]）
                all_scores: List[float] = []
                for ev in self._recall_events:
                    all_scores.extend(ev.returned_scores)
                if not all_scores:
                    return 0.0
                avg = sum(all_scores) / len(all_scores)
                return max(0.0, 1.0 - avg)
            avg_quality = sum(all_qualities) / len(all_qualities)
            return max(0.0, 1.0 - avg_quality)

    def metrics_report(self) -> Dict[str, Any]:
        """汇总指标报告。"""
        with self._lock:
            recall_count = len(self._recall_events)
            verify_count = len(self._verify_events)
            success_verify = sum(1 for e in self._verify_events if e.success)
            total_returned = sum(len(e.returned_ids) for e in self._recall_events)
            conversion = (success_verify / total_returned) if total_returned > 0 else 0.0

            # oracle gap
            all_qualities: List[float] = []
            for ev in self._recall_events:
                for q in ev.returned_qualities:
                    all_qualities.append(quality_to_numeric(q))
            if all_qualities:
                avg_q = sum(all_qualities) / len(all_qualities)
                gap = max(0.0, 1.0 - avg_q)
            else:
                all_scores = [s for ev in self._recall_events for s in ev.returned_scores]
                if all_scores:
                    gap = max(0.0, 1.0 - sum(all_scores) / len(all_scores))
                else:
                    gap = 0.0

            return {
                "recall_count": recall_count,
                "verify_count": verify_count,
                "success_verify_count": success_verify,
                "total_returned": total_returned,
                "conversion_rate": round(conversion, 6),
                "oracle_gap": round(gap, 6),
                "observer_enabled": self._enabled,
            }

    # ---- 持久化 ----
    def _persist_recall(self, ev: RecallEvent) -> None:
        path = self._storage / self._RECALL_FILE
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")

    def _persist_verify(self, ev: VerifyEvent) -> None:
        path = self._storage / self._VERIFY_FILE
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")

    def _load(self) -> None:
        """启动时从磁盘加载历史事件。"""
        recall_path = self._storage / self._RECALL_FILE
        if recall_path.exists():
            try:
                with open(recall_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            d = json.loads(line)
                            self._recall_events.append(RecallEvent(**d))
            except Exception:
                pass  # FAIL-OPEN
        verify_path = self._storage / self._VERIFY_FILE
        if verify_path.exists():
            try:
                with open(verify_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            d = json.loads(line)
                            self._verify_events.append(VerifyEvent(**d))
            except Exception:
                pass  # FAIL-OPEN


# ---------------------------------------------------------------------------
# GoldSetManager
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GoldSetEntry:
    """gold set 中的一条标注记忆。"""
    memory_id: str
    content: str
    gold_quality: str
    gold_confidence: float
    tags: List[str] = field(default_factory=list)
    annotator_quality: Optional[str] = None  # 第二标注人（用于 Cohen's kappa）


class GoldSetManager:
    """管理人工标注的 gold set（用于校准验证器）。

    千问建议：200–500 条，覆盖 S/A/B/C/D 各档 + 各 tag 类目，双人标注 Cohen's κ。
    """

    _GOLD_FILE = "gold_set.json"

    def __init__(self, storage_path: str):
        self._storage = Path(storage_path)
        self._storage.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._entries: Dict[str, GoldSetEntry] = {}
        self._load()

    def add(
        self,
        memory_id: str,
        content: str,
        gold_quality: str,
        gold_confidence: float,
        tags: Optional[List[str]] = None,
        annotator_quality: Optional[str] = None,
    ) -> None:
        """添加/覆盖一条 gold set 记录。"""
        try:
            entry = GoldSetEntry(
                memory_id=memory_id,
                content=content,
                gold_quality=str(gold_quality),
                gold_confidence=float(gold_confidence),
                tags=list(tags or []),
                annotator_quality=annotator_quality,
            )
            with self._lock:
                self._entries[memory_id] = entry
                self._persist()
        except Exception:
            pass  # FAIL-OPEN

    def get(self, memory_id: str) -> Optional[GoldSetEntry]:
        with self._lock:
            return self._entries.get(memory_id)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def list_ids(self) -> List[str]:
        with self._lock:
            return list(self._entries.keys())

    def cohen_kappa(self) -> float:
        """计算双人标注的 Cohen's kappa（基于 quality 等级一致性）。

        仅对有 annotator_quality 的条目计算。
        """
        with self._lock:
            paired = [
                (e.gold_quality, e.annotator_quality)
                for e in self._entries.values()
                if e.annotator_quality is not None
            ]
        if not paired:
            return 0.0
        n = len(paired)
        # 观测一致率
        agree = sum(1 for a, b in paired if a == b)
        po = agree / n
        # 期望一致率（各等级边缘概率乘积之和）
        from collections import Counter
        count_a = Counter(a for a, _ in paired)
        count_b = Counter(b for _, b in paired)
        pe = sum((count_a[c] / n) * (count_b[c] / n) for c in set(count_a) | set(count_b))
        if pe == 1.0:
            return 1.0 if po == 1.0 else 0.0
        kappa = (po - pe) / (1.0 - pe)
        return max(-1.0, min(1.0, kappa))

    # ---- 持久化 ----
    def _persist(self) -> None:
        path = self._storage / self._GOLD_FILE
        data = {mid: asdict(e) for mid, e in self._entries.items()}
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _load(self) -> None:
        path = self._storage / self._GOLD_FILE
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for mid, d in data.items():
                self._entries[mid] = GoldSetEntry(**d)
        except Exception:
            pass  # FAIL-OPEN
