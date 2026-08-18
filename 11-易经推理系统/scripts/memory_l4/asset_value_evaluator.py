"""
交易价值评估器 — 多维度资产筛选系统

理论映射 (BCRM矛盾普遍性+特殊性原理):
  不同资产有不同的交易价值，需要从流动性、波动性、趋势性等多维度评估
  加密资产和 TradFi 资产具有不同的运动规律，需分类评估

评估维度:
  1. 流动性: 24h 成交额（USDT），过滤低流动性资产
  2. 波动率: 适中波动率更适合交易（过低无利润空间，过高风险大）
  3. 趋势性: ADX 指标衡量趋势强度，趋势性强的资产更适合趋势跟踪
  4. 市值等级: 大/中市值资产更稳定，适合系统化交易
  5. 资产类别: 加密/Layer1/DeFi/TradFi，分散配置降低相关性
  6. 合约可用性: OKX 是否提供 USDT 本位 SWAP 合约

选择逻辑:
  - 从 OKX 获取所有 USDT-SWAP 合约的 24h ticker 数据
  - 按流动性初筛（剔除微流动性 meme 币）
  - 按波动率评估交易价值（适中波动率得分最高）
  - 按趋势性评分（ADX>25 趋势明确）
  - TradFi 资产（XAU/SPX）直接纳入，独立评估
  - 综合评分输出推荐交易标的池
"""

import json
import time
import math
import requests
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── 资产类别定义 ──────────────────────────────────────────

ASSET_CLASS_CRYPTO_L1 = "crypto_l1"      # Layer1 公链: BTC, ETH, SOL, AVAX, NEAR...
ASSET_CLASS_CRYPTO_DEFI = "crypto_defi"   # DeFi: UNI, AAVE, COMP...
ASSET_CLASS_CRYPTO_MEME = "crypto_meme"    # Meme: DOGE, PEPE, SHIB...
ASSET_CLASS_CRYPTO_L2 = "crypto_l2"        # Layer2: ARB, OP, MATIC...
ASSET_CLASS_CRYPTO_ORACLE = "crypto_oracle" # 预言机: LINK...
ASSET_CLASS_CRYPTO_OTHER = "crypto_other"  # 其他加密资产
ASSET_CLASS_USSTOCK = "us_stock"            # 美股个股: NVDA, TSLA, AAPL...
ASSET_CLASS_TRADFI = "tradfi"               # TradFi: XAU(黄金), XAG(白银)

