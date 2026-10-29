# -*- coding: utf-8 -*-
"""40 系统产出物承接适配器（P2 五维承接阶段 + 扩展）。

数据流：40-周期神经网络系统产出物 → 本适配器（只读）→
        five_domain_feature_computer 五维输入源。

承接产出物清单：
- cycle_state.json：real_cycle（天维 merrill_phase）、technical_anchor（地维
  ma200_distance_percentile）、sector_transmission（地维 regime）、
  data_coverage（将维 factor_coverage_pct）
- fund_flow.json：smart_money 稳定币供应（道维 stablecoin_mcap_bln /
  stablecoin_change_rate）、CFTC 投机净多（道维 policy_sentiment_score）、
  跨资产动量（天维 liquidity_score）
- washout_verdicts.json：BTC 洗盘判定（地维 regime：weakness→trend_down、
  washout→ranging；unknown 不注入）
- 编码器产出物（P6 X1 门槛未满足，预留接口，当前恒返回空，不伪造模型输出）

设计原则（与 23 系统 macro_constraint_adapter 对齐）：
- 只读：绝不写 40 系统任何文件
- fail-open：文件不存在/损坏/过期 → 对应字段不注入，各维度回退原有 fallback 值
- 优先级：调用方显式字段 > 40 产出物承接字段 > 原有 fallback 值
"""

import json
import os
from typing import Any, Dict, Optional

# 40 系统产出物路径（与 23 系统 macro_constraint_adapter 保持一致）
_CYCLE_STATE_PATH = "/home/luke/dreambuddy/40-周期神经网络系统/cycle_state.json"
_FUND_FLOW_PATH = "/home/luke/dreambuddy/40-周期神经网络系统/fund_flow.json"
_WASHOUT_PATH = "/home/luke/dreambuddy/40-周期神经网络系统/washout_verdicts.json"

# 产出物最大容忍时效（秒）：超过则视为过期 fail-open
_MAX_AGE_SECONDS = 7 * 24 * 3600

# FEDFUNDS 周期状态 → 美林时钟相位映射
_REAL_CYCLE_TO_MERRILL = {
    "hiking": "STAGFLATION",
    "cutting": "RECOVERY",
    "plateau": "OVERHEAT",
}

# 40 板块传导 regime → 地维后置层 5 态映射
_SECTOR_REGIME_MAP = {
    "bull_trend": "trend_up",
    "bear_trend": "trend_down",
    "bull_consolidation": "ranging",
    "bear_consolidation": "ranging",
    "high_volatility": "high_volatility",
    "breakout": "breakout",
}

# 洗盘判定 → 地维后置层 5 态映射（unknown 不注入，保持原 fallback）
_WASHOUT_REGIME_MAP = {
    "washout": "ranging",      # 洗盘持有：震荡整固，中性
    "weakness": "trend_down",  # 真弱势：下降趋势
}


def _load_json(path: str) -> Dict[str, Any]:
    """只读加载 JSON 产出物（fail-open 空 dict）。"""
    try:
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001  fail-open
        return {}


def load_cycle_state(path: str = _CYCLE_STATE_PATH) -> Dict[str, Any]:
    """只读加载 40 系统 cycle_state.json（fail-open 空 dict）。"""
    return _load_json(path)


def load_fund_flow(path: str = _FUND_FLOW_PATH) -> Dict[str, Any]:
    """只读加载 40 系统资金流动模块产出物 fund_flow.json（fail-open 空 dict）。"""
    return _load_json(path)


def load_washout_verdicts(path: str = _WASHOUT_PATH) -> Dict[str, Any]:
    """只读加载 40 系统洗盘模块产出物 washout_verdicts.json（fail-open 空 dict）。"""
    return _load_json(path)


def load_encoder_outputs() -> Dict[str, Any]:
    """预留：40 系统 P6 编码器产出物接口。

    当前 X1 门槛未满足（x1_ready=false，REJECT_TRAINING），编码器无可消费产出，
    恒返回空 dict（不伪造模型输出）。X1 就绪后在此接入真实产出物路径。
    """
    return {}


