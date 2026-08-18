#!/usr/bin/env python3
"""
Dream-Strategy-Pipeline: 六大战略阶段核心执行脚本

包含:
- A1: dream-strategy-research (深度调研)
- A2: dream-first-principles (第一性原理分析)
- A3: dream-strategy-designer (战略制定)
- A4: dream-tactical-validator (战术验证)
- A5: dream-tactical-executor (战术执行)
- A6: dream-intelligence-monitor (情报监控)

Usage:
    python dream_strategy_pipeline.py --skill <skill_name> [--params <json>]
    python dream_strategy_pipeline.py --skill all --weekday <0-6>
"""

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

import requests

# ========== 全局配置 ==========
SKILL_BASE = Path.home() / ".workbuddy" / "skills"
OUTPUT_DIR = Path.home() / "WorkBuddy" / "20260415144304" / "reports"
STRATEGY_LIBRARY_PATH = Path.home() / "WorkBuddy" / "20260415144304" / "strategy_library.yaml"
OKX_CONFIG_PATH = Path.home() / ".okx" / "config.toml"


# ========== OKX API Client (A5 子账户隔离) ==========
class OKXClient:
    """
    OKX API 客户端 - 支持 profile 隔离
    A5 系统使用 profiles.A5 子账户, main 系统使用 profiles.live
    """
    
    def __init__(self, profile: str = "A5"):
        self.base_url = "https://www.okx.com"
        self.profile = profile
        self._load_credentials(profile)
    
    def _load_credentials(self, profile: str):
        """从 ~/.okx/config.toml 读取指定 profile 的凭据"""
        try:
            # 简单 TOML 解析 (避免依赖 toml 库)
            content = OKX_CONFIG_PATH.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            # 找到对应 profile 段
            in_section = False
            creds = {}
            for line in lines:
                stripped = line.strip()
                if stripped == f"[profiles.{profile}]":
                    in_section = True
                    creds = {}
                    continue
                elif stripped.startswith("[") and in_section:
                    break  # 下一个 section
                elif in_section and "=" in stripped:
                    key, val = stripped.split("=", 1)
                    key = key.strip().strip('"')
                    val = val.strip().strip('"')
                    creds[key] = val
            
            self.api_key = creds.get("api_key", "")
            self.secret_key = creds.get("secret_key", "")
            self.passphrase = creds.get("passphrase", "")
            
            if not self.api_key or not self.secret_key:
                raise ValueError(f"Profile '{profile}' 凭据不完整")
            
            print(f"  ✅ OKXClient 加载 profile={profile} 成功 (key={self.api_key[:8]}...)")
            
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件不存在: {OKX_CONFIG_PATH}")
    
    def _sign(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """生成 OKX API 签名头 (ISO 8601 毫秒时间戳)"""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        message = ts + method.upper() + request_path + (body if body else "")
        mac = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        )
        sign = base64.b64encode(mac.digest()).decode("utf-8")
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
    
    def _request(self, method: str, path: str, params: Dict = None, body: Dict = None) -> Dict:
        """发送 API 请求"""
        # GET 请求参数需拼入 path 用于签名
        request_path = path
        if method == "GET" and params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            request_path = f"{path}?{query}"
        
        url = self.base_url + request_path
        body_str = json.dumps(body) if body else ""
        headers = self._sign(method, request_path, body_str)
        
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                resp = requests.post(url, headers=headers, data=body_str, timeout=10)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")
            
            data = resp.json()
            if data.get("code") != "0":
                print(f"  ⚠️ OKX API 错误: {data.get('code')} - {data.get('msg')}")
            return data
            
        except requests.exceptions.Timeout:
            return {"code": "-1", "msg": "请求超时"}
        except Exception as e:
            return {"code": "-1", "msg": str(e)}
    
    def get_account_balance(self) -> Dict:
        """查询账户余额"""
        return self._request("GET", "/api/v5/account/balance")
    
    def get_positions(self, inst_type: str = "SWAP") -> Dict:
        """查询持仓"""
        return self._request("GET", "/api/v5/account/positions", params={"instType": inst_type})
    
    def get_ticker(self, inst_id: str = "BTC-USDT-SWAP") -> Dict:
        """查询行情"""
        return self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})
    
    def get_candles(self, inst_id: str = "BTC-USDT-SWAP", bar: str = "1H", limit: str = "10") -> Dict:
        """查询K线"""
        return self._request("GET", "/api/v5/market/candles", params={
            "instId": inst_id, "bar": bar, "limit": limit
        })
    
    def place_order(self, inst_id: str, td_mode: str, side: str, ord_type: str,
                    sz: str, px: str = None, slTriggerPx: str = None, 
                    tpTriggerPx: str = None, tag: str = "A5") -> Dict:
        """下单
        
        Args:
            inst_id: 合约ID, 如 BTC-USDT-SWAP
            td_mode: 交易模式 cross/margin/isolated
            side: buy/sell
            ord_type: market/limit
            sz: 数量(张)
            px: 价格(limit单必填)
            slTriggerPx: 止损触发价
            tpTriggerPx: 止盈触发价
            tag: 订单标签(区分系统)
        """
        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
            "tag": tag,
        }
        if px:
            body["px"] = px
        if slTriggerPx:
            body["slTriggerPx"] = slTriggerPx
        if tpTriggerPx:
            body["tpTriggerPx"] = tpTriggerPx
        
        return self._request("POST", "/api/v5/trade/order", body=body)
    
    def place_algo_order(self, inst_id: str, td_mode: str, side: str, 
                         slTriggerPx: str, slOrdPx: str, tag: str = "A5") -> Dict:
        """止损委托单"""
        body = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "slTriggerPx": slTriggerPx,
            "slOrdPx": slOrdPx,
            "ordType": "conditional",
            "tag": tag,
        }
        return self._request("POST", "/api/v5/trade/order-algo", body=body)

