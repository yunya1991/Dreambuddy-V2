"""test_auto_set_leverage.py — 开仓前自动set_leverage(LEVERAGE)测试.

Bug背景: SOL开仓时OKX交易所端杠杆=10x，代码内LEVERAGE=5x只影响本地仓位大小计算，
但place_order没有显式调用set_leverage，导致交易所用默认杠杆(可能10x)。

修复: 每次place_order前显式调用OKX /set-leverage接口，保证交易所端杠杆=配置值。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))
if str(_V15_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(_V15_ROOT / "core"))
if str(_V15_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_V15_ROOT / "lib"))


class TestAutoSetLeverage:
    """OKX set_leverage必须在place_order前显式调用。"""

    CFG = {
        "dry_run": False, "simulated": False,
        "api_key": "a", "secret_key": "b", "passphrase": "c",
        "base_url": "https://www.okx.com",
        "default_inst_id": "BTC-USDT-SWAP", "default_usdt_amount": 100,
        "default_leverage": 5.0,
    }

    def test_okx_client_has_set_leverage_method(self):
        """OKXSimulatedClient应有set_leverage方法。"""
        from okx_client import OKXSimulatedClient
        assert hasattr(OKXSimulatedClient, "set_leverage"), (
            "OKXSimulatedClient缺少set_leverage方法"
        )

    def test_set_leverage_calls_okx_api(self):
        """set_leverage应POST /api/v5/account/set-leverage带正确参数。"""
        from okx_client import OKXSimulatedClient
        client = OKXSimulatedClient(config=self.CFG)
        mock_post = MagicMock(return_value={"code": "0", "msg": "", "data": [{}]})
        client._post = mock_post

        result = client.set_leverage(inst_id="SOL-USDT-SWAP", leverage=5, mgn_mode="isolated")

        assert result.get("ok") is True or result.get("code") == "0"
        calls = [c for c in mock_post.call_args_list if "set-leverage" in str(c.args[0])]
        assert len(calls) >= 1, f"未调用set-leverage接口: {mock_post.call_args_list}"
        body = calls[0].args[1]
        assert body.get("instId") == "SOL-USDT-SWAP"
        assert str(body.get("lever")) == "5"
        assert body.get("mgnMode") == "isolated"

    def test_place_order_auto_calls_set_leverage(self):
        """place_order内部应该先调set_leverage再下订单。"""
        from okx_client import OKXSimulatedClient
        client = OKXSimulatedClient(config=self.CFG)
        client.set_leverage = MagicMock(return_value={"ok": True, "code": "0"})
        mock_post = MagicMock(return_value={"code": "0", "msg": "", "data": [{"ordId": "123"}]})
        client._post = mock_post
        client._has_credentials = MagicMock(return_value=True)
        client._audit_log = MagicMock()

        client.place_order(
            inst_id="SOL-USDT-SWAP",
            side="buy",
            ord_type="market",
            sz=0.5,
            td_mode="isolated",
            pos_side="long",
            leverage=5,
        )

        # set_leverage必须被调用1次(位置参数形式：inst_id, leverage, mgn_mode)
        assert client.set_leverage.call_count == 1, f"set_leverage调用次数={client.set_leverage.call_count}"
        args, kwargs = client.set_leverage.call_args
        assert args[0] == "SOL-USDT-SWAP", f"args[0]={args[0]}"
        assert args[1] == 5, f"args[1]={args[1]}"
        assert (args[2] if len(args) > 2 else kwargs.get("mgn_mode")) == "isolated"

    def test_default_leverage_is_5(self):
        """不传leverage参数时应使用default_leverage=5。"""
        from okx_client import OKXSimulatedClient
        client = OKXSimulatedClient(config=self.CFG)
        client.set_leverage = MagicMock(return_value={"ok": True, "code": "0"})
        mock_post = MagicMock(return_value={"code": "0", "msg": "", "data": [{"ordId": "123"}]})
        client._post = mock_post
        client._has_credentials = MagicMock(return_value=True)
        client._audit_log = MagicMock()

        client.place_order(
            inst_id="BTC-USDT-SWAP",
            side="buy",
            ord_type="market",
            sz=0.01,
            td_mode="isolated",
            pos_side="long",
        )

        assert client.set_leverage.call_count == 1
        args, kwargs = client.set_leverage.call_args
        assert args[0] == "BTC-USDT-SWAP"
        # 默认应是cfg.default_leverage=5 (或5.0)
        assert abs(float(args[1]) - 5.0) < 0.001, f"默认杠杆={args[1]}非5x"
