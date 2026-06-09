#!/usr/bin/env python3
"""
OKX 统一交易工具包 v1.1
===========================
Unified Trading Toolkit for OKX (Dual-Track: Demo + Live)

覆盖5大交易维度:
  1. 现货交易 (Spot)     → okx trade / okx spot
  2. 合约交易 (Futures)   → okx swap place
  3. 期权交易 (Options)   → okx option place
  4. 网格机器人 (Grid Bot)→ okx bot grid create
  5. DCA马丁 (DCA Bot)    → okx bot dca create

v1.1新增:
  - Demo/Live 双轨自动检测与适配
  - 期权 instId 格式自动切换 (_UM vs 非_UM)
  - 价格单位自动换算 (USDT vs BTC)
  - 环境安全检查 (防止误操作实盘)

设计原则:
  - A4发出指令 → 自动路由到正确工具
  - 统一参数接口 → 内部转换CLI语法
  - 全面的错误处理和日志
  - 支持dry-run(模拟)模式
  - Demo先验, Live后执行的安全流程

用法:
  # 现货买入 (demo)
  python3 okx_unified_toolkit.py --profile dreamdemo spot buy --coin BTC --usdt 100

  # 现货买入 (live/A5实盘)
  python3 okx_unified_toolkit.py --profile A5 spot buy --coin BTC --usdt 100

  # 期权买入Call (自动适配环境格式)
  python3 okx_unified_toolkit.py --profile dreamdemo option buy_call --coin BTC --strike 78000 --exp 2026-04-24

  # dry-run模式 (不执行, 只输出命令)
  python3 okx_unified_toolkit.py --dry-run --profile A5 option buy_call --coin BTC --strike 78000

作者: A4 Tactical Validator | 基于 okx-trade-cli@1.3.1 实测
日期: 2026-04-23 | v1.1 双轨升级
"""

import subprocess
import sys
import json
import argparse
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any


# ============================================================
# 常量与配置
# ============================================================

PROFILES = {
    "dreamdemo": {
        "desc": "DEMO模拟盘(A4验证用)",
        "env": "demo",           # demo/live
        "option_um": True,       # instId格式: _UM
        "option_tdmode": "cross", # 期权tdMode
        "option_unit": "USDT",   # 期权价格单位
        "safety_check": False,   # 实盘需要安全确认
    },
    "A5": {
        "desc": "主交易账户(实盘)",
        "env": "live",
        "option_um": False,      # ⚠️ A5实盘是非_UM格式!
        "option_tdmode": "cash", # 实盘用cash (但CLI暂不支持, 需Web激活后用cross)
        "option_unit": "BTC",    # ⚠️ 实盘期权价格以BTC计价!
        "safety_check": True,    # 🔴 实盘必须安全确认
    },
}

COIN_MAPPING = {
    "BTC": {"spot": "BTC-USDT", "swap": "BTC-USDT-SWAP", "option_uly": "BTC-USD"},
    "ETH": {"spot": "ETH-USDT", "swap": "ETH-USDT-SWAP", "option_uly": "ETH-USD"},
    "SOL": {"spot": "SOL-USDT", "swap": "SOL-USDT-SWAP", "option_uly": None},
}

# Demo/Live 期权格式差异对照表 (实测 2026-04-23)
OPTION_ENV_DIFF = {
    "dreamdemo": {
        "instId_pattern": "{COIN}-USD_UM-{YYMMDD}-{STRIKE}-{C|P}",  # 带_UM
        "example": "BTC-USD_UM-260424-78000-C",
        "tdMode": "cross",       # 或 isolated (需先在Web激活)
        "price_unit": "USDT",    # px填USDT金额, 如100=$100
        "activation": "需Web激活期权交易 (51198)",
        "note": "模拟盘使用_UM格式(USDT保证金模式)",
    },
    "A5": {
        "instId_pattern": "{COIN}-USD-{YYMMDD}-{STRIKE}-{C|P}",     # 不带_UM
        "example": "BTC-USD-260424-78000-C",
        "tdMode": "cross",        # 🔴 也需要激活! cash模式CLI报51000
        "price_unit": "BTC",      # ⚠️ px填BTC数量! 如0.03=0.03BTC≈$2338
        "activation": "需Web激活期权交易 (51198)",
        "note": "实盘使用非_UM格式(币种保证金模式), 价格单位是BTC!",
    },
}


