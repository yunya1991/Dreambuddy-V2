# AI Trading Compliance SKILL

**版本**: v2.0
**日期**: 2026-05-07
**触发词**: 合规审查、变更门禁、风险评估、影子验证、灰度发布

---

## 定位

**合规审查**是 Dream-MultiSkill 系统的强制门禁层，负责：
1. 变更分类 (P0/P1/P2/P3)
2. 风险评估
3. 影子验证
4. 灰度发布控制
5. 回滚方案审查

---

## 核心功能

### §一、变更分类

#### 1.1 分类标准
| 分类 | 说明 | 示例 | 审查级别 |
|:---|:---|:---|:---:|
| **P0** | 核心逻辑变更，重大风险 | 修改A0矛盾论、A4验证逻辑变更 | 人工确认 |
| **P1** | 重要功能变更 | 新增A系列阶段、SKILL新增/删除 | 人工确认 |
| **P2** | 一般功能变更 | 参数调整、配置变更 | 自动执行 |
| **P3** | 小幅优化 | 文档更新、日志优化 | 自动执行 |

#### 1.2 分类决策树
```
变更描述
    │
    ├─ 是否涉及核心决策逻辑?
    │      ├─ YES → P0
    │      └─ NO
    │             │
    │             ├─ 是否影响交易执行?
    │             │      ├─ YES → P1
    │             │      └─ NO
    │             │             │
    │             │             ├─ 是否有回滚方案?
    │             │             │      ├─ YES → P2
    │             │             │      └─ NO → P1
    │             │             └─ 小幅优化 → P3
    │
    └─ 是否涉及资金/仓位?
           ├─ YES → P0
           └─ NO
```

---

### §二、风险评估

#### 2.1 风险维度
| 维度 | 评估项 | 权重 |
|:---|:---|:---:|
| 技术风险 | 代码质量、测试覆盖率 | 0.3 |
| 业务风险 | 对现有流程的影响 | 0.3 |
| 资金风险 | 对账户/仓位的影响 | 0.4 |

#### 2.2 风险等级
| 等级 | 分值 | 说明 | 操作 |
|:---|:---:|:---|:---|
| **LOW** | 0-30 | 风险可控 | 直接执行 |
| **MEDIUM** | 31-60 | 需要关注 | 自动执行 + 日志记录 |
| **HIGH** | 61-80 | 需要审查 | 人工确认 |
| **CRITICAL** | 81-100 | 高危操作 | 禁止执行 |

#### 2.3 风险评估代码
```python
class ComplianceGate:
    def __init__(self):
        self.risk_weights = {
            "technical": 0.3,
            "business": 0.3,
            "financial": 0.4
        }

    def assess_risk(self, change_description, change_type, financial_impact=None):
        """
        风险评估

        Args:
            change_description: 变更描述
            change_type: 变更类型 (P0/P1/P2/P3)
            financial_impact: 资金影响评估

        Returns:
            dict: 风险评估结果
        """
        # 技术风险评分
        tech_score = self._assess_technical_risk(change_description)

        # 业务风险评分
        biz_score = self._assess_business_risk(change_description)

        # 资金风险评分
        fin_score = self._assess_financial_risk(financial_impact)

        # 综合评分
        total_score = (
            tech_score * self.risk_weights["technical"] +
            biz_score * self.risk_weights["business"] +
            fin_score * self.risk_weights["financial"]
        )

        # 风险等级
        if total_score <= 30:
            level = "LOW"
        elif total_score <= 60:
            level = "MEDIUM"
        elif total_score <= 80:
            level = "HIGH"
        else:
            level = "CRITICAL"

        return {
            "total_score": round(total_score, 2),
            "level": level,
            "breakdown": {
                "technical": tech_score,
                "business": biz_score,
                "financial": fin_score
            },
            "action": self._get_action(level, change_type)
        }

    def _assess_technical_risk(self, description):
        """评估技术风险"""
        risk_keywords = {
            "high": ["核心", "重构", "删除", "替换", "数据库"],
            "medium": ["新增", "修改", "扩展", "集成"],
            "low": ["注释", "日志", "文档", "配置"]
        }

        for level, keywords in risk_keywords.items():
            if any(k in description for k in keywords):
                return {"high": 80, "medium": 50, "low": 20}[level]
        return 30  # 默认中等风险

    def _assess_business_risk(self, description):
        """评估业务风险"""
        if any(k in description for k in ["A0", "A4", "A5", "离场", "入场"]):
            return 80
        if any(k in description for k in ["A1", "A2", "A3", "调研", "分析"]):
            return 50
        return 20

    def _assess_financial_risk(self, impact):
        """评估资金风险"""
        if impact is None:
            return 0
        if impact in ["high", "significant"]:
            return 90
        if impact in ["medium", "moderate"]:
            return 60
        return 20

    def _get_action(self, level, change_type):
        """获取操作建议"""
        if level == "CRITICAL":
            return "BLOCK"  # 阻止执行
        if level == "HIGH" or change_type in ["P0", "P1"]:
            return "HUMAN_REVIEW"  # 人工审查
        if level == "MEDIUM":
            return "AUTO_WITH_LOG"  # 自动执行 + 日志
        return "AUTO"  # 自动执行
```

