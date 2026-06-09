#!/usr/bin/env python3
"""
A4 验证执行器 - 核心脚本
============================
A4 = A3推演验证方案设计师 + 矛盾论验证者

功能:
1. 接收A3推演结论（情景A/B/C）
2. 知识库索引，为每个情景匹配策略
3. 设计验证方案
4. 执行高级委托
5. 输出验证报告

版本: v1.0.0
日期: 2026-04-28
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# ============ 配置 ============
WORKSPACE = Path("/Users/zhangjiangtao/WorkBuddy/20260415144304")
PROFILE = "dreamdemo"  # 仅操作模拟盘
LOG_DIR = WORKSPACE / "reports" / "a4_validation"
STATE_FILE = WORKSPACE / ".workbuddy" / "a4_validation_state.json"

# ============ 工具函数 ============

def run_okx_cmd(cmd: list) -> dict:
    """执行OKX CLI命令"""
    try:
        result = subprocess.run(
            ["okx"] + cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            try:
                return {"success": True, "data": json.loads(result.stdout), "is_json": True}
            except:
                return {"success": True, "data": result.stdout.strip(), "is_json": False}
        else:
            return {"success": False, "error": result.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_current_price(inst_id: str = "BTC-USDT-SWAP") -> float:
    """获取当前价格"""
    result = run_okx_cmd(["market", "ticker", inst_id])
    if result["success"]:
        if result.get("is_json", False):
            try:
                return float(result["data"]["data"][0]["last"])
            except:
                pass
        # 文本解析
        lines = result["data"].split("\n") if isinstance(result["data"], str) else []
        for line in lines:
            if "last" in line.lower() or "最新价" in line:
                parts = line.split()
                for p in parts:
                    try:
                        return float(p.replace(",", ""))
                    except:
                        continue
    return 0.0


def get_account_info() -> dict:
    """获取账户信息"""
    result = run_okx_cmd(["account", "balance", "--profile", PROFILE])
    if result["success"]:
        return result
    return {"success": False}


def get_active_orders() -> dict:
    """获取活跃委托"""
    result = run_okx_cmd(["swap", "algo", "orders", "--instId", "BTC-USDT-SWAP", 
                          "--state", "live", "--profile", PROFILE])
    return result


def get_positions() -> dict:
    """获取持仓"""
    result = run_okx_cmd(["swap", "positions", "--instId", "BTC-USDT-SWAP", 
                          "--profile", PROFILE])
    return result


# ============ 知识库索引 ============

def load_knowledge_base() -> List[dict]:
    """加载知识库策略"""
    kb_dir = WORKSPACE / "knowledge_base"
    strategies = []
    
    for cat_dir in kb_dir.iterdir():
        if cat_dir.is_dir():
            for f in cat_dir.iterdir():
                if f.suffix == ".md" and f.name != "README.md":
                    content = f.read_text()
                    # 简单解析评分
                    score = 50
                    for line in content.split("\n"):
                        if "评分" in line or "score" in line.lower():
                            try:
                                score = int([x for x in line.split() if x.isdigit()][-1])
                            except:
                                pass
                    strategies.append({
                        "name": f.stem,
                        "category": cat_dir.name,
                        "file": str(f),
                        "score": score
                    })
    
    # 按评分排序
    strategies.sort(key=lambda x: x["score"], reverse=True)
    return strategies


def match_strategy_for_scenario(scenario: dict, kb: List[dict]) -> List[dict]:
    """为情景匹配知识库策略"""
    scenario_type = scenario.get("type", "").lower()
    direction = scenario.get("direction", "").lower()
    
    matched = []
    for s in kb:
        # 简单匹配逻辑
        if "突破" in scenario_type or "breakout" in scenario_type:
            if "突破" in s["name"] or "breakout" in s["name"].lower():
                matched.append(s)
        elif "网格" in scenario_type or "grid" in scenario_type:
            if "网格" in s["name"] or "grid" in s["name"].lower():
                matched.append(s)
        elif "马丁" in scenario_type or "martin" in scenario_type:
            if "马丁" in s["name"] or "martin" in s["name"].lower():
                matched.append(s)
        elif direction == "long":
            if "做多" in s["name"] or "long" in s["name"].lower():
                matched.append(s)
        elif direction == "short":
            if "做空" in s["name"] or "short" in s["name"].lower():
                matched.append(s)
    
    return matched[:3]  # 最多返回3个


# ============ 验证方案设计 ============

def design_verification_plan(a3_report: dict, kb: List[dict]) -> dict:
    """设计验证方案"""
    scenarios = a3_report.get("scenarios", [])
    current_price = get_current_price()
    
    verification_plan = {
        "created_at": datetime.now().isoformat(),
        "current_price": current_price,
        "scenarios": []
    }
    
    for scenario in scenarios:
        # 知识库索引
        matched_strategies = match_strategy_for_scenario(scenario, kb)
        
        # 设计验证方案
        plan = {
            "scenario_name": scenario.get("name", "unknown"),
            "probability": scenario.get("probability", 0),
            "verification_target": f"验证情景: {scenario.get('name')}",
            "matched_strategies": matched_strategies,
            "委托方案": design_order_placement(scenario, current_price),
            "验证标准": {
                "触发": f"价格触及{scenario.get('trigger_px', current_price)}",
                "成功": f"达到{scenario.get('target_px', '目标位')}",
                "失败": f"跌破{scenario.get('stop_px', '止损位')}"
            }
        }
        verification_plan["scenarios"].append(plan)
    
    return verification_plan


def design_order_placement(scenario: dict, current_price: float) -> dict:
    """设计委托方案"""
    direction = scenario.get("direction", "long")
    trigger_px = scenario.get("trigger_px", current_price)
    target_px = scenario.get("target_px", current_price * 1.02)
    stop_px = scenario.get("stop_px", current_price * 0.98)
    
    if direction == "long":
        return {
            "entry": {
                "type": "limit",
                "side": "buy",
                "px": trigger_px,
                "sz": 0.05,
                "posSide": "long"
            },
            "protection": {
                "type": "oco",
                "tp_trigger_px": target_px,
                "sl_trigger_px": stop_px,
                "sz": 0.05
            }
        }
    else:  # short
        return {
            "entry": {
                "type": "limit",
                "side": "sell",
                "px": trigger_px,
                "sz": 0.05,
                "posSide": "short"
            },
            "protection": {
                "type": "oco",
                "tp_trigger_px": stop_px,  # 做空时TP在下
                "sl_trigger_px": target_px,  # 做空时SL在上
                "sz": 0.05
            }
        }


# ============ 委托执行 ============

def place_verification_order(plan: dict, scenario_name: str) -> dict:
    """执行验证委托"""
    results = {"entry": None, "protection": None}
    
    entry = plan.get("entry", {})
    protection = plan.get("protection", {})
    
    # 1. 下入场单
    if entry:
        cmd = [
            "swap", "place",
            "--instId", "BTC-USDT-SWAP",
            "--side", entry.get("side", "buy"),
            "--ordType", entry.get("type", "limit"),
            "--px", str(entry.get("px", "")),
            "--sz", str(entry.get("sz", "0.01")),
            "--posSide", entry.get("posSide", "long"),
            "--tdMode", "isolated",
            "--profile", PROFILE
        ]
        result = run_okx_cmd(cmd)
        results["entry"] = {
            "command": " ".join(cmd),
            "result": result
        }
        print(f"  [入场委托] {entry.get('side')} {entry.get('sz')}@{entry.get('px')}")
        print(f"    → {result.get('success', False)}")
    
    # 2. 下OCO保护单
    if protection:
        cmd = [
            "swap", "algo", "place",
            "--instId", "BTC-USDT-SWAP",
            "--side", "sell" if entry.get("posSide") == "long" else "buy",
            "--sz", str(protection.get("sz", "0.01")),
            "--ordType", "oco",
            "--tpTriggerPx", str(protection.get("tp_trigger_px", "")),
            "--tpOrdPx", "-1",  # -1表示市价
            "--slTriggerPx", str(protection.get("sl_trigger_px", "")),
            "--slOrdPx", "-1",  # -1表示市价
            "--posSide", entry.get("posSide", "long"),
            "--tdMode", "isolated",
            "--profile", PROFILE
        ]
        result = run_okx_cmd(cmd)
        results["protection"] = {
            "command": " ".join(cmd),
            "result": result
        }
        print(f"  [OCO保护] TP@{protection.get('tp_trigger_px')} SL@{protection.get('sl_trigger_px')}")
        print(f"    → {result.get('success', False)}")
    
    return results


# ============ 验证报告 ============

def generate_validation_report(verification_plan: dict, execution_results: dict) -> dict:
    """生成验证报告"""
    report = {
        "report_id": f"A4-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now().isoformat(),
        "current_price": verification_plan.get("current_price"),
        "scenarios": []
    }
    
    for i, scenario in enumerate(verification_plan.get("scenarios", [])):
        scenario_result = {
            "name": scenario.get("scenario_name"),
            "probability": scenario.get("probability"),
            "verification_target": scenario.get("verification_target"),
            "matched_strategies": [s["name"] for s in scenario.get("matched_strategies", [])],
            "委托方案": scenario.get("委托方案"),
            "验证标准": scenario.get("验证标准"),
            "execution": execution_results.get(scenario.get("scenario_name"), {}),
            "status": "pending"
        }
        
        # 判断状态
        exec_data = scenario_result["execution"]
        if exec_data.get("entry", {}).get("result", {}).get("success"):
            scenario_result["status"] = "placed"
        else:
            scenario_result["status"] = "failed"
        
        report["scenarios"].append(scenario_result)
    
    return report


def save_report(report: dict):
    """保存报告"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON
    json_file = LOG_DIR / f"{report['report_id']}.json"
    json_file.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    
    # 保存Markdown
    md_file = LOG_DIR / f"{report['report_id']}.md"
    md_content = f"""# A4 验证报告

**报告ID**: {report['report_id']}
**生成时间**: {report['generated_at']}
**当前价格**: ${report['current_price']:,.0f}

---

## 验证情景

"""
    for s in report["scenarios"]:
        md_content += f"""### {s['name']} (P={s['probability']}%)

- **验证目标**: {s['verification_target']}
- **匹配策略**: {', '.join(s['matched_strategies']) or '无'}
- **入场委托**: {s['委托方案'].get('entry', {})}
- **保护委托**: {s['委托方案'].get('protection', {})}
- **验证标准**: 触发={s['验证标准'].get('触发')}, 成功={s['验证标准'].get('成功')}, 失败={s['验证标准'].get('失败')}
- **执行状态**: {s['status'].upper()}
- **入场命令**: `{s['execution'].get('entry', {}).get('command', 'N/A')}`

"""
    
    md_file.write_text(md_content)
    print(f"\n✅ 报告已保存:")
    print(f"   - JSON: {json_file}")
    print(f"   - MD: {md_file}")


