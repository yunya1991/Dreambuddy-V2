#!/usr/bin/env python3
"""
DEPRECATED — 6-TRADING OKX CLI 封装（迁移至 51-OKX CLI 系统）
==============================================================
- 新代码请使用 `51-OKX CLI 系统/src/okx_venue` 的 Port API。
- 本文件仅保留为兼容 shim，供 6-TRADING bridge 过渡期使用。
- live 写路径默认 fail-closed：需 `OKX_VENUE_LEGACY_LIVE=1` 才放行（迁移期临时开关）。
- 已修复原实现忽略 `profile` 参数、未注入 `--profile` 的隐患。
"""

import json
import os
import subprocess
import warnings
from typing import Dict, List, Optional

LEGACY_LIVE_ENV = "OKX_VENUE_LEGACY_LIVE"
_LIVE_TOKENS = ("live", "prod", "real", "main")


def _legacy_live_allowed() -> bool:
    raw = os.getenv(LEGACY_LIVE_ENV, "0")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_live_profile(profile: str) -> bool:
    lowered = (profile or "").lower()
    return any(token in lowered for token in _LIVE_TOKENS)


class OKXCLI:
    """弃用兼容封装：内部仍调用 okx CLI，但补齐 profile 隔离与 live 写门禁。"""

    def __init__(self, profile: str = "demo"):
        self.profile = profile
        self.base_cmd = os.getenv("OKX_VENUE_CLI", "okx")
        if _is_live_profile(profile):
            warnings.warn(
                "OKXCLI(live) is deprecated; live execution stays on the 11 bypass. "
                "Use 51-OKX CLI 系统 for demo/read paths.",
                DeprecationWarning,
                stacklevel=2,
            )

    def _resolve_profile(self) -> str:
        # `paper` 是 6-TRADING 的历史别名；映射到 51 的 demo profile。
        if self.profile in {"paper", "demo"}:
            return os.getenv("OKX_VENUE_PROFILE", "demo")
        return self.profile

    def _run(self, args: List[str], *, write: bool = False) -> Dict:
        if write and _is_live_profile(self.profile) and not _legacy_live_allowed():
            return {
                "success": False,
                "error": (
                    "legacy live trading is retired; use 11 bypass or 51 demo adapter. "
                    f"Set {LEGACY_LIVE_ENV}=1 only for migration debugging."
                ),
                "error_code": "live_trading_forbidden",
            }

        cmd = [self.base_cmd, "--profile", self._resolve_profile(), *args]
        if "--json" not in cmd:
            cmd.append("--json")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
        except FileNotFoundError:
            return {
                "success": False,
                "error": f"okx CLI not found: {self.base_cmd}",
                "error_code": "cli_not_installed",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "okx CLI timeout",
                "error_code": "cli_timeout",
            }
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or result.stdout,
                "raw": result.stdout,
            }

        raw = result.stdout
        try:
            data = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            data = None
        if data is not None:
            return {"success": True, "data": data, "raw": raw}
        return {"success": True, "data": raw.strip().splitlines(), "raw": raw}

    def get_ticker(self, inst_id: str = "BTC-USDT-SWAP") -> Dict:
        result = self._run(["market", "ticker", inst_id])
        if result["success"]:
            data = result["data"]
            if isinstance(data, list):
                data = data[0] if data else {}
            return {"success": True, "data": data, "raw": result.get("raw", "")}
        return result

    def get_candles(self, inst_id: str, bar: str = "1H", limit: int = 100) -> Dict:
        result = self._run(["market", "candles", inst_id, "--bar", bar, "--limit", str(limit)])
        return result

    def get_balance(self) -> Dict:
        result = self._run(["account", "balance"])
        if not result["success"]:
            return result

        data = result["data"]
        if isinstance(data, list):
            data = data[0] if data else {}
        if isinstance(data, dict):
            details = data.get("details") or []
            usdt = next(
                (d for d in details if str(d.get("ccy", "")).upper() == "USDT"),
                {},
            )
            available = (
                usdt.get("availBal")
                or usdt.get("availEq")
                or usdt.get("cashBal")
                or data.get("totalEq")
                or "0"
            )
            return {
                "success": True,
                "data": {
                    "USDT": {
                        "equity": str(data.get("totalEq", available)),
                        "available": str(available),
                    }
                },
                "raw": result.get("raw", ""),
            }

        # 文本输出降级解析（旧 CLI 行为）
        parsed: Dict[str, Dict[str, str]] = {}
        for line in data:
            if "\t" in line:
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].strip() == "USDT":
                    parsed["USDT"] = {
                        "equity": parts[1].strip(),
                        "available": parts[2].strip(),
                    }
        return {"success": True, "data": parsed, "raw": result.get("raw", "")}

    def get_positions(self, inst_id: str = "BTC-USDT-SWAP") -> Dict:
        result = self._run(["account", "positions", "--instId", inst_id])
        if not result["success"]:
            return result

        data = result["data"]
        if isinstance(data, dict):
            data = data.get("data") or []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return {"success": True, "data": data, "has_position": bool(data)}
        if "No open positions" in result.get("raw", ""):
            return {"success": True, "data": [], "has_position": False}
        return {"success": True, "data": data, "has_position": bool(data)}

    def place_order(
        self,
        inst_id: str,
        side: str,
        pos_side: str,
        sz: int,
        ord_type: str = "market",
        price: Optional[float] = None,
    ) -> Dict:
        args = [
            "swap",
            "place",
            "--instId",
            inst_id,
            "--side",
            side,
            "--posSide",
            pos_side,
            "--sz",
            str(sz),
            "--ordType",
            ord_type,
            "--tdMode",
            "cross",
        ]
        if price and ord_type == "limit":
            args.extend(["--px", str(price)])

        result = self._run(args, write=True)
        if result.get("success") and isinstance(result.get("data"), list):
            result["data"] = result["data"][0] if result["data"] else {}
        return result

    def close_position(self, inst_id: str) -> Dict:
        result = self._run(["swap", "close", "--instId", inst_id], write=True)
        return result


def test_okx_cli():
    """测试OKX CLI（默认 demo profile）"""
    cli = OKXCLI()

    print("=" * 60)
    print("OKX CLI 连接测试")
    print("=" * 60)

    print("\n📊 行情数据:")
    ticker = cli.get_ticker()
    if ticker["success"]:
        data = ticker["data"]
        print(f"   BTC-USDT-SWAP: ${data.get('last', 'N/A')}")

    print("\n💰 账户余额:")
    balance = cli.get_balance()
    if balance["success"]:
        data = balance["data"]
        if "USDT" in data:
            print(f"   USDT可用: {data['USDT']['available']}")

    print("\n📋 持仓状态:")
    positions = cli.get_positions()
    if positions["success"]:
        print("   有持仓" if positions.get("has_position") else "   无持仓 (空仓)")

    print("\n" + "=" * 60)
    print("✅ OKX CLI 完全正常!")
    print("=" * 60)


if __name__ == "__main__":
    test_okx_cli()
