#!/usr/bin/env python3
"""P3: Incremental Trainer — Rolling window retraining framework.

Architecture:
  ┌───────────────────────────────────────────────────────────────┐
  │  IncrementalTrainer                                           │
  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
  │  │ DataCollector │→│ WindowMgr   │→│ RetrainPipeline     │   │
  │  │ (real K-lines │  │ (rolling N  │  │ (SMOTE+Focal+train) │   │
  │  │  + trades)    │  │  days)      │  │                     │   │
  │  └─────────────┘  └─────────────┘  └─────────────────────┘   │
  │                                         ↓                     │
  │  ┌──────────────────────────────────────────────────────┐    │
  │  │ ModelVersionManager                                    │    │
  │  │ v1(live) ←→ v2(shadow) ←→ v3(shadow) ...             │    │
  │  │ ABShadowComparator drives auto-promotion/rollback     │    │
  │  └──────────────────────────────────────────────────────┘    │
  └───────────────────────────────────────────────────────────────┘

Workflow:
  1. collect_recent_data() — Fetch recent K-lines + trade history
  2. build_rolling_window() — Merge new data with existing window, drop expired
  3. retrain() — Run augment_and_retrain pipeline on rolling window data
  4. evaluate_and_promote() — ABShadowComparator decides promote/rollback
  5. update_gateway() — Hot-swap model paths in PhaseDGateway

Schedule: Daily (configurable), integrates with scheduler or cron.

Author: Dreambuddy-V2 DreamOS
Version: 1.0.0
Date: 2026-08-18
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_WINDOW_DAYS = 30          # Rolling window: last 30 days
DEFAULT_MIN_NEW_TRADES = 5        # Minimum new trades to trigger retrain
DEFAULT_MAX_VERSIONS = 5          # Keep at most 5 model versions
DEFAULT_MODEL_BASE_DIR = 'data/phase_d_models'
DEFAULT_STATE_FILE = 'data/incremental_trainer_state.json'
DEFAULT_COINS = ['BTC', 'ETH', 'SOL', 'HYPE']  # Default coins for data collection

# Retrain triggers
TRIGGER_SCHEDULED = 'scheduled'   # Daily scheduled
TRIGGER_THRESHOLD = 'threshold'   # Enough new trades collected
TRIGGER_MANUAL = 'manual'         # Manual trigger


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class ModelVersion:
    """A model version record."""
    version: str                   # e.g. 'v1', 'v2'
    created_at: str                # ISO timestamp
    bilstm_path: str              # Path to bilstm.pt
    patchtst_path: str            # Path to patchtst.pt
    training_report: Dict         # Training metrics
    status: str = 'shadow'        # live / shadow / disabled / archived
    promoted_at: Optional[str] = None
    sample_count: int = 0
    coins: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class IncrementalTrainerState:
    """Persistent state for incremental trainer."""
    current_live_version: Optional[str] = None
    current_shadow_version: Optional[str] = None
    versions: List[Dict] = field(default_factory=list)
    last_retrain_at: Optional[str] = None
    last_retrain_trigger: Optional[str] = None
    total_retrains: int = 0
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    collected_trade_count: int = 0
    last_evaluation: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Model Version Manager ─────────────────────────────────────────────────────

class ModelVersionManager:
    """Manages model versions with promotion/rollback support.

    Version lifecycle:
      create → shadow → (AB eval) → live / disabled
      live → (AB eval negative) → shadow (rollback)
      shadow → (max versions exceeded) → archived
    """

    def __init__(
        self,
        base_dir: str = DEFAULT_MODEL_BASE_DIR,
        state_file: str = DEFAULT_STATE_FILE,
        max_versions: int = DEFAULT_MAX_VERSIONS,
    ):
        self.base_dir = Path(base_dir)
        self.state_file = Path(state_file)
        self.max_versions = max_versions
        self.state = self._load_state()

    def _load_state(self) -> IncrementalTrainerState:
        if not self.state_file.exists():
            return IncrementalTrainerState()
        try:
            data = json.loads(self.state_file.read_text(encoding='utf-8'))
            return IncrementalTrainerState(**data)
        except Exception:
            return IncrementalTrainerState()

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.state_file) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_file)

    def register_version(
        self,
        bilstm_path: str,
        patchtst_path: str,
        training_report: Dict,
        sample_count: int = 0,
        coins: Optional[List[str]] = None,
    ) -> str:
        """Register a new model version. Returns version string (e.g. 'v2')."""
        version_num = len(self.state.versions) + 1
        version = f'v{version_num}'

        # If we have a live version, new one is shadow
        status = 'shadow' if self.state.current_live_version else 'live'

        mv = ModelVersion(
            version=version,
            created_at=datetime.utcnow().isoformat() + 'Z',
            bilstm_path=bilstm_path,
            patchtst_path=patchtst_path,
            training_report=training_report,
            status=status,
            sample_count=sample_count,
            coins=coins or [],
        )

        if status == 'live':
            self.state.current_live_version = version
            mv.promoted_at = mv.created_at
        else:
            self.state.current_shadow_version = version

        self.state.versions.append(mv.to_dict())

        # Archive old versions if exceeding max
        self._archive_old_versions()

        self._save_state()
        print(f'  Registered model version: {version} (status={status})')
        return version

    def _archive_old_versions(self) -> None:
        """Archive oldest non-live, non-shadow versions when exceeding max."""
        active = [v for v in self.state.versions if v['status'] in ('live', 'shadow')]
        archived = [v for v in self.state.versions if v['status'] not in ('live', 'shadow', 'archived')]

        if len(self.state.versions) > self.max_versions:
            for v in self.state.versions:
                if v['status'] not in ('live', 'shadow'):
                    v['status'] = 'archived'

    def promote_shadow(self, shadow_version: str) -> bool:
        """Promote a shadow version to live. Demote current live to shadow."""
        # Find shadow version
        shadow = None
        for v in self.state.versions:
            if v['version'] == shadow_version and v['status'] == 'shadow':
                shadow = v
                break

        if not shadow:
            print(f'  Cannot promote {shadow_version}: not found or not in shadow status')
            return False

        # Demote current live to shadow
        if self.state.current_live_version:
            for v in self.state.versions:
                if v['version'] == self.state.current_live_version:
                    v['status'] = 'shadow'
                    break

        # Promote shadow to live
        shadow['status'] = 'live'
        shadow['promoted_at'] = datetime.utcnow().isoformat() + 'Z'
        self.state.current_live_version = shadow_version
        self.state.current_shadow_version = None

        self._save_state()
        print(f'  Promoted {shadow_version} to live')
        return True

    def rollback_live(self) -> bool:
        """Rollback current live version to previous live version."""
        if not self.state.current_live_version:
            return False

        # Record current live version to exclude it from candidates
        demoted_version = self.state.current_live_version

        # Demote current live
        for v in self.state.versions:
            if v['version'] == demoted_version:
                v['status'] = 'shadow'
                # Clear promoted_at so it won't be considered as a previous live
                v['promoted_at'] = None
                break

        # Find previous live (most recent promoted_at, excluding the demoted one)
        candidates = [
            v for v in self.state.versions
            if v['version'] != demoted_version
            and v['status'] == 'shadow'
            and v.get('promoted_at')
        ]
        candidates.sort(key=lambda x: x['promoted_at'], reverse=True)

        if candidates:
            candidates[0]['status'] = 'live'
            self.state.current_live_version = candidates[0]['version']
            self._save_state()
            print(f'  Rolled back to {candidates[0]["version"]}')
            return True
        else:
            self.state.current_live_version = None
            self._save_state()
            print('  No previous live version to rollback to')
            return False

    def disable_shadow(self, shadow_version: str) -> bool:
        """Disable a shadow version that performed poorly."""
        for v in self.state.versions:
            if v['version'] == shadow_version:
                v['status'] = 'disabled'
                if self.state.current_shadow_version == shadow_version:
                    self.state.current_shadow_version = None
                self._save_state()
                print(f'  Disabled {shadow_version}')
                return True
        return False

    def get_live_paths(self) -> Optional[Tuple[str, str]]:
        """Returns (bilstm_path, patchtst_path) for current live version."""
        if not self.state.current_live_version:
            return None
        for v in self.state.versions:
            if v['version'] == self.state.current_live_version:
                return v['bilstm_path'], v['patchtst_path']
        return None

    def get_shadow_paths(self) -> Optional[Tuple[str, str]]:
        """Returns (bilstm_path, patchtst_path) for current shadow version."""
        if not self.state.current_shadow_version:
            return None
        for v in self.state.versions:
            if v['version'] == self.state.current_shadow_version:
                return v['bilstm_path'], v['patchtst_path']
        return None

    def get_version_info(self) -> Dict:
        """Get summary of all versions."""
        return {
            'current_live': self.state.current_live_version,
            'current_shadow': self.state.current_shadow_version,
            'total_versions': len(self.state.versions),
            'versions': [
                {
                    'version': v['version'],
                    'status': v['status'],
                    'created_at': v['created_at'],
                    'sample_count': v['sample_count'],
                    'coins': v['coins'],
                    'training_metrics': {
                        'bilstm_val_loss': v['training_report'].get('bilstm', {}).get('best_val_loss'),
                        'bilstm_precision': v['training_report'].get('bilstm', {}).get('best_precision'),
                        'bilstm_recall': v['training_report'].get('bilstm', {}).get('best_recall'),
                        'patchtst_val_loss': v['training_report'].get('patchtst', {}).get('best_val_loss'),
                        'patchtst_mae': v['training_report'].get('patchtst', {}).get('best_val_mae'),
                    },
                }
                for v in self.state.versions
            ],
        }


# ── Incremental Trainer ───────────────────────────────────────────────────────

class IncrementalTrainer:
    """P3: Rolling window incremental retraining framework.

    Collects recent trade data, retrains models on a rolling window,
    and manages model version promotion via ABShadowComparator.
    """

    def __init__(
        self,
        model_base_dir: str = DEFAULT_MODEL_BASE_DIR,
        state_file: str = DEFAULT_STATE_FILE,
        window_days: int = DEFAULT_WINDOW_DAYS,
        min_new_trades: int = DEFAULT_MIN_NEW_TRADES,
        coins: Optional[List[str]] = None,
        ab_comparator=None,
    ):
        self.window_days = window_days
        self.min_new_trades = min_new_trades
        self.coins = coins or DEFAULT_COINS
        self.ab_comparator = ab_comparator

        self.version_mgr = ModelVersionManager(
            base_dir=model_base_dir,
            state_file=state_file,
        )

        # Data directories
        self.data_dir = Path('data/ai_datasets')
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Trade history file (populated by v15_trader._save_trade_to_history)
        self.trade_history_file = Path('data/trade_history.json')
        self._last_trade_count = self._load_last_trade_count()

    def _load_last_trade_count(self) -> int:
        """Load the last known trade count from state."""
        return self.version_mgr.state.versions[-1].get('sample_count', 0) if self.version_mgr.state.versions else 0

    def check_new_trades(self) -> Dict[str, Any]:
        """Check trade_history.json for new closed trades since last check.

        Returns:
            {
                'total_trades': int,       # Total trades in history
                'new_trades': int,         # Trades since last check
                'should_retrain': bool,    # True if new_trades >= min_new_trades
                'recent_trades': [dict],   # Last 5 trade records
            }
        """
        if not self.trade_history_file.exists():
            return {
                'total_trades': 0,
                'new_trades': 0,
                'should_retrain': False,
                'recent_trades': [],
            }

        try:
            history = json.loads(self.trade_history_file.read_text(encoding='utf-8'))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

        total = len(history)
        new_trades = total - self._last_trade_count
        should_retrain = new_trades >= self.min_new_trades

        # Extract recent trades for context
        recent = history[-5:] if len(history) >= 5 else history

        # Compute win rate from recent trades
        wins = sum(1 for t in history if t.get('pnl_usdt', 0) > 0)
        win_rate = wins / total if total > 0 else 0.0

        print(f'\n[IncrementalTrainer] Trade history check:')
        print(f'  Total trades: {total}')
        print(f'  New since last: {new_trades}')
        print(f'  Win rate: {win_rate:.2%}')
        print(f'  Should retrain: {should_retrain} (threshold={self.min_new_trades})')

        return {
            'total_trades': total,
            'new_trades': new_trades,
            'should_retrain': should_retrain,
            'win_rate': round(win_rate, 4),
            'recent_trades': recent,
        }

    def auto_retrain_if_needed(self) -> Dict[str, Any]:
        """Check for new trades and automatically trigger retrain if threshold met.

        This is the main entry point for automated/scheduled execution.
        Can be called by cron, scheduler, or --action auto CLI.

        Returns:
            {
                'action': 'retrained' | 'skipped' | 'failed',
                'trade_check': dict,
                'retrain_result': dict (if retrained),
            }
        """
        print('\n' + '=' * 60)
        print('[IncrementalTrainer] Auto-retrain check')
        print('=' * 60)

        # Step 1: Check for new trades
        trade_check = self.check_new_trades()

        if not trade_check['should_retrain']:
            print(f'\n[IncrementalTrainer] Only {trade_check["new_trades"]} new trades '
                  f'(need {self.min_new_trades}), skipping retrain')
            return {
                'action': 'skipped',
                'reason': 'insufficient_new_trades',
                'trade_check': trade_check,
            }

        # Step 2: Collect K-line data for retraining
        print(f'\n[IncrementalTrainer] {trade_check["new_trades"]} new trades detected, '
              f'starting retrain cycle...')

        # Step 3: Run full retrain cycle
        result = self.run_retrain_cycle(trigger=TRIGGER_THRESHOLD)

        # Step 4: Update last trade count
        self._last_trade_count = trade_check['total_trades']

        return {
            'action': 'retrained' if result.get('status') == 'success' else 'failed',
            'trade_check': trade_check,
            'retrain_result': result,
        }

    def collect_recent_data(self, days: Optional[int] = None) -> Dict[str, Any]:
        """Collect recent K-line data and trade history for retraining.

        Args:
            days: Override window_days. Default uses self.window_days.

        Returns:
            Collection summary dict.
        """
        days = days or self.window_days
        now = datetime.utcnow()
        cutoff = now - timedelta(days=days)

        print(f'\n[IncrementalTrainer] Collecting data for last {days} days...')
        print(f'  Cutoff: {cutoff.isoformat()}Z')
        print(f'  Coins: {self.coins}')

        # Try to import dataset generator for real data collection
        collected_samples = 0
        collected_coins = []

        try:
            from phase_d_dataset_generator import build_dataset_from_real

            for coin in self.coins:
                try:
                    npz_path = str(self.data_dir / f'incremental_{coin}_{now.strftime("%Y%m%d")}.npz')
                    n = build_dataset_from_real(
                        coins=[coin],
                        limit=500,
                        output_path=npz_path,
                    )
                    collected_samples += n
                    collected_coins.append(coin)
                    print(f'  {coin}: {n} samples collected')
                except Exception as e:
                    print(f'  {coin}: collection failed — {e}')

        except ImportError:
            print('  phase_d_dataset_generator not available, using synthetic fallback')
            try:
                from phase_d_dataset_generator import build_dataset
                npz_path = str(self.data_dir / f'incremental_synth_{now.strftime("%Y%m%d")}.npz')
                build_dataset(n_samples=200, output_path=npz_path, seed=int(time.time()) % 10000)
                collected_samples = 200
                collected_coins = ['SYNTH']
            except Exception as e:
                print(f'  Synthetic fallback failed: {e}')

        # Update state
        self.version_mgr.state.window_start = cutoff.isoformat() + 'Z'
        self.version_mgr.state.window_end = now.isoformat() + 'Z'
        self.version_mgr.state.collected_trade_count = collected_samples
        self.version_mgr._save_state()

        print(f'  Total: {collected_samples} samples from {len(collected_coins)} coins')

        return {
            'samples': collected_samples,
            'coins': collected_coins,
            'window_days': days,
            'cutoff': cutoff.isoformat() + 'Z',
        }

    def should_retrain(self, trigger: str = TRIGGER_SCHEDULED) -> bool:
        """Check if retraining should be triggered.

        Args:
            trigger: TRIGGER_SCHEDULED / TRIGGER_THRESHOLD / TRIGGER_MANUAL

        Returns:
            True if retrain should run.
        """
        if trigger == TRIGGER_MANUAL:
            return True

        if trigger == TRIGGER_THRESHOLD:
            return self.version_mgr.state.collected_trade_count >= self.min_new_trades

        if trigger == TRIGGER_SCHEDULED:
            # Check if last retrain was more than 24h ago
            last = self.version_mgr.state.last_retrain_at
            if not last:
                return True
            try:
                last_dt = datetime.fromisoformat(last.rstrip('Z'))
                return (datetime.utcnow() - last_dt) >= timedelta(hours=24)
            except Exception:
                return True

        return False

    def run_retrain_cycle(self, trigger: str = TRIGGER_SCHEDULED) -> Dict[str, Any]:
        """Execute a complete incremental retrain cycle.

        Steps:
          1. Collect recent data
          2. Merge with existing rolling window
          3. Retrain BiLSTM + PatchTST
          4. Register new model version
          5. Evaluate and promote/rollback

        Returns:
            Retrain cycle report.
        """
        print('\n' + '=' * 60)
        print('[IncrementalTrainer] Starting retrain cycle')
        print(f'  Trigger: {trigger}')
        print('=' * 60)

        # Step 1: Collect data
        collection = self.collect_recent_data()

        if collection['samples'] == 0:
            print('\n[IncrementalTrainer] No samples collected, skipping retrain')
            return {'status': 'skipped', 'reason': 'no_data', 'collection': collection}

        # Step 2: Prepare data for training
        now = datetime.utcnow()
        version_num = len(self.version_mgr.state.versions) + 1
        version_str = f'v{version_num}'
        out_dir = Path(self.version_mgr.base_dir) / version_str
        out_dir.mkdir(parents=True, exist_ok=True)

        # Step 3: Retrain models
        print(f'\n[IncrementalTrainer] Retraining models → {out_dir}')
        training_report = self._run_training(out_dir, collection)

        if not training_report.get('success', False):
            print(f'\n[IncrementalTrainer] Training failed: {training_report.get("error", "unknown")}')
            return {'status': 'failed', 'training_report': training_report, 'collection': collection}

        # Step 4: Register new version
        bilstm_path = str(out_dir / 'bilstm.pt')
        patchtst_path = str(out_dir / 'patchtst.pt')

        version = self.version_mgr.register_version(
            bilstm_path=bilstm_path,
            patchtst_path=patchtst_path,
            training_report=training_report,
            sample_count=collection['samples'],
            coins=collection['coins'],
        )

        # Step 5: Update state
        self.version_mgr.state.last_retrain_at = now.isoformat() + 'Z'
        self.version_mgr.state.last_retrain_trigger = trigger
        self.version_mgr.state.total_retrains += 1
        self.version_mgr._save_state()

        # Step 6: Evaluate and promote (if AB comparator available)
        promotion = self.evaluate_and_promote()

        print(f'\n[IncrementalTrainer] Retrain cycle complete')
        print(f'  Version: {version}')
        print(f'  Status: {promotion.get("new_status", "unknown")}')

        return {
            'status': 'success',
            'version': version,
            'training_report': training_report,
            'collection': collection,
            'promotion': promotion,
        }

    def _run_training(self, out_dir: Path, collection: Dict) -> Dict:
        """Run the actual training pipeline (augment_and_retrain).

        Args:
            out_dir: Output directory for model files.
            collection: Data collection summary.

        Returns:
            Training report dict.
        """
        try:
            # Import training functions from augment_and_retrain
            import sys as _sys
            _root = str(Path(__file__).resolve().parent)
            if _root not in _sys.path:
                _sys.path.insert(0, _root)

            from augment_and_retrain import (
                load_and_balance_data,
                smote_oversample,
                augment_data,
                train_bilstm_focal,
                train_patchtst,
                save_model,
                BiLSTMAttentionBust,
                PatchTSTForDrawdown,
                BILSTM_EPOCHS,
                PATCHTST_EPOCHS,
                BATCH_SIZE,
                SMOTE_RATIO,
                AUGMENT_FACTOR,
                NOISE_STD,
                FOCAL_ALPHA,
                FOCAL_GAMMA,
                BUST_THRESHOLD,
            )
            import torch
            from torch.utils.data import DataLoader, TensorDataset

            device = torch.device('cpu')

            # Find the most recent NPZ files
            npz_files = sorted(self.data_dir.glob('incremental_*.npz'), reverse=True)
            if not npz_files:
                # Fallback to existing dataset
                npz_files = sorted(self.data_dir.glob('phase_d_train_all.npz'), reverse=True)

            if not npz_files:
                return {'success': False, 'error': 'No training data found'}

            train_npz = str(npz_files[0])
            test_npz = str(self.data_dir / 'phase_d_test_all.npz')

            if not os.path.isfile(test_npz):
                # Use train data split for test
                test_npz = train_npz

            print(f'  Train data: {train_npz}')
            print(f'  Test data: {test_npz}')

            # Load and balance
            b_ohlcv, b_scalar, p_in, l_bust, l_maxdd = load_and_balance_data(train_npz)
            t_ohlcv, t_scalar, t_p_in, t_bust, t_maxdd = load_and_balance_data(test_npz)

            # SMOTE + augment
            b_ohlcv, b_scalar, p_in, l_bust, l_maxdd = smote_oversample(
                b_ohlcv, b_scalar, p_in, l_bust, l_maxdd, SMOTE_RATIO,
            )
            b_ohlcv, b_scalar, p_in, l_bust, l_maxdd = augment_data(
                b_ohlcv, b_scalar, p_in, l_bust, l_maxdd, AUGMENT_FACTOR,
            )

            # Train BiLSTM
            bilstm_model = BiLSTMAttentionBust(
                ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2,
            )
            train_ds = TensorDataset(b_ohlcv, b_scalar, l_bust)
            val_ds = TensorDataset(t_ohlcv, t_scalar, t_bust)
            train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
            val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

            bilstm_result = train_bilstm_focal(
                bilstm_model, train_loader, val_loader, BILSTM_EPOCHS, device,
            )

            # Train PatchTST
            patchtst_model = PatchTSTForDrawdown(
                c_in=5, seq_len=120, patch_len=12, stride=6,
                d_model=32, n_layers=2, n_heads=4, d_ff=64,
            )
            p_in_t = p_in.transpose(1, 2)
            t_p_in_t = t_p_in.transpose(1, 2)
            train_ds2 = TensorDataset(p_in_t, l_maxdd)
            val_ds2 = TensorDataset(t_p_in_t, t_maxdd)
            train_loader2 = DataLoader(train_ds2, batch_size=BATCH_SIZE, shuffle=True)
            val_loader2 = DataLoader(val_ds2, batch_size=BATCH_SIZE, shuffle=False)

            patchtst_result = train_patchtst(
                patchtst_model, train_loader2, val_loader2, PATCHTST_EPOCHS, device,
            )

            # Save models
            bilstm_path = str(out_dir / 'bilstm.pt')
            patchtst_path = str(out_dir / 'patchtst.pt')

            bilstm_meta = {
                'model': 'BiLSTMAttentionBust', 'version': out_dir.name,
                'ohlcv_len': 60, 'n_channels': 5, 'n_scalar': 7,
                'hidden': 48, 'n_layers': 2,
                'bust_threshold': BUST_THRESHOLD,
                'focal_alpha': FOCAL_ALPHA, 'focal_gamma': FOCAL_GAMMA,
                'augment_factor': AUGMENT_FACTOR, 'noise_std': NOISE_STD,
                'smote_ratio': SMOTE_RATIO,
                'best_val_loss': bilstm_result['best_val_loss'],
                'best_val_acc': bilstm_result['best_val_acc'],
                'best_precision': bilstm_result['best_precision'],
                'best_recall': bilstm_result['best_recall'],
            }
            save_model(bilstm_model, bilstm_meta, bilstm_path)

            patchtst_meta = {
                'model': 'PatchTSTForDrawdown', 'version': out_dir.name,
                'c_in': 5, 'seq_len': 120, 'patch_len': 12, 'stride': 6,
                'd_model': 32, 'n_layers': 2, 'n_heads': 4, 'd_ff': 64,
                'best_val_loss': patchtst_result['best_val_loss'],
                'best_val_mae': patchtst_result['best_val_mae'],
            }
            save_model(patchtst_model, patchtst_meta, patchtst_path)

            return {
                'success': True,
                'version': out_dir.name,
                'bilstm': bilstm_result,
                'patchtst': patchtst_result,
                'bilstm_path': bilstm_path,
                'patchtst_path': patchtst_path,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}

    def evaluate_and_promote(self) -> Dict[str, Any]:
        """Evaluate shadow model via ABShadowComparator and decide promotion.

        Returns:
            Promotion decision dict.
        """
        if not self.ab_comparator:
            return {'action': 'no_comparator', 'new_status': 'shadow'}

        # Run AB evaluation
        eval_result = self.ab_comparator.evaluate()
        self.version_mgr.state.last_evaluation = datetime.utcnow().isoformat() + 'Z'
        self.version_mgr._save_state()

        transition = eval_result.get('transition')
        shadow_ver = self.version_mgr.state.current_shadow_version

        if transition == 'SHADOW→LIVE' and shadow_ver:
            # Promote shadow to live
            self.version_mgr.promote_shadow(shadow_ver)
            return {
                'action': 'promoted',
                'transition': transition,
                'new_status': 'live',
                'version': shadow_ver,
                'evaluation': eval_result,
            }

        elif transition == 'SHADOW→DISABLED' and shadow_ver:
            # Disable shadow
            self.version_mgr.disable_shadow(shadow_ver)
            return {
                'action': 'disabled',
                'transition': transition,
                'new_status': 'disabled',
                'version': shadow_ver,
                'evaluation': eval_result,
            }

        elif transition and 'LIVE→SHADOW' in transition:
            # Rollback live
            self.version_mgr.rollback_live()
            return {
                'action': 'rollback',
                'transition': transition,
                'new_status': 'shadow',
                'evaluation': eval_result,
            }

        return {
            'action': 'keep_collecting',
            'transition': None,
            'new_status': 'shadow',
            'evaluation': eval_result,
        }

    def get_active_model_paths(self) -> Dict[str, Optional[str]]:
        """Get model paths for live and shadow versions.

        Returns:
            {'live_bilstm': ..., 'live_patchtst': ..., 'shadow_bilstm': ..., 'shadow_patchtst': ...}
        """
        live = self.version_mgr.get_live_paths()
        shadow = self.version_mgr.get_shadow_paths()

        return {
            'live_bilstm': live[0] if live else None,
            'live_patchtst': live[1] if live else None,
            'shadow_bilstm': shadow[0] if shadow else None,
            'shadow_patchtst': shadow[1] if shadow else None,
        }

    def generate_report(self) -> Dict[str, Any]:
        """Generate full incremental trainer report."""
        return {
            'version_info': self.version_mgr.get_version_info(),
            'active_models': self.get_active_model_paths(),
            'last_retrain': self.version_mgr.state.last_retrain_at,
            'total_retrains': self.version_mgr.state.total_retrains,
            'window': {
                'start': self.version_mgr.state.window_start,
                'end': self.version_mgr.state.window_end,
                'days': self.window_days,
            },
            'collected_trades': self.version_mgr.state.collected_trade_count,
            'last_evaluation': self.version_mgr.state.last_evaluation,
        }


# ── CLI Entry ─────────────────────────────────────────────────────────────────

def main(argv=None):
    """CLI entry point for incremental training."""
    import argparse

    ap = argparse.ArgumentParser('incremental_trainer')
    ap.add_argument('--action', default='cycle',
                    choices=['cycle', 'collect', 'report', 'promote', 'rollback', 'auto', 'check-trades'],
                    help='Action to perform')
    ap.add_argument('--trigger', default=TRIGGER_SCHEDULED,
                    choices=[TRIGGER_SCHEDULED, TRIGGER_THRESHOLD, TRIGGER_MANUAL])
    ap.add_argument('--window-days', type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument('--min-trades', type=int, default=DEFAULT_MIN_NEW_TRADES)
    ap.add_argument('--coins', nargs='*', default=DEFAULT_COINS)
    ap.add_argument('--state-file', default=DEFAULT_STATE_FILE)
    ap.add_argument('--model-dir', default=DEFAULT_MODEL_BASE_DIR)
    args = ap.parse_args(argv)

    # Try to load AB comparator
    ab_cmp = None
    try:
        from ab_shadow_comparator import ABShadowComparator
        ab_cmp = ABShadowComparator(state_file='data/ab_comparator_state.json')
    except Exception:
        pass

    trainer = IncrementalTrainer(
        model_base_dir=args.model_dir,
        state_file=args.state_file,
        window_days=args.window_days,
        min_new_trades=args.min_trades,
        coins=args.coins,
        ab_comparator=ab_cmp,
    )

    if args.action == 'cycle':
        if not trainer.should_retrain(args.trigger):
            print('[IncrementalTrainer] Retrain not needed yet')
            report = trainer.generate_report()
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return

        result = trainer.run_retrain_cycle(trigger=args.trigger)
        print('\n' + '=' * 60)
        print('Retrain Cycle Result')
        print('=' * 60)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.action == 'collect':
        result = trainer.collect_recent_data()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == 'report':
        report = trainer.generate_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))

    elif args.action == 'promote':
        shadow = trainer.version_mgr.state.current_shadow_version
        if shadow:
            trainer.version_mgr.promote_shadow(shadow)
        else:
            print('No shadow version to promote')

    elif args.action == 'rollback':
        trainer.version_mgr.rollback_live()

    elif args.action == 'auto':
        result = trainer.auto_retrain_if_needed()
        print('\n' + '=' * 60)
        print('Auto-Retrain Result')
        print('=' * 60)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.action == 'check-trades':
        result = trainer.check_new_trades()
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
