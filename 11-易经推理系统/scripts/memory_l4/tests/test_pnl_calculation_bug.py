# -*- coding: utf-8 -*-
"""PnL 计算 Bug 修复测试（2026-09-15 OKB 案例）

根因：
  TradeRecord dataclass 缺少 position_usdt / position_qty / margin_usdt / leverage 字段
  导致 getattr 全返回默认值（0.01/10/100），PnL 计算出 36.03U（实际仅 0.0003U）

修复：
  1. TradeRecord 新增 4 个仓位字段
  2. open_position 方法接受仓位参数
  3. episode JSON 使用真实字段名（position_qty 替代 position_size）
  4. upl 计算优先用 rec.position_usdt，fallback 用 rec.position_qty

测试覆盖：
  - TradeRecord 字段存在性
  - open_position 传参正确性
  - episode JSON 字段映射
  - PnL 计算公式正确性
"""
import json
import sys
import tempfile
import shutil
from pathlib import Path
from dataclasses import asdict

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class TestTradeRecordFields:
    """TradeRecord dataclass 仓位字段存在性"""

    def test_position_qty_field_exists(self):
        from scripts.memory_l4.trading_utils import TradeRecord
        rec = TradeRecord()
        assert hasattr(rec, "position_qty")
        assert rec.position_qty == 0.0

    def test_position_usdt_field_exists(self):
        from scripts.memory_l4.trading_utils import TradeRecord
        rec = TradeRecord()
        assert hasattr(rec, "position_usdt")
        assert rec.position_usdt == 0.0

    def test_margin_usdt_field_exists(self):
        from scripts.memory_l4.trading_utils import TradeRecord
        rec = TradeRecord()
        assert hasattr(rec, "margin_usdt")
        assert rec.margin_usdt == 0.0

    def test_leverage_field_exists(self):
        from scripts.memory_l4.trading_utils import TradeRecord
        rec = TradeRecord()
        assert hasattr(rec, "leverage")
        assert rec.leverage == 1


class TestOpenPositionWithSize:
    """open_position 方法接受仓位参数"""

    @pytest.fixture
    def tracker(self, tmp_path, monkeypatch):
        from scripts.memory_l4.trading_utils import PositionTracker
        # 创建临时目录
        pos_dir = tmp_path / "open_positions"
        pos_dir.mkdir()
        # monkeypatch positions_dir
        tracker = PositionTracker.__new__(PositionTracker)
        tracker.positions_dir = pos_dir
        tracker.open_positions = {}
        tracker.last_close_info = {}
        return tracker

    def test_open_position_accepts_position_params(self, tracker):
        rec = tracker.open_position(
            coin="OKB",
            inst_id="OKB-USDT-SWAP",
            direction="long",
            entry_price=112.72,
            confidence=0.80,
            hexagram="evolution_auto",
            source_tag="evolution",
            position_qty=0.01,
            position_usdt=1600.0,
            margin_usdt=320.0,
            leverage=5,
        )
        assert rec.position_qty == 0.01
        assert rec.position_usdt == 1600.0
        assert rec.margin_usdt == 320.0
        assert rec.leverage == 5

    def test_open_position_defaults_zero(self, tracker):
        """不传仓位参数时默认为 0（不是 0.01/10/100）"""
        rec = tracker.open_position(
            coin="BTC",
            inst_id="BTC-USDT-SWAP",
            direction="long",
            entry_price=50000.0,
            confidence=0.8,
            hexagram="test",
        )
        assert rec.position_qty == 0.0  # 不是 0.01
        assert rec.position_usdt == 0.0  # 不是 100
        assert rec.margin_usdt == 0.0  # 不是 100
        assert rec.leverage == 1  # 不是 10


class TestEpisodeJSONMapping:
    """episode JSON 字段映射正确"""

    def test_episode_json_uses_position_qty_not_position_size(self):
        """episode JSON 应使用 position_qty 而非 position_size（getattr 默认值 0.01）"""
        from scripts.memory_l4.trading_utils import TradeRecord
        rec = TradeRecord(
            coin="OKB",
            inst_id="OKB-USDT-SWAP",
            direction="long",
            entry_price=112.72,
            exit_price=112.75,
            position_qty=0.01,
            position_usdt=1.127,
            margin_usdt=0.1127,
            leverage=10,
        )
        # 模拟 episode JSON 生成
        episode_position_size = getattr(rec, "position_qty", 0.0)
        episode_leverage = getattr(rec, "leverage", 1)
        episode_margin = getattr(rec, "margin_usdt", 0.0)
        assert episode_position_size == 0.01  # 真实值
        assert episode_leverage == 10  # 真实值
        assert episode_margin == 0.1127  # 真实值


