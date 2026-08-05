#!/usr/bin/env python3
"""
静息态反刍引擎 (Rumination Engine) — P2-7 DMN 默认模式网络

对齐 DMN 默认模式网络：空闲时从近期 episode 提取模式，
产出 C 级假设记忆（需 A8 验证才升级）。

关联文档: COGNITIVE_ARCHITECTURE.md §5.4 P2-7 / spec 2026-08-05-cognitive-science-p2-p3-design.md §3
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List


@dataclass
class RuminationFinding:
    """反刍发现的模式"""
    pattern_key: str              # "BTC|ranging|LONG" 格式
    observed_rate: float          # 观察到的胜率
    baseline_rate: float          # 基线胜率
    sample_n: int                 # 样本数
    deviation_pct: float          # 偏离基线百分比
    finding_text: str             # 自然语言描述
    generated_at: str             # ISO 时间戳


class RuminationEngine:
    """静息态反刍引擎（对齐 DMN 默认模式网络）"""

    DEVIATION_THRESHOLD = 0.15    # 偏离基线 15% 才记录
    MIN_SAMPLE_SIZE = 3           # 最小样本数
    LOOKBACK_DAYS = 7             # 默认回看天数

    def ruminate(self, episodes_dir: str, lookback_days: int = 7) -> List[RuminationFinding]:
        """从近期 episode 提取模式"""
        episodes = self._load_recent_episodes(episodes_dir, lookback_days)
        if len(episodes) < self.MIN_SAMPLE_SIZE:
            return []

        groups = self._group_episodes(episodes)
        baseline = self._calc_win_rate(episodes)
        if baseline <= 0:
            baseline = 0.01  # 避免除零

        findings: List[RuminationFinding] = []
        for key, group in groups.items():
            if len(group) < self.MIN_SAMPLE_SIZE:
                continue
            observed = self._calc_win_rate(group)
            if baseline <= 0:
                continue
            deviation = (observed - baseline) / baseline
            if abs(deviation) >= self.DEVIATION_THRESHOLD:
                findings.append(RuminationFinding(
                    pattern_key=key,
                    observed_rate=round(observed, 4),
                    baseline_rate=round(baseline, 4),
                    sample_n=len(group),
                    deviation_pct=round(deviation, 4),
                    finding_text=self._build_finding_text(key, observed, baseline, len(group)),
                    generated_at=datetime.now(timezone.utc).isoformat(),
                ))
        return findings

    def _load_recent_episodes(self, episodes_dir: str, lookback_days: int) -> List[Dict]:
        """加载近 N 天 episode（*.json）"""
        ep_path = Path(episodes_dir)
        if not ep_path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        episodes: List[Dict] = []
        for f in ep_path.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts_str = data.get("ts") or data.get("ts_entry") or ""
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        episodes.append(data)
                else:
                    # 无时间戳的视为近期
                    episodes.append(data)
            except Exception:
                continue
        return episodes

    def _group_episodes(self, episodes: List[Dict]) -> Dict[str, List[Dict]]:
        """按 coin × regime × direction 聚合"""
        groups: Dict[str, List[Dict]] = {}
        for ep in episodes:
            coin = ep.get("coin", "UNKNOWN")
            regime = ep.get("regime", "unknown")
            direction = ep.get("direction", "UNKNOWN")
            key = f"{coin}|{regime}|{direction}"
            groups.setdefault(key, []).append(ep)
        return groups

    def _calc_win_rate(self, group: List[Dict]) -> float:
        """计算组胜率"""
        if not group:
            return 0.0
        wins = sum(1 for e in group if float(e.get("pnl_pct", 0)) > 0)
        return wins / len(group)

    def _build_finding_text(self, key: str, observed: float, baseline: float, n: int) -> str:
        """生成自然语言 finding 文本"""
        parts = key.split("|")
        coin = parts[0] if len(parts) > 0 else "UNKNOWN"
        regime = parts[1] if len(parts) > 1 else "unknown"
        direction = parts[2] if len(parts) > 2 else "UNKNOWN"
        deviation_pct = (observed - baseline) / max(baseline, 0.01) * 100
        return (f"近{self.LOOKBACK_DAYS}天 {coin} {regime} {direction} "
                f"胜率 {observed:.1%} vs 基线 {baseline:.1%} "
                f"(样本{n}, 偏离{deviation_pct:+.1%})")
