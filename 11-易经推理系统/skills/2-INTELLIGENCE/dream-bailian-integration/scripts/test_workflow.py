#!/usr/bin/env python3
"""
百炼工作流执行测试
测试Dream-MultiSkill核心工作流的端到端执行
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.bailian_client import BailianClient

API_KEY = "sk-c233489e73e94b9591e4776d89ec8cb8"


def test_trading_workflow():
    """测试交易决策工作流"""
    print("\n" + "=" * 60)
    print("🧪 测试: 交易决策工作流")
    print("=" * 60)

    client = BailianClient(api_key=API_KEY)

    # Step 1: A1 深度调研
    print("\n📍 Step 1: A1 深度调研")
    prompt_a1 = """你是一个专业的市场调研分析师。请对 BTC-USDT 进行深度调研分析。

请输出：
1. 当前市场概况（价格、涨跌幅、成交量）
2. 近期关键事件
3. 链上信号分析
4. 宏观环境评估

请用简洁的格式输出调研结果。"""

    response = client.chat([
        {"role": "user", "content": prompt_a1}
    ], max_tokens=800, temperature=0.5)

    a1_result = response["choices"][0]["message"]["content"]
    print(f"✅ A1调研完成 ({response['usage']['completion_tokens']} tokens)")
    print(f"   预览: {a1_result[:200]}...")

    # Step 2: A2 第一性原理分析
    print("\n📍 Step 2: A2 第一性原理分析")
    prompt_a2 = """基于以下A1调研结果，请进行第一性原理分析：

核心原理：
1. 市场沿阻力最小方向运行
2. 趋势具有延续性
3. 关键点突破是趋势确认信号

A1调研结果：
{a1_result}

请分析：
1. 当前阻力最小方向
2. 趋势动力来源
3. 关键点位置
4. 主要矛盾是什么

请用简洁的结构化格式输出。"""

    response = client.chat([
        {"role": "user", "content": prompt_a2.format(a1_result=a1_result)}
    ], max_tokens=600, temperature=0.5)

    a2_result = response["choices"][0]["message"]["content"]
    print(f"✅ A2分析完成 ({response['usage']['completion_tokens']} tokens)")
    print(f"   预览: {a2_result[:200]}...")

    # Step 3: A3 沙盘推演
    print("\n📍 Step 3: A3 沙盘推演")
    prompt_a3 = """请对以下A2分析结果进行情景推演：

A2分析：
{a2_result}

请推演3种情景（每种包含触发条件、概率、关键价位、止损位）：
1. 看多情景
2. 看空情景
3. 震荡情景

最后输出：
- 主要矛盾
- 次要矛盾
- 矛盾转化时机"""

    response = client.chat([
        {"role": "user", "content": prompt_a3.format(a2_result=a2_result)}
    ], max_tokens=800, temperature=0.6)

    a3_result = response["choices"][0]["message"]["content"]
    print(f"✅ A3推演完成 ({response['usage']['completion_tokens']} tokens)")

    # Step 4: A4 战术验证
    print("\n📍 Step 4: A4 战术验证")
    prompt_a4 = """请对以下A3推演结果进行战术验证：

A3推演：
{a3_result}

验证要点：
1. 数据完整性
2. 置信度评估（>60%可通过）
3. 风险可控性（最大亏损<5%）

输出验证结果：
- validation_pass: true/false
- confidence: 0-100
- risk_level: LOW/MEDIUM/HIGH
- 验证说明"""

    response = client.chat([
        {"role": "user", "content": prompt_a4.format(a3_result=a3_result)}
    ], max_tokens=400, temperature=0.3)

    a4_result = response["choices"][0]["message"]["content"]
    print(f"✅ A4验证完成 ({response['usage']['completion_tokens']} tokens)")

    # Step 5: A5 战术执行
    print("\n📍 Step 5: A5 战术执行")
    prompt_a5 = """请基于以下A4验证结果给出最终执行建议：

重要提醒：
- A4仅提供验证，不做方向判断
- 最终决策由你综合判断

A4验证结果：
{a4_result}