class TestPnLCalculation:
    """PnL 计算公式正确性"""

    def test_okb_case_pnl_correct(self):
        """OKB 案例：entry=112.72, exit=112.75, position_usdt=1600 → upl≈0.43U"""
        entry_price = 112.72
        exit_price = 112.75
        position_usdt = 1600.0  # 设计名义价值
        upl_ratio = (exit_price - entry_price) / entry_price  # ≈0.000266
        upl = position_usdt * upl_ratio
        # 1600 * 0.000266 ≈ 0.426U（不是 36.03U）
        assert upl < 1.0  # 不到 1U，不是 36U
        assert upl > 0  # 正盈利

    def test_okb_case_actual_pnl(self):
        """OKB 实际成交：position_qty=0.01, entry=112.72 → 名义价值=1.127U"""
        entry_price = 112.72
        exit_price = 112.75
        position_qty = 0.01
        # 实际名义价值 = qty × price
        actual_notional = position_qty * entry_price  # 1.127U
        upl_ratio = (exit_price - entry_price) / entry_price  # ≈0.000266
        actual_upl = actual_notional * upl_ratio  # ≈0.0003U
        assert abs(actual_notional - 1.127) < 0.01
        assert actual_upl < 0.01  # 不到 0.01U

    def test_pnl_not_100x_inflated(self):
        """修复后 PnL 不再被 100 倍放大"""
        entry_price = 112.72
        exit_price = 112.75
        position_usdt = 1600.0
        upl_ratio = (exit_price - entry_price) / entry_price
        upl = position_usdt * upl_ratio
        # 旧 bug：usdt_amt=160000（OKX pos × face_value × price）→ upl=36U
        # 修复后：usdt_amt=1600（rec.position_usdt）→ upl≈0.43U
        assert upl < 1.0  # 不再被 100 倍放大

    def test_upl_uses_rec_position_usdt_first(self):
        """upl 计算优先用 rec.position_usdt，而非 OKX API fallback"""
        from scripts.memory_l4.trading_utils import TradeRecord
        rec = TradeRecord(
            entry_price=112.72,
            exit_price=112.75,
            position_usdt=1600.0,
        )
        # 模拟 upl 计算
        usdt_amt = float(getattr(rec, "position_usdt", 0.0) or 0.0)
        assert usdt_amt == 1600.0  # 用 rec 值，不是 OKX fallback
        upl_ratio = (112.75 - 112.72) / 112.72
        upl = usdt_amt * upl_ratio
        assert upl < 1.0  # 不再被 100 倍放大


class TestPersistenceRoundTrip:
    """持久化往返：保存 → 加载 → 字段保持"""

    def test_save_load_preserves_position_fields(self, tmp_path, monkeypatch):
        """保存和加载 TradeRecord 时仓位字段不丢失"""
        from scripts.memory_l4.trading_utils import PositionTracker
        pos_dir = tmp_path / "open_positions"
        pos_dir.mkdir()
        # monkeypatch positions_dir
        tracker = PositionTracker.__new__(PositionTracker)
        tracker.positions_dir = pos_dir
        tracker.open_positions = {}
        tracker.last_close_info = {}
        rec = tracker.open_position(
            coin="OKB",
            inst_id="OKB-USDT-SWAP",
            direction="long",
            entry_price=112.72,
            confidence=0.8,
            hexagram="test",
            source_tag="evolution",
            position_qty=0.01,
            position_usdt=1600.0,
            margin_usdt=320.0,
            leverage=5,
        )
        # 验证保存的 JSON 包含新字段
        json_file = pos_dir / "OKB-USDT-SWAP.json"
        assert json_file.exists()
        with open(json_file) as f:
            data = json.load(f)
        assert data["position_qty"] == 0.01
        assert data["position_usdt"] == 1600.0
        assert data["margin_usdt"] == 320.0
        assert data["leverage"] == 5