# ============ 主流程 ============

def a4_validation_flow(a3_report: Optional[dict] = None):
    """
    A4 验证流程主入口
    
    输入: A3沙盘推演报告
    输出: A4验证报告
    """
    print("=" * 60)
    print("🔬 A4 验证执行器 v1.0")
    print("=" * 60)
    
    # Step 0: 前置检查
    print("\n[Step 0] 前置检查...")
    
    # 检查账户
    acc_info = get_account_info()
    if not acc_info["success"]:
        print(f"❌ 账户检查失败: {acc_info.get('error', 'Unknown')}")
        return None
    
    # 检查持仓
    positions = get_positions()
    active_orders = get_active_orders()
    
    print(f"✅ 账户正常")
    print(f"   持仓: {len(positions.get('data', [])) if positions.get('success') else 'N/A'}")
    print(f"   活跃委托: {len(active_orders.get('data', [])) if active_orders.get('success') else 'N/A'}")
    
    # Step 1: 加载知识库
    print("\n[Step 1] 加载知识库...")
    kb = load_knowledge_base()
    print(f"✅ 加载 {len(kb)} 条策略")
    for s in kb[:3]:
        print(f"   - {s['name']} (评分: {s['score']})")
    
    # Step 2: 设计验证方案
    print("\n[Step 2] 设计验证方案...")
    
    # 如果没有A3报告，使用模拟数据
    if a3_report is None:
        current_price = get_current_price()
        print(f"⚠️ 无A3报告，使用模拟情景 (当前价格: ${current_price:,.0f})")
        a3_report = {
            "scenarios": [
                {
                    "name": "情景A_反弹",
                    "type": "突破",
                    "direction": "long",
                    "probability": 35,
                    "trigger_px": current_price * 1.01,
                    "target_px": current_price * 1.03,
                    "stop_px": current_price * 0.98
                },
                {
                    "name": "情景B_震荡",
                    "type": "网格",
                    "direction": "neutral",
                    "probability": 45,
                    "trigger_px": current_price,
                    "target_px": current_price * 1.01,
                    "stop_px": current_price * 0.99
                },
                {
                    "name": "情景C_下跌",
                    "type": "突破",
                    "direction": "short",
                    "probability": 20,
                    "trigger_px": current_price * 0.99,
                    "target_px": current_price * 0.97,
                    "stop_px": current_price * 1.01
                }
            ]
        }
    
    verification_plan = design_verification_plan(a3_report, kb)
    print(f"✅ 设计 {len(verification_plan['scenarios'])} 个情景验证方案")
    
    # Step 3: 执行验证委托
    print("\n[Step 3] 执行验证委托...")
    execution_results = {}
    
    for scenario in verification_plan["scenarios"]:
        print(f"\n  📋 {scenario['scenario_name']}:")
        result = place_verification_order(scenario["委托方案"], scenario["scenario_name"])
        execution_results[scenario["scenario_name"]] = result
    
    # Step 4: 生成报告
    print("\n[Step 4] 生成验证报告...")
    report = generate_validation_report(verification_plan, execution_results)
    save_report(report)
    
    # 汇总
    print("\n" + "=" * 60)
    print("📊 验证执行汇总")
    print("=" * 60)
    placed = sum(1 for s in report["scenarios"] if s["status"] == "placed")
    print(f"总情景数: {len(report['scenarios'])}")
    print(f"已下单: {placed}")
    print(f"待验证: {len(report['scenarios']) - placed}")
    
    return report


# ============ CLI入口 ============

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="A4 验证执行器")
    parser.add_argument("--a3-report", type=str, help="A3报告JSON文件路径")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不实际下单")
    parser.add_argument("--check-only", action="store_true", help="仅检查状态")
    args = parser.parse_args()
    
    if args.check_only:
        print("🔍 检查当前状态...")
        price = get_current_price()
        print(f"当前价格: ${price:,.0f}")
        positions = get_positions()
        print(f"持仓: {positions}")
        active = get_active_orders()
        print(f"活跃委托: {active}")
    else:
        a3_report = None
        if args.a3_report:
            with open(args.a3_report) as f:
                a3_report = json.load(f)
        
        if args.dry_run:
            print("🔍 模拟运行（不实际下单）...")
            # TODO: 模拟执行
        else:
            result = a4_validation_flow(a3_report)
            if result:
                print("\n✅ A4验证流程完成!")