# 已知资产分类（先验知识）
KNOWN_ASSET_CLASS = {
    # Layer1
    "BTC": ASSET_CLASS_CRYPTO_L1, "ETH": ASSET_CLASS_CRYPTO_L1,
    "SOL": ASSET_CLASS_CRYPTO_L1, "BNB": ASSET_CLASS_CRYPTO_L1,
    "XRP": ASSET_CLASS_CRYPTO_L1, "ADA": ASSET_CLASS_CRYPTO_L1,
    "AVAX": ASSET_CLASS_CRYPTO_L1, "NEAR": ASSET_CLASS_CRYPTO_L1,
    "SUI": ASSET_CLASS_CRYPTO_L1, "APT": ASSET_CLASS_CRYPTO_L1,
    "ATOM": ASSET_CLASS_CRYPTO_L1, "DOT": ASSET_CLASS_CRYPTO_L1,
    "LTC": ASSET_CLASS_CRYPTO_L1, "BCH": ASSET_CLASS_CRYPTO_L1,
    "ETC": ASSET_CLASS_CRYPTO_L1, "TRX": ASSET_CLASS_CRYPTO_L1,
    "TON": ASSET_CLASS_CRYPTO_L1, "TONCOIN": ASSET_CLASS_CRYPTO_L1,
    "FIL": ASSET_CLASS_CRYPTO_L1, "AR": ASSET_CLASS_CRYPTO_L1,
    "INJ": ASSET_CLASS_CRYPTO_L1, "SEI": ASSET_CLASS_CRYPTO_L1,
    "TIA": ASSET_CLASS_CRYPTO_L1, "IMX": ASSET_CLASS_CRYPTO_L1,
    # DeFi
    "UNI": ASSET_CLASS_CRYPTO_DEFI, "AAVE": ASSET_CLASS_CRYPTO_DEFI,
    "COMP": ASSET_CLASS_CRYPTO_DEFI, "MKR": ASSET_CLASS_CRYPTO_DEFI,
    "CRV": ASSET_CLASS_CRYPTO_DEFI, "SNX": ASSET_CLASS_CRYPTO_DEFI,
    "PENDLE": ASSET_CLASS_CRYPTO_DEFI, "ENA": ASSET_CLASS_CRYPTO_DEFI,
    # Layer2
    "ARB": ASSET_CLASS_CRYPTO_L2, "OP": ASSET_CLASS_CRYPTO_L2,
    "MATIC": ASSET_CLASS_CRYPTO_L2, "POL": ASSET_CLASS_CRYPTO_L2,
    "STRK": ASSET_CLASS_CRYPTO_L2, "MANTA": ASSET_CLASS_CRYPTO_L2,
    "ZK": ASSET_CLASS_CRYPTO_L2, "ZKSYNC": ASSET_CLASS_CRYPTO_L2,
    # Oracle
    "LINK": ASSET_CLASS_CRYPTO_ORACLE,
    # Meme
    "DOGE": ASSET_CLASS_CRYPTO_MEME, "SHIB": ASSET_CLASS_CRYPTO_MEME,
    "PEPE": ASSET_CLASS_CRYPTO_MEME, "WIF": ASSET_CLASS_CRYPTO_MEME,
    "BONK": ASSET_CLASS_CRYPTO_MEME, "FLOKI": ASSET_CLASS_CRYPTO_MEME,
    "MEME": ASSET_CLASS_CRYPTO_MEME, "PNUT": ASSET_CLASS_CRYPTO_MEME,
    # 美股个股（OKX USDT-SWAP）
    "NVDA": ASSET_CLASS_USSTOCK, "TSLA": ASSET_CLASS_USSTOCK,
    "MSFT": ASSET_CLASS_USSTOCK, "META": ASSET_CLASS_USSTOCK,
    "GOOGL": ASSET_CLASS_USSTOCK, "AAPL": ASSET_CLASS_USSTOCK,
    "AMZN": ASSET_CLASS_USSTOCK, "COIN": ASSET_CLASS_USSTOCK,
    # TradFi（贵金属）
    "XAU": ASSET_CLASS_TRADFI, "XAG": ASSET_CLASS_TRADFI,
}

# 交易价值权重（不同类别的基础权重）
CLASS_BASE_WEIGHT = {
    ASSET_CLASS_CRYPTO_L1: 1.0,       # Layer1 最优先
    ASSET_CLASS_USSTOCK: 0.95,         # 美股高价值（低相关性分散）
    ASSET_CLASS_TRADFI: 0.95,          # TradFi 高价值
    ASSET_CLASS_CRYPTO_L2: 0.75,       # Layer2 次之
    ASSET_CLASS_CRYPTO_ORACLE: 0.75,   # 预言机
    ASSET_CLASS_CRYPTO_DEFI: 0.65,     # DeFi
    ASSET_CLASS_CRYPTO_OTHER: 0.4,     # 其他
    ASSET_CLASS_CRYPTO_MEME: 0.25,     # Meme 最低（高波动低价值）
}