---

### §三、影子验证

#### 3.1 影子验证流程
```
[1] 创建影子环境 → [2] 复制数据 → [3] 执行变更 → [4] 验证结果 → [5] 生成报告 → [6] 决策
```

#### 3.2 影子验证代码
```python
class ShadowVerifier:
    def __init__(self):
        self.shadow_prefix = "shadow_"

    def run_shadow_verification(self, change_plan):
        """
        执行影子验证

        Args:
            change_plan: 变更计划

        Returns:
            dict: 影子验证报告
        """
        trace_id = generate_trace_id()
        print(f"🔍 开始影子验证: {trace_id}")

        # 1. 创建影子环境
        shadow_env = self._create_shadow_env(change_plan)

        # 2. 执行变更 (影子模式)
        result = self._execute_shadow(change_plan, shadow_env)

        # 3. 验证结果
        verification = self._verify_result(result)

        # 4. 生成报告
        report = {
            "trace_id": trace_id,
            "timestamp": datetime.now().isoformat(),
            "change_plan_id": change_plan.get("id"),
            "verification_result": verification,
            "metrics": {
                "execution_time_ms": result.get("duration_ms", 0),
                "success": verification.get("success", False),
                "metrics_impact": result.get("metrics", {})
            },
            "recommendation": self._get_recommendation(verification)
        }

        # 5. 清理影子环境
        self._cleanup_shadow_env(shadow_env)

        return report

    def _execute_shadow(self, change_plan, shadow_env):
        """影子执行"""
        # 复制当前环境到影子环境
        # 在影子环境中执行变更
        # 记录执行指标
        pass

    def _verify_result(self, result):
        """验证执行结果"""
        return {
            "success": result.get("success", False),
            "metrics_unchanged": self._check_metrics(result),
            "no_data_corruption": self._check_data_integrity(result)
        }

    def _get_recommendation(self, verification):
        """获取建议"""
        if not verification.get("success"):
            return "REJECT"
        if not verification.get("metrics_unchanged"):
            return "REVIEW_METRICS"
        if not verification.get("no_data_corruption"):
            return "REJECT"
        return "APPROVE"
```

---

### §四、合规审查入口

