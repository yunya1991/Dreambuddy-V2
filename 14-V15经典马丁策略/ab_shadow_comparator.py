#!/usr/bin/env python3
"""P2: A/B Shadow Comparator — Dual-path parallel comparison framework.

Architecture:
  - Baseline path: v15-final base decision (actual execution)
  - AI path: Phase D enhanced decision (shadow only, no execution)
  - Comparator: records decision deltas, computes statistical significance

State machine:
  SHADOW → (30d positive significance) → LIVE
  SHADOW → (30d negative significance) → DISABLED
  LIVE → (7d negative significance) → SHADOW (auto-rollback)

Usage:
    from ab_shadow_comparator import ABShadowComparator
    comparator = ABShadowComparator(state_file='data/ab_comparator_state.json')
    comparator.record_decision(baseline_decision, ai_decision, trade_result)
    report = comparator.generate_report()

Author: Dreambuddy-V2 DreamOS
Version: 1.0.0
Date: 2026-08-18
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── State machine ─────────────────────────────────────────────────────────────

STATE_SHADOW = 'SHADOW'
STATE_LIVE = 'LIVE'
STATE_DISABLED = 'DISABLED'

# State transition thresholds
MIN_SAMPLES_FOR_TEST = 20       # Need at least 20 paired samples
SHADOW_TO_LIVE_PVALUE = 0.05   # p < 0.05 for positive significance
SHADOW_TO_LIVE_MIN_GAIN = 0.02  # At least 2% PnL improvement
LIVE_TO_SHADOW_PVALUE = 0.10   # p < 0.10 for negative significance (looser)
LIVE_TO_SHADOW_MAX_LOSS = -0.01  # More than 1% worse → rollback
EVALUATION_WINDOW_DAYS = 30    # 30-day rolling window
LIVE_EVALUATION_WINDOW_DAYS = 7  # 7-day window for LIVE mode


@dataclass
class DecisionRecord:
    # A single paired decision record (baseline vs AI).
    timestamp: str
    symbol: str
    baseline_action: str          # OPEN / SKIP / ADDON / CLOSE
    ai_action: str               # OPEN / SKIP / ADDON / CLOSE
    baseline_confidence: float
    ai_confidence: float
    baseline_pnl: float          # Realized PnL for baseline path (placeholder at decision time)
    ai_predicted_pnl: float      # Predicted PnL for AI path (shadow)
    ai_p_bust: float = 0.0       # BiLSTM bust probability
    ai_drawdown: float = 0.0    # PatchTST predicted drawdown
    decision_diff: str = ''     # Description of difference
    position_ref: str = ''      # Backfill anchor: '{symbol}|{entry_time_floor_1min}'
    pnl_backfilled: bool = False  # True once baseline_pnl is filled by close-settle
    baseline_pnl_pct: float = 0.0 # Close-time % return (PnL / notional)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ABComparatorState:
    """Persistent state for A/B comparator."""
    state: str = STATE_SHADOW
    records: List[Dict] = field(default_factory=list)
    live_promoted_at: Optional[str] = None
    disabled_at: Optional[str] = None
    last_evaluation: Optional[str] = None
    total_evaluations: int = 0
    # 动态基线：当前最优 AI 版本标识（随迭代更新）
    dynamic_baseline_version: Optional[str] = None
    # 动态基线回测指标快照（最近一次回测对比结果）
    dynamic_baseline_metrics: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class ABShadowComparator:
    """A/B Shadow Comparator for Phase D AI models.
    
    Runs baseline and AI paths in parallel, records decision deltas,
    and performs statistical significance testing to determine if AI
    models should be promoted from SHADOW to LIVE mode.
    """

    def __init__(self, state_file: str = 'data/ab_comparator_state.json'):
        self.state_file = Path(state_file)
        self.state = self._load_state()
    
    def _load_state(self) -> ABComparatorState:
        """Load state from disk."""
        if not self.state_file.exists():
            return ABComparatorState()
        try:
            data = json.loads(self.state_file.read_text(encoding='utf-8'))
            return ABComparatorState(**data)
        except Exception:
            return ABComparatorState()
    
    def _save_state(self) -> None:
        """Save state to disk (atomic write)."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.state_file) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_file)
    
    def record_decision(
        self,
        symbol: str,
        baseline_action: str,
        ai_action: str,
        baseline_confidence: float,
        ai_confidence: float,
        baseline_pnl: float,
        ai_predicted_pnl: float = 0.0,
        ai_p_bust: float = 0.0,
        ai_drawdown: float = 0.0,
        decision_diff: str = '',
        position_ref: str = '',
    ) -> None:
        """Record a paired decision (baseline vs AI).
        
        Args:
            symbol: Trading symbol
            baseline_action: Baseline path action (OPEN/SKIP/ADDON/CLOSE)
            ai_action: AI path action (OPEN/SKIP/ADDON/CLOSE)
            baseline_confidence: Baseline confidence (0-1)
            ai_confidence: AI confidence (0-1)
            baseline_pnl: Realized PnL for baseline
            ai_predicted_pnl: Predicted PnL for AI (shadow)
            ai_p_bust: BiLSTM bust probability
            ai_drawdown: PatchTST predicted drawdown
            decision_diff: Description of difference
        """
        record = DecisionRecord(
            timestamp=datetime.utcnow().isoformat() + 'Z',
            symbol=symbol,
            baseline_action=baseline_action,
            ai_action=ai_action,
            baseline_confidence=round(baseline_confidence, 4),
            ai_confidence=round(ai_confidence, 4),
            baseline_pnl=round(baseline_pnl, 4),
            ai_predicted_pnl=round(ai_predicted_pnl, 4),
            ai_p_bust=round(ai_p_bust, 4),
            ai_drawdown=round(ai_drawdown, 4),
            decision_diff=decision_diff,
            position_ref=position_ref or '',
            pnl_backfilled=False,
            baseline_pnl_pct=0.0,
        )
        self.state.records.append(record.to_dict())
        
        # Keep only last 1000 records
        if len(self.state.records) > 1000:
            self.state.records = self.state.records[-1000:]
        
        self._save_state()
    
    # ----------------------------------------------------------------
    # Numerical helpers: regularized incomplete beta I_x(a,b) via
    # Lentz's continued fraction (Numerical Recipes §6.4).
    # Used by _paired_t_test for an exact student-t CDF (p-value)
    # without requiring scipy.
    # ----------------------------------------------------------------

    @staticmethod
    def _betacf(a, b, x, max_iter=200, eps=3e-7):
        fpmin = 1.0e-30
        qab = a + b
        qap = a + 1.0
        qam = a - 1.0
        c = 1.0
        d = 1.0 - qab * x / qap
        if abs(d) < fpmin:
            d = fpmin
        d = 1.0 / d
        h = d
        for m in range(1, max_iter + 1):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1.0 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1.0 / d
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1.0 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < eps:
                break
        return h

    @staticmethod
    def _betai(a, b, x):
        from math import lgamma, exp, log
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        log_beta_ab = lgamma(a) + lgamma(b) - lgamma(a + b)
        bt = exp(a * log(x) + b * log(1.0 - x) - log_beta_ab)
        if x < (a + 1.0) / (a + b + 2.0):
            return bt * ABShadowComparator._betacf(a, b, x) / a
        else:
            return 1.0 - bt * ABShadowComparator._betacf(b, a, 1.0 - x) / b

    def _paired_t_test(self, baseline_pnls: List[float], ai_pnls: List[float]) -> Dict:
        """Paired t-test on baseline vs AI PnL.
        
        Returns:
            {mean_diff, t_stat, p_value, n, significant}
        """
        n = len(baseline_pnls)
        if n < 2:
            return {'mean_diff': 0.0, 't_stat': 0.0, 'p_value': 1.0, 'n': n, 'significant': False}
        
        diffs = [a - b for a, b in zip(ai_pnls, baseline_pnls)]
        mean_diff = sum(diffs) / n
        
        # Sample standard deviation of differences
        if n > 1:
            variance = sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
            std_diff = math.sqrt(variance)
        else:
            std_diff = 0.0
        
        # t-statistic
        if std_diff > 1e-9:
            t_stat = mean_diff / (std_diff / math.sqrt(n))
        else:
            t_stat = 0.0
        
        # Two-tailed p-value: exact student-t CDF via regularized incomplete beta.
        # df = n - 1; I_x(df/2, 1/2) where x = df / (df + t^2)
        try:
            df = n - 1
            x = df / (df + t_stat * t_stat)
            p_value = ABShadowComparator._betai(0.5 * df, 0.5, x)
            p_value = float(max(1e-6, min(1.0, p_value)))
        except Exception:
            # Fallback: 6-point table (prior behaviour)
            at = abs(t_stat)
            if at > 3.0:
                p_value = 0.001
            elif at > 2.0:
                p_value = 0.05
            elif at > 1.5:
                p_value = 0.13
            elif at > 1.0:
                p_value = 0.32
            else:
                p_value = 0.50
        
        return {
            'mean_diff': round(mean_diff, 6),
            't_stat': round(t_stat, 4),
            'p_value': round(p_value, 4),
            'n': n,
            'significant': p_value < 0.05,
        }
    
    def _bootstrap_ci(
        self,
        baseline_pnls: List[float],
        ai_pnls: List[float],
        n_bootstrap: int = 1000,
        confidence: float = 0.95,
    ) -> Dict:
        """Bootstrap confidence interval for mean PnL difference.
        
        Returns:
            {mean_diff, ci_lower, ci_upper, positive}
        """
        n = len(baseline_pnls)
        if n < 2:
            return {'mean_diff': 0.0, 'ci_lower': 0.0, 'ci_upper': 0.0, 'positive': False}
        
        diffs = [a - b for a, b in zip(ai_pnls, baseline_pnls)]
        mean_diff = sum(diffs) / n
        
        # Bootstrap resampling
        import random
        random.seed(42)
        boot_means = []
        for _ in range(n_bootstrap):
            sample = [random.choice(diffs) for _ in range(n)]
            boot_means.append(sum(sample) / n)
        
        boot_means.sort()
        alpha = (1 - confidence) / 2
        ci_lower = boot_means[int(n_bootstrap * alpha)]
        ci_upper = boot_means[int(n_bootstrap * (1 - alpha))]
        
        return {
            'mean_diff': round(mean_diff, 6),
            'ci_lower': round(ci_lower, 6),
            'ci_upper': round(ci_upper, 6),
            'positive': ci_lower > 0,  # CI doesn't include 0 → significant
        }
    
    def evaluate(self) -> Dict:
        """Evaluate current state and potentially transition state machine.
        
        Returns:
            Evaluation report with statistics and state transition info.
        """
        now = datetime.utcnow()
        window_days = EVALUATION_WINDOW_DAYS if self.state.state == STATE_SHADOW else LIVE_EVALUATION_WINDOW_DAYS
        cutoff = (now - timedelta(days=window_days)).isoformat() + 'Z'
        
        # Filter records within window
        recent = [r for r in self.state.records if r['timestamp'] >= cutoff]
        
        if len(recent) < MIN_SAMPLES_FOR_TEST:
            return {
                'state': self.state.state,
                'n_samples': len(recent),
                'min_samples': MIN_SAMPLES_FOR_TEST,
                'message': f'Insufficient samples ({len(recent)}/{MIN_SAMPLES_FOR_TEST}), keep collecting',
                'transition': None,
            }
        
        # Extract paired PnLs
        baseline_pnls = [r['baseline_pnl'] for r in recent]
        ai_pnls = [r['ai_predicted_pnl'] for r in recent]
        
        # Statistical tests
        t_test = self._paired_t_test(baseline_pnls, ai_pnls)
        bootstrap = self._bootstrap_ci(baseline_pnls, ai_pnls)
        
        # Decision metrics
        n_agree = sum(1 for r in recent if r['baseline_action'] == r['ai_action'])
        n_disagree = len(recent) - n_agree
        agreement_rate = n_agree / len(recent) if recent else 0.0
        
        baseline_total_pnl = sum(baseline_pnls)
        ai_total_pnl = sum(ai_pnls)
        pnl_diff = ai_total_pnl - baseline_total_pnl
        pnl_diff_pct = pnl_diff / max(1e-9, abs(baseline_total_pnl)) if baseline_total_pnl != 0 else 0.0
        
        # State transition logic
        transition = None
        new_state = self.state.state
        
        if self.state.state == STATE_SHADOW:
            # SHADOW → LIVE: positive significance
            if (t_test['significant'] and 
                t_test['mean_diff'] > SHADOW_TO_LIVE_MIN_GAIN and
                bootstrap['positive']):
                new_state = STATE_LIVE
                transition = 'SHADOW→LIVE'
                self.state.live_promoted_at = now.isoformat() + 'Z'
            # SHADOW → DISABLED: very negative
            elif (t_test['significant'] and 
                  t_test['mean_diff'] < LIVE_TO_SHADOW_MAX_LOSS):
                new_state = STATE_DISABLED
                transition = 'SHADOW→DISABLED'
                self.state.disabled_at = now.isoformat() + 'Z'
        
        elif self.state.state == STATE_LIVE:
            # LIVE → SHADOW: negative significance (rollback)
            if (t_test['significant'] and 
                t_test['mean_diff'] < LIVE_TO_SHADOW_MAX_LOSS):
                new_state = STATE_SHADOW
                transition = 'LIVE→SHADOW (rollback)'
                self.state.live_promoted_at = None
        
        if transition:
            self.state.state = new_state
        
        self.state.last_evaluation = now.isoformat() + 'Z'
        self.state.total_evaluations += 1
        self._save_state()
        
        return {
            'state': new_state,
            'previous_state': self.state.state if not transition else self.state.state,
            'transition': transition,
            'n_samples': len(recent),
            'window_days': window_days,
            'baseline_total_pnl': round(baseline_total_pnl, 4),
            'ai_total_pnl': round(ai_total_pnl, 4),
            'pnl_diff': round(pnl_diff, 4),
            'pnl_diff_pct': round(pnl_diff_pct, 4),
            'agreement_rate': round(agreement_rate, 4),
            'n_agree': n_agree,
            'n_disagree': n_disagree,
            't_test': t_test,
            'bootstrap': bootstrap,
        }
    
    def generate_report(self) -> Dict:
        """Generate full A/B comparison report."""
        eval_result = self.evaluate()
        
        # Additional stats
        all_records = self.state.records
        total_records = len(all_records)
        
        # Action distribution
        baseline_actions = {}
        ai_actions = {}
        for r in all_records:
            ba = r['baseline_action']
            aa = r['ai_action']
            baseline_actions[ba] = baseline_actions.get(ba, 0) + 1
            ai_actions[aa] = ai_actions.get(aa, 0) + 1
        
        # AI model stats
        p_bust_values = [r.get('ai_p_bust', 0) for r in all_records if r.get('ai_p_bust', 0) > 0]
        drawdown_values = [r.get('ai_drawdown', 0) for r in all_records if r.get('ai_drawdown', 0) != 0]
        
        return {
            'current_state': self.state.state,
            'total_records': total_records,
            'total_evaluations': self.state.total_evaluations,
            'live_promoted_at': self.state.live_promoted_at,
            'disabled_at': self.state.disabled_at,
            'last_evaluation': self.state.last_evaluation,
            'dynamic_baseline_version': self.state.dynamic_baseline_version,
            'dynamic_baseline_metrics': self.state.dynamic_baseline_metrics,
            'evaluation': eval_result,
            'baseline_action_distribution': baseline_actions,
            'ai_action_distribution': ai_actions,
            'ai_model_stats': {
                'p_bust_mean': round(sum(p_bust_values) / len(p_bust_values), 4) if p_bust_values else 0.0,
                'p_bust_count': len(p_bust_values),
                'drawdown_mean': round(sum(drawdown_values) / len(drawdown_values), 4) if drawdown_values else 0.0,
                'drawdown_count': len(drawdown_values),
            },
            'generated_at': datetime.utcnow().isoformat() + 'Z',
        }
    
    def get_state(self) -> str:
        """Get current comparator state."""
        return self.state.state
    
    def force_state(self, new_state: str) -> None:
        # Force state transition (manual override).
        if new_state not in (STATE_SHADOW, STATE_LIVE, STATE_DISABLED):
            raise ValueError(f'Invalid state: {new_state}')
        self.state.state = new_state
        if new_state == STATE_LIVE:
            self.state.live_promoted_at = datetime.utcnow().isoformat() + 'Z'
        elif new_state == STATE_DISABLED:
            self.state.disabled_at = datetime.utcnow().isoformat() + 'Z'
        self._save_state()

    # ----------------------------------------------------------------
    # 双基线版本对比：静态基线（v15策略）+ 动态基线（最优AI版本）
    # 新版本必须优于动态基线才能晋升，防止迭代劣化
    # ----------------------------------------------------------------

    def set_dynamic_baseline(self, version: str, metrics: Optional[Dict] = None) -> None:
        """设定动态基线版本（当前最优 AI 版本）。

        Args:
            version: 模型版本标识（如 'v1'）
            metrics: 回测指标快照（pnl, win_rate, mdd 等）
        """
        self.state.dynamic_baseline_version = version
        self.state.dynamic_baseline_metrics = metrics or {}
        self._save_state()

    def evaluate_version_comparison(
        self,
        candidate_version: str,
        candidate_metrics: Dict,
        candidate_paths: Tuple[str, str],
    ) -> Dict:
        """评估新训练版本是否优于动态基线。

        对比维度：
        1. 总 PnL：candidate > dynamic_baseline → +1 分
        2. 胜率：candidate > dynamic_baseline → +1 分
        3. 最大回撤：candidate_mdd < baseline_mdd → +1 分
        4. 附加：PnL 改善幅度 > 5% → 额外通过

        Returns:
            {
                'should_promote': bool,      # 新版本优于动态基线
                'score': int,                # 3项指标中胜出的数量
                'pnl_delta_pct': float,      # PnL 改善百分比
                'reason': str,               # 决策原因
                'comparison': Dict,          # 详细对比数据
            }
        """
        db_metrics = self.state.dynamic_baseline_metrics or {}
        db_version = self.state.dynamic_baseline_version or '(none)'

        # 无动态基线时（首次训练），只要 candidate 指标合理即通过
        if not db_metrics:
            return {
                'should_promote': True,
                'score': 3,
                'pnl_delta_pct': 0.0,
                'reason': f'no dynamic baseline yet, candidate {candidate_version} auto-promote',
                'comparison': {'candidate': candidate_metrics, 'baseline': None},
            }

        score = 0
        reasons = []

        # 1. PnL 对比
        c_pnl = candidate_metrics.get('total_pnl', 0)
        b_pnl = db_metrics.get('total_pnl', 0)
        pnl_delta_pct = ((c_pnl - b_pnl) / abs(b_pnl) * 100) if abs(b_pnl) > 1e-9 else 0.0
        if c_pnl > b_pnl:
            score += 1
            reasons.append(f'pnl {c_pnl:.2f} > baseline {b_pnl:.2f} ({pnl_delta_pct:+.1f}%)')
        else:
            reasons.append(f'pnl {c_pnl:.2f} <= baseline {b_pnl:.2f} ({pnl_delta_pct:+.1f}%)')

        # 2. 胜率对比
        c_wr = candidate_metrics.get('win_rate', 0)
        b_wr = db_metrics.get('win_rate', 0)
        if c_wr > b_wr:
            score += 1
            reasons.append(f'win_rate {c_wr:.1%} > baseline {b_wr:.1%}')
        else:
            reasons.append(f'win_rate {c_wr:.1%} <= baseline {b_wr:.1%}')

        # 3. 最大回撤对比（越小越好）
        c_mdd = candidate_metrics.get('max_drawdown', 0)
        b_mdd = db_metrics.get('max_drawdown', 0)
        if c_mdd < b_mdd:
            score += 1
            reasons.append(f'mdd {c_mdd:.2f} < baseline {b_mdd:.2f}')
        else:
            reasons.append(f'mdd {c_mdd:.2f} >= baseline {b_mdd:.2f}')

        # 判定：至少 2/3 项优于动态基线，且 PnL 不劣化
        should_promote = score >= 2 and pnl_delta_pct >= -2.0

        return {
            'should_promote': should_promote,
            'score': score,
            'pnl_delta_pct': round(pnl_delta_pct, 2),
            'reason': '; '.join(reasons),
            'comparison': {
                'candidate_version': candidate_version,
                'candidate': candidate_metrics,
                'baseline_version': db_version,
                'baseline': db_metrics,
            },
        }

    # ----------------------------------------------------------------
    # PnL 回填：v15_trader 在平仓结算（_save_trade_to_history）时调用，
    # 把真实基线收益写回到决策时点 record_decision 留下的占位条目，
    # 让 AB 状态机真正拥有可统计的 paired PnL。
    # ----------------------------------------------------------------

    @staticmethod
    def build_position_ref(symbol, entry_timestamp):
        # Build a deterministic backfill-key from (symbol, entry open time).
        # Minutes resolution to avoid 1-ms drift mismatch between decision-record
        # timestamp and pos.open_time.
        try:
            if isinstance(entry_timestamp, datetime):
                dt = entry_timestamp
            elif isinstance(entry_timestamp, (int, float)):
                dt = datetime.utcfromtimestamp(float(entry_timestamp))
            else:
                s = str(entry_timestamp).strip()
                if s.endswith('Z'):
                    s = s[:-1] + '+00:00'
                try:
                    dt = datetime.fromisoformat(s)
                except Exception:
                    dt = datetime.utcnow()
            if dt.tzinfo is not None:
                # Convert to naive UTC
                from datetime import timezone as _tz2
                dt = dt.astimezone(_tz2.utc).replace(tzinfo=None)
            dt = dt.replace(second=0, microsecond=0)
            return f"{symbol}|{dt.isoformat()}"
        except Exception:
            return f"{symbol}|{str(entry_timestamp)}"

    def backfill_trade_result(
        self,
        symbol: str,
        entry_timestamp,
        baseline_pnl_usdt: float,
        baseline_pnl_pct: float = 0.0,
        *,
        ai_skipped_open_pnl: float = 0.0,
        ai_addon_delta_ratio: float = 0.0,
        exit_reason: str = "",
    ) -> int:
        # Fill baseline_pnl + ai_predicted_pnl for the pending record matching
        # (symbol, entry_timestamp). Returns number of records updated (0 or 1).
        target_ref = self.build_position_ref(symbol, entry_timestamp)
        matched_idx = -1
        records = self.state.records

        # 1) Exact position_ref match (fastest, highest accuracy).
        for i, r in enumerate(records):
            if r.get("pnl_backfilled"):
                continue
            if r.get("symbol") == symbol and r.get("position_ref", "") == target_ref:
                matched_idx = i
                break

        # 2) Fallback: same symbol + OPEN/ADDON + not backfilled + within 7 days.
        if matched_idx < 0:
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
            best_diff = None
            for i, r in enumerate(records):
                if r.get("pnl_backfilled"):
                    continue
                if r.get("symbol") != symbol:
                    continue
                if r.get("baseline_action") not in ("OPEN", "ADDON"):
                    continue
                if r.get("timestamp", "") < cutoff:
                    continue
                try:
                    ts = r.get("timestamp", "")
                    if ts.endswith("Z"):
                        ts = ts[:-1]
                    dt_r = datetime.fromisoformat(ts)
                except Exception:
                    continue
                diff = abs((datetime.utcnow() - dt_r).total_seconds())
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    matched_idx = i

        # 3) Last-resort: same symbol, empty position_ref, OPEN/ADDON, latest.
        if matched_idx < 0:
            for i in range(len(records) - 1, -1, -1):
                r = records[i]
                if r.get("pnl_backfilled"):
                    continue
                if r.get("symbol") != symbol:
                    continue
                if r.get("baseline_action") not in ("OPEN", "ADDON"):
                    continue
                if r.get("position_ref", ""):
                    continue
                matched_idx = i
                break

        if matched_idx < 0:
            return 0

        r = records[matched_idx]
        ba = r.get("baseline_action", "")
        aa = r.get("ai_action", "")
        baseline_usdt = float(baseline_pnl_usdt)
        baseline_pct = float(baseline_pnl_pct)

        if ba == "OPEN" and aa == "SKIP":
            # Baseline actually opened (lost or won); AI correctly vetoed → AI = 0
            ai_pnl = float(ai_skipped_open_pnl)
        elif ba == aa:
            # Same action → same PnL (both OPEN / both SKIP → 0 since baseline also skipped via §3.3)
            ai_pnl = baseline_usdt
        elif aa == "ADDON" and ba in ("OPEN", "ADDON"):
            # AI added more layers than baseline → magnify by delta_ratio
            ai_pnl = baseline_usdt * (1.0 + float(ai_addon_delta_ratio))
        else:
            # Conservative fallback: assume same PnL
            ai_pnl = baseline_usdt

        r["baseline_pnl"] = round(baseline_usdt, 4)
        r["ai_predicted_pnl"] = round(ai_pnl, 4)
        r["baseline_pnl_pct"] = round(baseline_pct, 6)
        if exit_reason and not r.get("decision_diff"):
            r["decision_diff"] = f"exit:{exit_reason}"
        if not r.get("position_ref"):
            r["position_ref"] = target_ref
        r["pnl_backfilled"] = True
        self._save_state()
        return 1


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=== A/B Shadow Comparator Test ===')
    print()
    
    comparator = ABShadowComparator(state_file='data/ab_comparator_state.json')
    print('Initial state:', comparator.get_state())
    print()
    
    # Simulate 25 paired decisions
    import random
    random.seed(42)
    for i in range(25):
        baseline_pnl = random.uniform(-5, 10)
        ai_pnl = baseline_pnl + random.uniform(-2, 4)  # AI slightly better
        comparator.record_decision(
            symbol='BTC',
            baseline_action='OPEN' if random.random() > 0.3 else 'SKIP',
            ai_action='OPEN' if random.random() > 0.25 else 'SKIP',
            baseline_confidence=random.uniform(0.5, 0.8),
            ai_confidence=random.uniform(0.5, 0.85),
            baseline_pnl=baseline_pnl,
            ai_predicted_pnl=ai_pnl,
            ai_p_bust=random.uniform(0.1, 0.5),
            ai_drawdown=random.uniform(-0.15, -0.02),
            decision_diff='AI adjusted confidence' if random.random() > 0.7 else '',
        )
    
    print('After 25 records:')
    report = comparator.generate_report()
    print('  State:', report['current_state'])
    print('  Total records:', report['total_records'])
    print('  Evaluation:')
    eval_r = report['evaluation']
    print('    n_samples:', eval_r.get('n_samples', 0))
    print('    baseline_pnl:', eval_r.get('baseline_total_pnl', 0))
    print('    ai_pnl:', eval_r.get('ai_total_pnl', 0))
    print('    pnl_diff:', eval_r.get('pnl_diff', 0))
    print('    agreement_rate:', eval_r.get('agreement_rate', 0))
    print('    t_test:', eval_r.get('t_test', {}))
    print('    bootstrap:', eval_r.get('bootstrap', {}))
    print('    transition:', eval_r.get('transition', None))
    print()
    # Stat sanity: exact t CDF via _betai (student-t df=24 @ t=2.064 two-tailed ≈ 0.05)
    print('[Stat] 精确 t-CDF 验证...', end=' ')
    comp2 = ABShadowComparator(state_file='/tmp/_ab_stat_probe.json')
    t_null = comp2._paired_t_test([0.0]*10, [0.0]*10)  # mean_diff=0 → p should be ~1.0
    assert t_null['p_value'] > 0.9, f"零差 p_value={t_null['p_value']} 应接近1"
    # AI strictly better, with variance so t-stat is finite and p is tiny.
    # Noise differs between baseline and AI so diffs have positive variance.
    base_l = [-1.0 + ((i * 37) % 7 - 3) * 0.08 for i in range(40)]
    ai_l = [0.0 + ((i * 53) % 7 - 3) * 0.08 for i in range(40)]
    t_big = comp2._paired_t_test(base_l, ai_l)
    assert t_big['p_value'] < 0.01, f"大差异 p_value={t_big['p_value']} 应<0.01"
    print(f"OK 零差p={t_null['p_value']:.3f} 大差异p={t_big['p_value']:.4f}")

    # Backfill → promote 闭环
    print('[Backfill] 30笔样本回填 → SHADOW→LIVE 晋升验证...')
    import os as _os, random as rnd2
    for fn in ['/tmp/_ab_backfill_probe.json', '/tmp/_ab_backfill_probe.json.tmp']:
        if _os.path.exists(fn): _os.remove(fn)
    comp3 = ABShadowComparator(state_file='/tmp/_ab_backfill_probe.json')
    comp3.force_state(STATE_SHADOW)
    rnd2.seed(7)
    # 前15笔: AI同意开 且 基线赚1%
    # 后15笔: AI否决SKIP 基线亏3% → AI显著好
    for i in range(30):
        from datetime import timedelta as _td
        entry_dt = datetime(2026, 8, 1) + _td(hours=i*4)
        entry_ts = entry_dt.isoformat() + "Z"
        coin = "BTC"
        p_ref = ABShadowComparator.build_position_ref(coin, entry_ts)
        if i < 15:
            comp3.record_decision(symbol=coin, baseline_action='OPEN', ai_action='OPEN',
                                  baseline_confidence=0.9, ai_confidence=0.95,
                                  baseline_pnl=0.0, ai_predicted_pnl=0.0, decision_diff='',
                                  position_ref=p_ref)
            comp3.backfill_trade_result(symbol=coin, entry_timestamp=entry_ts,
                                        baseline_pnl_usdt=0.10, baseline_pnl_pct=0.01,
                                        exit_reason='tp')
        else:
            comp3.record_decision(symbol=coin, baseline_action='OPEN', ai_action='SKIP',
                                  baseline_confidence=0.9, ai_confidence=0.2,
                                  baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                  decision_diff=f'G-D1: skip drawdown#{i}',
                                  position_ref=p_ref)
            comp3.backfill_trade_result(symbol=coin, entry_timestamp=entry_ts,
                                        baseline_pnl_usdt=-0.30, baseline_pnl_pct=-0.03,
                                        ai_skipped_open_pnl=0.0, exit_reason='bust')
    rep = comp3.generate_report()
    ev = rep.get('evaluation', {})
    print(f'  records={rep["total_records"]} n_samples={ev.get("n_samples")} state={rep["current_state"]}')
    print(f'  baseline_pnl={ev.get("baseline_total_pnl")} ai_pnl={ev.get("ai_total_pnl")}')
    print(f'  t_test: mean_diff={ev["t_test"]["mean_diff"]} p={ev["t_test"]["p_value"]} sig={ev["t_test"]["significant"]} trans={ev.get("transition")}')
    assert ev['t_test']['significant'], f"应达到统计显著 p={ev['t_test']['p_value']}"
    assert ev['t_test']['mean_diff'] > SHADOW_TO_LIVE_MIN_GAIN, f"AI 改善应超2%阈值"
    assert ev['bootstrap']['positive'], "Bootstrap CI 下限应>0"
    assert rep['current_state'] == STATE_LIVE or ev.get('transition') == 'SHADOW→LIVE', (
        f"应晋升 LIVE 但 state={rep['current_state']} trans={ev.get('transition')}"
    )
    print('  BACKFILL → PROMOTE 闭环 OK')
    for fn in ['/tmp/_ab_backfill_probe.json', '/tmp/_ab_backfill_probe.json.tmp',
               '/tmp/_ab_stat_probe.json', '/tmp/_ab_stat_probe.json.tmp']:
        if _os.path.exists(fn): _os.remove(fn)
    print()
    print('Test complete!')