@dataclass
class AssetEvaluation:
    """单资产评估结果"""
    inst_id: str              # OKX 合约 ID, 如 BTC-USDT-SWAP
    symbol: str               # 基础符号, 如 BTC
    asset_class: str           # 资产类别

    # 原始指标
    last_price: float = 0     # 最新价
    vol24h_usdt: float = 0    # 24h 成交额(USDT)
    high24h: float = 0        # 24h 最高
    low24h: float = 0         # 24h 最低
    volatility: float = 0     # 24h 波动率 (high-low)/low

    # 评分
    liquidity_score: float = 0   # 流动性评分 0-1
    volatility_score: float = 0  # 波动率评分 0-1（适中最高）
    trend_score: float = 0       # 趋势性评分 0-1（需K线计算）
    class_score: float = 0       # 资产类别评分 0-1

    total_score: float = 0    # 综合评分 0-1
    rank: int = 0             # 排名

    # 合约规格
    ct_val: float = 1        # 合约面值
    lot_sz: float = 1        # 最小下单量
    tick_sz: float = 0.01    # 价格精度
    max_lever: float = 10    # 最大杠杆

    # 标记
    is_tradfi: bool = False  # 是否TradFi
    recommended: bool = False # 是否推荐


class AssetValueEvaluator:
    """交易价值评估器

    从 OKX 获取所有 USDT 本位 SWAP 合约数据，
    按多维度评分筛选最有交易价值的资产。
    """

    # 评估参数
    MIN_VOL24H_USDT = 500_000       # 最低24h成交额：50万USDT
    MIN_VOL24H_USDT_TRADFI = 10_000 # TradFi 门槛更低
    OPTIMAL_VOL_LOW = 0.02          # 最优波动率下限 2%
    OPTIMAL_VOL_HIGH = 0.08          # 最优波动率上限 8%
    MAX_VOL = 0.15                   # 超过15%波动率视为过高
    TOP_N = 15                       # 推荐数量

    # 评分权重
    W_LIQUIDITY = 0.30
    W_VOLATILITY = 0.25
    W_TREND = 0.15
    W_CLASS = 0.20
    W_DIVERSITY = 0.10              # 多样性加分

    def __init__(self, okx_client=None):
        self.okx = okx_client
        self.base_url = "https://www.okx.com"
        self._cache: Dict[str, AssetEvaluation] = {}
        self._last_update = 0

    def _get_public(self, path: str, params: dict = None) -> dict:
        """OKX 公开接口（无需签名）"""
        url = self.base_url + path
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url += f"?{qs}"
        r = requests.get(url, timeout=15)
        return r.json()

    def evaluate_all(self) -> List[AssetEvaluation]:
        """评估所有 OKX USDT 本位 SWAP 合约

        Returns:
            按总分降序排列的评估结果列表
        """
        # 1. 获取所有 SWAP ticker
        r = self._get_public("/api/v5/market/tickers?instType=SWAP")
        if r.get("code") != "0":
            return []

        tickers = r.get("data", [])

        # 2. 获取合约规格
        inst_specs = self._get_instrument_specs()

        # 3. 逐个评估
        evaluations: List[AssetEvaluation] = []
        for t in tickers:
            inst_id = t.get("instId", "")
            if "USDT-SWAP" not in inst_id:
                continue

            symbol = inst_id.split("-")[0]
            if not symbol:
                continue

            last_price = float(t.get("last", 0) or 0)
            vol24h = float(t.get("volCcy24h", 0) or 0)
            high24h = float(t.get("high24h", 0) or 0)
            low24h = float(t.get("low24h", 0) or 0)

            if last_price <= 0 or low24h <= 0:
                continue

            # 波动率
            volatility = (high24h - low24h) / low24h if low24h > 0 else 0

            # 资产类别
            asset_class = KNOWN_ASSET_CLASS.get(symbol, ASSET_CLASS_CRYPTO_OTHER)
            is_tradfi = asset_class == ASSET_CLASS_TRADFI

            # 流动性门槛
            min_vol = self.MIN_VOL24H_USDT_TRADFI if is_tradfi else self.MIN_VOL24H_USDT
            if vol24h < min_vol:
                continue

            # 合约规格
            spec = inst_specs.get(inst_id, {})

            ev = AssetEvaluation(
                inst_id=inst_id,
                symbol=symbol,
                asset_class=asset_class,
                last_price=last_price,
                vol24h_usdt=vol24h,
                high24h=high24h,
                low24h=low24h,
                volatility=volatility,
                is_tradfi=is_tradfi,
                ct_val=spec.get("ct_val", 1),
                lot_sz=spec.get("lot_sz", 1),
                tick_sz=spec.get("tick_sz", 0.01),
                max_lever=spec.get("max_lever", 10),
            )

            # 评分
            ev.liquidity_score = self._score_liquidity(vol24h, is_tradfi)
            ev.volatility_score = self._score_volatility(volatility, is_tradfi)
            ev.class_score = CLASS_BASE_WEIGHT.get(asset_class, 0.4)
            ev.trend_score = 0.5  # 默认中性，需K线数据才能精确计算

            evaluations.append(ev)

        # 4. 多样性加分：每个类别最多保留 N 个
        class_counts: Dict[str, int] = {}
        for ev in evaluations:
            cls = ev.asset_class
            class_counts[cls] = class_counts.get(cls, 0) + 1
            # 同类别超过5个时降低评分
            if class_counts[cls] > 5:
                ev.class_score *= 0.7

        # 5. 综合评分
        for ev in evaluations:
            ev.total_score = (
                ev.liquidity_score * self.W_LIQUIDITY
                + ev.volatility_score * self.W_VOLATILITY
                + ev.trend_score * self.W_TREND
                + ev.class_score * self.W_CLASS
                + (1 if ev.is_tradfi else 0) * self.W_DIVERSITY
            )

        # 6. 排序
        evaluations.sort(key=lambda e: e.total_score, reverse=True)
        for i, ev in enumerate(evaluations):
            ev.rank = i + 1
            ev.recommended = i < self.TOP_N

        self._cache = {e.inst_id: e for e in evaluations}
        self._last_update = time.time()

        return evaluations

    def _get_instrument_specs(self) -> Dict[str, Dict]:
        """获取合约规格"""
        r = self._get_public("/api/v5/public/instruments?instType=SWAP")
        if r.get("code") != "0":
            return {}
        specs = {}
        for d in r.get("data", []):
            inst_id = d.get("instId", "")
            specs[inst_id] = {
                "ct_val": float(d.get("ctVal", 1) or 1),
                "lot_sz": float(d.get("lotSz", 1) or 1),
                "tick_sz": float(d.get("tickSz", 0.01) or 0.01),
                "max_lever": float(d.get("lever", 10) or 10),
            }
        return specs

    def _score_liquidity(self, vol24h_usdt: float, is_tradfi: bool) -> float:
        """流动性评分

        成交额越高流动性越好，但对数缩放避免大市值垄断。
        """
        if vol24h_usdt <= 0:
            return 0
        # 对数缩放: 10万→0.3, 100万→0.5, 1000万→0.7, 1亿→0.9
        score = 0.3 + 0.2 * math.log10(max(vol24h_usdt / 100_000, 1))
        return min(score, 1.0)

    def _score_volatility(self, vol: float, is_tradfi: bool) -> float:
        """波动率评分

        适中波动率得分最高:
        - TradFi: 0.5%-3% 最优（TradFi 波动率天然较低）
        - Crypto: 2%-8% 最优
        过低: 无利润空间
        过高: 噪音大止损易触发
        """
        if is_tradfi:
            low, high = 0.005, 0.03
        else:
            low, high = self.OPTIMAL_VOL_LOW, self.OPTIMAL_VOL_HIGH

        if vol < low:
            # 过低
            return max(vol / low * 0.5, 0.1)
        elif vol > high:
            # 过高
            if vol > self.MAX_VOL:
                return 0.1
            # 线性衰减
            return max(1.0 - (vol - high) / (self.MAX_VOL - high) * 0.7, 0.3)
        else:
            # 最优区间
            mid = (low + high) / 2
            if vol <= mid:
                return 0.7 + 0.3 * (vol - low) / (mid - low)
            else:
                return 0.7 + 0.3 * (high - vol) / (high - mid)

    def get_recommended_symbols(self, top_n: int = None) -> List[str]:
        """获取推荐交易标的列表

        Args:
            top_n: 返回前 N 个，默认 TOP_N

        Returns:
            标的符号列表，如 ['BTC', 'ETH', 'XAU', ...]
        """
        if not self._cache or time.time() - self._last_update > 3600:
            self.evaluate_all()

        n = top_n or self.TOP_N
        return [ev.symbol for ev in sorted(
            self._cache.values(), key=lambda e: e.total_score, reverse=True
        )[:n]]

    def get_recommended_inst_ids(self, top_n: int = None) -> List[str]:
        """获取推荐合约 ID 列表"""
        if not self._cache or time.time() - self._last_update > 3600:
            self.evaluate_all()

        n = top_n or self.TOP_N
        return [ev.inst_id for ev in sorted(
            self._cache.values(), key=lambda e: e.total_score, reverse=True
        )[:n]]

    def format_report(self, top_n: int = 20) -> str:
        """生成评估报告"""
        if not self._cache:
            self.evaluate_all()

        evs = sorted(self._cache.values(), key=lambda e: e.total_score, reverse=True)

        lines = []
        lines.append(f"=== 交易价值评估报告 ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===\n")
        lines.append(f"{'排名':<4} {'符号':<8} {'类别':<12} {'成交额(万U)':>12} {'波动率':>8} "
                     f"{'流动性':>6} {'波动分':>6} {'类别分':>6} {'总分':>6} {'推荐':>4}")
        lines.append("-" * 95)

        for ev in evs[:top_n]:
            vol_wan = ev.vol24h_usdt / 10000
            class_name = ev.asset_class.replace("crypto_", "").replace("_", "/")
            rec = "✓" if ev.recommended else ""
            lines.append(
                f"{ev.rank:<4} {ev.symbol:<8} {class_name:<12} {vol_wan:>12.0f} "
                f"{ev.volatility:>7.2%} {ev.liquidity_score:>6.2f} "
                f"{ev.volatility_score:>6.2f} {ev.class_score:>6.2f} "
                f"{ev.total_score:>6.2f} {rec:>4}"
            )

        return "\n".join(lines)


