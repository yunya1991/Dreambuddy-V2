"""DSH 子 Agent reasoning_chain 采集器 — DSH 层原生序列数据源 (P2)。

通过调用 SubagentNode.execute() 跑多组样本批次,从 SubagentOutput.reasoning_chain
提取 3-8 节点推理链,专供 DSH 层训练。

设计（SPEC-DSH §1.5 方案 - 沙箱模式主动调用,不依赖生产日志）:
  - 用 create_subagent_nodes(llm_fn=None) 创建 8 个 SubagentNode（走规则降级）
  - 构造 mock node_output（含 indicators + rationale）触发不同推理链
  - SubagentOutput.reasoning_chain split(" | ") → node_sequence
  - 补日志到 SubagentNode.execute() 供生产环境采集（EN_DSH_TRACE=true）
  - FAIL-OPEN: agent 异常返回空列表

依赖 subagent_registry.py 的 SubagentNode.execute()。
"""
import os
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_DSH_DIR = os.path.join(_PROJECT_ROOT, "1-ARCHITECTURE", "dream-harness-bridge", "packages", "python-server")

for _p in [_THIS_DIR, _34_DIR, _DSH_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# ============================================================
# Mock node_output 样本 — 覆盖 8 个 subagent 类型
# 每个样本含 indicators + rationale（→ reasoning_chain）+ direction + confidence
# ============================================================

_SAMPLE_NODE_OUTPUTS = [
    # technical: EMA 排列 + RSI + MACD
    ("technical", {
        "indicators": {"price": 45000, "ema20": 44800, "ema50": 44000, "rsi14": 62, "macd": 120, "volume": 1500},
        "rationale": ["EMA20上穿EMA50", "RSI14处于多头区间", "MACD金叉确认", "量能放大"],
        "direction": "LONG",
        "confidence": 0.75,
    }),
    # sentiment: FGI + 新闻情绪
    ("sentiment", {
        "indicators": {"fgi": 72, "news_sentiment": 0.6, "social_volume": 12000},
        "rationale": ["FGI=72贪婪区间", "新闻情绪偏多", "社交热度上升"],
        "direction": "LONG",
        "confidence": 0.65,
    }),
    # macro: 利率 + 通胀
    ("macro", {
        "indicators": {"cpi": 2.5, "fed_rate": 5.25, "gdp_growth": 2.1},
        "rationale": ["CPI回落至2.5%", "利率维持高位", "GDP增长稳健"],
        "direction": "NEUTRAL",
        "confidence": 0.55,
    }),
    # flow: 资金流向
    ("flow", {
        "indicators": {"net_inflow": 50000000, "northbound": 20000000, "stablecoin_mcap": 150000000000},
        "rationale": ["主力资金净流入", "北向资金加仓", "稳定币市值扩张"],
        "direction": "LONG",
        "confidence": 0.70,
    }),
    # onchain: 链上活跃度
    ("onchain", {
        "indicators": {"active_addresses": 950000, "exchange_balance": 2.1e6, "mvrv": 1.8},
        "rationale": ["活跃地址增长", "交易所余额下降", "MVRV处于合理区间"],
        "direction": "LONG",
        "confidence": 0.60,
    }),
    # valuation: PE/PB
    ("valuation", {
        "indicators": {"pe_ratio": 25, "pb_ratio": 3.5, "dcf_fair_value": 50000},
        "rationale": ["PE处于历史中位", "PB略高于行业中位", "DCF估值合理"],
        "direction": "NEUTRAL",
        "confidence": 0.50,
    }),
    # risk: VaR
    ("risk", {
        "indicators": {"var95": -0.08, "var99": -0.15, "stress_loss": -0.25},
        "rationale": ["VaR95=-8%可接受", "VaR99=-15%触警戒线", "压力损失较大"],
        "direction": "SHORT",
        "confidence": 0.65,
    }),
    # portfolio: 漂移 + 总仓位
    ("portfolio", {
        "indicators": {"drift": 0.12, "total_exposure": 0.75, "rebalance_needed": True},
        "rationale": ["漂移度12%超阈值", "总仓位75%偏高", "需再平衡减仓"],
        "direction": "SHORT",
        "confidence": 0.60,
    }),
]


# ============================================================
# 采集器主体
# ============================================================

class DshSubagentCollector(TrainingDataProvider):
    """DSH 子 Agent reasoning_chain 采集器。

    通过调用 SubagentNode.execute() 跑样本批次,从 reasoning_chain
    提取 3-8 节点推理链,作为 DSH 层训练数据。
    """

    def __init__(self):
        pass

    def get_source_name(self) -> str:
        return "dsh_subagent"

    def get_quality_threshold(self) -> str:
        return "A"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """跑样本批次采集 subagent reasoning_chain 序列。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳（sandbox 模式忽略）

        Returns:
            训练案例列表（FAIL-OPEN）
        """
        cases: List[TrainingCase] = []
        try:
            from subagent_registry import create_subagent_nodes
        except Exception:
            return cases

        # 创建 8 个 SubagentNode（走规则降级, 不需要 LLM）
        nodes = create_subagent_nodes(llm_fn=None)
        if not nodes:
            return cases

        # 构建 module → SubagentNode 映射
        node_map = {n.module: n for n in nodes}

        for module_name, mock_output in _SAMPLE_NODE_OUTPUTS:
            try:
                node = node_map.get(module_name)
                if node is None:
                    continue  # 该 agent 未注册（FAIL-OPEN 跳过）

                result = node.execute(mock_output)

                # reasoning_chain split 为 node_sequence
                reasoning = result.reasoning_chain or ""
                rationale_steps = [s.strip() for s in reasoning.split(" | ") if s.strip()] if reasoning else []

                # 组装 node_sequence: dispatch → execute → rationale steps → response
                node_seq = ["subagent.dispatch"]
                if rationale_steps:
                    node_seq.append("subagent.execute")
                    node_seq.extend(f"reason.{step}" for step in rationale_steps)
                    node_seq.append("subagent.response")
                else:
                    # 无 reasoning_chain,最小序列
                    node_seq.extend(["subagent.execute", "subagent.response"])

                outcome = "success"
                cases.append(TrainingCase(
                    intent=f"subagent.{module_name}",
                    actions=node_seq,
                    outcome_text=outcome,
                    learned=[
                        f"node_count={len(node_seq)}",
                        f"module={module_name}",
                        f"direction={mock_output.get('direction', 'NEUTRAL')}",
                        f"confidence={result.confidence}",
                    ],
                    layer_tags=["DSH"],
                    quality="A",
                    confidence=0.8,
                    source="dsh_subagent",
                    metadata={
                        "module": module_name,
                        "node_id": node.node_id,
                        "direction": mock_output.get("direction", "NEUTRAL"),
                        "confidence": result.confidence,
                        "rationale_count": len(rationale_steps),
                        "evidence_refs": getattr(result, "evidence_refs", [])[:5],
                        "node_count": len(node_seq),
                    },
                ))
            except Exception:
                continue  # FAIL-OPEN: 单 agent 失败不影响其他

        return cases[:limit]