def _is_fresh(payload: Dict[str, Any]) -> bool:
    """检查 generated_at 时效，超过 _MAX_AGE_SECONDS 视为过期。"""
    try:
        from datetime import datetime, timezone
        gen = payload.get("generated_at")
        if not gen:
            return False
        gen_dt = datetime.fromisoformat(gen)
        if gen_dt.tzinfo is None:
            gen_dt = gen_dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - gen_dt).total_seconds()
        return 0 <= age <= _MAX_AGE_SECONDS
    except Exception:  # noqa: BLE001
        return False


def build_bridge_inputs(
    cs: Optional[Dict[str, Any]] = None,
    asset_class: str = "crypto_usdt",
) -> Dict[str, Any]:
    """将 40 产出物映射为五维特征计算的输入字段。

    Returns:
        dict，可能包含：
        - merrill_phase: str（天维，美林时钟相位）
        - liquidity_score: float（天维，流动性周期 [0,1]）
        - ma200_distance_percentile: float（地维，MA200 距离分位 [0,1]）
        - regime: str（地维，后置层 5 态）
        - stablecoin_mcap_bln: float（道维，稳定币市值十亿美元）
        - stablecoin_change_rate: float（道维，稳定币供应 30d 变化率）
        - policy_sentiment_score: float（道维，CFTC 投机情绪 [0,1]）
        - factor_coverage_pct: float（将维，因子覆盖度 [0,1]）
        任何字段缺失/异常均不写入，由调用方回退 fallback。
    """
    if cs is None:
        cs = load_cycle_state()
    out: Dict[str, Any] = {}

    # ══════════ cycle_state.json（周期锚定 + 技术锚 + 板块传导）══════════
    if cs and _is_fresh(cs):
        # ── 天维：FEDFUNDS 周期状态 → 美林时钟相位 ──
        real_cycle = cs.get("real_cycle") or {}
        state = real_cycle.get("state")
        if state in _REAL_CYCLE_TO_MERRILL:
            out["merrill_phase"] = _REAL_CYCLE_TO_MERRILL[state]

        # ── 地维：MA200 技术锚（仅 crypto_usdt 类承接 BTC/USDT 锚）──
        if asset_class == "crypto_usdt":
            tech = cs.get("technical_anchor") or {}
            btc = (tech.get("assets") or {}).get("BTC/USDT") or {}
            above = btc.get("above")
            dist_pct = btc.get("distance_pct")
            if isinstance(above, bool) and isinstance(dist_pct, (int, float)):
                pct = float(dist_pct) / 100.0
                if above:
                    out["ma200_distance_percentile"] = min(1.0, 0.5 + pct)
                else:
                    out["ma200_distance_percentile"] = max(0.0, 0.5 - pct)

        # ── 地维：板块传导 regime → 后置层 5 态 ──
        sector = cs.get("sector_transmission") or {}
        sregime = sector.get("regime")
        if sregime in _SECTOR_REGIME_MAP:
            out["regime"] = _SECTOR_REGIME_MAP[sregime]

        # ── 将维：数据覆盖度 + 周期置信度 → 因子覆盖度 ──
        coverage = cs.get("data_coverage") or {}
        records = coverage.get("records")
        confidence = real_cycle.get("confidence")
        if isinstance(records, (int, float)) and records > 0:
            rec_score = min(1.0, float(records) / 800.0)
            conf_score = 1.0 if confidence == "high" else (0.7 if confidence == "medium" else 0.4)
            out["factor_coverage_pct"] = round(rec_score * conf_score, 4)

    # ══════════ fund_flow.json（资金流动 + 聪明钱，仅 crypto_usdt 类）══════════
    if asset_class == "crypto_usdt":
        ff = load_fund_flow()
        if ff and _is_fresh(ff):
            # ── 道维：稳定币供应 → 机构资金净流入代理 ──
            smart = ff.get("smart_money") or {}
            usdt = ((smart.get("stablecoin_supply") or {}).get("usdt")) or {}
            circulating = usdt.get("circulating_usd")
            if isinstance(circulating, (int, float)) and circulating > 0:
                out["stablecoin_mcap_bln"] = round(float(circulating) / 1e9, 2)
            change_30d = usdt.get("change_30d_pct")
            if isinstance(change_30d, (int, float)):
                out["stablecoin_change_rate"] = round(float(change_30d) / 100.0, 6)

            # ── 道维：CFTC 投机净多 → 政策景气度/情绪代理 ──
            cftc = smart.get("cftc_btc") or {}
            noncomm_net = cftc.get("noncomm_net")
            open_interest = cftc.get("open_interest")
            if (isinstance(noncomm_net, (int, float))
                    and isinstance(open_interest, (int, float)) and open_interest > 0):
                # 净多占比 → [0,1] 情绪分：0 占比=0.5 中性，±25% 占比打满
                ratio = float(noncomm_net) / float(open_interest)
                out["policy_sentiment_score"] = round(max(0.0, min(1.0, 0.5 + ratio * 2.0)), 4)

            # ── 天维：跨资产动量（加密流入领先 → 流动性充裕）──
            cross = ff.get("cross_asset_flow") or {}
            cat_momentum = cross.get("category_momentum_pct") or {}
            crypto_momentum = cat_momentum.get("加密")
            if isinstance(crypto_momentum, (int, float)):
                # ±25% 动量 → liquidity_score [0.25, 0.75]，0% → 0.5 中性
                out["liquidity_score"] = round(
                    max(0.0, min(1.0, 0.5 + float(crypto_momentum) / 100.0)), 4
                )

    # ══════════ washout_verdicts.json（洗盘判定，仅 crypto_usdt 类）══════════
    if asset_class == "crypto_usdt":
        wv = load_washout_verdicts()
        if wv and _is_fresh(wv):
            btc_verdict = (wv.get("verdicts") or {}).get("BTC/USDT") or {}
            label = btc_verdict.get("label")
            # unknown（含未触发触发门）不注入，保持原 fallback
            # 洗盘判定是 BTC 直接判定，比板块传导 regime 更具体：
            # weakness（真弱势）覆盖板块传导的震荡判定；washout（洗盘持有）与震荡等价
            if label in _WASHOUT_REGIME_MAP:
                out["regime"] = _WASHOUT_REGIME_MAP[label]

    # ══════════ 编码器产出物（预留接口，X1 就绪前恒空）══════════
    encoder = load_encoder_outputs()
    if encoder:
        out.update(encoder)

    return out