# ── CLI 入口 ──────────────────────────────────────────────

def main():
    """CLI: 评估所有资产并输出推荐列表"""
    import sys

    evaluator = AssetValueEvaluator()

    print("正在评估 OKX 所有 USDT 本位合约...")
    evaluations = evaluator.evaluate_all()

    print(f"\n共评估 {len(evaluations)} 个资产\n")
    print(evaluator.format_report(top_n=25))

    # 输出推荐标的
    recommended = evaluator.get_recommended_symbols()
    print(f"\n推荐交易标的 (Top {len(recommended)}):")
    print(",".join(recommended))

    # 保存到文件
    output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "okx_sim"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "update_time": datetime.now(timezone.utc).isoformat(),
        "total_evaluated": len(evaluations),
        "recommended_symbols": recommended,
        "evaluations": [
            {
                "rank": e.rank,
                "symbol": e.symbol,
                "inst_id": e.inst_id,
                "asset_class": e.asset_class,
                "vol24h_usdt": round(e.vol24h_usdt, 2),
                "volatility": round(e.volatility, 4),
                "total_score": round(e.total_score, 4),
                "recommended": e.recommended,
                "ct_val": e.ct_val,
                "lot_sz": e.lot_sz,
                "max_lever": e.max_lever,
            }
            for e in evaluations[:30]
        ],
    }

    output_file = output_dir / "asset_evaluation.json"
    output_file.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n评估结果已保存至: {output_file}")


if __name__ == "__main__":
    main()