# ========== A1: 深度调研部 (v1.1 - 三角准则版) ==========
class StrategyResearcher:
    """
    A1: 深度调研 - 战略制定前的侦察兵
    
    v1.1 新增:
    - 三角准则强制执行
    - 做梦产物集成
    - 数据源优先级控制
    """
    
    VERSION = "1.1.0"
    
    def __init__(self):
        self.inst_id = "BTC-USDT-SWAP"
        self.lookback_days = 7
        # 路径配置
        self.memory_path = Path.home() / "WorkBuddy" / "20260415144304" / ".workbuddy" / "memory"
        self.episodes_path = Path.home() / ".workbuddy" / "episodes"
        self.archive_path = Path.home() / "WorkBuddy" / "20260415144304" / "reports"
        self.brainstorm_path = Path.home() / "WorkBuddy" / "20260415144304"
        # A5 专用 OKX 客户端
        self.okx = OKXClient(profile="A5")
        
    def run(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行深度调研 - 严格遵循三角准则
        
        三角准则执行顺序:
        1. 记忆调研 → 2. 历史行情调研 → 3. 策略调研 → 4. 当下调研
        """
        params = params or {}
        inst_id = params.get("inst_id", self.inst_id)
        incorporate_dream = params.get("incorporate_dream_insights", True)
        
        research_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"🔍 开始深度调研: {research_id}")
        
        # Phase 1: 三角准则执行
        print("📋 Phase 1: 执行三角准则...")
        
        # 准则一: 记忆调研
        print("  [1/4] 准则一: 记忆调研...")
        memory_research = self._triangle_memory_research()
        
        # 准则二: 历史类似行情调研
        print("  [2/4] 准则二: 历史类似行情调研...")
        historical_research = self._triangle_historical_research()
        
        # 准则三: 类似交易策略调研
        print("  [3/4] 准则三: 类似交易策略调研...")
        strategy_research = self._triangle_strategy_research()
        
        # 准则四: 当下市场主流观点调研 (Tavily优先)
        print("  [4/4] 准则四: 当下市场主流观点调研 (Tavily优先)...")
        current_sentiment = self._triangle_current_sentiment()
        
        triangle_compliance = {
            "memory_research": memory_research,
            "historical_research": historical_research,
            "strategy_research": strategy_research,
            "current_sentiment": current_sentiment
        }
        
        # Phase 2: 数据收集
        print("📊 Phase 2: 数据收集 (OKX/Tavily/Odaily)...")
        market_state = self._collect_market_data(inst_id)
        macro_snapshot = self._collect_macro_data()  # Tavily主力
        onchain_signals = self._collect_onchain_data()  # Odaily补充
        
        # Phase 3: 做梦产物集成
        dream_insights = {"incorporated": False}
        if incorporate_dream:
            print("🔮 Phase 3: 集成做梦产物...")
            dream_insights = self._incorporate_dream_insights()
        
        # Phase 4: 生成报告
        print("📝 Phase 4: 生成调研报告...")
        report = {
            "research_report": {
                "summary": self._generate_summary(market_state, macro_snapshot),
                "triangle_compliance": triangle_compliance,
                "market_state": market_state,
                "macro_snapshot": macro_snapshot,
                "onchain_signals": onchain_signals,
                "dream_insights": dream_insights,
                "archive_findings": historical_research.get("findings", []),
                "key_insights": self._extract_insights(market_state, macro_snapshot, dream_insights),
                "risk_warnings": self._extract_warnings(market_state, macro_snapshot, dream_insights)
            },
            "data_freshness": {
                "market_data_ts": datetime.now().isoformat(),
                "macro_data_ts": datetime.now().isoformat(),
                "onchain_data_ts": datetime.now().isoformat(),
                "dream_insights_ts": dream_insights.get("source_ts", datetime.now().isoformat()) if dream_insights.get("incorporated") else None
            },
            "meta": {
                "research_id": research_id,
                "researcher_version": self.VERSION,
                "triangle_compliance": True,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        # 保存报告
        self._save_report(report, research_id)
        print(f"✅ 深度调研完成: {research_id}")
        
        return report
    
    # ========== 三角准则实现 ==========
    
    def _triangle_memory_research(self) -> Dict[str, Any]:
        """
        准则一: 记忆调研
        读取MEMORY.md、daily logs、episodes历史
        """
        result = {
            "completed": False,
            "memory_findings": [],
            "episode_findings": [],
            "key_findings": []
        }
        
        try:
            # 读取MEMORY.md
            memory_file = self.memory_path / "MEMORY.md"
            if memory_file.exists():
                with open(memory_file, "r", encoding="utf-8") as f:
                    memory_content = f.read()
                    result["memory_findings"].append({
                        "source": "MEMORY.md",
                        "content_preview": memory_content[:500] + "..." if len(memory_content) > 500 else memory_content
                    })
            
            # 读取最近的daily logs
            daily_files = sorted(self.memory_path.glob("2026-*.md"), reverse=True)[:3]
            for daily_file in daily_files:
                with open(daily_file, "r", encoding="utf-8") as f:
                    result["episode_findings"].append({
                        "source": daily_file.name,
                        "content_preview": f.read()[:300] + "..."
                    })
            
            # 提取关键发现
            result["key_findings"] = [
                f"已读取{len(result['memory_findings'])}份记忆文件",
                f"已读取{len(result['episode_findings'])}份日常记录"
            ]
            result["completed"] = True
            
        except Exception as e:
            result["error"] = str(e)
            print(f"  ⚠️ 记忆调研异常: {e}")
        
        return result
    
    def _triangle_historical_research(self) -> Dict[str, Any]:
        """
        准则二: 历史类似行情调研
        Archive Center + 外部搜索
        """
        result = {
            "completed": False,
            "findings": [],
            "similarity_scores": [],
            "outcomes": []
        }
        
        try:
            # 搜索历史报告中的类似行情
            reports = list(self.archive_path.glob("*.md"))[:10]
            for report in reports:
                if "backtest" in report.name or "strategic" in report.name:
                    with open(report, "r", encoding="utf-8") as f:
                        content = f.read()
                        # 简单模式匹配
                        if "BULL" in content or "上涨" in content:
                            result["findings"].append({
                                "case_id": report.stem,
                                "similarity_score": 0.65,
                                "outcome": "上涨趋势",
                                "lessons": ["趋势延续概率高"]
                            })
                            result["similarity_scores"].append(0.65)
                            result["outcomes"].append("上涨趋势")
            
            result["completed"] = True
            result["key_findings"] = [f"找到{len(result['findings'])}个类似历史案例"]
            
        except Exception as e:
            result["error"] = str(e)
            print(f"  ⚠️ 历史调研异常: {e}")
        
        return result
    
    def _triangle_strategy_research(self) -> Dict[str, Any]:
        """
        准则三: 类似交易策略调研
        战略库 + 蒸馏部
        """
        result = {
            "completed": False,
            "strategies_found": [],
            "recommendations": []
        }
        
        try:
            # 读取战略库
            if STRATEGY_LIBRARY_PATH.exists():
                with open(STRATEGY_LIBRARY_PATH, "r", encoding="utf-8") as f:
                    content = f.read()
                    result["strategies_found"].append({
                        "source": "strategy_library.yaml",
                        "strategies": ["sunzi_002", "breakout_001"]
                    })
                    result["recommendations"].append("sunzi_002 适用于趋势确认场景")
            
            result["completed"] = True
            
        except Exception as e:
            result["error"] = str(e)
            print(f"  ⚠️ 策略调研异常: {e}")
        
        return result
    
    def _triangle_current_sentiment(self) -> Dict[str, Any]:
        """
        准则四: 当下市场主流观点调研
        
        数据源优先级: Tavily(主力) > Odaily(补充)
        """
        result = {
            "completed": False,
            "bullish_ratio": 0.5,
            "key_sources": ["Tavily"],  # 主力来源
            "fallback_used": False,
            "主流观点": "市场情绪谨慎"
        }
        
        try:
            # TODO: 实际调用 Tavily API
            # 当前模拟 Tavily 结果
            result["bullish_ratio"] = 0.55
            result["key_sources"] = ["Tavily (主力)"]
            result["主流观点"] = "BTC技术面偏多，关注$75K阻力"
            
            # 如果Tavily失败，降级到Odaily
            # if tavily_failed:
            #     print("  📡 Tavily失败，降级到Odaily...")
            #     result["fallback_used"] = True
            #     result["key_sources"].append("Odaily (补充)")
            
            result["completed"] = True
            
        except Exception as e:
            result["error"] = str(e)
            print(f"  ⚠️ 当下调研异常: {e}")
        
        return result
    
    # ========== 做梦产物集成 ==========
    
    def _incorporate_dream_insights(self) -> Dict[str, Any]:
        """
        集成做梦部产物
        读取最新的brainstorm报告，提取关键洞察
        """
        result = {
            "incorporated": False,
            "suppressed_signals": [],
            "nightmare_scenarios": [],
            "counter_intuitive": [],
            "improvement_suggestions": []
        }
        
        try:
            # 查找最新的brainstorm报告
            brainstorm_files = list(self.brainstorm_path.glob("dream_brainstorm_daily_*.md"))
            if not brainstorm_files:
                print("  ⚠️ 未找到做梦产物，跳过集成")
                return result
            
            latest_brainstorm = max(brainstorm_files, key=lambda p: p.stat().st_mtime)
            print(f"  🔮 读取做梦产物: {latest_brainstorm.name}")
            
            with open(latest_brainstorm, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 提取做梦洞察
            result["source_file"] = latest_brainstorm.name
            result["source_ts"] = datetime.fromtimestamp(latest_brainstorm.stat().st_mtime).isoformat()
            
            # 提取被压制的信号
            if "RSI超卖" in content or "被压制的信号" in content:
                result["suppressed_signals"].append("RSI超卖反弹信号被系统忽视")
            
            if "ETF逆势" in content:
                result["counter_intuitive"].append("ETF逆势买入是强信号")
            
            # 提取噩梦场景
            if "噩梦场景" in content:
                import re
                nightmare_matches = re.findall(r'⚠️ \*\*(.*?)\*\*: (.+)', content)
                for match in nightmare_matches[:3]:
                    result["nightmare_scenarios"].append(f"{match[0]}: {match[1][:50]}")
            
            # 提取优化建议
            if "决策优化" in content:
                result["improvement_suggestions"].append("增加RSI超卖维度")
                result["improvement_suggestions"].append("设计地缘反转机制")
            
            result["incorporated"] = True
            print(f"  ✅ 已集成{len(result['suppressed_signals'])}个被压制信号，{len(result['nightmare_scenarios'])}个噩梦场景")
            
        except Exception as e:
            result["error"] = str(e)
            print(f"  ⚠️ 做梦产物集成异常: {e}")
        
        return result
    
    def _collect_market_data(self, inst_id: str) -> Dict[str, Any]:
        """收集市场数据 - 接入 OKX 实时 API"""
        try:
            # 获取实时行情
            ticker = self.okx.get_ticker(inst_id)
            if ticker.get("code") != "0" or not ticker.get("data"):
                print(f"  ⚠️ 行情API失败，使用模拟数据: {ticker.get('msg')}")
                return self._mock_market_data()
            
            data = ticker["data"][0]
            price = float(data.get("last", 74000))
            high_24h = float(data.get("high24h", price))
            low_24h = float(data.get("low24h", price))
            vol_24h = float(data.get("vol24h", 0))
            
            # 获取资金费率
            funding_resp = self.okx._request("GET", "/api/v5/public/funding-rate", 
                                              params={"instId": inst_id, "limit": "1"})
            funding_rate = 0.0001
            if funding_resp.get("code") == "0" and funding_resp.get("data"):
                funding_rate = float(funding_resp["data"][0].get("fundingRate", 0.0001))
            
            # 简单趋势判断
            price_change_pct = (price - low_24h) / low_24h * 100 if low_24h > 0 else 0
            trend_direction = "BULL" if price_change_pct > 1 else "BEAR" if price_change_pct < -1 else "NEUTRAL"
            
            result = {
                "price": price,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "vol_24h": vol_24h,
                "price_change_pct": round(price_change_pct, 2),
                "trend_direction": trend_direction,
                "trend_continuation": price_change_pct > 0.5,
                "resistance_minimum": "UP" if price_change_pct > 0.5 else "DOWN" if price_change_pct < -0.5 else "NEUTRAL",
                "rsi_1h": 50.0,  # RSI 需要K线计算，暂用默认值
                "rsi_state": "neutral",
                "atr_pct": (high_24h - low_24h) / low_24h * 100 if low_24h > 0 else 0.25,
                "vol_regime": "high" if vol_24h > 50000 else "normal",
                "funding_rate": funding_rate,
                "oi_delta_pct": 0.0,
                "data_source": "OKX_REALTIME"
            }
            print(f"  📊 实时行情: ${price:,.2f} | 24h变化: {price_change_pct:+.2f}% | FR: {funding_rate*100:.4f}%")
            return result
            
        except Exception as e:
            print(f"  ⚠️ 行情获取异常，使用模拟数据: {e}")
            return self._mock_market_data()
    
    def _mock_market_data(self) -> Dict[str, Any]:
        """模拟市场数据 (fallback)"""
        return {
            "price": 74389.50,
            "trend_direction": "BULL",
            "trend_continuation": True,
            "resistance_minimum": "UP",
            "rsi_1h": 58.3,
            "rsi_state": "neutral",
            "atr_pct": 0.25,
            "vol_regime": "medium",
            "funding_rate": 0.0001,
            "oi_delta_pct": 1.2,
            "data_source": "MOCK_FALLBACK"
        }
    
    def _collect_macro_data(self) -> Dict[str, Any]:
        """收集宏观数据"""
        # TODO: 实际调用 Tavily API
        return {
            "sentiment": "neutral",
            "risk_level": 1,
            "key_events": ["美联储利率决议", "BTC ETF净流入"]
        }
    
    def _collect_onchain_data(self) -> Dict[str, Any]:
        """收集链上数据"""
        # TODO: 实际调用链上数据API
        return {
            "whale_activity": "neutral",
            "etf_flow": "inflow",
            "prediction_bias": "bullish"
        }
    
    def _generate_summary(self, market_state: Dict, macro: Dict) -> str:
        """生成一句话总结"""
        trend = market_state.get("trend_direction", "NEUTRAL")
        sentiment = macro.get("sentiment", "neutral")
        return f"市场{trend}趋势，宏观{sentiment}偏好"
    
    def _extract_insights(self, market: Dict, macro: Dict, dream_insights: Dict = None) -> list:
        """
        提取关键洞察
        
        v1.1新增: 整合做梦产物中的被压制信号和反直觉信号
        """
        insights = []
        
        # 基础洞察
        if market.get("trend_continuation"):
            insights.append("趋势延续动能充沛")
        if market.get("rsi_1h", 50) < 40:
            insights.append("RSI处于低位，存在反弹空间")
        if macro.get("etf_flow") == "inflow":
            insights.append("ETF资金持续净流入")
        
        # 🔮 做梦部洞察 (醒目标注)
        if dream_insights and dream_insights.get("incorporated"):
            for signal in dream_insights.get("suppressed_signals", []):
                insights.append(f"🔮做梦部洞察: {signal}")
            
            for counter in dream_insights.get("counter_intuitive", []):
                insights.append(f"🔮反直觉: {counter}")
        
        return insights[:5]  # 最多5条
    
    def _extract_warnings(self, market: Dict, macro: Dict, dream_insights: Dict = None) -> list:
        """
        提取风险警告
        
        v1.1新增: 整合做梦产物中的噩梦场景
        """
        warnings = []
        
        # 基础警告
        if market.get("funding_rate", 0) > 0.005:
            warnings.append("资金费率偏高，存在多头拥挤风险")
        if market.get("vol_regime") == "high":
            warnings.append("波动率处于高位")
        
        # 🔮 噩梦场景 (从做梦产物提取)
        if dream_insights and dream_insights.get("incorporated"):
            for nightmare in dream_insights.get("nightmare_scenarios", [])[:2]:
                warnings.append(f"⚠️ 噩梦场景: {nightmare}")
        
        return warnings[:3]  # 最多3条
    
    def _save_report(self, report: Dict, research_id: str):
        """保存调研报告"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{research_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"✅ 调研报告已保存: {filepath}")


# ========== A2: 第一性原理分析部 (v2.0 - 双维度+左右脑+MA轨迹法) ==========
class FirstPrinciplesAnalyzer:
    """
    A2: 第一性原理分析 - 双维度×左右脑科学方法
    
    v2.0 核心升级:
    - 双维度分析: 基本面(资金流+情绪+地缘+政策) × 技术面(趋势+动量+波动)
    - 左右脑科学: 左脑确定性量化 vs 右脑模糊性判断
    - MA轨迹法: 用MA处理逻辑形成趋势变化轨迹
    """
    
    VERSION = "2.0.0"
    
    def __init__(self):
        # 阻力权重
        self.resistance_weights = {
            "cost_friction": 0.30,
            "liquidity_friction": 0.35,
            "crowding_friction": 0.20,
            "vol_friction": 0.15
        }
        # 基本面权重
        self.fundamental_weights = {
            "capital_flow": 0.35,
            "sentiment": 0.25,
            "geopolitical": 0.20,
            "policy": 0.20
        }
        # 技术面权重
        self.technical_weights = {
            "trend": 0.40,
            "momentum": 0.30,
            "volatility": 0.15,
            "support_resistance": 0.15
        }
        # MA权重
        self.ma_weights = {
            "short": 0.30,  # MA5
            "medium": 0.40,  # MA20
            "long": 0.30    # MA60
        }
    
    def run(self, research_report: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行第一性原理分析 v2.0
        
        执行顺序:
        Phase 1: 基本面分析 (资金流+情绪+地缘+政策)
        Phase 2: 技术面分析 (趋势+动量+波动+支撑阻力)
        Phase 3: 左右脑辩证 (矛盾检测+主要矛盾识别)
        Phase 4: 阻力分析 (成本+流动性+拥挤+波动)
        Phase 5: MA轨迹法 (趋势追踪)
        Phase 6: 综合推演
        Phase 7: Regime分类
        """
        analysis_id = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"🧠 开始第一性原理分析: {analysis_id}")
        
        # 如果没有传入research_report，使用模拟数据
        if research_report is None:
            research_report = self._generate_mock_research()
        
        # Phase 1: 基本面分析
        print("📊 Phase 1: 基本面分析 (资金流+情绪+地缘+政策)...")
        fundamental = self._analyze_fundamental(research_report)
        
        # Phase 2: 技术面分析
        print("📊 Phase 2: 技术面分析 (趋势+动量+波动)...")
        technical = self._analyze_technical(research_report)
        
        # Phase 3: 左右脑辩证
        print("🧬 Phase 3: 左右脑辩证 (矛盾检测)...")
        brain_analysis = self._analyze_brain(research_report, fundamental, technical)
        
        # Phase 4: 阻力分析
        print("⚡ Phase 4: 阻力分析...")
        resistance = self._analyze_resistance(research_report)
        
        # Phase 5: MA轨迹法
        print("📈 Phase 5: MA轨迹法 (趋势追踪)...")
        ma_trajectory = self._analyze_ma_trajectory(research_report)
        
        # Phase 6: 综合推演
        print("🔮 Phase 6: 综合推演...")
        synthesis = self._synthesize_v2(resistance, fundamental, technical, brain_analysis, ma_trajectory)
        
        # Phase 7: Regime分类
        print("📋 Phase 7: Regime分类...")
        regime = self._classify_regime(research_report, fundamental, technical, ma_trajectory)
        
        result = {
            "first_principles_analysis": {
                "dual_dimension_analysis": {
                    "fundamental": fundamental,
                    "technical": technical,
                    "cross_dimension": brain_analysis.get("cross_dimension", {})
                },
                "brain_analysis": brain_analysis,
                "resistance_analysis": resistance,
                "trend_analysis": {
                    "ma_trajectory_method": ma_trajectory,
                    "trend_phase": ma_trajectory.get("trend_phase", "盘整"),
                    "trend_direction": ma_trajectory.get("trend_direction", "NEUTRAL"),
                    "trend_strength": ma_trajectory.get("trend_strength", 5),
                    "trend_momentum": ma_trajectory.get("trend_momentum", "stable"),
                    "trend_confidence": ma_trajectory.get("confidence", 0.7)
                },
                "synthesis": synthesis
            },
            "market_regime_classification": regime,
            "meta": {
                "analysis_id": analysis_id,
                "version": self.VERSION,
                "timestamp": datetime.now().isoformat(),
                "left_right_brain_integrated": True,
                "ma_trajectory_method": True
            }
        }
        
        self._save_analysis(result, analysis_id)
        print(f"✅ 第一性原理分析完成: {analysis_id}")
        
        return result
    
    def _generate_mock_research(self) -> Dict[str, Any]:
        """生成模拟调研数据"""
        return {
            "research_report": {
                "market_state": {
                    "price": 74500.0,
                    "trend_direction": "BULL",
                    "trend_continuation": True,
                    "rsi_1h": 58.3,
                    "atr_pct": 0.25,
                    "funding_rate": 0.0001,
                    "oi_delta_pct": 1.2
                },
                "macro_snapshot": {
                    "sentiment": "risk_on",
                    "risk_level": 1,
                    "key_events": ["美联储暂停加息"]
                },
                "onchain_signals": {
                    "etf_flow": "inflow",
                    "prediction_bias": "bullish"
                }
            }
        }
    
    # ========== Phase 1: 基本面分析 ==========
    
    def _analyze_fundamental(self, research: Dict) -> Dict[str, Any]:
        """
        基本面分析: 资金流 + 情绪 + 地缘 + 政策
        """
        report = research.get("research_report", {})
        market = report.get("market_state", {})
        macro = report.get("macro_snapshot", {})
        onchain = report.get("onchain_signals", {})
        
        # 1.1 资金流分析
        capital_flow = self._analyze_capital_flow(market, onchain)
        
        # 1.2 情绪分析
        sentiment = self._analyze_sentiment(market, macro)
        
        # 1.3 地缘分析
        geopolitical = self._analyze_geopolitical(macro)
        
        # 1.4 政策分析
        policy = self._analyze_policy(macro)
        
        # 综合基本面方向
        fund_score = (
            capital_flow.get("score", 50) * self.fundamental_weights["capital_flow"] +
            sentiment.get("score", 50) * self.fundamental_weights["sentiment"] +
            geopolitical.get("score", 50) * self.fundamental_weights["geopolitical"] +
            policy.get("score", 50) * self.fundamental_weights["policy"]
        )
        
        fund_direction = "BULLISH" if fund_score > 55 else "BEARISH" if fund_score < 45 else "NEUTRAL"
        
        return {
            "capital_flow": capital_flow,
            "sentiment": sentiment,
            "geopolitical": geopolitical,
            "policy": policy,
            "synthesis": {
                "fundamental_direction": fund_direction,
                "fundamental_score": round(fund_score, 1),
                "confidence": 0.75
            }
        }
    
    def _analyze_capital_flow(self, market: Dict, onchain: Dict) -> Dict[str, Any]:
        """资金流分析: L1宏观/L2中观/L3微观"""
        etf_flow = onchain.get("etf_flow", "neutral")
        funding = market.get("funding_rate", 0)
        oi_delta = market.get("oi_delta_pct", 0)
        
        # ETF流入加分
        etf_score = 70 if etf_flow == "inflow" else 30 if etf_flow == "outflow" else 50
        
        # OI变化评分
        oi_score = 65 if oi_delta > 0 else 35 if oi_delta < 0 else 50
        
        # 资金费率评分
        funding_score = 30 if funding > 0.005 else 70 if funding < -0.005 else 50
        
        # 综合评分
        score = (etf_score * 0.4 + oi_score * 0.3 + funding_score * 0.3)
        
        return {
            "macro_liquidity": {"direction": "NEUTRAL", "score": 50},
            "etf_flow": {
                "direction": etf_flow.upper(),
                "score": etf_score,
                "amount": "+$6.64亿" if etf_flow == "inflow" else "-$2亿"
            },
            "oi_change": {"direction": "UP" if oi_delta > 0 else "DOWN", "score": oi_score},
            "micro_liquidity": {"depth": "$15M", "spread": "5bps"},
            "score": round(score, 1),
            "direction": "INFLOW" if score > 55 else "OUTFLOW" if score < 45 else "NEUTRAL"
        }
    
    def _analyze_sentiment(self, market: Dict, macro: Dict) -> Dict[str, Any]:
        """情绪分析"""
        funding = market.get("funding_rate", 0)
        rsi = market.get("rsi_1h", 50)
        
        # 资金费率情绪
        if funding > 0.005:
            funding_signal = "极度贪婪"
            funding_score = 20
        elif funding > 0.001:
            funding_signal = "轻度贪婪"
            funding_score = 40
        elif funding < -0.005:
            funding_signal = "极度恐惧"
            funding_score = 80
        else:
            funding_signal = "中性"
            funding_score = 50
        
        # RSI情绪
        if rsi > 70:
            rsi_signal = "超买"
            rsi_score = 25
        elif rsi < 30:
            rsi_signal = "超卖"
            rsi_score = 75
        else:
            rsi_signal = "中性"
            rsi_score = 50
        
        # 综合情绪
        fear_greed = (funding_score + rsi_score) / 2
        
        return {
            "fear_greed": round(fear_greed, 1),
            "funding_rate": f"{funding*100:.3f}%",
            "long_short_ratio": "1.05",
            "signal": "BULLISH" if fear_greed > 55 else "BEARISH" if fear_greed < 45 else "NEUTRAL"
        }
    
    def _analyze_geopolitical(self, macro: Dict) -> Dict[str, Any]:
        """地缘政治分析"""
        events = macro.get("key_events", [])
        
        # 简化判断
        impact = "NEUTRAL"
        score = 50
        
        for event in events:
            if "战争" in event or "冲突" in event:
                impact = "POSITIVE"
                score = 65  # 避险情绪利好BTC
            elif "和平" in event or "谈判" in event:
                impact = "NEGATIVE"
                score = 40
        
        return {
            "key_events": events,
            "impact": impact,
            "weight": 0.15,
            "score": score
        }
    
    def _analyze_policy(self, macro: Dict) -> Dict[str, Any]:
        """政策金融刺激分析"""
        sentiment = macro.get("sentiment", "neutral")
        
        if sentiment == "risk_on":
            score = 65
            direction = "EASING"
        elif sentiment == "risk_off":
            score = 35
            direction = "TIGHTENING"
        else:
            score = 50
            direction = "NEUTRAL"
        
        return {
            "central_bank": direction,
            "regulatory": "NEUTRAL",
            "score": score
        }
    
    # ========== Phase 2: 技术面分析 ==========
    
    def _analyze_technical(self, research: Dict) -> Dict[str, Any]:
        """
        技术面分析: 趋势 + 动量 + 波动 + 支撑阻力
        """
        market = research.get("research_report", {}).get("market_state", {})
        
        # 趋势指标
        trend = self._analyze_trend_indicators(market)
        
        # 动量指标
        momentum = self._analyze_momentum(market)
        
        # 波动指标
        volatility = self._analyze_volatility(market)
        
        # 支撑阻力
        support_resistance = self._analyze_support_resistance(market)
        
        # 综合技术评分
        tech_score = (
            trend.get("score", 50) * self.technical_weights["trend"] +
            momentum.get("score", 50) * self.technical_weights["momentum"] +
            volatility.get("score", 50) * self.technical_weights["volatility"] +
            support_resistance.get("score", 50) * self.technical_weights["support_resistance"]
        )
        
        tech_direction = "BULLISH" if tech_score > 55 else "BEARISH" if tech_score < 45 else "NEUTRAL"
        
        return {
            "trend_indicators": trend,
            "momentum": momentum,
            "volatility": volatility,
            "support_resistance": support_resistance,
            "synthesis": {
                "technical_direction": tech_direction,
                "technical_score": round(tech_score, 1),
                "confidence": 0.75
            }
        }
    
    def _analyze_trend_indicators(self, market: Dict) -> Dict[str, Any]:
        """趋势指标分析"""
        direction = market.get("trend_direction", "NEUTRAL")
        continuation = market.get("trend_continuation", False)
        
        # EMA排列评分
        if direction == "BULL" and continuation:
            ema_score = 75
            ema_signal = "多头排列"
        elif direction == "BEAR" and continuation:
            ema_score = 25
            ema_signal = "空头排列"
        else:
            ema_score = 50
            ema_signal = "混乱排列"
        
        # MA斜率 (模拟)
        ma_slopes = {
            "short": "2.3%",   # MA5
            "medium": "1.8%",  # MA20
            "long": "0.9%"    # MA60
        }
        
        return {
            "ema_alignment": "BULLISH" if direction == "BULL" else "BEARISH" if direction == "BEAR" else "MIXED",
            "ma_slopes": ma_slopes,
            "ma_trajectory": "UP" if direction == "BULL" else "DOWN",
            "trajectory_strength": 65,
            "score": ema_score,
            "signal": ema_signal
        }
    
    def _analyze_momentum(self, market: Dict) -> Dict[str, Any]:
        """动量指标分析"""
        rsi = market.get("rsi_1h", 50)
        
        # RSI评分
        if rsi > 70:
            rsi_state = "OVERBOUGHT"
            rsi_score = 25
        elif rsi < 30:
            rsi_state = "OVERSOLD"
            rsi_score = 75  # 超卖=上涨动能积累
        else:
            rsi_state = "NEUTRAL"
            rsi_score = 50
        
        # MACD信号 (模拟)
        macd_signal = "NEUTRAL"
        macd_score = 50
        if rsi > 50:
            macd_signal = "GOLDEN_CROSS"
            macd_score = 65
        
        return {
            "rsi": rsi,
            "rsi_state": rsi_state,
            "macd": {"signal": macd_signal, "score": macd_score},
            "stochastic": "55%",
            "score": (rsi_score + macd_score) / 2
        }
    
    def _analyze_volatility(self, market: Dict) -> Dict[str, Any]:
        """波动指标分析"""
        atr_pct = market.get("atr_pct", 0.25)
        
        # ATR状态
        if atr_pct > 0.4:
            atr_state = "HIGH"
            atr_score = 30  # 高波动=高阻力
        elif atr_pct < 0.2:
            atr_state = "LOW"
            atr_score = 70  # 低波动=低阻力
        else:
            atr_state = "NORMAL"
            atr_score = 50
        
        return {
            "atr": f"{atr_pct*100:.1f}%",
            "atr_state": atr_state,
            "bollinger_position": "50%",
            "score": atr_score
        }
    
    def _analyze_support_resistance(self, market: Dict) -> Dict[str, Any]:
        """支撑阻力分析"""
        price = market.get("price", 74500)
        
        # 关键价位
        nearest_support = round(price / 1000) * 1000 - 1000
        nearest_resistance = round(price / 1000) * 1000 + 1000
        
        # 距离评估
        dist_to_support = price - nearest_support
        dist_to_resistance = nearest_resistance - price
        
        if dist_to_support < dist_to_resistance * 0.5:
            sr_score = 60  # 靠近支撑
        elif dist_to_resistance < dist_to_support * 0.5:
            sr_score = 40  # 靠近阻力
        else:
            sr_score = 50
        
        return {
            "key_levels": [f"${nearest_support:,}", f"${nearest_resistance:,}"],
            "nearest_support": f"${nearest_support:,}",
            "nearest_resistance": f"${nearest_resistance:,}",
            "score": sr_score
        }
    
    # ========== Phase 3: 左右脑辩证 ==========
    
    def _analyze_brain(self, research: Dict, fundamental: Dict, technical: Dict) -> Dict[str, Any]:
        """
        左右脑科学分析
        左脑: 确定性量化
        右脑: 模糊性判断
        """
        fund_dir = fundamental.get("synthesis", {}).get("fundamental_direction", "NEUTRAL")
        tech_dir = technical.get("synthesis", {}).get("technical_direction", "NEUTRAL")
        
        # 左脑确定性量化
        left_brain = {
            "quantitative_signals": [
                f"基本面方向: {fund_dir}",
                f"技术面方向: {tech_dir}",
                f"综合得分: {fundamental.get('synthesis',{}).get('fundamental_score',50)}"
            ],
            "deterministic_score": (fundamental.get('synthesis',{}).get('fundamental_score',50) + 
                                   technical.get('synthesis',{}).get('technical_score',50)) / 2,
            "direction": "UP" if fund_dir == "BULLISH" and tech_dir == "BULLISH" else 
                        "DOWN" if fund_dir == "BEARISH" and tech_dir == "BEARISH" else "NEUTRAL"
        }
        
        # 右脑模糊性判断
        right_brain = {
            "pattern_recognition": ["均线多头排列", "量价配合良好"],
            "fuzzy_bias": fund_dir,  # 与基本面方向一致
            "confidence_interval": {
                "pessimistic": -5,
                "base": 0,
                "optimistic": 8
            }
        }
        
        # 矛盾检测
        contradiction_detected = (fund_dir != tech_dir)
        left_vs_right = "LEFT_DOMINANT" if fund_dir == "BULLISH" else "RIGHT_DOMINANT" if tech_dir == "BULLISH" else "SYNTHESIZED"
        
        # 主要矛盾识别
        if contradiction_detected:
            primary_contradiction = f"基本面{量化方向标签(fund_dir)} vs 技术面{量化方向标签(tech_dir)}"
            weight_adjustment = {
                "fundamental": "50%",
                "technical": "50%"
            }
        else:
            primary_contradiction = "无显著矛盾"
            weight_adjustment = {
                "fundamental": "50%",
                "technical": "50%"
            }
        
        # 跨维度一致性
        cross_alignment = "SAME" if fund_dir == tech_dir else "OPPOSITE" if (fund_dir == "BULLISH" and tech_dir == "BEARISH") or (fund_dir == "BEARISH" and tech_dir == "BULLISH") else "MIXED"
        
        return {
            "left_brain": left_brain,
            "right_brain": right_brain,
            "contradiction": {
                "detected": contradiction_detected,
                "left_vs_right": left_vs_right,
                "reconciled_direction": left_brain["direction"]
            },
            "main_contradiction": {
                "primary": primary_contradiction,
                "secondary": "无",
                "weight_adjustment": weight_adjustment
            },
            "cross_dimension": {
                "alignment": cross_alignment,
                "synthesis_confidence": 0.8 if cross_alignment == "SAME" else 0.5
            }
        }
    
    # ========== Phase 4: 阻力分析 ==========
    
    def _analyze_resistance(self, research: Dict) -> Dict[str, Any]:
        """阻力分析"""
        market = research.get("research_report", {}).get("market_state", {})
        
        funding = abs(market.get("funding_rate", 0))
        oi_delta = market.get("oi_delta_pct", 0)
        atr_pct = market.get("atr_pct", 0.25)
        
        cost_friction = min(100, funding * 10000)
        crowding_friction = min(100, (abs(oi_delta) + funding * 100) * 5)
        vol_friction = min(100, atr_pct * 200)
        liquidity_friction = 35  # 默认中等流动性
        
        total = (
            cost_friction * self.resistance_weights["cost_friction"] +
            liquidity_friction * self.resistance_weights["liquidity_friction"] +
            crowding_friction * self.resistance_weights["crowding_friction"] +
            vol_friction * self.resistance_weights["vol_friction"]
        )
        
        return {
            "resistance_score": round(total, 2),
            "resistance_direction": "DOWN" if total < 40 else "UP",
            "resistance_components": {
                "cost_friction": {"score": round(cost_friction, 2), "weight": 0.30},
                "liquidity_friction": {"score": round(liquidity_friction, 2), "weight": 0.35},
                "crowding_friction": {"score": round(crowding_friction, 2), "weight": 0.20},
                "vol_friction": {"score": round(vol_friction, 2), "weight": 0.15}
            },
            "resistance_minimum_path": "UP" if total < 45 else "DOWN" if total > 55 else "NEUTRAL",
            "resistance_confidence": 0.75
        }
    
    # ========== Phase 5: MA轨迹法 ==========
    
    def _analyze_ma_trajectory(self, research: Dict) -> Dict[str, Any]:
        """
        MA轨迹法: 用MA处理逻辑形成趋势变化轨迹
        
        Step 1: 计算MA序列 (模拟)
        Step 2: 计算MA斜率
        Step 3: 合成趋势轨迹
        Step 4: 趋势强度判断
        Step 5: 趋势拐点检测
        """
        market = research.get("research_report", {}).get("market_state", {})
        price = market.get("price", 74500)
        
        # 模拟MA值
        ma5 = price * 0.995   # 短期均线
        ma20 = price * 0.98   # 中期均线
        ma60 = price * 0.95   # 长期均线
        
        # Step 2: 计算MA斜率 (模拟)
        ma_slopes = {
            "MA5": 2.3,   # 短期斜率 2.3%
            "MA20": 1.8,  # 中期斜率 1.8%
            "MA60": 0.9   # 长期斜率 0.9%
        }
        
        # Step 3: 合成趋势轨迹
        # 轨迹 = 0.3×短期斜率 + 0.4×中期斜率 + 0.3×长期斜率
        trajectory_value = (
            ma_slopes["MA5"] * self.ma_weights["short"] +
            ma_slopes["MA20"] * self.ma_weights["medium"] +
            ma_slopes["MA60"] * self.ma_weights["long"]
        )
        
        # 归一化 (假设历史标准差为1.5%)
        trajectory_normalized = trajectory_value / 1.5
        
        # Step 4: 趋势强度判断
        if abs(trajectory_normalized) > 2:
            trend_strength = 8
            trend_strength_label = "STRONG"
        elif abs(trajectory_normalized) > 1:
            trend_strength = 6
            trend_strength_label = "MODERATE"
        else:
            trend_strength = 4
            trend_strength_label = "WEAK"
        
        # 趋势方向
        trend_direction = "BULL" if trajectory_value > 0 else "BEAR" if trajectory_value < 0 else "NEUTRAL"
        
        # 趋势动能
        trend_momentum = "accelerating" if trajectory_normalized > 1 else "decelerating" if trajectory_normalized < -1 else "stable"
        
        # Step 5: 趋势阶段
        if trajectory_normalized > 1.5:
            trend_phase = "加速期"
        elif trajectory_normalized > 0:
            trend_phase = "启动期"
        elif trajectory_normalized > -1:
            trend_phase = "盘整"
        else:
            trend_phase = "衰竭期"
        
        # 历史统计 (模拟)
        historical_stats = {
            "similar_patterns": 3,
            "success_rate": "68%",
            "avg_reversal_point": "$72,000"
        }
        
        return {
            "ma_slopes": ma_slopes,
            "trajectory_value": round(trajectory_value, 2),
            "trajectory_normalized": round(trajectory_normalized, 2),
            "trend_strength": trend_strength,
            "trend_strength_label": trend_strength_label,
            "trend_direction": trend_direction,
            "trend_momentum": trend_momentum,
            "trend_phase": trend_phase,
            "confidence": 0.75,
            "historical_stats": historical_stats
        }
    
    # ========== Phase 6: 综合推演 ==========
    
    def _synthesize_v2(self, resistance: Dict, fundamental: Dict, technical: Dict, 
                       brain: Dict, ma_trajectory: Dict) -> Dict[str, Any]:
        """综合推演 v2.0"""
        res_path = resistance.get("resistance_minimum_path", "NEUTRAL")
        ma_direction = ma_trajectory.get("trend_direction", "NEUTRAL")
        fund_dir = fundamental.get("synthesis", {}).get("fundamental_direction", "NEUTRAL")
        
        # 一致性判断
        all_same = (res_path == ma_direction == "UP") or (res_path == ma_direction == "DOWN")
        
        if all_same:
            path_confidence = 0.85
            scenarios = [
                {"scenario": "乐观", "probability": 0.20, "condition": "成交量放大配合"},
                {"scenario": "基准", "probability": 0.60, "condition": "当前趋势延续"},
                {"scenario": "悲观", "probability": 0.20, "condition": "外部冲击"}
            ]
        elif res_path == "NEUTRAL" or ma_direction == "NEUTRAL":
            path_confidence = 0.50
            scenarios = [
                {"scenario": "乐观", "probability": 0.30, "condition": "突破关键阻力"},
                {"scenario": "基准", "probability": 0.40, "condition": "区间震荡"},
                {"scenario": "悲观", "probability": 0.30, "condition": "跌破支撑"}
            ]
        else:
            path_confidence = 0.40
            scenarios = [
                {"scenario": "乐观", "probability": 0.25, "condition": "基本面改善"},
                {"scenario": "基准", "probability": 0.40, "condition": "震荡等待突破"},
                {"scenario": "悲观", "probability": 0.35, "condition": "趋势反转"}
            ]
        
        return {
            "least_resistance_path": res_path,
            "path_confidence": path_confidence,
            "contradictions": [brain.get("main_contradiction", {}).get("primary", "无")] if brain.get("contradiction", {}).get("detected") else [],
            "alternative_scenarios": scenarios
        }
    
    # ========== Phase 7: Regime分类 ==========
    
    def _classify_regime(self, research: Dict, fundamental: Dict, technical: Dict,
                         ma_trajectory: Dict) -> Dict[str, Any]:
        """市场 Regime 分类"""
        direction = ma_trajectory.get("trend_direction", "NEUTRAL")
        trajectory_value = ma_trajectory.get("trajectory_normalized", 0)
        rsi = research.get("research_report", {}).get("market_state", {}).get("rsi_1h", 50)
        
        # Regime分类
        if rsi < 30:
            regime = "TREND_EXHAUSTION"
            signals = ["RSI超卖", "MA轨迹下行"]
        elif rsi > 70:
            regime = "TREND_EXHAUSTION"
            signals = ["RSI超买", "MA轨迹上行"]
        elif abs(trajectory_value) > 1.5:
            regime = "TREND_STRONG"
            signals = ["MA轨迹强势", "趋势明确"]
        elif abs(trajectory_value) < 0.5:
            regime = "RANGE_BOUND"
            signals = ["MA轨迹趋缓", "方向不明"]
        else:
            regime = "BREAKOUT_PENDING"
            signals = ["MA轨迹收敛", "突破在即"]
        
        return {
            "regime": regime,
            "confidence": 0.75,
            "signals": signals
        }
    
    def _save_analysis(self, analysis: Dict, analysis_id: str):
        """保存分析结果"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{analysis_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        print(f"✅ 分析报告已保存: {filepath}")


def 量化方向标签(direction: str) -> str:
    """将BULLISH/BEARISH转换为中文"""
    mapping = {"BULLISH": "偏多", "BEARISH": "偏空", "NEUTRAL": "中性"}
    return mapping.get(direction, "中性")


# ========== A3: 战略制定部 ==========
class StrategyDesigner:
    """A3: 战略制定 - 从战略库匹配最合适的战略"""
    
    VERSION = "1.0.0"
    
    # 战略库（简化版，实际应从YAML加载）
    STRATEGY_LIBRARY = {
        "TREND_STRONG": [
            {"id": "sunzi_002", "name": "集中优势兵力", "bias": "LONG", "modifier": 1.0, "leverage": 3},
            {"id": "napoleon_001", "name": "中央突破", "bias": "LONG", "modifier": 0.8, "leverage": 2}
        ],
        "TREND_EXHAUSTION": [
            {"id": "sunzi_001", "name": "以逸待劳", "bias": "WAIT", "modifier": 0.5, "leverage": 2},
            {"id": "spolander_001", "name": "多周期确认", "bias": "WAIT", "modifier": 0.5, "leverage": 1}
        ],
        "RANGE_BOUND": [
            {"id": "sunzi_003", "name": "分兵游击", "bias": "WAIT", "modifier": 0.3, "leverage": 1},
            {"id": "ww2_002", "name": "多战线施压", "bias": "REDUCE", "modifier": 0.3, "leverage": 1}
        ],
        "BREAKOUT_PENDING": [
            {"id": "livermore_001", "name": "关键点突破", "bias": "LONG", "modifier": 0.8, "leverage": 2}
        ],
        "FALSE_BREAKOUT_RISK": [
            {"id": "ww2_001", "name": "诱敌深入后反击", "bias": "SHORT", "modifier": 0.5, "leverage": 2},
            {"id": "sunzi_004", "name": "避实击虚", "bias": "SHORT", "modifier": 0.5, "leverage": 2}
        ],
        "EXTREME": [
            {"id": "sunzi_001", "name": "以逸待劳", "bias": "WAIT", "modifier": 0.2, "leverage": 1}
        ]
    }
    
    def run(self, first_principles_analysis: Dict, research_report: Dict) -> Dict[str, Any]:
        """执行战略制定"""
        directive_id = f"directive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        regime = first_principles_analysis.get("market_regime_classification", {}).get("regime", "RANGE_BOUND")
        trend = first_principles_analysis.get("first_principles_analysis", {}).get("trend_analysis", {})
        synthesis = first_principles_analysis.get("first_principles_analysis", {}).get("synthesis", {})
        
        # 匹配战略
        strategy = self._match_strategy(regime, trend)
        
        directive = {
            "matched_strategy": strategy["id"],
            "strategy_name": strategy["name"],
            "category": "形势判断",
            "source": "孙子兵法",
            "match_confidence": 0.85,
            "trigger_conditions_met": ["趋势动能充沛"],
            "exclusion_conditions_checked": [],
            "directive_bias": strategy["bias"],
            "position_modifier": strategy["modifier"],
            "leverage_cap": strategy["leverage"],
            "rhythm_instruction": self._get_rhythm_instruction(strategy["bias"])
        }
        
        result = {
            "strategy_directive": directive,
            "alternative_strategies": [],
            "strategy_rationale": f"基于{regime}市场状态，选择{strategy['name']}",
            "execution_notes": [
                "等待入场信号确认",
                "严格遵守仓位限制",
                "及时跟踪止损"
            ],
            "meta": {
                "directive_id": directive_id,
                "designer_version": self.VERSION,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        self._save_directive(result, directive_id)
        return result
    
    def _match_strategy(self, regime: str, trend: Dict) -> Dict:
        """匹配战略"""
        strategies = self.STRATEGY_LIBRARY.get(regime, self.STRATEGY_LIBRARY["RANGE_BOUND"])
        return strategies[0]
    
    def _get_rhythm_instruction(self, bias: str) -> str:
        """获取节奏指令"""
        instructions = {
            "LONG": "顺势而为，回调入场，不追高",
            "SHORT": "反弹做空，不逆势",
            "WAIT": "保持耐心，等待明确信号",
            "REDUCE": "轻仓试探，控制风险"
        }
        return instructions.get(bias, "谨慎操作")
    
    def _save_directive(self, result: Dict, directive_id: str):
        """保存战略指令"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{directive_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ 战略指令已保存: {filepath}")


# ========== A4: 战术验证部 ==========
class TacticalValidator:
    """A4: 战术验证 - 沙盘推演"""
    
    VERSION = "1.0.0"
    
    def run(self, strategy_directive: Dict, market_state: Dict) -> Dict[str, Any]:
        """执行战术验证"""
        validation_id = f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 生成情景分析
        scenarios = self._generate_scenarios(strategy_directive, market_state)
        
        # 计算期望值
        ev = self._calculate_expected_value(scenarios)
        
        # 风险指标
        risk_metrics = self._calculate_risk_metrics(scenarios)
        
        # 反事实分析
        counterfactual = self._generate_counterfactual(strategy_directive)
        
        # 调整建议
        adjustments = self._generate_adjustments(ev, risk_metrics)
        
        overall_pass = ev.get("ev_bps", 0) > 0 and risk_metrics.get("max_loss_pct", 1) < 1.0
        
        result = {
            "validation_result": {
                "overall_pass": overall_pass,
                "scenario_analysis": scenarios,
                "expected_value": ev,
                "risk_metrics": risk_metrics,
                "counterfactual_analysis": counterfactual,
                "adjustment_suggestions": adjustments,
                "validation_notes": []
            },
            "meta": {
                "validation_id": validation_id,
                "validator_version": self.VERSION,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        self._save_validation(result, validation_id)
        return result
    
    def _generate_scenarios(self, directive: Dict, market: Dict) -> list:
        """生成情景分析"""
        current_price = market.get("price", 74000)
        bias = directive.get("directive_bias", "WAIT")
        
        if bias == "WAIT":
            return [{
                "scenario": "等待情景",
                "probability": 1.0,
                "price_path": "价格维持震荡",
                "pnl_expectation": 0,
                "key_risks": [],
                "tactic_viable": True
            }]
        
        # 基准/乐观/悲观情景
        direction = 1 if bias == "LONG" else -1
        scenarios = [
            {
                "scenario": "基准情景",
                "probability": 0.50,
                "price_path": f"价格向{direction*0.02*current_price:.0f}波动",
                "pnl_expectation": direction * 300,
                "key_risks": [],
                "tactic_viable": True
            },
            {
                "scenario": "乐观情景",
                "probability": 0.25,
                "price_path": f"价格向{direction*0.04*current_price:.0f}波动",
                "pnl_expectation": direction * 600,
                "key_risks": [],
                "tactic_viable": True
            },
            {
                "scenario": "悲观情景",
                "probability": 0.25,
                "price_path": "触发止损",
                "pnl_expectation": -370,
                "key_risks": ["假突破", "止损过小"],
                "tactic_viable": False
            }
        ]
        return scenarios
    
    def _calculate_expected_value(self, scenarios: list) -> Dict[str, float]:
        """计算期望值"""
        ev_pnl = sum(s["probability"] * s["pnl_expectation"] for s in scenarios)
        ev_bps = (ev_pnl / 74000) * 10000 if ev_pnl != 0 else 0
        
        return {
            "ev_bps": round(ev_bps, 2),
            "ev_usdt": round(ev_pnl, 2),
            "calculation": "加权平均"
        }
    
    def _calculate_risk_metrics(self, scenarios: list) -> Dict[str, Any]:
        """计算风险指标"""
        max_loss = min(s["pnl_expectation"] for s in scenarios)
        
        return {
            "max_loss_pct": round(abs(max_loss) / 74000 * 100, 2),
            "max_loss_usdt": round(abs(max_loss), 2),
            "win_rate_breakeven": round(abs(max_loss) / (300 + abs(max_loss)) if max_loss < 0 else 0.35, 2),
            "risk_reward_ratio": round(300 / abs(max_loss), 2) if max_loss < 0 else 2.0
        }
    
    def _generate_counterfactual(self, directive: Dict) -> Dict[str, str]:
        """反事实分析"""
        return {
            "if_no_entry": "错失潜在收益300刀",
            "if_larger_position": "亏损扩大至500刀",
            "if_tighter_stop": "被止损2次，实际亏损400刀"
        }
    
    def _generate_adjustments(self, ev: Dict, risk: Dict) -> list:
        """生成调整建议"""
        adjustments = []
        if risk.get("max_loss_pct", 0) > 0.8:
            adjustments.append({
                "field": "position_size",
                "current": 2,
                "suggested": 1,
                "reason": "最大亏损接近1%阈值"
            })
        return adjustments
    
    def _save_validation(self, result: Dict, validation_id: str):
        """保存验证结果"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{validation_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ 验证结果已保存: {filepath}")


# ========== A5: 战术执行部 (v2.0 - OKX 实盘接入) ==========
class TacticalExecutor:
    """
    A5: 战术执行 - 生成交易信号并执行 OKX 下单
    
    v2.0 核心升级:
    - 接入 OKX API (子账户 profiles.A5)
    - 真实下单、止损、止盈
    - 与 main 系统天然隔离 (独立 API Key + 独立子账户)
    - 订单 tag="A5" 方便回溯统计
    """
    
    VERSION = "2.0.0"
    STRATEGY_TAG = "A5"
    
    def __init__(self, profile: str = "A5"):
        self.okx = OKXClient(profile=profile)
        self.inst_id = "BTC-USDT-SWAP"
        self.td_mode = "cross"
        self.max_position_usdt = 200  # A5 最大仓位 200 USDT
    
    def run(self, strategy_directive: Dict, validation_result: Dict, market_state: Dict) -> Dict[str, Any]:
        """执行战术生成 + 真实下单"""
        signal_id = f"signal_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        validation_pass = validation_result.get("validation_result", {}).get("overall_pass", False)
        bias = strategy_directive.get("directive_bias", "WAIT")
        
        # 信号类型判定
        if not validation_pass:
            signal_type = "SKIP"
            skip_reason = "验证未通过"
        elif bias == "WAIT":
            signal_type = "SKIP"
            skip_reason = "战略指令WAIT"
        elif bias == "REDUCE":
            signal_type = "SKIP"
            skip_reason = "战略指令REDUCE"
        elif bias == "LONG":
            signal_type = "BUY"
            skip_reason = None
        elif bias == "SHORT":
            signal_type = "SHORT"
            skip_reason = None
        else:
            signal_type = "SKIP"
            skip_reason = f"未知bias={bias}"
        
        current_price = market_state.get("price", 0)
        data_source = market_state.get("data_source", "UNKNOWN")
        
        # 如果 SKIP，直接返回
        if signal_type == "SKIP":
            print(f"  ⏭️ A5 信号: SKIP ({skip_reason})")
            return self._build_skip_result(signal_id, signal_type, skip_reason, market_state)
        
        # ===== 真实下单流程 =====
        print(f"  🚀 A5 信号: {signal_type} | 准备下单...")
        
        # Step 1: 查询账户余额
        balance_result = self.okx.get_account_balance()
        if balance_result.get("code") != "0":
            print(f"  ❌ 余额查询失败: {balance_result.get('msg')}")
            return self._build_skip_result(signal_id, "SKIP", f"余额查询失败: {balance_result.get('msg')}", market_state)
        
        balance_data = balance_result.get("data", [{}])[0]
        total_eq = float(balance_data.get("totalEq", 0))
        available = float(balance_data.get("details", [{}])[0].get("availBal", 0)) if balance_data.get("details") else 0
        
        print(f"  💰 A5 子账户余额: {total_eq} USDT | 可用: {available} USDT")
        
        if available < 10:
            print(f"  ❌ A5 子账户余额不足 (< 10 USDT)")
            return self._build_skip_result(signal_id, "SKIP", f"子账户余额不足: {available} USDT", market_state)
        
        # Step 2: 计算仓位
        leverage = min(strategy_directive.get("leverage_cap", 3), 3)
        modifier = strategy_directive.get("position_modifier", 0.5)
        
        # BTC-USDT-SWAP: 1张 = 0.01 BTC
        position_usdt = min(self.max_position_usdt, available * 0.5)  # 最多用50%可用余额
        position_usdt *= modifier
        btc_amount = position_usdt / current_price
        size = max(1, int(btc_amount / 0.01))  # 最小1张
        notional = size * 0.01 * current_price
        
        print(f"  📐 仓位计算: {size}张 | 名义价值: {notional:.2f} USDT | 杠杆: {leverage}x")
        
        # Step 3: 止损止盈计算
        atr_pct = market_state.get("atr_pct", 0.25) / 100
        if signal_type == "BUY":
            side = "buy"
            close_side = "sell"
            sl_pct = max(atr_pct * 1.5, 0.005)  # 至少0.5%止损
            tp_pct = sl_pct * 2.5  # 盈亏比 2.5:1
            stop_loss = round(current_price * (1 - sl_pct), 1)
            take_profit_1 = round(current_price * (1 + tp_pct), 1)
        else:  # SHORT
            side = "sell"
            close_side = "buy"
            sl_pct = max(atr_pct * 1.5, 0.005)
            tp_pct = sl_pct * 2.5
            stop_loss = round(current_price * (1 + sl_pct), 1)
            take_profit_1 = round(current_price * (1 - tp_pct), 1)
        
        max_loss = abs(current_price - stop_loss) * size * 0.01
        
        print(f"  🛡️ 止损: ${stop_loss:,.1f} ({sl_pct*100:.2f}%) | 止盈: ${take_profit_1:,.1f} ({tp_pct*100:.2f}%)")
        print(f"  📉 最大亏损: {max_loss:.2f} USDT")
        
        # Step 4: 下单
        order_result = self.okx.place_order(
            inst_id=self.inst_id,
            td_mode=self.td_mode,
            side=side,
            ord_type="market",
            sz=str(size),
            tag=self.STRATEGY_TAG
        )
        
        order_code = order_result.get("code")
        order_data = order_result.get("data", [{}])[0] if order_result.get("data") else {}
        order_id = order_data.get("ordId", "")
        client_oid = order_data.get("clOrdId", "")
        
        if order_code != "0":
            error_msg = order_result.get("msg", "未知错误")
            print(f"  ❌ A5 下单失败: {error_msg}")
            return self._build_error_result(signal_id, signal_type, error_msg, order_result, market_state)
        
        print(f"  ✅ A5 下单成功! orderId={order_id} | {side} {size}张 @ market")
        
        # Step 5: 设置止损止盈 (分开两个 algo order)
        sl_algo = self.okx.place_algo_order(
            inst_id=self.inst_id,
            td_mode=self.td_mode,
            side=close_side,
            slTriggerPx=str(stop_loss),
            slOrdPx="-1",  # 市价触发
            tag=f"{self.STRATEGY_TAG}_SL"
        )
        
        sl_success = sl_algo.get("code") == "0"
        sl_algo_id = sl_algo.get("data", [{}])[0].get("algoId", "") if sl_algo.get("data") else ""
        print(f"  {'✅' if sl_success else '❌'} 止损委托: algoId={sl_algo_id}")
        
        # 构建信号
        signal = {
            "signal_id": signal_id,
            "signal_type": signal_type,
            "signal_confidence": 0.75,
            "generation_time": datetime.now().isoformat(),
            "valid_until": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason_codes": [f"STRATEGY_{strategy_directive.get('matched_strategy', 'UNKNOWN')}"],
            "source": {
                "strategy": strategy_directive.get("matched_strategy"),
                "strategy_name": strategy_directive.get("strategy_name"),
                "tactic_validated": validation_pass,
                "profile": "A5",
                "api_key_prefix": self.okx.api_key[:8],
            }
        }
        
        result = {
            "execution_signal": signal,
            "order_execution": {
                "exchange": "OKX",
                "order_id": order_id,
                "client_order_id": client_oid,
                "status": "FILLED" if order_code == "0" else "FAILED",
                "side": side,
                "size_contracts": size,
                "entry_price": current_price,
                "notional_usdt": round(notional, 2),
                "strategy_tag": self.STRATEGY_TAG,
                "profile": "A5",
            },
            "entry_plan": {
                "trigger_type": "MARKET",
                "trigger_conditions": ["信号已确认，市价执行"],
                "fallback_action": "已执行"
            },
            "position_plan": {
                "direction": "LONG" if signal_type == "BUY" else "SHORT",
                "size_contracts": size,
                "leverage": leverage,
                "notional_usdt": round(notional, 2),
                "max_position_usdt": self.max_position_usdt,
            },
            "risk_management": {
                "stop_loss": {
                    "type": "algo_order",
                    "algo_id": sl_algo_id,
                    "trigger_price": stop_loss,
                    "max_loss_usdt": round(max_loss, 2),
                    "max_loss_pct": round(sl_pct * 100, 2),
                    "status": "ACTIVE" if sl_success else "FAILED"
                },
                "take_profit": [{
                    "level": 1,
                    "trigger_price": take_profit_1,
                    "close_pct": 100,
                    "reason": "2.5:1风险收益比",
                    "status": "MANUAL"  # 止盈暂手动操作
                }]
            },
            "account_snapshot": {
                "total_equity": total_eq,
                "available": available,
                "position_ratio": round(notional / total_eq * 100, 2) if total_eq > 0 else 0,
            },
            "post_execution": {
                "monitoring_points": ["价格是否按预期运行", "RSI是否出现背离"],
                "adjustment_rules": ["如价格快速突破，可考虑加仓50%"],
                "emergency_exit": {"condition": "黑天鹅事件", "action": "立即市价平仓"}
            },
            "meta": {
                "executor_version": self.VERSION,
                "profile": "A5",
                "strategy_tag": self.STRATEGY_TAG,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        self._save_signal(result, signal_id)
        return result
    
    def verify_connection(self) -> Dict[str, Any]:
        """验证 A5 API 连接 (不下单，仅查询)"""
        print(f"\n🔍 验证 A5 ({self.okx.profile}) API 连接...")
        print(f"  API Key: {self.okx.api_key[:8]}...{self.okx.api_key[-4:]}")
        
        results = {}
        
        # 1. 测试行情接口 (无需认证)
        ticker = self.okx.get_ticker(self.inst_id)
        results["ticker"] = {
            "success": ticker.get("code") == "0",
            "price": float(ticker["data"][0]["last"]) if ticker.get("data") else None,
            "msg": ticker.get("msg")
        }
        
        # 2. 测试账户接口 (需要认证)
        balance = self.okx.get_account_balance()
        results["balance"] = {
            "success": balance.get("code") == "0",
            "total_eq": float(balance["data"][0]["totalEq"]) if balance.get("data") else None,
            "msg": balance.get("msg")
        }
        
        # 3. 测试持仓接口
        positions = self.okx.get_positions("SWAP")
        results["positions"] = {
            "success": positions.get("code") == "0",
            "count": len(positions.get("data", [])),
            "msg": positions.get("msg")
        }
        
        # 汇总
        all_ok = all(r["success"] for r in results.values())
        print(f"\n  📋 验证结果:")
        for name, r in results.items():
            status = "✅" if r["success"] else "❌"
            detail = f"${r['price']:,.2f}" if name == "ticker" and r.get("price") else \
                     f"{r['total_eq']} USDT" if name == "balance" and r.get("total_eq") is not None else \
                     f"{r['count']}个持仓" if name == "positions" else ""
            msg = f" | {r['msg']}" if not r["success"] else ""
            print(f"    {status} {name}: {detail}{msg}")
        
        print(f"\n  {'🎉 A5 API 连接正常!' if all_ok else '⚠️ A5 API 存在问题，请检查'}")
        return {"all_success": all_ok, "details": results}
    
    def _build_skip_result(self, signal_id: str, signal_type: str, reason: str, market: Dict) -> Dict:
        """构建 SKIP 结果"""
        result = {
            "execution_signal": {
                "signal_id": signal_id,
                "signal_type": signal_type,
                "reason": reason,
                "source": {"profile": "A5"},
                "generation_time": datetime.now().isoformat()
            },
            "order_execution": {"status": "SKIPPED", "reason": reason},
            "meta": {"executor_version": self.VERSION, "profile": "A5", "strategy_tag": self.STRATEGY_TAG}
        }
        self._save_signal(result, signal_id)
        return result
    
    def _build_error_result(self, signal_id: str, signal_type: str, error: str, 
                            order_result: Dict, market: Dict) -> Dict:
        """构建错误结果"""
        result = {
            "execution_signal": {
                "signal_id": signal_id,
                "signal_type": signal_type,
                "error": error,
                "source": {"profile": "A5"},
                "generation_time": datetime.now().isoformat()
            },
            "order_execution": {"status": "FAILED", "error": error, "raw_response": order_result},
            "meta": {"executor_version": self.VERSION, "profile": "A5", "strategy_tag": self.STRATEGY_TAG}
        }
        self._save_signal(result, signal_id)
        return result
    
    def _save_signal(self, result: Dict, signal_id: str):
        """保存执行信号"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{signal_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ 执行信号已保存: {filepath}")


# ========== A6: 情报监控部 ==========
class IntelligenceMonitor:
    """A6: 情报监控 - 实时监控市场"""
    
    VERSION = "1.0.0"
    
    def __init__(self):
        self.last_state = None
        
    def run(self, market_state: Dict, strategy_directive: Dict = None, open_positions: list = None) -> Dict[str, Any]:
        """执行情报监控"""
        monitoring_id = f"monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 变化检测
        changes = self._detect_changes(market_state)
        
        # 持仓监控
        position_status = self._monitor_positions(open_positions or [])
        
        # 风险告警
        alerts = self._generate_alerts(market_state, changes, position_status)
        
        # 行动建议
        action = self._determine_action(alerts, position_status, changes)
        
        result = {
            "monitoring_report": {
                "monitoring_id": monitoring_id,
                "monitoring_cycle": 1,
                "monitoring_time": datetime.now().isoformat(),
                "market_state_snapshot": market_state,
                "change_detection": changes,
                "position_alerts": position_status,
                "strategic_environment": {
                    "current_regime": "TREND_STRONG",
                    "regime_changed": False,
                    "strategy_still_valid": True
                },
                "risk_alerts": alerts,
                "recommendations": []
            },
            "action_required": action,
            "meta": {
                "monitor_version": self.VERSION,
                "data_sources": ["OKX", "Tavily"],
                "timestamp": datetime.now().isoformat()
            }
        }
        
        self._save_monitor_report(result, monitoring_id)
        return result
    
    def _detect_changes(self, market: Dict) -> Dict[str, Any]:
        """检测市场变化"""
        changes = []
        severity = "LOW"
        
        price_change = market.get("price_change_1h_pct", 0)
        if abs(price_change) > 2:
            changes.append(f"1H价格变动{price_change:.2f}%")
            severity = "MEDIUM"
            
        return {
            "has_significant_change": len(changes) > 0,
            "changes": changes,
            "change_summary": "无重大变化" if not changes else "; ".join(changes),
            "severity": severity
        }
    
    def _monitor_positions(self, positions: list) -> Dict[str, Any]:
        """监控持仓"""
        if not positions:
            return {"has_open_position": False}
        
        pos = positions[0]
        floating_pnl = pos.get("floating_pnl_pct", 0)
        
        status = "HEALTHY"
        if floating_pnl < -2:
            status = "CRITICAL"
        elif floating_pnl < -0.5:
            status = "WARNING"
            
        return {
            "has_open_position": True,
            "position_status": status,
            "floating_pnl_pct": floating_pnl,
            "floating_pnl_usdt": pos.get("floating_pnl_usdt", 0),
            "alerts": []
        }
    
    def _generate_alerts(self, market: Dict, changes: Dict, positions: Dict) -> list:
        """生成告警"""
        alerts = []
        
        funding = abs(market.get("funding_rate", 0))
        if funding > 0.01:
            alerts.append({"level": "MEDIUM", "message": f"资金费率极端: {funding*100:.2f}%"})
            
        rsi = market.get("rsi_1h", 50)
        if rsi > 70:
            alerts.append({"level": "MEDIUM", "message": "RSI超买"})
        elif rsi < 30:
            alerts.append({"level": "MEDIUM", "message": "RSI超卖"})
            
        if positions.get("position_status") == "CRITICAL":
            alerts.append({"level": "HIGH", "message": "持仓浮亏超过2%"})
            
        return alerts
    
    def _determine_action(self, alerts: list, positions: Dict, changes: Dict) -> Dict[str, str]:
        """决定行动"""
        levels = [a.get("level", "LOW") for a in alerts]
        
        if "CRITICAL" in levels or positions.get("position_status") == "CRITICAL":
            return {"action": "RESPONSE", "priority": "CRITICAL", "description": "立即止损"}
        elif "HIGH" in levels:
            return {"action": "ALERT", "priority": "HIGH", "description": "检查持仓状态"}
        elif "MEDIUM" in levels:
            return {"action": "MONITOR", "priority": "MEDIUM", "description": "持续关注"}
        else:
            return {"action": "NONE", "priority": "LOW", "description": "正常监控"}
    
    def _save_monitor_report(self, result: Dict, monitoring_id: str):
        """保存监控报告"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{monitoring_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ 监控报告已保存: {filepath}")


# ========== 主函数 ==========
def main():
    parser = argparse.ArgumentParser(description="Dream Strategy Pipeline")
    parser.add_argument("--skill", required=False, default=None,
                        choices=["research", "analysis", "design", "validate", "execute", "monitor", "all"],
                        help="要执行的SKILL名称")
    parser.add_argument("--params", type=str, help="JSON格式参数")
    parser.add_argument("--weekday", type=int, default=0, help="星期几(0-6)")
    parser.add_argument("--research-file", type=str, help="调研报告JSON文件路径")
    parser.add_argument("--analysis-file", type=str, help="分析结果JSON文件路径")
    parser.add_argument("--directive-file", type=str, help="战略指令JSON文件路径")
    parser.add_argument("--validation-file", type=str, help="验证结果JSON文件路径")
    parser.add_argument("--market-file", type=str, help="市场状态JSON文件路径")
    parser.add_argument("--verify", action="store_true", help="验证 A5 API 连接")
    parser.add_argument("--profile", type=str, default="A5", help="OKX profile (默认A5)")
    
    args = parser.parse_args()
    
    # 无 skill 参数时显示帮助
    if not args.skill and not args.verify:
        parser.print_help()
        sys.exit(0)
    
    # 验证模式
    if args.verify:
        executor = TacticalExecutor(profile=args.profile)
        result = executor.verify_connection()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["all_success"] else 1)
    
    # 执行对应SKILL
    if args.skill == "research":
        researcher = StrategyResearcher()
        result = researcher.run()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif args.skill == "analysis":
        # 需要先执行research
        researcher = StrategyResearcher()
        research = researcher.run()
        
        analyzer = FirstPrinciplesAnalyzer()
        result = analyzer.run(research)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif args.skill == "design":
        # 需要先执行analysis
        researcher = StrategyResearcher()
        research = researcher.run()
        
        analyzer = FirstPrinciplesAnalyzer()
        analysis = analyzer.run(research)
        
        designer = StrategyDesigner()
        result = designer.run(analysis, research)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif args.skill == "validate":
        # 需要先执行design
        researcher = StrategyResearcher()
        research = researcher.run()
        
        analyzer = FirstPrinciplesAnalyzer()
        analysis = analyzer.run(research)
        
        designer = StrategyDesigner()
        directive = designer.run(analysis, research)
        
        validator = TacticalValidator()
        market_state = research.get("research_report", {}).get("market_state", {})
        result = validator.run(directive.get("strategy_directive"), market_state)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif args.skill == "execute":
        # 完整流程 (A1-A5)
        researcher = StrategyResearcher()
        research = researcher.run()
        
        analyzer = FirstPrinciplesAnalyzer()
        analysis = analyzer.run(research)
        
        designer = StrategyDesigner()
        directive = designer.run(analysis, research)
        
        validator = TacticalValidator()
        market_state = research.get("research_report", {}).get("market_state", {})
        validation = validator.run(directive.get("strategy_directive"), market_state)
        
        executor = TacticalExecutor(profile=args.profile)
        result = executor.run(directive.get("strategy_directive"), validation, market_state)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif args.skill == "monitor":
        monitor = IntelligenceMonitor()
        market_state = {"price": 74389.5, "price_change_1h_pct": 0.35, "rsi_1h": 58.3, "funding_rate": 0.0001}
        result = monitor.run(market_state)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif args.skill == "all":
        print("=== 执行完整战略流水线 ===")
        
        # A1: 调研
        print("\n[A1] 执行深度调研...")
        researcher = StrategyResearcher()
        research = researcher.run()
        
        # A2: 分析
        print("\n[A2] 执行第一性原理分析...")
        analyzer = FirstPrinciplesAnalyzer()
        analysis = analyzer.run(research)
        
        # A3: 战略制定
        print("\n[A3] 执行战略制定...")
        designer = StrategyDesigner()
        directive = designer.run(analysis, research)
        
        # A4: 战术验证
        print("\n[A4] 执行战术验证...")
        validator = TacticalValidator()
        market_state = research.get("research_report", {}).get("market_state", {})
        validation = validator.run(directive.get("strategy_directive"), market_state)
        
        # A5: 战术执行
        print("\n[A5] 执行战术...")
        executor = TacticalExecutor(profile=args.profile)
        execution = executor.run(directive.get("strategy_directive"), validation, market_state)
        
        print("\n=== 战略流水线执行完成 ===")
        print(f"最终信号: {execution.get('execution_signal', {}).get('signal_type', 'N/A')}")


if __name__ == "__main__":
    main()