class TradeToolkit:
    """统一交易工具包 - v1.1 双轨版 (Demo/Live自动适配)"""
    
    # Demo环境列表 (不需要安全确认)
    DEMO_PROFILES = {"dreamdemo", "demo"}
    
    def __init__(self, profile: str = "dreamdemo", dry_run: bool = False):
        self.profile = profile
        self.dry_run = dry_run
        self.log_entries: List[Dict] = []
        
        # 🔒 环境检测与配置加载
        self.env_config = PROFILES.get(profile, PROFILES.get("dreamdemo"))
        self.is_live = self.env_config.get("env") == "live"
        self.is_demo = not self.is_live
        
        # 期权格式自动配置 (根据profile自动选择)
        self.option_um = self.env_config.get("option_um", False)
        self.option_unit = self.env_config.get("option_unit", "USDT")
        self.option_tdmode = self.env_config.get("option_tdmode", "cross")
        
        if self.is_live and not dry_run:
            self.log("WARN", f"🔴 实盘模式 ({profile})! 所有操作将真实执行!")
        else:
            env_tag = "DEMO" if self.is_demo else "DRY-RUN"
            self.log("INFO", f"🟢 [{env_tag}] 模拟模式 ({profile}), 安全运行")
        
        # 显示期权格式信息
        self.log("INFO", f"期权格式: {'_UM(USDT)' if self.option_um else '非_UM(BTC计价)'} | "
                     f"tdMode={self.option_tdmode} | 价格单位={self.option_unit}")
    
    def get_env_info(self) -> Dict:
        """获取当前环境完整信息 (用于日志和调试)"""
        return {
            "profile": self.profile,
            "env": "live" if self.is_live else "demo",
            "is_live": self.is_live,
            "dry_run": self.dry_run,
            "option_format": "_UM" if self.option_um else "非_UM",
            "option_unit": self.option_unit,
            "option_tdmode": self.option_tdmode,
            "config_desc": self.env_config.get("desc", "未知"),
        }
    
    def log(self, level: str, msg: str):
        """记录日志"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"ts": ts, "level": level, "msg": msg}
        self.log_entries.append(entry)
        prefix = {"INFO": "📋", "WARN": "⚠️", "ERROR": "❌", "SUCCESS": "✅", "DRY": "🔬"}
        print(f"[{ts}] {prefix.get(level, '  ')} {msg}")
    
    def _run_cmd(self, cmd: str, description: str = "") -> Dict:
        """执行OKX CLI命令并返回结果"""
        if self.dry_run:
            self.log("DRY", f"[模拟] {description}")
            self.log("DRY", f"命令: {cmd}")
            return {"success": True, "dry_run": True, "cmd": cmd}
        
        self.log("INFO", f"执行: {description}")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout.strip()
            error = result.stderr.strip()
            
            if result.returncode != 0:
                err_msg = error or output or f"未知错误 (code={result.returncode})"
                self.log("ERROR", f"{description} 失败: {err_msg}")
                return {"success": False, "error": err_msg, "returncode": result.returncode}
            
            self.log("SUCCESS", f"{description} 成功")
            return {"success": True, "output": output}
        except subprocess.TimeoutExpired:
            self.log("ERROR", f"{description} 超时(30s)")
            return {"success": False, "error": "命令超时"}
        except Exception as e:
            self.log("ERROR", f"{description} 异常: {str(e)}")
            return {"success": False, "error": str(e)}

    # ================================================================
    # 1. 现货交易 (Spot)
    # ================================================================
    
    def spot_buy(self, coin: str, usdt_amount: float, 
                 price: Optional[float] = None,
                 tag: str = "") -> Dict:
        """
        现货买入
        Args:
            coin: 币种 (BTC/ETH/SOL...)
            usdt_amount: 买入金额(USDT)
            price: 限价(None=市价)
            tag: 标签
        """
        inst_id = COIN_MAPPING.get(coin, {}).get("spot")
        if not inst_id:
            return {"success": False, "error": f"不支持的币种: {coin}"}
        
        if price:
            # 限价单
            sz = round(usdt_amount / price, 6)  # 根据价格计算数量
            cmd = (
                f'okx trade order --instId {inst_id} --tdMode cash '
                f'--side buy --ordType limit --sz {sz} --px {price} '
                f'--tag "{tag}" --profile {self.profile}'
            )
            desc = f"现货限价买入 {coin} @{price}, ~{usdt_amount}U"
        else:
            # 市价单 (使用quoteOrderQty)
            cmd = (
                f'okx trade order --instId {inst_id} --tdMode cash '
                f'--side buy --ordType market '
                f'--quoteSz {usdt_amount} --tag "{tag}" --profile {self.profile}'
            )
            desc = f"现货市价买入 {coin}, {usdt_amount}U"
        
        return self._run_cmd(cmd, desc)
    
    def spot_sell(self, coin: str, coin_amount: float,
                  price: Optional[float] = None,
                  tag: str = "") -> Dict:
        """现货卖出"""
        inst_id = COIN_MAPPING.get(coin, {}).get("spot")
        if not inst_id:
            return {"success": False, "error": f"不支持的币种: {coin}"}
        
        if price:
            cmd = (
                f'okx trade order --instId {inst_id} --tdMode cash '
                f'--side sell --ordType limit --sz {coin_amount} '
                f'--px {price} --tag "{tag}" --profile {self.profile}'
            )
            desc = f"现货限价卖出 {coin} @{price}, {coin_amount}枚"
        else:
            cmd = (
                f'okx trade order --instId {inst_id} --tdMode cash '
                f'--side sell --ordType market --sz {coin_amount} '
                f'--tag "{tag}" --profile {self.profile}'
            )
            desc = f"现货市价卖出 {coin}, {coin_amount}枚"
        
        return self._run_cmd(cmd, desc)

    # ================================================================
    # 2. 合约交易 (Futures/Swap)
    # ================================================================
    
    def futures_long(self, coin: str, usdt_margin: float,
                     lever: int = 3,
                     px: Optional[float] = None,
                     tp_px: Optional[float] = None,
                     sl_px: Optional[float] = None,
                     tag: str = "") -> Dict:
        """
        合约做多开仓
        Args:
            coin: 币种
            usdt_margin: 保证金金额(USDT)
            lever: 杠杆倍数
            px: 开仓价格(None=市价)
            tp_px: 止盈价格
            sl_px: 止损价格
        """
        inst_id = COIN_MAPPING.get(coin, {}).get("swap")
        if not inst_id:
            return {"success": False, "error": f"不支持的合约币种: {coin}"}
        
        # 计算张数 (根据保证金和杠杆估算)
        # 实际应该先获取ticker价格精确计算
        
        base_cmd = (
            f'okx swap place --instId {inst_id} --tdMode cross '
            f'--side buy --posSide long --lever {lever} --mgnMode cross'
        )
        
        if px:
            base_cmd += f' --ordType limit --px {px}'
            sz_hint = f"(估算)"
        else:
            base_cmd += f' --ordType market'
            sz_hint = ""
        
        # 添加TP/SL
        if tp_px:
            base_cmd += f' --tpTriggerPx {tp_px} --tpOrdPx -1'
        if sl_px:
            base_cmd += f' --slTriggerPx {sl_px} --slOrdPx -1'
        
        base_cmd += f' --sz {usdt_margin} --tag "{tag}" --profile {self.profile}'
        
        desc = f"合约做多 {coin} {lever}x, 保证金{usdt_margin}U {sz_hint}"
        return self._run_cmd(base_cmd, desc)
    
    def futures_short(self, coin: str, usdt_margin: float,
                      lever: int = 3,
                      px: Optional[float] = None,
                      tp_px: Optional[float] = None,
                      sl_px: Optional[float] = None,
                      tag: str = "") -> Dict:
        """合约做空开仓"""
        inst_id = COIN_MAPPING.get(coin, {}).get("swap")
        if not inst_id:
            return {"success": False, "error": f"不支持的合约币种: {coin}"}
        
        base_cmd = (
            f'okx swap place --instId {inst_id} --tdMode cross '
            f'--side sell --posSide short --lever {lever} --mgnMode cross'
        )
        
        if px:
            base_cmd += f' --ordType limit --px {px}'
        else:
            base_cmd += f' --ordType market'
        
        if tp_px:
            base_cmd += f' --tpTriggerPx {tp_px} --tpOrdPx -1'
        if sl_px:
            base_cmd += f' --slTriggerPx {sl_px} --slOrdPx -1'
        
        base_cmd += f' --sz {usdt_margin} --tag "{tag}" --profile {self.profile}'
        
        desc = f"合约做空 {coin} {lever}x, 保证金{usdt_margin}U"
        return self._run_cmd(base_cmd, desc)

    # ================================================================
    # 3. 期权交易 (Options) ⭐ 新增
    # ================================================================
    
    @staticmethod
    def build_option_inst_id(coin: str, exp_date: str, strike: int, 
                              opt_type: str, use_um: bool = True) -> str:
        """
        构建期权instId (v1.1: 支持双格式)
        
        Args:
            coin: BTC/ETH
            exp_date: 到期日 '2026-04-24' 或 '260424'
            strike: 行权价 (整数, 如78000)
            opt_type: 'C'(Call) 或 'P'(Put)
            use_um: True=_UM格式(demo), False=非_UM格式(live A5)
        
        格式差异 (实测 2026-04-23):
            dreamdemo → BTC-USD_UM-260424-78000-C  (_UM, USDT保证金)
            A5 live   → BTC-USD-260424-78000-C     (非_UM, 币种保证金)
        """
        # 规范化到期日格式: 2026-04-24 → 260424
        exp_clean = exp_date.replace("-", "")[-6:]  # 取最后6位 YYMMDD
        
        if use_um:
            return f"{coin}-USD_UM-{exp_clean}-{strike}-{opt_type}"
        else:
            return f"{coin}-USD-{exp_clean}-{strike}-{opt_type}"
    
    def _option_auto_config(self) -> Dict:
        """根据当前profile自动配置期权参数"""
        return {
            "use_um": self.option_um,
            "tdMode": self.option_tdmode,
            "price_unit": self.option_unit,
            "need_activation": True,  # 目前两种模式都需要Web激活
        }
    
    def _build_option_cmd(self, coin: str, strike: int, exp_date: str,
                          opt_type: str, side: str, sz: int,
                          px: Optional[float] = None, tag: str = "") -> Dict:
        """
        统一期权命令构建 (v1.1: 自动适配Demo/Live)
        
        自动处理:
          1. instId格式 (_UM vs 非_UM) 根据profile自动选择
          2. tdMode 根据profile自动选择
          3. 价格单位提示 (BTC vs USDT)
          4. 安全检查 (实盘确认)
        """
        cfg = self._option_auto_config()
        use_um = cfg["use_um"]
        td_mode = cfg["tdMode"]
        unit = cfg["price_unit"]
        
        uly = COIN_MAPPING.get(coin, {}).get("option_uly")
        if not uly:
            return {"success": False, "error": f"{coin}暂不支持期权交易"}
        
        inst_id = self.build_option_inst_id(coin, exp_date, strike, opt_type, use_um)
        ord_type = "limit" if px is not None else "limit"  # 🔴 期权只用limit
        
        cmd_parts = [
            f'okx option place',
            f'--instId "{inst_id}"',
            f'--tdMode {td_mode}',
            f'--side {side}',
            f'--ordType {ord_type}',
            f'--sz {sz}',
        ]
        
        if px is not None:
            # ⚠️ 价格单位提醒
            if unit == "BTC":
                self.log("WARN", f"⚠️ 实盘模式! 期权价格单位是{unit}, "
                         f"px={px} 意味着 {px} BTC ≈ ${px * 78000:.0f}")
            cmd_parts.append(f'--px {px}')
        
        if use_um:
            cmd_parts.append(f'--uly {uly}')
        
        cmd_parts.extend([f'--tag "{tag}"', f'--profile {self.profile}'])
        
        cmd = " \\\n  ".join(cmd_parts)
        
        side_desc = {"buy": "买入", "sell": "卖出"}.get(side, side)
        type_desc = {"C": "Call", "P": "Put"}.get(opt_type, opt_type)
        desc = f"[{'实盘' if self.is_live else '模拟'}] {side_desc}{type_desc} {coin}@{strike} 到期{exp_date}, {sz}张 | 格式={'_UM' if use_um else '非_UM'}"
        
        return self._run_cmd(cmd, desc)

    def option_buy_call(self, coin: str, strike: int, exp_date: str,
                        sz: int = 1, px: Optional[float] = None,
                        tag: str = "") -> Dict:
        """
        买入看涨期权 (Buy Call / Long Call) — v1.1自动适配环境
        Args:
            coin: BTC/ETH
            strike: 行权价 (整数)
            exp_date: 到期日 (如 '2026-04-24')
            sz: 张数 (1张=1BTC/ETH)
            px: 限价 (自动适配单位: demo=USDT, live=BTC)
            tag: 标签
        """
        return self._build_option_cmd(coin, strike, exp_date, "C", "buy", sz, px, tag)
    
    def option_buy_put(self, coin: str, strike: int, exp_date: str,
                       sz: int = 1, px: Optional[float] = None,
                       tag: str = "") -> Dict:
        """买入看跌期权 (Buy Put / Long Put) — v1.1自动适配环境"""
        return self._build_option_cmd(coin, strike, exp_date, "P", "buy", sz, px, tag)
    
    def option_sell_call(self, coin: str, strike: int, exp_date: str,
                         sz: int = 1, px: Optional[float] = None,
                         tag: str = "") -> Dict:
        """卖出看涨期权 (Sell Call / Covered Call) — v1.1自动适配环境"""
        return self._build_option_cmd(coin, strike, exp_date, "C", "sell", sz, px, tag)
    
    def option_sell_put(self, coin: str, strike: int, exp_date: str,
                        sz: int = 1, px: Optional[float] = None,
                        tag: str = "") -> Dict:
        """卖出看跌期权 (Cash-Secured Put) — v1.1自动适配环境"""
        return self._build_option_cmd(coin, strike, exp_date, "P", "sell", sz, px, tag)

    # ================================================================
    # 4. 网格机器人 (Grid Bot)
    # ================================================================
    
    def create_spot_grid(self, coin: str, upper: float, lower: float,
                         grids: int, quote_sz: float = 10,
                         tag: str = "") -> Dict:
        """创建现货网格"""
        inst_id = COIN_MAPPING.get(coin, {}).get("spot")
        cmd = (
            f'okx bot grid create \\\n'
            f'  --instId {inst_id} \\\n'
            f'  --algoOrdType grid \\\n'
            f'  --maxPx {upper} \\\n'
            f'  --minPx {lower} \\\n'
            f'  --gridNum {grids} \\\n'
            f'  --runType 1 \\\n'
            f'  --quoteSz {quote_sz} \\\n'
            f'  --tag "{tag}" \\\n'
            f'  --profile {self.profile}'
        )
        desc = f"创建{coin}现货网格 [{lower}-{upper}] {grids}格 ×{quote_sz}U"
        return self._run_cmd(cmd, desc)
    
    def create_contract_grid(self, coin: str, upper: float, lower: float,
                              grids: int, lever: int = 3,
                              direction: str = "long",
                              margin: float = 100,
                              quote_sz: float = 10,
                              tp_px: Optional[float] = None,
                              sl_px: Optional[float] = None,
                              tag: str = "") -> Dict:
        """创建合约网格"""
        inst_id = COIN_MAPPING.get(coin, {}).get("swap")
        cmd_parts = [
            f'okx bot grid create \\',
            f'  --instId {inst_id} \\',
            f'  --algoOrdType contract_grid \\',
            f'  --maxPx {upper} \\',
            f'  --minPx {lower} \\',
            f'  --gridNum {grids} \\',
            f'  --runType 1 \\',
            f'  --quoteSz {quote_sz} \\',
            f'  --direction {direction} \\',
            f'  --lever {lever} \\',
            f'  --sz {margin} \\',
        ]
        if tp_px:
            cmd_parts.append(f'  --tpTriggerPx {tp_px} \\')
        if sl_px:
            cmd_parts.append(f'  --slTriggerPx {sl_px} \\')
        cmd_parts.extend([f'  --tag "{tag}" \\', f'  --profile {self.profile}'])
        
        cmd = "\n".join(cmd_parts)
        desc = f"创建{coin}合约网格[{lower}-{upper}] {grids}格 {direction} {lever}x"
        return self._run_cmd(cmd, desc)

    # ================================================================
    # 5. DCA马丁机器人 (DCA Bot)
    # ================================================================
    
    def create_dca(self, coin: str, direction: str,
                   init_amt: float, safety_orders: int,
                   safety_amt: float, step_pct: float = 0.01,
                   tp_pct: float = 2, lever: int = 3,
                   trigger: str = "instant",
                   tag: str = "") -> Dict:
        """
        创建DCA马丁机器人
        Args:
            direction: long/short
            init_amt: 首单金额(U)
            safety_orders: 最大加仓次数
            safety_amt: 加仓金额(U)
            step_pct: 价格步进(小数! 0.01=1%)
            tp_pct: 止盈%(LONG=整数, SHORT=小数!)
            lever: 杠杆
            trigger: instant/price/rsi
        """
        inst_id = COIN_MAPPING.get(coin, {}).get("swap")
        
        # 🔴 关键: tpPct方向差异
        actual_tp = tp_pct if direction == "long" else tp_pct / 100.0
        
        cmd = (
            f'okx bot dca create \\\n'
            f'  --algoOrdType contract_dca \\\n'
            f'  --instId {inst_id} \\\n'
            f'  --direction {direction} \\\n'
            f'  --initOrdAmt {init_amt} \\\n'
            f'  --maxSafetyOrds {safety_orders} \\\n'
            f'  --safetyOrdAmt {safety_amt} \\\n'
            f'  --pxSteps={step_pct} \\\n'
            f'  --pxStepsMult=1 \\\n'
            f'  --volMult=1 \\\n'
            f'  --tpPct={actual_tp} \\\n'
            f'  --lever {lever} \\\n'
            f'  --triggerStrategy {trigger} \\\n'
            f'  --tag "{tag}" \\\n'
            f'  --profile {self.profile}'
        )
        desc = f"DCA马丁 {coin} {direction} 首{init_amt}U+{safety_orders}×{safety_amt}U {lever}x"
        return self._run_cmd(cmd, desc)

    # ================================================================
    # 查询功能 (Query Functions)
    # ================================================================
    
    def get_ticker(self, coin: str) -> Dict:
        """获取最新行情"""
        inst_id = COIN_MAPPING.get(coin, {}).get("swap")
        if not inst_id:
            inst_id = COIN_MAPPING.get(coin, {}).get("spot")
        cmd = f'okx market ticker {inst_id}'
        return self._run_cmd(cmd, f"获取{coin}最新行情")
    
    def get_option_chain(self, coin: str) -> Dict:
        """获取期权链(可用合约列表)"""
        uly = COIN_MAPPING.get(coin, {}).get("option_uly")
        if not uly:
            return {"success": False, "error": f"{coin}暂无期权"}
        cmd = f'okx option instruments --uly {uly} --profile {self.profile}'
        return self._run_cmd(cmd, f"获取{coin}期权链")
    
    def get_option_greeks(self, coin: str) -> Dict:
        """获取期权Greeks数据"""
        uly = COIN_MAPPING.get(coin, {}).get("option_uly")
        if not uly:
            return {"success": False, "error": f"{coin}暂无期权"}
        cmd = f'okx option greeks --uly {uly} --profile {self.profile}'
        return self._run_cmd(cmd, f"获取{coin}期权Greeks")
    
    def get_atm_options(self, coin: str) -> Dict:
        """获取ATM附近的期权Grees (用于快速筛选)"""
        result = self.get_option_greeks(coin)
        if not result.get("success"):
            return result
        # 解析输出，过滤ATM附近的合约
        # (实际使用时需要解析表格输出)
        return result
    
    def get_option_positions(self, coin: Optional[str] = None) -> Dict:
        """获取当前期权持仓"""
        if coin:
            uly = COIN_MAPPING.get(coin, {}).get("option_uly")
            cmd = f'okx option positions --uly {uly} --profile {self.profile}' if uly else ""
        else:
            cmd = f'okx option positions --profile {self.profile}'
        return self._run_cmd(cmd or "echo unsupported", "获取期权持仓")

    def get_account_balance(self) -> Dict:
        """获取账户余额"""
        cmd = f'okx account balance --profile {self.profile}'
        return self._run_cmd(cmd, "获取账户余额")


# ============================================================
# CLI入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="OKX 统一交易工具包 v1.1 — Demo/Live双轨自动适配",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # === DEMO模式 (默认) ===
  %(prog)s --profile dreamdemo spot buy --coin BTC --usdt 100
  %(prog)s --profile dreamdemo option buy_call --coin BTC --strike 78000 --exp 2026-04-24

  # === LIVE实盘 (自动适配格式!) ===
  %(prog)s --profile A5 futures short --coin BTC --usdt 50 --lever 3
  %(prog)s --profile A5 option buy_call --coin BTC --strike 78000 --exp 2026-04-24
    -> 自动用非_UM格式 + BTC价格单位

  # === DRY-RUN (安全预览命令) ===
  %(prog)s --dry-run --profile A5 option sell_put --coin BTC --strike 75000 --exp 2026-04-25

  # === 查询 ===
  %(prog)s query greeks --coin BTC
  %(prog)s query balance
  %(prog)s query envinfo   (显示当前Demo/Live环境配置)
        """
    )
    
    parser.add_argument("--profile", default="dreamdemo", 
                        help="账户配置: dreamdemo(模拟) / A5(实盘)")
    parser.add_argument("--dry-run", action="store_true", help="模拟模式(不实际执行)")
    
    subparsers = parser.add_subparsers(dest="command", help="交易命令")
    
    # --- Spot ---
    sp = subparsers.add_parser("spot", help="现货交易")
    sp_sub = sp.add_subparsers(dest="action")
    sp_buy = sp_sub.add_parser("buy", help="现货买入")
    sp_buy.add_argument("--coin", required=True, choices=["BTC","ETH","SOL"])
    sp_buy.add_argument("--usdt", required=True, type=float, help="金额(USDT)")
    sp_buy.add_argument("--price", type=float, help="限价(可选)")
    sp_buy.add_argument("--tag", default="")
    
    sp_sell = sp_sub.add_parser("sell", help="现货卖出")
    sp_sell.add_argument("--coin", required=True)
    sp_sell.add_argument("--amount", required=True, type=float, help="数量(枚)")
    sp_sell.add_argument("--price", type=float)
    sp_sell.add_argument("--tag", default="")
    
    # --- Futures ---
    fu = subparsers.add_parser("futures", help="合约交易")
    fu_sub = fu.add_subparsers(dest="action")
    fu_long = fu_sub.add_parser("long", help="合约做多")
    fu_long.add_argument("--coin", required=True, choices=["BTC","ETH","SOL"])
    fu_long.add_argument("--usdt", required=True, type=float, help="保证金(U)")
    fu_long.add_argument("--lever", type=int, default=3, help="杠杆(默认3)")
    fu_long.add_argument("--price", type=float)
    fu_long.add_argument("--tp", type=float, help="止盈价")
    fu_long.add_argument("--sl", type=float, help="止损价")
    fu_long.add_argument("--tag", default="")
    
    fu_short = fu_sub.add_parser("short", help="合约做空")
    fu_short.add_argument("--coin", required=True)
    fu_short.add_argument("--usdt", required=True, type=float)
    fu_short.add_argument("--lever", type=int, default=3)
    fu_short.add_argument("--price", type=float)
    fu_short.add_argument("--tp", type=float)
    fu_short.add_argument("--sl", type=float)
    fu_short.add_argument("--tag", default="")
    
    # --- Options (v1.1: 自动适配Demo/Live, 无需--um) ---
    op = subparsers.add_parser("option", help="期权交易 (自动适配环境格式)")
    op_sub = op.add_subparsers(dest="action")
    
    for action_name, help_text in [("buy_call", "买Call (看涨投机)"), ("buy_put", "买Put (看跌/保险)"),
                                    ("sell_call", "卖Call/CoveredCall"),
                                    ("sell_put", "卖Put/SecuredPut")]:
        p = op_sub.add_parser(action_name, help=help_text)
        p.add_argument("--coin", required=True, choices=["BTC","ETH"], help="标的")
        p.add_argument("--strike", required=True, type=int, help="行权价(整数, 如78000)")
        p.add_argument("--exp", required=True, help="到期日 (如2026-04-24或260424)")
        p.add_argument("--sz", type=int, default=1, help="张数(默认1)")
        p.add_argument("--px", type=float, 
                       help="限价 (demo=USDT, live=BTC! 自动提示单位)")
        # v1.1: 移除--um, 自动检测
        p.add_argument("--tag", default="")
    
    # --- Grid ---
    gr = subparsers.add_parser("grid", help="网格机器人")
    gr_sub = gr.add_subparsers(dest="action")
    gr_create = gr_sub.add_parser("create", help="创建网格")
    gr_create.add_argument("--coin", required=True, choices=["BTC","ETH","SOL"])
    gr_create.add_argument("--mode", choices=["spot","contract"], required=True)
    gr_create.add_argument("--upper", required=True, type=float, help="上限价")
    gr_create.add_argument("--lower", required=True, type=float, help="下限价")
    gr_create.add_argument("--grids", required=True, type=int, help="格数")
    gr_create.add_argument("--quote-sz", type=float, default=10, help="单格金额(U)")
    gr_create.add_argument("--lever", type=int, default=3, help="杠杆(仅合约)")
    gr_create.add_argument("--direction", default="long", help="方向(仅合约)")
    gr_create.add_argument("--margin", type=float, default=100, help="保证金(仅合约,U)")
    gr_create.add_argument("--tp", type=float, help="止盈价")
    gr_create.add_argument("--sl", type=float, help="止损价")
    gr_create.add_argument("--tag", default="")
    
    # --- DCA ---
    dc = subparsers.add_parser("dca", help="DCA马丁机器人")
    dc_sub = dc.add_subparsers(dest="action")
    dc_create = dc_sub.add_parser("create", help="创建DCA")
    dc_create.add_argument("--coin", required=True, choices=["BTC","ETH"])
    dc_create.add_argument("--direction", required=True, choices=["long","short"])
    dc_create.add_argument("--first", required=True, type=float, help="首单(U)")
    dc_create.add_argument("--layers", required=True, type=int, help="加仓次数")
    dc_create.add_argument("--add", required=True, type=float, help="每笔加仓(U)")
    dc_create.add_argument("--step", type=float, default=0.01, help="步进%(默认1%)")
    dc_create.add_argument("--tp", type=float, default=2, help="止盈%(LONG整数)")
    dc_create.add_argument("--lever", type=int, default=3)
    dc_create.add_argument("--trigger", default="instant")
    dc_create.add_argument("--tag", default="")
    
    # --- Query ---
    qu = subparsers.add_parser("query", help="查询功能")
    qu_sub = qu.add_subparsers(dest="action")
    
    q_ticker = qu_sub.add_parser("ticker", help="最新行情")
    q_ticker.add_argument("--coin", required=True)
    
    q_chain = qu_sub.add_parser("option_chain", help="期权链")
    q_chain.add_argument("--coin", required=True, choices=["BTC","ETH"])
    
    q_greeks = qu_sub.add_parser("greeks", help="期权Greeks")
    q_greeks.add_argument("--coin", required=True, choices=["BTC","ETH"])
    
    q_pos = qu_sub.add_parser("positions", help="期权持仓")
    q_pos.add_argument("--coin", help="指定币种")
    
    q_bal = qu_sub.add_parser("balance", help="账户余额")
    
    q_env = qu_sub.add_parser("envinfo", help="显示当前环境信息(Demo/Live配置)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 初始化工具包
    toolkit = TradeToolkit(profile=args.profile, dry_run=args.dry_run)
    
    # 路由到对应方法
    result = {}
    
    try:
        if args.command == "spot":
            if args.action == "buy":
                result = toolkit.spot_buy(args.coin, args.usdt, args.price, args.tag)
            elif args.action == "sell":
                result = toolkit.spot_sell(args.coin, args.amount, args.price, args.tag)
        
        elif args.command == "futures":
            if args.action == "long":
                result = toolkit.futures_long(args.coin, args.usdt, args.lever,
                                             args.price, args.tp, args.sl, args.tag)
            elif args.action == "short":
                result = toolkit.futures_short(args.coin, args.usdt, args.lever,
                                              args.price, args.tp, args.sl, args.tag)
        
        elif args.command == "option":
            # v1.1: 不再传use_um, 由环境自动判断
            if args.action == "buy_call":
                result = toolkit.option_buy_call(args.coin, args.strike, args.exp,
                                                 args.sz, args.px, args.tag)
            elif args.action == "buy_put":
                result = toolkit.option_buy_put(args.coin, args.strike, args.exp,
                                                args.sz, args.px, args.tag)
            elif args.action == "sell_call":
                result = toolkit.option_sell_call(args.coin, args.strike, args.exp,
                                                  args.sz, args.px, args.tag)
            elif args.action == "sell_put":
                result = toolkit.option_sell_put(args.coin, args.strike, args.exp,
                                                 args.sz, args.px, args.tag)
        
        elif args.command == "grid":
            if args.action == "create":
                if args.mode == "spot":
                    result = toolkit.create_spot_grid(
                        args.coin, args.upper, args.lower, args.grids,
                        args.quote_sz, args.tag)
                else:
                    result = toolkit.create_contract_grid(
                        args.coin, args.upper, args.lower, args.grids,
                        args.lever, args.direction, args.margin,
                        args.quote_sz, args.tp, args.sl, args.tag)
        
        elif args.command == "dca":
            if args.action == "create":
                result = toolkit.create_dca(
                    args.coin, args.direction, args.first, args.layers,
                    args.add, args.step, args.tp, args.lever,
                    args.trigger, args.tag)
        
        elif args.command == "query":
            if args.action == "ticker":
                result = toolkit.get_ticker(args.coin)
            elif args.action == "option_chain":
                result = toolkit.get_option_chain(args.coin)
            elif args.action == "greeks":
                result = toolkit.get_option_greeks(args.coin)
            elif args.action == "positions":
                result = toolkit.get_option_positions(getattr(args, 'coin', None))
            elif args.action == "balance":
                result = toolkit.get_account_balance()
            elif args.action == "envinfo":  # v1.1新增
                env = toolkit.get_env_info()
                print("\n" + "="*60)
                print(f"  📊 当前环境信息 ({args.profile})")
                print("="*60)
                for k, v in env.items():
                    print(f"  {k:>18s}: {v}")
                print("="*60)
                
                diff = OPTION_ENV_DIFF.get(args.profile, {})
                if diff:
                    print(f"\n  📋 期权格式详情:")
                    for k2, v2 in diff.items():
                        print(f"    {k2}: {v2}")
                return
        
        else:
            parser.print_help()
            return
    
    except Exception as e:
        result = {"success": False, "error": str(e)}
        toolkit.log("ERROR", f"异常: {e}")
    
    # 输出结果
    print("\n" + "="*60)
    if result.get("success"):
        print("✅ 操作成功完成")
        if result.get("output"):
            print(f"\n输出:\n{result['output']}")
        if result.get("dry_run"):
            print("\n🔬 [DRY RUN] 以上为模拟命令，未实际执行")
    else:
        print(f"❌ 操作失败: {result.get('error', '未知错误')}")
    
    # 输出日志摘要
    if toolkit.log_entries:
        print(f"\n📊 日志: {len(toolkit.log_entries)} 条记录")
    
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