def bridge_coin_data(
    coin_data: Optional[Dict[str, Any]],
    asset_class: str = "crypto_usdt",
) -> Optional[Dict[str, Any]]:
    """将承接字段合并进 coin_data（承接字段不覆盖调用方显式提供的字段）。"""
    bridge = build_bridge_inputs(asset_class=asset_class)
    if not bridge:
        return coin_data
    if not coin_data:
        return bridge
    merged = dict(coin_data)
    for k, v in bridge.items():
        if k not in merged or merged.get(k) is None:
            merged[k] = v
    return merged


def bridge_system_state(
    system_state: Optional[Dict[str, Any]],
    asset_class: str = "crypto_usdt",
) -> Optional[Dict[str, Any]]:
    """将承接字段合并进 system_state（将维智因子输入，同样不覆盖显式字段）。"""
    bridge = build_bridge_inputs(asset_class=asset_class)
    if not bridge:
        return system_state
    if not system_state:
        system_state = {}
    merged = dict(system_state)
    if "factor_coverage_pct" in bridge:
        existing = merged.get("factor_coverage_pct")
        if existing is None:
            merged["factor_coverage_pct"] = bridge["factor_coverage_pct"]
    return merged


if __name__ == "__main__":
    print(json.dumps(build_bridge_inputs(), ensure_ascii=False, indent=2))
