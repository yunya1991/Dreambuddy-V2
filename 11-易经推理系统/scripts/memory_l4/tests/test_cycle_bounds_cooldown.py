"""T9 验收测试：冷却联动（T_CB6）

位置: scripts/memory_l4/tests/test_cycle_bounds_cooldown.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_cooldown.py -v

对应 Spec §3bis.5.4 轨道三→轨道二冷却联动 + §3bis.9 T_CB6。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2 import morph_cycle_predictor as mcp
from bcrm2.storage import EvolutionStorageSQLite, RegimeStateFrame
from bcrm2.morph_cycle_predictor import MorphCyclePredictor


def _make_synthetic_frames(days: int, seed: int = 42, level_shift: float = 0.0) -> list:
    """构造合成数据。level_shift 用于制造形态切换。"""
    rng = np.random.default_rng(seed)
    t = np.arange(days, dtype=float)
    level_raw = (2.0 * np.sin(2 * np.pi * t / 120.0 + 0.5)
                 + 1.2 * np.sin(2 * np.pi * t / 60.0 - 0.8)
                 + rng.normal(0, 0.15, days)
                 + level_shift)
    smooth = np.zeros(days)
    smooth[0] = level_raw[0]
    for i in range(1, days):
        smooth[i] = 0.3 * level_raw[i] + 0.7 * smooth[i - 1]
    trend_smooth = np.concatenate([[0.0], np.diff(smooth)])
    price_base = 40000.0 * np.exp(smooth / 10.0)

    frames = []
    for i in range(days):
        from datetime import date, timedelta
        d = date(2026, 1, 1) + timedelta(days=i)
        frames.append(RegimeStateFrame(
            t=d.strftime("%Y-%m-%d"),
            price=float(price_base[i]),
            level_raw=float(level_raw[i]),
            trend_raw=float(trend_smooth[i]),
            level_smooth=float(smooth[i]),
            trend_smooth=float(trend_smooth[i] * 5.0),
            regime_probs={},
            top3=[["TREND_BULL", 0.4]],
            consensus=0.7,
            hmm_state=0,
            bocpd_cp_prob=0.01,
            indicators={},
        ))
    return frames


# ================================================================
# T_CB6: 冷却联动
# ================================================================

class TestCooldownReduction:
    """验证 overshoot_hint 存在时，_maybe_anchor_correct 冷却降低。"""

    def test_cooldown_reduced_with_overshoot_hint(self, tmp_path):
        """overshoot_hint.need_anchor_correct=True 时，冷却从 72h 降至 24h。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)

        # 构造数据
        frames = _make_synthetic_frames(days=180, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        # 先保存一个 30h 前的大调整记录（正常冷却 72h 下应被跳过）
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(hours=30)

        storage.save_anchor_state(
            "BTCUSDT",
            anchor_overrides={"主升浪加速": {"t_rel": 170.0, "level": 1.0}},
            switch_from="均衡蓄力",
            switch_to="主升浪加速",
            switch_date="2026-08-15",
        )
        # 手动修改 last_corrected_at 为 30h 前
        cur = storage._conn.cursor()
        cur.execute(
            "UPDATE morph_anchor_state SET last_corrected_at = ? WHERE symbol = ?",
            (old_time.isoformat(timespec="seconds"), "BTCUSDT")
        )
        storage._conn.commit()

        # 保存 overshoot_hint
        storage.save_overshoot_hint("BTCUSDT", {
            "reason": "overshoot_streak",
            "streak": 5,
            "need_anchor_correct": True,
        })

        predictor = MorphCyclePredictor(storage)
        # 调用 _maybe_anchor_correct，检查冷却是否被降低
        # 由于 30h < 72h（正常冷却），但 30h > 24h（降低后冷却），
        # 所以如果 overshoot_hint 生效，应仍跳过（30h > 24h）
        # 我们需要测试 25h 前的记录：25h < 72h 但 25h > 24h

        # 改为 25h 前
        old_time_25 = now - timedelta(hours=25)
        cur.execute(
            "UPDATE morph_anchor_state SET last_corrected_at = ? WHERE symbol = ?",
            (old_time_25.isoformat(timespec="seconds"), "BTCUSDT")
        )
        storage._conn.commit()

        # 25h > 24h（降低后冷却）→ 应跳过
        result = predictor._maybe_anchor_correct("BTCUSDT")
        # 可能返回 None（无形态切换）或结果（有形态切换）
        # 关键是冷却没有被进一步降低到 < 24h

        # 改为 23h 前
        old_time_23 = now - timedelta(hours=23)
        cur.execute(
            "UPDATE morph_anchor_state SET last_corrected_at = ? WHERE symbol = ?",
            (old_time_23.isoformat(timespec="seconds"), "BTCUSDT")
        )
        storage._conn.commit()

        # 23h < 24h（降低后冷却）→ 应不被冷却阻止
        # 但如果没有形态切换，仍返回 None
        # 这里验证冷却逻辑：通过检查 _get_effective_cooldown_hours
        cooldown = predictor._get_effective_cooldown_hours("BTCUSDT")
        assert cooldown == 24, f"有 overshoot_hint 时冷却应为 24h，实际 {cooldown}"

        storage.close()

    def test_cooldown_normal_without_overshoot_hint(self, tmp_path):
        """无 overshoot_hint 时，冷却保持 72h。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)

        frames = _make_synthetic_frames(days=180, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        # 不保存 overshoot_hint
        storage.save_anchor_state(
            "BTCUSDT",
            anchor_overrides={},
            switch_from=None,
            switch_to="均衡蓄力",
            switch_date="2026-08-15",
        )

        predictor = MorphCyclePredictor(storage)
        cooldown = predictor._get_effective_cooldown_hours("BTCUSDT")
        assert cooldown == mcp.ANCHOR_SWITCH_COOLDOWN_HOURS, \
            f"无 overshoot_hint 时冷却应为 {mcp.ANCHOR_SWITCH_COOLDOWN_HOURS}h，实际 {cooldown}"

        storage.close()

    def test_cooldown_normal_after_clear_hint(self, tmp_path):
        """清除 overshoot_hint 后，冷却恢复 72h。"""
        db_path = tmp_path / "evo_test.db"
        storage = EvolutionStorageSQLite(db_path)

        frames = _make_synthetic_frames(days=180, seed=42)
        storage.upsert_daily_batch("BTCUSDT", frames)

        storage.save_anchor_state(
            "BTCUSDT",
            anchor_overrides={},
            switch_from=None,
            switch_to="均衡蓄力",
            switch_date="2026-08-15",
        )
        storage.save_overshoot_hint("BTCUSDT", {
            "reason": "overshoot_streak",
            "streak": 5,
            "need_anchor_correct": True,
        })

        predictor = MorphCyclePredictor(storage)
        # 有 hint → 24h
        assert predictor._get_effective_cooldown_hours("BTCUSDT") == 24

        # 清除 hint
        storage.clear_overshoot_hint("BTCUSDT")
        # 恢复 72h
        assert predictor._get_effective_cooldown_hours("BTCUSDT") == mcp.ANCHOR_SWITCH_COOLDOWN_HOURS

        storage.close()