#### 4.1 审查代码
```python
def compliance_review(change_description, change_type, change_plan):
    """
    合规审查入口

    Args:
        change_description: 变更描述
        change_type: P0/P1/P2/P3
        change_plan: 变更计划

    Returns:
        dict: 审查结果
    """
    gate = ComplianceGate()
    verifier = ShadowVerifier()

    # 1. 风险评估
    risk_result = gate.assess_risk(
        change_description,
        change_type,
        change_plan.get("financial_impact")
    )

    # 2. 审查决策
    action = risk_result["action"]

    if action == "BLOCK":
        return {
            "decision": "REJECT",
            "reason": "CRITICAL risk level - blocked",
            "risk_result": risk_result
        }

    if action == "HUMAN_REVIEW":
        # P0/P1 必须人工确认
        return {
            "decision": "PENDING_HUMAN_REVIEW",
            "reason": f"{change_type} requires human approval",
            "risk_result": risk_result,
            "waiting_for": "human_confirmation"
        }

    # 3. 影子验证 (HIGH/MEDIUM 风险)
    if risk_result["level"] in ["HIGH", "MEDIUM"]:
        shadow_report = verifier.run_shadow_verification(change_plan)

        if shadow_report["recommendation"] == "REJECT":
            return {
                "decision": "REJECT",
                "reason": "Shadow verification failed",
                "risk_result": risk_result,
                "shadow_report": shadow_report
            }

    # 4. 执行
    return {
        "decision": "APPROVE",
        "action": action,
        "risk_result": risk_result,
        "rollback_plan_id": change_plan.get("rollback_plan_id"),
        "execution_mode": "auto" if action == "AUTO" else "auto_with_log"
    }
```

#### 4.2 使用示例
```python
# 变更计划
change_plan = {
    "id": "change_20260507_001",
    "description": "A4验证逻辑参数调整",
    "type": "P2",
    "financial_impact": "low",
    "rollback_plan_id": "rollback_abc123",
    "evidence_refs": ["doc_xxx", "lesson_yyy"]
}

# 执行合规审查
result = compliance_review(
    change_description=change_plan["description"],
    change_type=change_plan["type"],
    change_plan=change_plan
)

print(f"审查结果: {result['decision']}")
if result['decision'] == "APPROVE":
    execute_change(change_plan)
elif result['decision'] == "PENDING_HUMAN_REVIEW":
    send_human_review_request(result)
else:
    log_rejection(result)
```

---

### §五、灰度发布

#### 5.1 灰度策略
| 阶段 | 流量比例 | 监控指标 |
|:---|:---:|:---|
| 灰度1% | 1% | 错误率 < 0.1% |
| 灰度10% | 10% | 延迟 < 200ms |
| 灰度50% | 50% | 评分无显著下降 |
| 全量 | 100% | 稳定运行 24h |

#### 5.2 灰度代码
```python
class GradualRollout:
    def __init__(self):
        self.stages = [
            {"name": "1%", "ratio": 0.01},
            {"name": "10%", "ratio": 0.10},
            {"name": "50%", "ratio": 0.50},
            {"name": "100%", "ratio": 1.00}
        ]

    def should_rollout(self, stage_name, metrics):
        """判断是否进入下一阶段"""
        thresholds = {
            "1%": {"error_rate": 0.001, "latency_p99": 500},
            "10%": {"error_rate": 0.001, "latency_p99": 300},
            "50%": {"error_rate": 0.001, "latency_p99": 200},
            "100%": {"error_rate": 0.001, "latency_p99": 200}
        }

        threshold = thresholds.get(stage_name, {})

        for metric, limit in threshold.items():
            if metrics.get(metric, 0) > limit:
                return False, f"{metric} exceeds threshold: {metrics.get(metric)} > {limit}"

        return True, "Metrics OK"
```

---

### §六、审计日志

#### 6.1 审计日志格式
```json
{
  "timestamp": "2026-05-07T10:00:00+08:00",
  "level": "INFO",
  "trace_id": "compliance_20260507_xxx",
  "action": "compliance_review",
  "change_type": "P2",
  "risk_level": "MEDIUM",
  "decision": "APPROVE",
  "actor": "system|human",
  "change_plan_id": "change_xxx"
}
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v2.0 | 2026-05-07 | 增加完整风险评估、影子验证、灰度发布流程 |
| v1.0 | 2026-04-15 | 初始版本 |

---

*本文档是 AI Trading Compliance SKILL 的标准化规范，所有系统变更必须通过合规审查。*
