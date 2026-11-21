"""留出集 H-70：
A) 40 条决策/外部状态（用未出现在 v0.3 词表中的措辞）——测漏存
B) 30 条"陈述式代码事实"（不含定义/导入/赋值/读取/依赖等结构谓语）——测误存
"""

import ast
import json
import os

TARGET = "/tmp/e1b_clean/1-ARCHITECTURE/dreamos"
OUT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments/H-70.jsonl"

DECISIONS = [
    ("TradingAgent", "的开仓动作要经过交易主管签字"),
    ("GraphExecutor", "在夜间批次里串行推进各节点"),
    ("NodeRunner", "的失败重试次数和品种风险等级挂钩"),
    ("SkillAdapter", "的加载范围取决于季度评审结论"),
    ("MemoryTree", "的节点命名由项目负责人裁定"),
    ("CostTracker", "的告警对象随轮班表轮换"),
    ("IntentEngine", "的低置信样本交给标注组处理"),
    ("CapabilityRegistry", "的新增条目需经接口人确认"),
    ("GraphStore", "的历史数据按监管要求留存"),
    ("APIAdapter", "的对外字段由合规部门审定"),
    ("EvaluationMemory", "的评分结论每两周同步一次"),
    ("ScenarioClassifier", "的新场景先做离线影子对比"),
    ("BudgetPlanner", "的年度额度在预算委员会上敲定"),
    ("LlmClient", "的外部调用受供应商配额约束"),
    ("RegistryNode", "的下线流程要走资产台账"),
    ("BacktestRunner", "的结果只在内网可查"),
    ("TradeJournal", "的成交明细单独归档"),
    ("RiskGate", "的异常处置顺序由交易主管排定"),
    ("FlowPlanner", "的跨域编排需架构评审通过"),
    ("MemoryCompactor", "的整理动作放在非交易时段"),
    ("TradingAgent", "的持仓上限与账户等级绑定"),
    ("GraphExecutor", "的并行度受机器核数约束"),
    ("NodeRunner", "的超时处置按品种分层"),
    ("SkillAdapter", "的技能包来源限定在内部仓库"),
    ("MemoryTree", "的跨项目引用需项目负责人同意"),
    ("CostTracker", "的账单颗粒度到策略级"),
    ("IntentEngine", "的兜底路径交给标注组兜住"),
    ("CapabilityRegistry", "的命名规范由平台组维护"),
    ("GraphStore", "的冷数据转入归档介质"),
    ("APIAdapter", "的鉴权方式随网关版本演进"),
    ("EvaluationMemory", "的评审判定以双人结论为准"),
    ("ScenarioClassifier", "的标签体系跟随业务口径走"),
    ("BudgetPlanner", "的额度调整需财务接口人确认"),
    ("LlmClient", "的供应商切换要经过安全评估"),
    ("RegistryNode", "的元数据由平台组统一维护"),
    ("BacktestRunner", "的样本区间跟随策略定义"),
    ("TradeJournal", "的对账频率按日终批次"),
    ("RiskGate", "的熔断恢复由交易主管决定"),
    ("FlowPlanner", "的节点顺序以评审纪要为准"),
    ("MemoryCompactor", "的保留周期随存储水位调整"),
]


def files():
    out = []
    for root, dirs, fs in os.walk(TARGET):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        out += [os.path.join(root, f) for f in fs if f.endswith(".py")]
    return sorted(out)


def mod_of(path):
    return os.path.relpath(path, TARGET)[:-3].replace("/", ".").replace(".__init__", "")


def build_facts():
    defs, asyncs, classes, arities = [], [], [], []
    for f in files():
        try:
            tree = ast.parse(open(f, encoding="utf-8").read(), filename=f)
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel, mod = os.path.relpath(f, TARGET), mod_of(f)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                if len(name) < 8 and "_" not in name and not any(c.isupper() for c in name):
                    continue
                defs.append((rel, name, mod))
                if isinstance(node, ast.AsyncFunctionDef):
                    asyncs.append((rel, name, mod))
                if isinstance(node, ast.ClassDef) and node.bases:
                    base = node.bases[0]
                    bname = getattr(base, "id", getattr(base, "attr", ""))
                    if bname:
                        classes.append((rel, name, mod, bname))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arities.append((rel, name, mod, len(node.args.args)))

    def uniq(rows, idx=1):
        cnt = {}
        for r in rows:
            cnt[r[idx]] = cnt.get(r[idx], 0) + 1
        return [r for r in rows if cnt[r[idx]] == 1]

    facts = []
    for rel, name, mod in uniq(defs)[:10]:
        facts.append((f"`{name}` 位于 `{mod}` 模块。", f"{rel}"))
    for rel, name, _mod in uniq(asyncs)[:5]:
        facts.append((f"`{name}` 是异步函数。", f"{rel}"))
    for rel, name, _mod, base in uniq(classes)[:7]:
        facts.append((f"`{name}` 的父类是 `{base}`。", f"{rel}"))
    for rel, name, _mod, n in uniq(arities)[:8]:
        facts.append((f"`{name}` 的入参个数是 {n}。", f"{rel}"))
    return facts[:30]


def main():
    rows = []
    for i, (sym, text) in enumerate(DECISIONS, 1):
        rows.append(
            {
                "id": f"HA{i:02d}",
                "text": f"`{sym}` {text}。",
                "question": f"{sym} {text}",
                "label": "non_derivable",
                "category": "留出-决策",
                "truth_evidence": [],
            }
        )
    for j, (text, rel) in enumerate(build_facts(), 1):
        rows.append(
            {
                "id": f"HB{j:02d}",
                "text": text,
                "question": text,
                "label": "derivable",
                "category": "留出-陈述事实",
                "truth_evidence": [rel],
            }
        )
    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(
        "total",
        len(rows),
        {c: sum(1 for r in rows if r["category"] == c) for c in {r["category"] for r in rows}},
    )


if __name__ == "__main__":
    main()