请输出：
1. 方向建议：BUY / SHORT / HOLD
2. 入场价位
3. 止损价位
4. 止盈价位
5. 仓位建议
6. 执行理由"""

    response = client.chat([
        {"role": "user", "content": prompt_a5.format(a4_result=a4_result)}
    ], max_tokens=400, temperature=0.5)

    a5_result = response["choices"][0]["message"]["content"]
    print(f"✅ A5决策完成 ({response['usage']['completion_tokens']} tokens)")
    print(f"\n📋 最终决策:\n{a5_result}")

    return {
        "a1": a1_result,
        "a2": a2_result,
        "a3": a3_result,
        "a4": a4_result,
        "a5": a5_result
    }


def test_knowledge_qa():
    """测试知识问答"""
    print("\n" + "=" * 60)
    print("🧪 测试: 知识问答工作流")
    print("=" * 60)

    client = BailianClient(api_key=API_KEY)

    questions = [
        "A4战术验证的核心职责是什么？",
        "Dream-MultiSkill的A系列决策链是什么？",
        "frontmatter规范有哪些字段？"
    ]

    for q in questions:
        print(f"\n❓ 问题: {q}")

        # 意图分类
        intent_prompt = f"""判断以下问题的类型（只需回答编号）：
1. A系列咨询
2. 技术实现
3. 治理规范
4. 使用帮助
5. 其他

问题: {q}"""

        intent_response = client.chat([
            {"role": "user", "content": intent_prompt}
        ], max_tokens=50)
        intent = intent_response["choices"][0]["message"]["content"]
        print(f"   意图: {intent.strip()}")

        # 生成回答
        answer_prompt = f"""你是一个Dream-MultiSkill系统的专业助手。请回答以下问题：

问题: {q}

注意：
- 基于Dream-MultiSkill系统的最佳实践回答
- 如果不确定，说明情况并提供一般性建议
- 回答要简洁专业"""

        answer_response = client.chat([
            {"role": "user", "content": answer_prompt}
        ], max_tokens=500, temperature=0.5)

        answer = answer_response["choices"][0]["message"]["content"]
        print(f"   回答: {answer[:300]}...")


def test_compliance_review():
    """测试合规审查"""
    print("\n" + "=" * 60)
    print("🧪 测试: 合规审查工作流")
    print("=" * 60)

    client = BailianClient(api_key=API_KEY)

    changes = [
        {
            "description": "A4验证逻辑参数调整",
            "type": "P2"
        },
        {
            "description": "新增A5战术执行模块",
            "type": "P1"
        },
        {
            "description": "修改A0矛盾论核心算法",
            "type": "P0"
        }
    ]

    for change in changes:
        print(f"\n📝 变更: {change['description']} ({change['type']})")

        prompt = f"""你是一个合规审查专家。请评估以下变更：

变更描述：{change['description']}
变更类型：{change['type']}

风险维度（评分0-100）：
1. 技术风险
2. 业务风险
3. 资金风险

请输出：
1. 综合风险评分
2. 风险等级：LOW/MEDIUM/HIGH/CRITICAL
3. 建议操作：BLOCK/REVIEW/AUTO"""

        response = client.chat([
            {"role": "user", "content": prompt}
        ], max_tokens=300, temperature=0.3)

        result = response["choices"][0]["message"]["content"]
        print(f"   审查结果: {result[:300]}...")


def main():
    """主函数"""
    print("=" * 60)
    print("🚀 Dream-MultiSkill 百炼工作流测试")
    print("=" * 60)

    # 测试交易决策工作流
    try:
        test_trading_workflow()
    except Exception as e:
        print(f"\n❌ 交易决策工作流测试失败: {e}")

    # 测试知识问答
    try:
        test_knowledge_qa()
    except Exception as e:
        print(f"\n❌ 知识问答测试失败: {e}")

    # 测试合规审查
    try:
        test_compliance_review()
    except Exception as e:
        print(f"\n❌ 合规审查测试失败: {e}")

    print("\n" + "=" * 60)
    print("✅ 所有工作流测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
