"""生成 P1 场景矩阵 YAML（45 个：3 意图 × 15 样本）

用法: cd 30-真实环境交互系统 && python scripts/gen_p1_scenarios.py
输出: scenarios/intent_training/*.yaml
"""
import yaml
from pathlib import Path

# 3 意图 × 1 场景 × (10 train + 5 eval) = 45 场景
MATRIX = [
    {
        "gold_intent": "trend_following",
        "scenario_id": "TREND_UP",
        "market_features": {"regime": "trending", "volatility": "medium", "data_freshness": "realtime"},
        "queries_train": [
            "BTC 现在是上升趋势吗，要不要顺势加仓",
            "以太坊涨得不错，趋势还能延续吗",
            "现在适合追多 BTC 吗，趋势向上",
            "看看 BTC 趋势，向上还是向下",
            "ETH 趋势跟随，现在入场合适吗",
            "BTC 涨势明确，加仓还是等回调",
            "趋势交易，BTC 现在什么方向",
            "顺势操作 BTC，向上趋势确认吗",
            "BTC 趋势强度如何，能跟进吗",
            "以太坊上升趋势，要不要追",
        ],
        "queries_eval": [
            "BTC 趋势怎么看，向上吗",
            "ETH 现在趋势方向",
            "顺势 BTC，趋势确认了吗",
            "BTC 涨势还能持续吗",
            "趋势跟随策略，BTC 现在能做吗",
        ],
    },
    {
        "gold_intent": "mean_reversion",
        "scenario_id": "RANGE",
        "market_features": {"regime": "ranging", "volatility": "low", "data_freshness": "realtime"},
        "queries_train": [
            "BTC 在区间震荡，高抛低吸怎么做",
            "以太坊来回震荡，适合做均值回归吗",
            "BTC 区间上下沿在哪，能反向操作吗",
            "现在 BTC 震荡，适合低买高卖吗",
            "ETH 横盘，均值回归策略可行吗",
            "BTC 偏离均线多少，会回归吗",
            "震荡行情 BTC，高抛低吸点位",
            "均值回归，BTC 现在偏离多少",
            "BTC 区间震荡，反向做单可以吗",
            "ETH 震荡区间，适合做反转吗",
        ],
        "queries_eval": [
            "BTC 震荡，高抛低吸怎么做",
            "ETH 均值回归，现在偏离吗",
            "BTC 区间上下沿",
            "震荡行情 BTC 怎么操作",
            "ETH 横盘，能反向做吗",
        ],
    },
    {
        "gold_intent": "breakout",
        "scenario_id": "BREAKOUT_UP",
        "market_features": {"regime": "breakout", "volatility": "high", "data_freshness": "realtime"},
        "queries_train": [
            "BTC 突破前高了，能追突破吗",
            "以太坊向上突破，突破策略怎么做",
            "BTC 突破阻力位，跟进吗",
            "ETH 放量突破，突破交易可行吗",
            "BTC 突破信号，现在能入场吗",
            "向上突破 BTC，目标位在哪",
            "BTC 突破确认，突破策略生效吗",
            "ETH 跌破支撑，向下突破吗",
            "BTC 突破后回踩，能追吗",
            "突破行情 BTC，怎么操作",
        ],
        "queries_eval": [
            "BTC 突破了吗，能追吗",
            "ETH 突破策略",
            "BTC 突破阻力位",
            "突破行情 BTC 怎么做",
            "ETH 向上突破，跟进吗",
        ],
    },
]


def gen_scenario(intent: str, scenario_id: str, split: str, idx: int,
                 query: str, market_features: dict) -> dict:
    """生成单个场景 YAML 字典"""
    return {
        "name": f"P1-{intent.upper()}-{scenario_id}-{split}-{idx:03d}",
        "description": f"{intent} 意图 × {scenario_id} 场景 ({split})",
        "timeout": 60,
        "retry": 0,
        "intent_training": {
            "gold_intent": intent,
            "scenario_id": scenario_id,
            "split": split,
            "market_features": market_features,
        },
        "steps": [
            {"name": "打开聊天页面", "action": "navigate", "url": "http://localhost:3001/chat"},
            {"name": "输入问法", "action": "type",
             "selector": "textarea, input[type='text'], [contenteditable]",
             "text": query, "human": True},
            {"name": "提交查询", "action": "click",
             "selector": "button[type='submit'], button:has-text('发送')", "human": True},
            {"name": "等待响应", "action": "wait", "seconds": 3},
        ],
    }


def main():
    out_dir = Path("scenarios/intent_training")
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for entry in MATRIX:
        for idx, q in enumerate(entry["queries_train"], 1):
            sc = gen_scenario(entry["gold_intent"], entry["scenario_id"], "train", idx, q, entry["market_features"])
            fname = f"{entry['gold_intent']}_{entry['scenario_id']}_train_{idx:03d}.yaml"
            with open(out_dir / fname, "w", encoding="utf-8") as f:
                yaml.dump(sc, f, allow_unicode=True, sort_keys=False)
            count += 1
        for idx, q in enumerate(entry["queries_eval"], 1):
            sc = gen_scenario(entry["gold_intent"], entry["scenario_id"], "eval", idx, q, entry["market_features"])
            fname = f"{entry['gold_intent']}_{entry['scenario_id']}_eval_{idx:03d}.yaml"
            with open(out_dir / fname, "w", encoding="utf-8") as f:
                yaml.dump(sc, f, allow_unicode=True, sort_keys=False)
            count += 1
    print(f"生成 {count} 个场景文件 → {out_dir}")


if __name__ == "__main__":
    main()
