"""生成 P1 场景矩阵 YAML（120 个：3 意图 × 40 样本）

扩容版：每意图 30 train + 10 eval = 40 样本，3 意图 = 120 场景。
每桶 train ≥ BUCKET_THRESHOLD(30)，可触发 IntentTrainer 贝叶斯训练。

生成策略：句式模板 × 币种组合，保持意图关键词不变以确保意图可识别。
- train: 6 模板 × 5 币种 = 30
- eval:  2 模板 × 5 币种 = 10

用法: cd 30-真实环境交互系统 && python scripts/gen_p1_scenarios.py
输出: scenarios/intent_training/*.yaml
"""
import yaml
from pathlib import Path

# 5 个币种，用于模板组合
COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]

# 3 意图 × 1 场景 × (30 train + 10 eval) = 120 场景
# 每个意图的模板必须含意图关键词（趋势/顺势/涨势 | 震荡/高抛低吸/均值回归 | 突破）
MATRIX = [
    {
        "gold_intent": "trend_following",
        "scenario_id": "TREND_UP",
        "market_features": {"regime": "trending", "volatility": "medium", "data_freshness": "realtime"},
        "train_templates": [
            "{coin} 现在是上升趋势吗，要不要顺势加仓",
            "{coin} 涨得不错，趋势还能延续吗",
            "现在适合追多 {coin} 吗，趋势向上",
            "{coin} 趋势跟随，现在入场合适吗",
            "{coin} 涨势明确，加仓还是等回调",
            "顺势操作 {coin}，向上趋势确认吗",
        ],
        "eval_templates": [
            "{coin} 趋势怎么看，向上吗",
            "顺势 {coin}，趋势确认了吗",
        ],
    },
    {
        "gold_intent": "mean_reversion",
        "scenario_id": "RANGE",
        "market_features": {"regime": "ranging", "volatility": "low", "data_freshness": "realtime"},
        "train_templates": [
            "{coin} 在区间震荡，高抛低吸怎么做",
            "{coin} 来回震荡，适合做均值回归吗",
            "{coin} 区间上下沿在哪，能反向操作吗",
            "{coin} 横盘，均值回归策略可行吗",
            "{coin} 偏离均线多少，会回归吗",
            "震荡行情 {coin}，高抛低吸点位",
        ],
        "eval_templates": [
            "{coin} 震荡，高抛低吸怎么做",
            "{coin} 均值回归，现在偏离吗",
        ],
    },
    {
        "gold_intent": "breakout",
        "scenario_id": "BREAKOUT_UP",
        "market_features": {"regime": "breakout", "volatility": "high", "data_freshness": "realtime"},
        "train_templates": [
            "{coin} 突破前高了，能追突破吗",
            "{coin} 向上突破，突破策略怎么做",
            "{coin} 突破阻力位，跟进吗",
            "{coin} 放量突破，突破交易可行吗",
            "{coin} 突破信号，现在能入场吗",
            "突破行情 {coin}，怎么操作",
        ],
        "eval_templates": [
            "{coin} 突破了吗，能追吗",
            "{coin} 突破策略怎么做",
        ],
    },
]


def expand_queries(templates, coins):
    """句式模板 × 币种组合生成问法列表"""
    queries = []
    for t in templates:
        for c in coins:
            queries.append(t.format(coin=c))
    return queries


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
        train_queries = expand_queries(entry["train_templates"], COINS)
        eval_queries = expand_queries(entry["eval_templates"], COINS)
        for idx, q in enumerate(train_queries, 1):
            sc = gen_scenario(entry["gold_intent"], entry["scenario_id"], "train", idx, q, entry["market_features"])
            fname = f"{entry['gold_intent']}_{entry['scenario_id']}_train_{idx:03d}.yaml"
            with open(out_dir / fname, "w", encoding="utf-8") as f:
                yaml.dump(sc, f, allow_unicode=True, sort_keys=False)
            count += 1
        for idx, q in enumerate(eval_queries, 1):
            sc = gen_scenario(entry["gold_intent"], entry["scenario_id"], "eval", idx, q, entry["market_features"])
            fname = f"{entry['gold_intent']}_{entry['scenario_id']}_eval_{idx:03d}.yaml"
            with open(out_dir / fname, "w", encoding="utf-8") as f:
                yaml.dump(sc, f, allow_unicode=True, sort_keys=False)
            count += 1
    print(f"生成 {count} 个场景文件 → {out_dir}")
    for entry in MATRIX:
        print(f"  {entry['gold_intent']}: train={len(entry['train_templates'])*len(COINS)}, eval={len(entry['eval_templates'])*len(COINS)}")


if __name__ == "__main__":
    main()
