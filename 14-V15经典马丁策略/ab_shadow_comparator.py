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
    """A single paired decision record (baseline vs AI)."""
    timestamp: str
    symbol: str
    baseline_action: str          # OPEN / SKIP / ADDON / CLOSE
    ai_action: str               # OPEN / SKIP / ADDON / CLOSE
    baseline_confidence: float
    ai_confidence: float
    baseline_pnl: float          # Realized PnL for baseline path
    ai_predicted_pnl: float      # Predicted PnL for AI path (shadow)
    ai_p_bust: float = 0.0       # BiLSTM bust probability
    ai_drawdown: float = 0.0    # PatchTST predicted drawdown
    decision_diff: str = ''     # Description of difference
    
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
        )
        self.state.records.append(record.to_dict())
        
        # Keep only last 1000 records
        if len(self.state.records) > 1000:
            self.state.records = self.state.records[-1000:]
        
        self._save_state()
    
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
        
        # Approximate p-value (two-tailed) using normal approximation
        # For large n, t-distribution approaches normal
        # p = 2 * (1 - CDF(|t|))
        # Using simple approximation: p ≈ 2 * exp(-t^2 / 2) / sqrt(2*pi) for large |t|
        if abs(t_stat) > 3.0:
            # Very significant
            p_value = 0.001
        elif abs(t_stat) > 2.0:
            p_value = 0.05
        elif abs(t_stat) > 1.5:
            p_value = 0.13
        elif abs(t_stat) > 1.0:
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
        """Force state transition (manual override)."""
        if new_state not in (STATE_SHADOW, STATE_LIVE, STATE_DISABLED):
            raise ValueError(f'Invalid state: {new_state}')
        self.state.state = new_state
        if new_state == STATE_LIVE:
            self.state.live_promoted_at = datetime.utcnow().isoformat() + 'Z'
        elif new_state == STATE_DISABLED:
            self.state.disabled_at = datetime.utcnow().isoformat() + 'Z'
        self._save_state()


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
    print('Test complete!')
