"""生成 60 条对抗样本：含代码符号但语义不可由代码推导；以及带符号的敏感项。"""

import json

OUT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/55-AI大模型研究报告/认知系统研究/experiments/A-60.jsonl"

DECISIONS = [
    ("TradingAgent", "实盘开仓由风控岗复核后才执行"),
    ("GraphExecutor", "在回测模式下默认关闭重试"),
    ("NodeRunner", "超时时间由业务方按品种单独配置"),
    ("SkillAdapter", "只加载白名单内的技能包"),
    ("MemoryTree", "删改操作要留审计记录"),
    ("CostTracker", "预算告警发给值班群而不是负责人"),
    ("IntentEngine", "低置信结果直接走人工分流"),
    ("CapabilityRegistry", "新增节点需要两人复核"),
    ("GraphStore", "只保留最近 90 天历史"),
    ("APIAdapter", "对外只暴露只读接口"),
    ("EvaluationMemory", "评分口径以周为单位冻结"),
    ("ScenarioClassifier", "新场景上线前先跑一周影子模式"),
    ("BudgetPlanner", "预算上限按季度调整一次"),
    ("LlmClient", "调用失败时降级到本地规则"),
    ("RegistryNode", "节点下线要走变更单"),
    ("BacktestRunner", "回测结果只允许出现在内部报表"),
    ("TradeJournal", "成交记录保留在独立存储"),
    ("RiskGate", "异常波动时先暂停开仓再排查"),
    ("FlowPlanner", "跨域编排需要架构组会签"),
    ("MemoryCompactor", "压缩动作在收盘后执行"),
]

PREF_WITH_MARK = [
    ("TradingAgent", "报告输出中文"),
    ("DreamOS", "日志保留 14 天"),
    ("GraphExecutor", "默认不开并行分支"),
    ("SkillAdapter", "优先本地技能包"),
    ("CapabilityRegistry", "节点命名用下划线"),
]

DISGUISED = [
    ("NodeRunner", "团队已经确认不再考虑自动重试方案"),
    ("TradingAgent", "这一版不再做盘中调仓"),
    ("GraphStore", "历史数据回填已经停掉"),
    ("IntentEngine", "多意图拆分的方案已经放弃"),
    ("MemoryTree", "跨项目共享节点暂不开放"),
    ("CostTracker", "成本告警阈值维持现状"),
    ("ScenarioClassifier", "场景标签沿用上一版口径"),
    ("LlmClient", "外部模型切换押后到下一季度"),
    ("APIAdapter", "接口版本冻结在当前大版本"),
    ("EvaluationMemory", "评分脚本不再接受手工改判"),
]

EXTERNAL = [
    ("GraphExecutor", "部署在 3102 实例上，版本 v3"),
    ("TradingAgent", "挂在主交易网关后面，灰度 20%"),
    ("NodeRunner", "跑在备用节点，CPU 上限 2 核"),
    ("MemoryTree", "数据目录在 /data/memory"),
    ("CostTracker", "账单落在财务共享中心"),
    ("IntentEngine", "模型服务走内网地址"),
    ("SkillAdapter", "技能包仓库在私有 GitLab"),
    ("CapabilityRegistry", "注册表快照备份在对象存储"),
    ("GraphStore", "图库实例为单副本"),
    ("APIAdapter", "网关证书 90 天后到期"),
]

SENSITIVE = [
    ("db_client", "连接密码在 /etc/db.env"),
    ("payment_sdk", "API key 在 CI secrets"),
    ("ssh_runner", "私钥在运维堡垒机"),
    ("mail_service", "password 在配置中心"),
    ("backup_job", "凭证在 K8s Secret"),
    ("monitor_agent", "token 在环境变量"),
    ("exchange_api", "密钥在本地 keychain"),
    ("object_store", "secret 在部署脚本"),
    ("gateway_proxy", "证书口令在运维手册"),
    ("audit_log", "访问 token 在日志目录"),
]


def main():
    rows = []
    n = 0

    for sym, text in DECISIONS:
        n += 1
        rows.append(
            {
                "id": f"A{n:03d}",
                "text": f"`{sym}` 的{text}。",
                "question": f"{sym} {text}",
                "label": "non_derivable",
                "category": "决策约束",
                "adversarial": True,
                "truth_evidence": [],
            }
        )
    for sym, text in PREF_WITH_MARK:
        for _ in range(2):
            n += 1
            rows.append(
                {
                    "id": f"A{n:03d}",
                    "text": f"用户偏好：`{sym}` 的{text}。",
                    "question": f"{sym} {text}",
                    "label": "non_derivable",
                    "category": "偏好带符号",
                    "adversarial": True,
                    "truth_evidence": [],
                }
            )
    for sym, text in DISGUISED:
        n += 1
        rows.append(
            {
                "id": f"A{n:03d}",
                "text": f"关于 `{sym}`，{text}。",
                "question": f"{sym} {text}",
                "label": "non_derivable",
                "category": "伪装决策",
                "adversarial": True,
                "truth_evidence": [],
            }
        )
    for sym, text in EXTERNAL:
        n += 1
        rows.append(
            {
                "id": f"A{n:03d}",
                "text": f"`{sym}` {text}。",
                "question": f"{sym} {text}",
                "label": "non_derivable",
                "category": "外部状态带符号",
                "adversarial": True,
                "truth_evidence": [],
            }
        )
    for sym, text in SENSITIVE:
        n += 1
        rows.append(
            {
                "id": f"A{n:03d}",
                "text": f"`{sym}` 的{text}。",
                "question": f"{sym} {text}",
                "label": "sensitive",
                "category": "敏感带符号",
                "adversarial": True,
                "truth_evidence": [],
            }
        )

    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(
        "total",
        len(rows),
        {
            c: sum(1 for r in rows if r["category"] == c)
            for c in dict.fromkeys(r["category"] for r in rows)
        },
    )


if __name__ == "__main__":
    main()
