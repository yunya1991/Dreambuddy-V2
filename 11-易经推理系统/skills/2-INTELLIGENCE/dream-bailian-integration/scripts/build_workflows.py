#!/usr/bin/env python3
"""
百炼工作流构建器
直接在百炼平台构建Dream-MultiSkill核心工作流
"""
import json
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.bailian_client import BailianClient

API_KEY = "sk-c233489e73e94b9591e4776d89ec8cb8"


class DreamMultiSkillWorkflowBuilder:
    """Dream-MultiSkill 百炼工作流构建器"""

    def __init__(self, api_key):
        self.client = BailianClient(api_key=api_key)

    def build_trading_workflow(self):
        """
        构建交易决策工作流

        工作流结构:
        1. 用户输入 → A1调研请求
        2. A1调研 → RAG知识库检索
        3. RAG结果 → A2第一性原理分析
        4. A2分析 → A3沙盘推演
        5. A3推演 → A4战术验证
        6. A4验证 → A5执行建议
        7. 最终输出 → AAM产物投递
        """
        workflow = {
            "name": "Dream-MultiSkill 交易决策工作流",
            "version": "v1.0",
            "description": "基于A系列决策链的完整交易决策流程",
            "trigger": {
                "type": "manual",
                "description": "手动触发或A6自动触发"
            },
            "nodes": [
                {
                    "id": "input",
                    "type": "start",
                    "name": "输入",
                    "description": "接收交易信号或市场数据",
                    "output": {
                        "signal": "string",
                        "symbol": "string",
                        "context": "object"
                    }
                },
                {
                    "id": "a1_research",
                    "type": "llm",
                    "name": "A1 深度调研",
                    "model": "qwen-plus",
                    "description": "收集市场情报、档案数据、链上信号",
                    "prompt_template": """你是一个专业的市场调研分析师。请对 {symbol} 进行深度调研：

1. 市场情报
   - 当前价格、涨跌幅、成交量
   - 近期关键事件

2. 档案数据
   - 历史相似行情
   - 历史处理模式

3. 链上信号
   - 交易所流入/流出
   - 大户地址变动

4. 宏观环境
   - 相关市场走势
   - 资金流向

请输出结构化的调研报告。
""",
                    "input": {"symbol": "input.symbol"},
                    "output": {"research_report": "string"}
                },
                {
                    "id": "rag_retrieve",
                    "type": "rag",
                    "name": "RAG 知识检索",
                    "description": "从知识库检索相关经验",
                    "config": {
                        "top_k": 5,
                        "similarity_threshold": 0.7,
                        "index": "dream_multiskill"
                    },
                    "input": {"query": "input.signal"},
                    "output": {"knowledge_chunks": "array"}
                },
                {
                    "id": "a2_analysis",
                    "type": "llm",
                    "name": "A2 第一性原理",
                    "model": "qwen-plus",
                    "description": "基于阻力最小原理分析市场",
                    "prompt_template": """你是一个基于第一性原理的交易分析师。请分析当前市场状态：

核心原理：
1. 市场沿阻力最小方向运行
2. 趋势具有延续性
3. 关键点突破是趋势确认信号
4. 矛盾转化是时机判断依据

当前信号：{signal}
调研报告：{research_report}
相关知识：{knowledge_chunks}

请分析：
1. 当前阻力最小方向
2. 趋势动力来源
3. 关键点位置
4. 主要矛盾是什么
""",
                    "input": {
                        "signal": "input.signal",
                        "research_report": "a1_research.research_report",
                        "knowledge_chunks": "rag_retrieve.knowledge_chunks"
                    },
                    "output": {"analysis_result": "object"}
                },
                {
                    "id": "a3_simulation",
                    "type": "llm",
                    "name": "A3 沙盘推演",
                    "model": "qwen-plus",
                    "description": "多情景模拟验证",
                    "prompt_template": """你是一个交易策略推演专家。请对以下分析进行情景推演：

A2分析结果：{analysis_result}

请推演3种情景：
1. 看多情景 - 假设上涨的概率和路径
2. 看空情景 - 假设下跌的概率和路径
3. 震荡情景 - 假设区间震荡的概率和范围

每种情景需包含：
- 触发条件
- 概率评估 (0-100%)
- 关键价位
- 止损位置

最终给出矛盾分析：
- 主要矛盾
- 次要矛盾
- 矛盾转化时机
""",
                    "input": {"analysis_result": "a2_analysis.analysis_result"},
                    "output": {"simulation_result": "object"}
                },
                {
                    "id": "a4_validation",
                    "type": "gate",
                    "name": "A4 战术验证",
                    "description": "验证方案的技术可行性",
                    "checks": [
                        {
                            "name": "数据完整性",
                            "check": "input.context.data_complete == true"
                        },
                        {
                            "name": "置信度阈值",
                            "check": "a3_simulation.confidence >= 60"
                        },
                        {
                            "name": "风险可控",
                            "check": "a3_simulation.max_loss_percent <= 5"
                        }
                    ],
                    "input": {
                        "context": "input.context",
                        "simulation": "a3_simulation.simulation_result"
                    },
                    "output": {"validation_result": "object"}
                },
                {
                    "id": "a5_decision",
                    "type": "llm",
                    "name": "A5 战术执行",
                    "model": "qwen-plus",
                    "description": "综合判断并给出执行建议",
                    "prompt_template": """你是一个交易执行专家。请基于以下信息给出执行建议：

A4验证结果：{validation_result}
A3推演情景：{simulation}

重要提醒：
- A4仅提供验证，不做方向判断
- 最终决策由你综合判断

请输出：
1. 方向建议 (BUY/SHORT/HOLD)
2. 入场价位
3. 止损价位
4. 止盈价位
5. 仓位建议
6. 执行理由
""",
                    "input": {
                        "validation_result": "a4_validation.validation_result",
                        "simulation": "a3_simulation.simulation_result"
                    },
                    "output": {"decision": "object"}
                },
                {
                    "id": "aam_deliver",
                    "type": "action",
                    "name": "AAM 产物投递",
                    "description": "将决策结果投递到产物中心",
                    "input": {
                        "signal": "input.signal",
                        "a1_report": "a1_research.research_report",
                        "a2_analysis": "a2_analysis.analysis_result",
                        "a3_simulation": "a3_simulation.simulation_result",
                        "a4_validation": "a4_validation.validation_result",
                        "a5_decision": "a5_decision.decision"
                    },
                    "output": {"delivery_result": "object"}
                },
                {
                    "id": "output",
                    "type": "end",
                    "name": "输出",
                    "description": "输出最终决策结果",
                    "input": {
                        "decision": "a5_decision.decision",
                        "delivery": "aam_deliver.delivery_result"
                    }
                }
            ],
            "edges": [
                {"from": "input", "to": "a1_research", "condition": None},
                {"from": "input", "to": "rag_retrieve", "condition": None},
                {"from": "rag_retrieve", "to": "a2_analysis", "condition": None},
                {"from": "a1_research", "to": "a2_analysis", "condition": None},
                {"from": "a2_analysis", "to": "a3_simulation", "condition": None},
                {"from": "a3_simulation", "to": "a4_validation", "condition": None},
                {"from": "a4_validation", "to": "a5_decision", "condition": "validation_result.pass == true"},
                {"from": "a5_decision", "to": "aam_deliver", "condition": None},
                {"from": "aam_deliver", "to": "output", "condition": None}
            ]
        }

        return workflow

    def build_knowledge_qa_workflow(self):
        """
        构建知识问答工作流
        """
        workflow = {
            "name": "Dream-MultiSkill 知识问答工作流",
            "version": "v1.0",
            "description": "基于RAG的Dream-MultiSkill知识库问答",
            "trigger": {
                "type": "manual",
                "description": "用户提问触发"
            },
            "nodes": [
                {
                    "id": "input",
                    "type": "start",
                    "name": "用户提问",
                    "output": {"question": "string"}
                },
                {
                    "id": "intent_classify",
                    "type": "llm",
                    "name": "意图分类",
                    "model": "qwen-plus",
                    "description": "判断用户问题类型",
                    "prompt_template": """请判断用户问题的类型：

问题：{question}

类型选项：
1. A系列咨询 - 关于A0-A9各模块的功能
2. 技术实现 - 关于代码、技术细节
3. 治理规范 - 关于流程、合规、宪法
4. 使用帮助 - 如何使用系统
5. 其他咨询

请只输出类型编号和简短说明。
""",
                    "input": {"question": "input.question"},
                    "output": {"intent": "string", "confidence": "float"}
                },
                {
                    "id": "rag_retrieve",
                    "type": "rag",
                    "name": "RAG 检索",
                    "description": "从知识库检索相关内容",
                    "config": {
                        "top_k": 3,
                        "similarity_threshold": 0.6,
                        "index": "dream_multiskill"
                    },
                    "input": {"query": "input.question"},
                    "output": {"chunks": "array"}
                },
                {
                    "id": "generate",
                    "type": "llm",
                    "name": "生成回答",
                    "model": "qwen-plus",
                    "description": "基于检索结果生成回答",
                    "prompt_template": """你是一个Dream-MultiSkill系统的专业助手。请基于以下知识回答用户问题：

用户问题：{question}
问题类型：{intent}
检索到的知识：

{knowledge_chunks}

请用清晰、专业的方式回答。如果知识库中没有相关信息，请说明并提供一般性建议。
""",
                    "input": {
                        "question": "input.question",
                        "intent": "intent_classify.intent",
                        "knowledge_chunks": "rag_retrieve.chunks"
                    },
                    "output": {"answer": "string", "sources": "array"}
                },
                {
                    "id": "output",
                    "type": "end",
                    "name": "输出",
                    "input": {
                        "answer": "generate.answer",
                        "sources": "generate.sources",
                        "intent": "intent_classify.intent"
                    }
                }
            ],
            "edges": [
                {"from": "input", "to": "intent_classify", "condition": None},
                {"from": "intent_classify", "to": "rag_retrieve", "condition": None},
                {"from": "rag_retrieve", "to": "generate", "condition": None},
                {"from": "generate", "to": "output", "condition": None}
            ]
        }

        return workflow

    def build_compliance_review_workflow(self):
        """
        构建合规审查工作流
        """
        workflow = {
            "name": "Dream-MultiSkill 合规审查工作流",
            "version": "v1.0",
            "description": "系统变更的合规性审查",
            "trigger": {
                "type": "manual",
                "description": "变更提交时触发"
            },
            "nodes": [
                {
                    "id": "input",
                    "type": "start",
                    "name": "变更输入",
                    "output": {
                        "change_description": "string",
                        "change_type": "string",  # P0/P1/P2/P3
                        "change_plan": "object"
                    }
                },
                {
                    "id": "risk_assess",
                    "type": "llm",
                    "name": "风险评估",
                    "model": "qwen-plus",
                    "description": "评估变更风险",
                    "prompt_template": """你是一个合规审查专家。请评估以下变更的风险：

变更描述：{change_description}
变更类型：{change_type}

风险维度：
1. 技术风险 - 代码质量、测试覆盖率
2. 业务风险 - 对现有流程的影响
3. 资金风险 - 对账户/仓位的影响

请给出：
1. 综合风险评分 (0-100)
2. 风险等级 (LOW/MEDIUM/HIGH/CRITICAL)
3. 风险说明
4. 建议的操作 (BLOCK/REVIEW/AUTO)
""",
                    "input": {
                        "change_description": "input.change_description",
                        "change_type": "input.change_type"
                    },
                    "output": {
                        "risk_score": "int",
                        "risk_level": "string",
                        "risk_reasons": "array",
                        "suggested_action": "string"
                    }
                },
                {
                    "id": "gate_check",
                    "type": "gate",
                    "name": "门禁判断",
                    "description": "根据风险等级决定后续流程",
                    "checks": [
                        {
                            "name": "P0/P1必须人工",
                            "check": "input.change_type in ['P0', 'P1']"
                        },
                        {
                            "name": "CRITICAL阻止",
                            "check": "risk_assess.risk_level != 'CRITICAL'"
                        }
                    ],
                    "input": {
                        "change_type": "input.change_type",
                        "risk": "risk_assess"
                    },
                    "output": {"gate_result": "object"}
                },
                {
                    "id": "human_review",
                    "type": "action",
                    "name": "人工审批",
                    "description": "触发人工审批流程",
                    "input": {"gate_result": "gate_check.gate_result"},
                    "output": {"review_result": "object"}
                },
                {
                    "id": "auto_approve",
                    "type": "action",
                    "name": "自动通过",
                    "description": "低风险变更自动通过",
                    "input": {"gate_result": "gate_check.gate_result"},
                    "output": {"approval": "object"}
                },
                {
                    "id": "output",
                    "type": "end",
                    "name": "审查结果",
                    "input": {
                        "decision": "gate_check.gate_result.decision",
                        "reason": "gate_check.gate_result.reason"
                    }
                }
            ],
            "edges": [
                {"from": "input", "to": "risk_assess", "condition": None},
                {"from": "risk_assess", "to": "gate_check", "condition": None},
                {"from": "gate_check", "to": "human_review", "condition": "gate_result.requires_human == true"},
                {"from": "gate_check", "to": "auto_approve", "condition": "gate_result.requires_human == false"},
                {"from": "human_review", "to": "output", "condition": None},
                {"from": "auto_approve", "to": "output", "condition": None}
            ]
        }

        return workflow


def main():
    """主函数"""
    print("=" * 60)
    print("🚀 Dream-MultiSkill 百炼工作流构建")
    print("=" * 60)

    builder = DreamMultiSkillWorkflowBuilder(API_KEY)

    # 构建三个核心工作流
    workflows = [
        ("交易决策工作流", builder.build_trading_workflow()),
        ("知识问答工作流", builder.build_knowledge_qa_workflow()),
        ("合规审查工作流", builder.build_compliance_review_workflow())
    ]

    # 保存工作流定义
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflows")
    os.makedirs(output_dir, exist_ok=True)

    for name, workflow in workflows:
        filename = f"{workflow['name'].split()[0]}_workflow.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(workflow, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 工作流已生成: {name}")
        print(f"   文件: {filepath}")
        print(f"   节点数: {len(workflow['nodes'])}")
        print(f"   描述: {workflow['description']}")

    print("\n" + "=" * 60)
    print("📋 工作流概览")
    print("=" * 60)

    for name, workflow in workflows:
        print(f"\n【{name}】")
        for node in workflow["nodes"]:
            print(f"  {node['id']}: {node['name']} ({node['type']})")

    print("\n✅ 所有工作流定义已生成！")


if __name__ == "__main__":
    main()
