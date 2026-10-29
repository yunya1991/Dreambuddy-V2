#!/usr/bin/env python3
"""P5 统计学习阶段框架骨架（40-周期神经网络系统）。

设计原则（SPEC 主规格 + 风险 3/7）：
  - 最小复杂度原则：优先简单统计基线（逻辑回归/分位数统计），
    复杂模型必须证明相对简单基线的增量收益
  - 门槛拦截：训练入口先过 p5_gate（预注册门槛，未达标拒绝启动）
  - Walk-Forward 滚动验证：禁止随机打乱时序
  - 验证窗口封板：最近 20% 时间段纯验证，参数不得依据该段表现调整
  - 参数预注册：本文件所有超参数为预注册值，禁止运行时调整

当前状态：框架骨架。训练主链路在门槛达标（p5_gate.all_passed）后解锁。
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p5_gate import check_gate, save_report

BASE = "/home/luke/dreambuddy/40-周期神经网络系统"

# ── 预注册超参数（禁止运行时调整）────────────────────────────────
PREREG = {
    "train_ratio": 0.6,        # 前 60% 训练
    "validate_ratio": 0.2,     # 中 20% 滚动验证
    "test_ratio": 0.2,         # 最近 20% 封板纯验证
    "walk_forward_step": 4,    # 滚动窗口步长（周）
    "baseline_model": "logistic_regression",  # 简单统计基线
    "label_horizon_weeks": 4,  # 标签前瞻窗口（4 周后方向）
    "label_threshold_pct": 2.0,  # 涨跌幅超 ±2% 才标注方向，否则 NEUTRAL
}

FEATURE_SOURCES = [
    "cycle_state.json",         # 周期状态（真实周期+技术锚+传导摘要）
    "asset_rotation.json",      # 资产轮动
    "strategy_mapping.json",    # 策略映射（含 effective_confidence）
    "fund_flow.json",           # 资金流（七维度：层内/跨资产/相关性/RS 比率/价差/聪明钱）
    "stovall_breadth.json",     # 市场广度
    "sector_transmission.json", # 板块传导（L1-L4 分层资产+动量+相对强度）
    "washout_verdicts.json",    # 洗盘判定（按资产 label/confidence/trigger）
    "meme_platform.json",       # L4 meme 层平台观测
]


def load_features() -> dict:
    """从 40 系统产出物提取特征快照（只读）。"""
    features = {}
    for name in FEATURE_SOURCES:
        path = os.path.join(BASE, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                features[name] = json.load(f)
        except Exception as e:
            features[name] = {"_error": str(e)}
    return features


def extract_feature_vector(features: dict) -> dict:
    """从产出物快照提取扁平特征向量（骨架：当前可提取的字段）。

    完整时序特征工程（历史逐期回放）待门槛达标后随训练主链路实现。
    """
    cs = features.get("cycle_state.json", {})
    sm = features.get("strategy_mapping.json", {})
    ff = features.get("fund_flow.json", {})
    st = features.get("sector_transmission.json", {})
    wv = features.get("washout_verdicts.json", {})
    vec = {
        # 周期状态特征
        "cycle_state": cs.get("real_cycle", {}).get("state"),
        "cycle_rate": cs.get("real_cycle", {}).get("current_rate"),
        # 技术锚特征（BTC）
        "btc_above_ma200": cs.get("technical_anchor", {}).get("assets", {}).get("BTC/USDT", {}).get("above"),
        "btc_ma200_dist_pct": cs.get("technical_anchor", {}).get("assets", {}).get("BTC/USDT", {}).get("distance_pct"),
        # 传导特征
        "transmission_state": cs.get("sector_transmission", {}).get("state"),
        # 策略映射特征（消费 effective_confidence 而非原始置信度）
        "quadrant": sm.get("inputs", {}).get("quadrant"),
        "effective_confidence": sm.get("risk_guards", {}).get("effective_confidence"),
        # 资金流特征（聪明钱：CFTC 净头寸 + 稳定币供应变化）
        "cftc_noncomm_net": ff.get("smart_money", {}).get("cftc_btc", {}).get("noncomm_net"),
        "usdt_change_7d_pct": ff.get("smart_money", {}).get("stablecoin_supply", {}).get("usdt", {}).get("change_7d_pct"),
        # 板块传导特征（L1-L4 层动量中位数）
        "l1_anchor_momentum": st.get("layers", {}).get("L1_anchor"),
        # 洗盘判定特征（BTC 触发状态与标签）
        "btc_washout_label": wv.get("verdicts", {}).get("BTC/USDT", {}).get("label"),
        "btc_washout_trigger": wv.get("verdicts", {}).get("BTC/USDT", {}).get("trigger_activated"),
    }
    return vec


def train() -> dict:
    """训练入口：先过门槛守卫，未达标拒绝启动。"""
    report = check_gate()
    save_report(report)
    if not report["all_passed"]:
        return {
            "status": "REJECTED",
            "reason": "P5 预注册门槛未达标，训练入口拒绝启动",
            "gate_report": report,
        }

    # ── 门槛达标后的训练主链路（骨架，待解锁后实现）──
    # 1. 历史逐期特征回放（时序样本构建，Walk-Forward 切分）
    # 2. 标签构建（前瞻 4 周，±2% 阈值三分类）
    # 3. 简单统计基线训练（逻辑回归）
    # 4. 封板验证段评估（最近 20%）
    # 5. 产出 p5_model_status.json（含相对基线增量收益证据）
    return {
        "status": "NOT_IMPLEMENTED",
        "reason": "门槛已达标，训练主链路待实现（框架骨架阶段）",
        "gate_report": report,
    }


def main() -> int:
    result = train()
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "P5 统计学习框架",
        "prereg_params": PREREG,
        "feature_vector_sample": extract_feature_vector(load_features()),
        "train_result": result,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("OK", "NOT_IMPLEMENTED") else 1


if __name__ == "__main__":
    sys.exit(main())
