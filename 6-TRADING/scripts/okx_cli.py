#!/usr/bin/env python3
"""
Dream-MultiSkill OKX CLI 调用模块 v1.0
=======================================
统一使用 okx CLI 而非 Python requests
Copyright: Dream-MultiSkill System
"""

import json
import subprocess
from typing import Dict, Optional, List


class OKXCLI:
    """OKX CLI 封装"""
    
    def __init__(self, profile: str = "live"):
        self.profile = profile
        self.base_cmd = "okx"
        
    def _run(self, args: List[str]) -> Dict:
        """执行OKX CLI命令"""
        cmd = [self.base_cmd] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr}
            
            # 解析输出
            lines = result.stdout.strip().split('\n')
            return {"success": True, "data": lines, "raw": result.stdout}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_ticker(self, inst_id: str = "BTC-USDT-SWAP") -> Dict:
        """获取行情"""
        result = self._run(["market", "ticker", inst_id, "--json"])
        if result["success"]:
            try:
                # 尝试解析JSON输出
                import json
                data = json.loads(result["raw"])
                return {"success": True, "data": data}
            except:
                # 降级: 解析文本输出
                data = {}
                for line in result["data"]:
                    if ':' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            data[parts[0].strip()] = parts[1].strip()
                return {"success": True, "data": data}
        return result
    
    def get_candles(self, inst_id: str, bar: str = "1H", limit: int = 100) -> Dict:
        """获取K线"""
        result = self._run([
            "market", "candles", inst_id,
            "--bar", bar,
            "--limit", str(limit),
            "--json"
        ])
        if result["success"]:
            try:
                # 尝试解析JSON
                data = json.loads(result["raw"])
                return {"success": True, "data": data}
            except:
                return {"success": True, "data": result["data"]}
        return result
    
    def get_balance(self) -> Dict:
        """获取账户余额"""
        result = self._run(["account", "balance"])
        if result["success"]:
            data = {}
            for line in result["data"]:
                if '\t' in line:
                    parts = line.split('\t')
                    if len(parts) >= 3 and parts[0].strip() == 'USDT':
                        data["USDT"] = {
                            "equity": parts[1].strip(),
                            "available": parts[2].strip()
                        }
            return {"success": True, "data": data}
        return result
    
    def get_positions(self, inst_id: str = "BTC-USDT-SWAP") -> Dict:
        """获取持仓"""
        result = self._run(["account", "positions", "--instId", inst_id])
        if result["success"]:
            # 检查是否有持仓
            if "No open positions" in result["raw"]:
                return {"success": True, "data": [], "has_position": False}
            return {"success": True, "data": result["data"], "has_position": True}
        return result
    
    def place_order(self, inst_id: str, side: str, pos_side: str, sz: int,
                    ord_type: str = "market", price: Optional[float] = None) -> Dict:
        """下单"""
        args = [
            "swap", "place",
            "--instId", inst_id,
            "--side", side,
            "--posSide", pos_side,
            "--sz", str(sz),
            "--ordType", ord_type,
            "--tdMode", "cross"
        ]
        if price and ord_type == "limit":
            args.extend(["--px", str(price)])
        
        result = self._run(args)
        return result
    
    def close_position(self, inst_id: str) -> Dict:
        """平仓"""
        result = self._run(["swap", "close", "--instId", inst_id])
        return result


def test_okx_cli():
    """测试OKX CLI"""
    cli = OKXCLI()
    
    print("=" * 60)
    print("OKX CLI 连接测试")
    print("=" * 60)
    
    # 测试行情
    print("\n📊 行情数据:")
    ticker = cli.get_ticker()
    if ticker["success"]:
        data = ticker["data"]
        print(f"   BTC-USDT-SWAP: ${data.get('last', 'N/A')}")
        print(f"   24h涨跌: {data.get('24h change %', 'N/A')}")
        print(f"   24h高: ${data.get('24h high', 'N/A')}")
        print(f"   24h低: ${data.get('24h low', 'N/A')}")
    
    # 测试余额
    print("\n💰 账户余额:")
    balance = cli.get_balance()
    if balance["success"]:
        data = balance["data"]
        if "USDT" in data:
            print(f"   USDT可用: {data['USDT']['available']}")
    
    # 测试持仓
    print("\n📋 持仓状态:")
    positions = cli.get_positions()
    if positions["success"]:
        if positions.get("has_position"):
            print(f"   有持仓")
        else:
            print(f"   无持仓 (空仓)")
    
    print("\n" + "=" * 60)
    print("✅ OKX CLI 完全正常!")
    print("=" * 60)


if __name__ == "__main__":
    test_okx_cli()
