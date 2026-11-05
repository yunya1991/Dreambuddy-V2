"""数据域 agent 奖励分量 — SPEC-L0-DATA-AGENT v0.1 §5 (P3)
为数据域六子 agent (macro/chain/flow/breadth/capital_flow/sentiment) 提供专属奖励分量：
  1. collect_success_rate 采集成功率（库内新鲜度代理；真实调度日志接入后替换）
  2. data_freshness 数据新鲜度（now − max(ts) 按子协议频率阈值分级）
  3. coverage 覆盖率（子协议登记指标非空占比）
  4. psi_stability PSI 漂移稳定性（复用 TB1，缺省中性）
指标注册表唯一事实源 = 47-MCP管理系统/docs/tech/data-agents/ 六个子协议文件（DA-*-v0.1 §2）。
FAIL-OPEN：DB 缺失/查询异常 → 各分量中性值，不抛异常。
硬约束：权重为常量，禁止运行期动态调整（对齐 TB1 H8 / training_reward.py）。
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# 数据域四维权重（和=1.0）；影子期按 SPEC §6.5 校准协议回测后改常量
DATA_AGENT_WEIGHTS: Tuple[float, float, float, float] = (0.35, 0.30, 0.25, 0.10)

# 中性值（FAIL-OPEN）
NEUTRAL: float = 0.5

# 指标注册表：(sub_category, metric_name, 新鲜度阈值秒)
# 阈值与 DA-* 子协议 §1 采集频率一致
DATA_AGENT_REGISTRY: Dict[str, List[Tuple[str, str, int]]] = {
    "macro": [
        ("DX-Y.NYB", "value", 900),
        ("^TNX", "value", 900),
        ("^VIX", "value", 900),
        ("GC=F", "value", 900),
        ("SP500", "value", 3600),
        ("WALCL", "value", 3600),
        ("FEDFUNDS", "value", 3600),
        ("CPIAUCSL", "value", 3600),
        ("PPIACO", "value", 3600),
        ("DCOILWTICO", "value", 3600),
        ("NASDAQCOM", "value", 3600),
    ],
    "chain": [
        ("btc_onchain", "difficulty_change_pct", 300),
        ("btc_onchain", "difficulty_progress_pct", 300),
        ("btc_onchain", "mempool_count", 300),
        ("btc_onchain", "mempool_fee_btc", 300),
        ("btc_onchain", "mempool_size_kb", 300),
        ("btc_onchain", "remaining_blocks", 300),
        ("btc_onchain", "tip_height", 300),
        ("exchanges_whales", "us_SP500_value", 14400),
        ("exchanges_whales", "us_VIXCLS_value", 14400),
        ("exchanges_whales", "us_DTWEXBGS_value", 14400),
    ],
    "flow": [
        ("etf_flow", "total_flow", 86400),
        ("stablecoins_top_10", "usdt_pct_of_total", 14400),
        ("tether_current", "usdt_circulating_usd_bln", 3600),
        ("usdc_current", "usdc_circulating_usd_bln", 3600),
    ],
    "breadth": [
        ("stablecoins_top_10", "USDT_bln", 14400),
        ("stablecoins_top_10", "USDC_bln", 14400),
        ("social_volume", "social_volume", 1800),
        ("social_volume", "news_count_24h", 1800),
    ],
    "capital_flow": [
        ("long_short_ratio", "long_short_ratio", 1800),
        ("long_short_ratio", "long_account_pct", 1800),
        ("funding_rate", "funding_rate_pct", 1800),
        ("funding_rate", "funding_rate_annualized_pct", 1800),
        ("open_interest", "open_interest_value", 1800),
        ("open_interest", "open_interest_amount", 1800),
    ],
    "sentiment": [
        ("crypto_fear_greed", "value", 1800),
        ("fear_greed_enhanced", "momentum", 1800),
        ("fear_greed_enhanced", "volatility", 1800),
        ("fear_greed_enhanced", "capital_flow", 1800),
        ("fear_greed_enhanced", "funding", 1800),
    ],
}


@dataclass
class DataAgentReward:
    """数据域 agent 四维奖励分量。"""

    agent: str
    collect_success_rate: float  # 维度 1：阈值内更新指标占比（调度日志代理）
    data_freshness: float  # 维度 2：新鲜度归一分（0=过期 1=最新）
    coverage: float  # 维度 3：登记指标有数据占比
    psi_stability: float  # 维度 4：1 − PSI（缺省中性）
    pareto: float  # 加权总分


def _resolve_db() -> str:
    env_path = os.environ.get("DREAMBUDDY_CORE_DB")
    if env_path and os.path.isfile(env_path):
        return env_path
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "19-数据访问层",
        "data",
        "dreambuddy_core.db",
    )


def _freshness_score(age_sec: float, threshold_sec: int) -> float:
    """年龄 → [0,1]：阈值内线性衰减，超阈值 0。"""
    if age_sec <= 0:
        return 1.0
    if age_sec >= threshold_sec:
        return 0.0
    return 1.0 - age_sec / threshold_sec


def compute_data_agent_rewards(
    db_path: Optional[str] = None,
    psi_values: Optional[Dict[str, float]] = None,
    now: Optional[float] = None,
) -> Dict[str, DataAgentReward]:
    """计算六子 agent 四维奖励分量。
    FAIL-OPEN：DB 缺失或查询异常 → 该 agent 全部分量中性 0.5。
    psi_values: {agent: PSI}，缺省 psi_stability=0.5（中性）。
    """
    if db_path is None:
        db_path = _resolve_db()
    if now is None:
        now = time.time()
    psi_values = psi_values or {}
    results: Dict[str, DataAgentReward] = {}
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
    except sqlite3.Error:
        conn = None
    for agent, metrics in DATA_AGENT_REGISTRY.items():
        if conn is None:
            results[agent] = DataAgentReward(agent, NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL)
            continue
        total = len(metrics)
        have_data = 0
        fresh_sum = 0.0
        in_threshold = 0
        try:
            for sub_cat, name, threshold in metrics:
                row = conn.execute(
                    "SELECT metric_value, timestamp FROM mm_metrics "
                    "WHERE sub_category=? AND metric_name=? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (sub_cat, name),
                ).fetchone()
                if row is None or row[0] is None:
                    continue
                have_data += 1
                age = now - float(row[1])
                fresh_sum += _freshness_score(age, threshold)
                if age <= threshold:
                    in_threshold += 1
        except sqlite3.Error:
            results[agent] = DataAgentReward(agent, NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL, NEUTRAL)
            continue
        coverage = have_data / max(total, 1)
        freshness = fresh_sum / max(total, 1)
        success = in_threshold / max(total, 1)
        psi = psi_values.get(agent)
        psi_stab = max(0.0, 1.0 - min(psi, 1.0)) if isinstance(psi, (int, float)) else NEUTRAL
        pareto = (
            DATA_AGENT_WEIGHTS[0] * success
            + DATA_AGENT_WEIGHTS[1] * freshness
            + DATA_AGENT_WEIGHTS[2] * coverage
            + DATA_AGENT_WEIGHTS[3] * psi_stab
        )
        results[agent] = DataAgentReward(agent, success, freshness, coverage, psi_stab, pareto)
    if conn is not None:
        conn.close()
    return results


def map_to_alpha_pareto(reward: DataAgentReward) -> Dict[str, float]:
    """数据域四维 → TB3 七维奖励分量映射（供 TB5 PolicySelectLoop 消费）。
    p_verify_success ← collect_success_rate（采集成功率即数据域 verify）
    psi_stability ← psi_stability（直接复用 TB1 语义）
    其余维度由调用方按原口径提供。
    """
    return {
        "p_verify_success": reward.collect_success_rate,
        "psi_stability": reward.psi_stability,
        "data_freshness": reward.data_freshness,
        "data_coverage": reward.coverage,
    }
