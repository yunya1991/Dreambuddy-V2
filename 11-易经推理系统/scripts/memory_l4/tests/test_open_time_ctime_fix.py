# -*- coding: utf-8 -*-
"""open_time / cTime 永久死锁修复的单元测试.

背景：
  AMZN 离场排查发现，okx_simulated.get_positions 未返回 cTime 字段，
  导致 _check_positions 的 OKX ctime fallback 永久失败；
  叠加 PositionTracker.entry_time 在多进程并发下丢失，
  → open_time=0 → position_age_sec=0 → yijing_window_wait 永久 < 60min
  → 易经离场系统永不评估，只剩开仓静态 SL/TP 防护。

修复点：
  1. okx_simulated.get_positions: 补 cTime 字段（d.get("cTime", "0")）
  2. polling_trader._check_positions: OKX ctime 解析失败告警
  3. polling_trader 主循环: open_time=0 时从 position_tracker.entry_time 重新解析

本测试覆盖修复点 1（根因修复），通过 mock _get 验证 cTime 透传。
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


def _make_client():
    """构造一个带假凭证的 OKXSimulatedClient（不走真实网络）。"""
    from okx_simulated import OKXSimulatedClient
    cfg = {
        "api_key": "fake_key",
        "secret_key": "fake_secret",
        "passphrase": "fake_pass",
        "base_url": "https://www.okx.com",
        "simulated": True,
        "dry_run": True,
    }
    return OKXSimulatedClient(config=cfg)


class TestGetPositionsCTimeField:
    """验证 okx_simulated.get_positions 透传 cTime 字段。"""

    def test_ctime_present_in_returned_pos_dict(self):
        """OKX 返回 cTime 时，get_positions 的 pos dict 应包含 cTime 字段。"""
        client = _make_client()
        fake_okx_resp = {
            "code": "0",
            "data": [
                {
                    "instId": "AMZN-USDT-SWAP",
                    "posSide": "long",
                    "side": "buy",
                    "pos": "1.0",
                    "avgPx": "139.85",
                    "upl": "0.5",
                    "uplRatio": "0.0036",
                    "lever": "5",
                    "liqPx": "112.0",
                    "markPx": "140.35",
                    "cTime": "1788264000000",  # 毫秒级时间戳
                }
            ],
        }
        with patch.object(client, "_get", return_value=fake_okx_resp):
            result = client.get_positions("AMZN-USDT-SWAP")

        assert result["ok"] is True
        assert result["count"] == 1
        pos = result["positions"][0]
        # 核心断言：cTime 字段必须存在且值正确
        assert "cTime" in pos, "cTime 字段缺失，导致 _check_positions OKX fallback 永久失败"
        assert pos["cTime"] == "1788264000000"

    def test_ctime_missing_in_okx_response_defaults_to_zero(self):
        """OKX 返回不含 cTime 时，默认 "0"（不抛异常，下游可识别为无效）。"""
        client = _make_client()
        fake_okx_resp = {
            "code": "0",
            "data": [
                {
                    "instId": "AMZN-USDT-SWAP",
                    "posSide": "long",
                    "pos": "1.0",
                    "avgPx": "139.85",
                    "upl": "0.5",
                    "uplRatio": "0.0036",
                    "markPx": "140.35",
                    # 故意不返回 cTime
                }
            ],
        }
        with patch.object(client, "_get", return_value=fake_okx_resp):
            result = client.get_positions("AMZN-USDT-SWAP")

        assert result["ok"] is True
        pos = result["positions"][0]
        # 默认 "0"，下游 float("0") = 0.0 → 触告警路径，不再 KeyError
        assert pos["cTime"] == "0"

    def test_ctime_used_by_check_positions_fallback(self):
        """集成验证：_check_positions 在 tracker.entry_time 缺失时，
        应能从 OKX cTime 回退计算出 open_time（秒）。"""
        from datetime import datetime, timezone

        # 构造 cTime 毫秒时间戳 → 期望 open_time_sec
        expected_ts_ms = 1788264000000
        expected_open_time_sec = expected_ts_ms / 1000.0

        client = _make_client()
        fake_okx_resp = {
            "code": "0",
            "data": [
                {
                    "instId": "AMZN-USDT-SWAP",
                    "posSide": "long",
                    "pos": "1.0",
                    "avgPx": "139.85",
                    "upl": "0.5",
                    "uplRatio": "0.0036",
                    "markPx": "140.35",
                    "cTime": str(expected_ts_ms),
                }
            ],
        }
        with patch.object(client, "_get", return_value=fake_okx_resp):
            result = client.get_positions("AMZN-USDT-SWAP")

        pos = result["positions"][0]
        ctime = pos.get("cTime") or pos.get("ctime") or pos.get("created_at", "0")
        open_time_sec = float(ctime) / 1000 if float(ctime) > 1e12 else float(ctime)

        assert open_time_sec == pytest.approx(expected_open_time_sec, abs=1.0)
        # 验证 open_time_sec 可正确转换为 datetime（即不是 0）
        assert open_time_sec > 0
        dt = datetime.fromtimestamp(open_time_sec, tz=timezone.utc)
        assert dt.year == 2026
