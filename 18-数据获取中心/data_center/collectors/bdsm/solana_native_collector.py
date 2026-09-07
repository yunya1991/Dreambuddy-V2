# -*- coding: utf-8 -*-
"""Solana (SOL) 原生数据采集器 — 通过 Solana 官方 RPC API 获取链上数据。

数据源：Solana 官方主网 RPC (https://api.mainnet-beta.solana.com)
这是 Solana 官方提供的公开 API 端点，非第三方数据聚合网站。

RPC 方法：
  1. getSupply → 总供应量、流通量、非流通量
  2. getVoteAccounts → 验证节点数、质押量、集中度
  3. getEpochInfo → epoch 信息
  4. getRecentPerformanceSamples → TPS 性能

采集字段（对齐 BDSM E5/E6/E7 信号需求）：
  - sol_total_supply: 总供应量（SOL）
  - sol_circulating_supply: 流通供应量
  - sol_non_circulating: 非流通量
  - sol_burned_pct: 非流通占比（代理销毁/锁定比例）
  - sol_validator_count: 活跃验证节点数
  - sol_delinquent_count: 不活跃验证节点数
  - sol_total_staked: 总质押量（SOL）
  - sol_top_validator_pct: 最大验证节点占比（集中度）
  - sol_staking_ratio: 质押率（staked / circulating）
  - sol_epoch: 当前 epoch
  - sol_tps: 最近 TPS
  - annualized_revenue_usd: 年化收入代理（交易费 * 365）

FAIL-OPEN: 网络异常/解析失败 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.bdsm.solana")

_RPC_URL = "https://api.mainnet-beta.solana.com"
_HTTP_TIMEOUT = 15
_HEADERS = {"Content-Type": "application/json"}

# Solana 交易费：基础费 5000 lamports/signature = 0.000005 SOL
# 优先费另计，平均每笔约 0.00001 SOL（含优先费）
# 年化交易数 ≈ 每秒 TPS * 86400 * 365
# 收入代理 = avg_fee_per_tx * tx_count * 365 天
_AVG_FEE_SOL = 0.00001  # 每笔平均费用（含优先费）SOL
# SOL 价格代理（从 CoinGecko 获取，回退 0）
_SOL_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"


class SolanaNativeCollector(BaseCollector):
    """Solana (SOL) 链上数据采集器 — 官方 RPC API。"""

    source = "bdsm_solana"
    category = "bdsm"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 Solana 链上数据，返回 DataRecord。"""
        supply_data = self._rpc_call("getSupply", [{"commitment": "finalized"}])
        vote_data = self._rpc_call(
            "getVoteAccounts", [{"commitment": "finalized", "keepUnstakedAccounts": False}]
        )
        epoch_data = self._rpc_call("getEpochInfo", [{"commitment": "finalized"}])
        perf_data = self._rpc_call("getRecentPerformanceSamples", [5])

        # 任何 RPC 失败 → FAIL-OPEN
        if not supply_data:
            return []

        sol_price = self._fetch_sol_price()

        return [self._build_record(
            supply_data, vote_data, epoch_data, perf_data, sol_price
        )]

    def _rpc_call(self, method: str, params: list) -> dict | None:
        """调用 Solana RPC 方法。"""
        try:
            resp = requests.post(
                _RPC_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                headers=_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result")
        except Exception as exc:
            logger.warning("Solana RPC %s failed: %s", method, exc)
            return None

    def _fetch_sol_price(self) -> float:
        """从 CoinGecko 获取 SOL 价格（FAIL-OPEN → 0.0）。"""
        try:
            resp = requests.get(_SOL_PRICE_URL, timeout=_HTTP_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("CoinGecko rate limit for SOL")
                return 0.0
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("solana", {}).get("usd", 0) or 0)
        except Exception as exc:
            logger.warning("SOL price fetch failed: %s", exc)
            return 0.0

    def _build_record(
        self, supply: dict, vote: dict | None, epoch: dict | None,
        perf: list | None, sol_price: float,
    ) -> DataRecord:
        """构建 DataRecord。"""
        now = datetime.now(timezone.utc).isoformat()

        # 供应量（lamports → SOL，1 SOL = 1e9 lamports）
        supply_val = supply.get("value", supply) if supply else {}
        total_supply = float(supply_val.get("total", 0)) / 1e9
        circulating = float(supply_val.get("circulating", 0)) / 1e9
        non_circulating = float(supply_val.get("nonCirculating", 0)) / 1e9

        burned_pct = (non_circulating / total_supply * 100) if total_supply > 0 else 0.0

        # 验证节点
        validator_count = 0
        delinquent_count = 0
        total_staked = 0.0
        top_validator_pct = 0.0
        if vote and isinstance(vote, dict):
            current = vote.get("current", [])
            delinquent = vote.get("delinquent", [])
            validator_count = len(current)
            delinquent_count = len(delinquent)
            stakes = [float(v.get("activatedStake", 0)) / 1e9 for v in current]
            total_staked = sum(stakes)
            if stakes and total_staked > 0:
                top_validator_pct = max(stakes) / total_staked * 100

        staking_ratio = (total_staked / circulating * 100) if circulating > 0 else 0.0

        # epoch
        epoch_num = 0
        slot = 0
        if epoch and isinstance(epoch, dict):
            epoch_num = int(epoch.get("epoch", 0))
            slot = int(epoch.get("slotIndex", 0))

        # TPS
        tps = 0.0
        if perf and isinstance(perf, list) and len(perf) > 0:
            sample = perf[0] if isinstance(perf[0], dict) else {}
            tps = float(sample.get("numTransactions", 0)) / float(
                sample.get("numSlots", 1) or 1
            )
            # 更准确：numTransactions / samplePeriod（秒）
            period = float(sample.get("samplePeriodSecs", 1) or 1)
            tps = float(sample.get("numTransactions", 0)) / period if period > 0 else 0.0

        # 年化收入代理：TPS * 平均费 * 86400 * 365
        daily_tx_count = tps * 86400
        annualized_revenue_sol = daily_tx_count * _AVG_FEE_SOL * 365
        annualized_revenue_usd = annualized_revenue_sol * sol_price

        # 市值（流通量 × 价格）
        market_cap_usd = circulating * sol_price if sol_price > 0 else 0.0

        metrics: dict[str, Any] = {
            # 供应量
            "sol_total_supply": round(total_supply, 2),
            "sol_circulating_supply": round(circulating, 2),
            "sol_non_circulating": round(non_circulating, 2),
            "sol_burned_pct": round(burned_pct, 4),
            "burned_pct": round(burned_pct, 4),  # E5 信号字段别名
            "sol_price_usd": sol_price,
            "market_cap_usd": round(market_cap_usd, 2),  # E6 信号所需
            # 验证节点
            "sol_validator_count": validator_count,
            "sol_delinquent_count": delinquent_count,
            "sol_total_staked": round(total_staked, 2),
            "sol_top_validator_pct": round(top_validator_pct, 2),
            "sol_staking_ratio_pct": round(staking_ratio, 2),
            # epoch
            "sol_epoch": epoch_num,
            "sol_slot": slot,
            # 性能
            "sol_tps": round(tps, 1),
            # 收入
            "annualized_revenue_sol": round(annualized_revenue_sol, 2),
            "annualized_revenue_usd": round(annualized_revenue_usd, 2),
            # E5 信号数据：非流通量作为锁定/销毁代理
            "supply_shrinkage_intensity": round(burned_pct / 100, 4),
        }

        return DataRecord(
            source=self.source,
            category=self.category,
            sub_category="sol_chain_data",
            timestamp=now,
            metrics=metrics,
            events=[],
            timeseries=[
                {
                    "epoch": epoch_num,
                    "tps": round(tps, 1),
                    "circulating": round(circulating, 2),
                    "total_staked": round(total_staked, 2),
                }
            ],
            raw={
                "rpc_url": _RPC_URL,
                "method": "getSupply+getVoteAccounts+getEpochInfo+getRecentPerformanceSamples",
            },
        )


if __name__ == "__main__":
    c = SolanaNativeCollector()
    recs = c.fetch({})
    if recs:
        r = recs[0]
        print("metrics:")
        for k, v in r.metrics.items():
            print(f"  {k}: {v}")
    else:
        print("FAIL-OPEN: empty")
