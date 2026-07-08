---
name: "ai-trading-compliance"
description: "AI 驱动的交易创新合规与治理门禁审查 v2.0 - 可执行版本。对 AI 建议/自动化/策略创新做合规审查并输出 pass/warn/fail。涉及变更包、门禁、灰度发布、回滚、审计时调用。"
license: Internal
version: 2.0.0
---

# AI Trading Compliance v2.0 - 可执行合规门禁

> **现在可以执行！** 运行 `python scripts/run_compliance_check.py <change_bundle.json>` 即可看到效果。

---

## 一、目标 (Goal)

把"AI 的建议/自动化/策略创新"约束在可控闭环内，强制满足：
- **最小权限** (Least Privilege)
- **沙箱验证** (Sandbox Verification)
- **门禁通过** (Gate Pass)
- **审批与灰度** (Approval & Canary)
- **可回滚** (Rollback Ready)
- **可审计** (Auditable)

避免 AI 越权导致生产侧不可控行为。

---

## 二、何时调用 (Trigger Conditions)

当用户提出以下任一诉求时，**必须调用本 SKILL**：

| # | 触发条件 | 示例 |
|:---:|:---|:---|
| 1 | 上线/启用/替换策略 | "启用新策略"、"优化参数后上线" |
| 2 | 生产侧配置键变更 | "修改杠杆阈值"、"调整风控参数" |
| 3 | 引入/扩展外联能力 | "推特发布"、"TG 消息推送" |
| 4 | 设计/调整自动化链路 | "影子闭环"、"自动回滚" |
| 5 | 重要更新/高风险变更 | "发布规范"、"审计回放策略" |

---

## 三、输入 (Input) - change_bundle.json

### 3.1 最小材料集

优先使用"变更包 JSON" (`change_bundle.json`)，若缺失则要求补齐。

**必需字段** (`required`):
```json
{
  "intent": {
    "what": "要做什么 (string)",
    "why": "为什么做 (string)",
    "impact_scope": ["strategy" | "parameter" | "system" | "external" | "automation"]
  },
  "change_type": "R0" | "R1" | "R2" | "R3",
  "risk_level": "P0" | "P1" | "P3"
}
```

**可选字段**:
```json
{
  "doc_refs": ["string"],           // SSoT 文档引用
  "artifacts": {                  // 沙箱输入/输出产物
    "data_snapshot_id": "string",
    "config_version": "string",
    "strategy_key": "string",
    "gating_report": {
      "gate_result": {},
      "baseline_ref": "string"
    }
  },
  "rollout_plan": {               // 灰度发布计划
    "mode": "canary" | "disabled" | "full",
    "canary_percentage": 0-100
  },
  "rollback_plan": {              // 回滚计划
    "rollback_plan_id": "string",
    "rollback_points": ["string"],
    "triggers": ["string"],
    "actions": ["string"]
  },
  "external_publish": {           // 外联发布
    "channel": "string",
    "approval_status": "pending" | "approved" | "rejected"
  },
  "trace_id": "string",
  "parents": ["string"],
  "evidence": ["string"]
}
```

### 3.2 Schema 验证

使用 `schemas/change_bundle_schema.json` 验证输入格式。

---

## 四、输出 (Output) - compliance_receipt.json

合规审查生成的**合规回执**，可直接落审计并驱动后续审批/执行器。

```json
{
  "decision": "pass" | "warn" | "fail",
  "change_classification": {
    "change_type": "R0" | "R1" | "R2" | "R3",
    "risk_level": "P0" | "P1" | "P3",
    "environment": "Explore" | "Pilot" | "Prod",
    "tighten_only": true | false
  },
  "hard_constraints_checked": {
    "prod_write_prohibited_without_approval": true,
    "sandbox_no_network_no_secrets": true,
    "gate_result_present": true,
    "baseline_ref_present": true,
    "rollback_defined": true,
    "audit_replayable": true,
    "external_publish_outbox_only": true
  },
  "blockers": [
    {"id": "B001", "title": "SSoT 引用缺失", "evidence": ""}
  ],
  "warnings": [
    {"id": "W001", "title": "风险扩张型变更", "reason": "需要审批"}
  ],
  "required_actions": [
    {"id": "A001", "title": "补齐三件套", "how": "在沙箱重跑..."}
  ],
  "rollout_requirements": {
    "mode": "canary" | "disabled" | "full",
    "must_monitor": ["pnl", "max_drawdown"],
    "auto_rollback_triggers": ["Hard-Reject"],
    "second_approval_required": true
  },
  "audit_fields": {
    "doc_refs": ["..."],
    "trace_id": "string",
    "artifacts": ["..."],
    "approver_roles": ["risk_owner", "strategy_owner"]
  }
}
```

使用 `schemas/compliance_receipt_schema.json` 验证输出格式。

---

## 五、处理流程 (Process)

### 5.1 完整流程 (7 步)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AI Trading Compliance v2.0                       │
│                        处理流程                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   输入: change_bundle.json                                        │
│         │                                                           │
│         ▼                                                           │
│   ┌─────────────────────┐                                          │
│   │ Step 1: 验证输入   │                                           │
│   └─────────┬───────────┘                                          │
│              │ pass                                                  │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │ Step 2: R0-R3 分级 │ ← r_level_classifier.py                │
│   └─────────┬───────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │ Step 3: 硬门禁检查 │ ← hard_gate_checker.py (9项)          │
│   └─────────┬───────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │ Step 4: 回滚验证   │ ← rollback_validator.py                │
│   └─────────┬───────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │ Step 5: 风险方向   │ ← risk_direction_checker.py             │
│   └─────────┬───────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │ Step 6: 生成决策   │                                           │
│   └─────────┬───────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │ Step 7: 生成回执   │ → compliance_receipt.json              │
│   │        + 写入审计   │ → audit/audit_YYYYMMDD.jsonl          │
│   └─────────────────────┘                                          │
│                                                                     │
│   输出: compliance_receipt.json                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 执行方式

**命令行**:
```bash
python scripts/run_compliance_check.py sample_change_bundle.json
```

**作为 Python 模块**:
```python
from scripts.compliance_engine import ComplianceEngine

engine = ComplianceEngine()
receipt = engine.process(change_bundle)
```

---

## 六、核心检查器

### 6.1 R0-R3 自动分级器 (`r_level_classifier.py`)

| 分类 | 条件 | 说明 |
|:---|:---|:---|
| **R0** | 纯读取/诊断/报告生成 | 只读观测，允许自动执行 |
| **R1** | 配置参数查看/非生产变更 | 允许自动执行但必须可审计 |
| **R2** | 受控变更（配置/灰度/回滚/触发） | 必须审批后才能执行 |
| **R3** | 代码变更（策略逻辑/执行链路） | 禁止直接生效，必须走更严格流程 |

**判定逻辑**:
1. 检查是否涉及 `prod_write`、`external_publish`、`strategy_change`
2. 自动检测变更内容，可能覆盖手动分级
3. 返回更严格的分级

### 6.2 硬门禁检查器 (`hard_gate_checker.py`) - 9 项

| 门禁ID | 检查项 | FAIL 条件 |
|:---|:---|:---|
| H001 | SSoT 引用 | `doc_refs` 为空或不完整 |
| H002 | 可复现性 | 缺少 `data_snapshot_id/config_version/strategy_key` |
| H003 | P3 门禁产物 | 缺少 `gating_report.gate_result` 或 `baseline_ref` |
| H004 | 回滚可执行 | 缺少回滚点或触发条件不可观测 |
| H005 | 密钥不出域 | 输出包含 token/密钥 |
| H006 | 环境隔离 | 沙箱加载真实密钥或实盘下单 |
| H007 | 外联控制 | 未经审批的外联发布 |
| H008 | 风险扩张 | R2/R3 变更存在风险扩张但无人工审批 |
| H009 | Rollback Plan ID | 缺少 `rollback_plan_id` |

**Fail-Closed**: 任一 FAIL → 决策 = `fail`

### 6.3 回滚验证器 (`rollback_validator.py`)

验证项:
1. 回滚点存在且可执行
2. 触发条件可观测（来自指标/告警/执行失败）
3. 回滚动作已定义且幂等
4. 与 `hermes-rollback-actuator` 格式兼容

### 6.4 风险方向检查器 (`risk_direction_checker.py`)

判定变更是**收紧型** (tighten-only) 还是**风险扩张型** (risk expansion):

- **收紧型**: 修复/自动化动作默认为收紧型（止血型），禁止用"放宽门槛/加仓"掩盖问题
- **风险扩张型**: 扩大交易对/杠杆/频率/放宽风控阈值/新增外联发布
  - 必须证明通过更高证据等级的沙箱验证
  - 在 Prod 走人工审批 (risk owner + strategy owner)
  - 先 Canary，再二次审批后扩面

---

## 七、决策规则 (Decision Rules)

### 7.1 决策矩阵

| 条件 | 决策 |
|:---|:---|
| 硬门禁检查 = FAIL | `fail` |
| 回滚验证 = FAIL | `fail` |
| 风险扩张 + 无审批 | `warn` (需要审批) |
| 所有检查通过 | `pass` |

### 7.2 Fail-Closed 原则

**所有治理技能默认失败关闭**，确保安全性:
- 硬门禁检查失败 → 直接 `fail`
- 回滚验证失败 → 直接 `fail`
- 无法判定 → 默认 `fail`

---

## 八、集成方式 (Integration)

### 8.1 三道门机制

```
┌─────────────────────────────────────────────────────────────────────┐
│                        三道门机制                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   任意重要变更触发                                                   │
│         │                                                           │
│         ▼                                                           │
│   ┌──────────────────────┐                                          │
│   │ 第一道门              │ ← ai-trading-compliance (v2.0)         │
│   │ R0-R3分级 + 硬门禁   │                                          │
│   └──────────┬───────────┘                                          │
│              │ pass/warn                                            │
│              ▼                                                      │
│   ┌──────────────────────┐                                          │
│   │ 第二道门              │ ← dream-pretrade-gatekeeper            │
│   │ 交易前门禁           │                                          │
│   └──────────┬───────────┘                                          │
│              │ pass                                                 │
│              ▼                                                      │
│   ┌──────────────────────┐                                          │
│   │ 第三道门              │ ← hermes-shadow-verification-gate      │
│   │ 影子验证             │                                          │
│   └──────────┬───────────┘                                          │
│              │ PASS                                                 │
│              ▼                                                      │
│   ┌──────────────────────┐                                          │
│   │ 执行变更              │                                          │
│   └──────────────────────┘                                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 与现有技能集成

| 技能 | 关系 | 说明 |
|:---|:---|:---|
| **dream-tactical-executor (A5)** | 调用 | 执行前必须通过合规审查 |
| **dream-tactical-validator (A4)** | 调用 | 验证方案必须通过合规审查 |
| **dream-strategy-designer (A3)** | 调用 | 战略设计必须通过合规审查 |
| **hermes-shadow-verification-gate** | 被调用 | 第三道门 |
| **dream-pretrade-gatekeeper** | 被调用 | 第二道门 |
| **dream-governance-manager** | 报告 | 合规审查结果同步到治理部 |
| **boss-secretary** | 投递 | 重要合规报告投递到秘书 |

---

## 九、使用示例 (Usage Examples)

### 9.1 命令行使用

```bash
# 进入技能目录
cd ~/.workbuddy/skills/ai-trading-compliance

# 运行合规审查 (MVP 版本)
python scripts/run_compliance_check.py scripts/sample_change_bundle.json

# 输出:
# ================================================================
# 🚀 开始合规审查...
# ================================================================
# [Step 1/7] 验证输入...
# [Step 2/7] R0-R3 自动分级...
# ...
# 合规回执已保存: scripts/sample_change_bundle_receipt.json
```

### 9.2 Python 模块使用

```python
import sys
from pathlib import Path

# 添加 scripts 目录到路径
scripts_dir = Path(__file__).parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from compliance_engine import ComplianceEngine

# 创建引擎
engine = ComplianceEngine()

# 读取变更包
import json
with open("change_bundle.json", "r") as f:
    change_bundle = json.load(f)

# 执行合规审查
receipt = engine.process(change_bundle)

# 处理合规回执
if receipt["decision"] == "pass":
    print("✅ 合规审查通过，可以进入下一道门")
elif receipt["decision"] == "warn":
    print("⚠️ 合规审查警告，需要审批")
else:
    print("❌ 合规审查失败，禁止上线")
```

### 9.3 作为 SKILL 调用

在 WorkBuddy 对话中:
```
用户: 合规审查这个变更包
助手: → 加载 ai-trading-compliance SKILL
      → 读取 change_bundle.json
      → 执行 7 步审查流程
      → 返回 compliance_receipt.json
```

---

## 十、审计与可追溯 (Audit & Traceability)

### 10.1 审计轨迹存储

所有合规审查结果自动写入审计日志:
```
~/.workbuddy/skills/ai-trading-compliance/audit/
├── audit_20260506.jsonl       # 按日期存储 (JSON Lines 格式)
├── audit_20260507.jsonl
└── ...
```

每条记录包含:
- `audit_id`: 审计 ID
- `timestamp`: 时间戳 (ISO 8601)
- `decision`: 决策 (pass/warn/fail)
- `change_classification`: 变更分类
- `blockers`: 阻断项
- `warnings`: 警告项
- `audit_fields`: 审计字段

### 10.2 查询审计记录

```python
from scripts.audit_trail import AuditTrailManager

manager = AuditTrailManager()

# 查询所有记录
results = manager.query()

# 按决策过滤
pass_results = manager.query(decision="pass")

# 按 trace_id 过滤
trace_results = manager.query(trace_id="trace_20260506_001")

# 获取统计信息
stats = manager.get_statistics()
print(stats)
# {'total_records': 10, 'by_decision': {'pass': 7, 'warn': 2, 'fail': 1}, ...}
```

---

## 十一、文件结构 (File Structure)

```
~/.workbuddy/skills/ai-trading-compliance/
├── SKILL.md                          # 本文件 (v2.0)
├── scripts/                          # 执行脚本
│   ├── __init__.py
│   ├── compliance_engine.py          # 主引擎 (Phase 1)
│   ├── r_level_classifier.py         # R0-R3 分级器 (Phase 1)
│   ├── hard_gate_checker.py         # 硬门禁检查器 (Phase 1)
│   ├── rollback_validator.py        # 回滚验证器 (Phase 1)
│   ├── risk_direction_checker.py   # 风险方向检查器 (Phase 1)
│   ├── audit_trail.py               # 审计轨迹管理器 (Phase 1)
│   ├── run_compliance_check.py     # MVP 可运行版本 (立即演示)
│   └── sample_change_bundle.json   # 示例变更包
├── schemas/                         # JSON Schema
│   ├── __init__.py
│   ├── change_bundle_schema.json    # 变更包 Schema
│   └── compliance_receipt_schema.json  # 合规回执 Schema
├── audit/                           # 审计日志存储
│   └── audit_YYYYMMDD.jsonl
└── PLAN.md                          # 实施计划
```

---

## 十二、宪法绑定 (Constitution Binding)

### 12.1 宪法 §14 (待新增)

在 `dream-constitution/SKILL.md` 新增 §14:

```markdown
## 第十四章：重要变更合规审查 (v2.0 新增)

### 14.1 强制审查原则

规则 14.1.1: 任何重要变更（定义见 ai-trading-compliance R0-R3 分级）
             必须先通过 ai-trading-compliance 审查

规则 14.1.2: 合规审查不通过 → 变更禁止上线

规则 14.1.3: 合规回执必须归档到审计系统

规则 14.1.4: 变更分级由 ai-trading-compliance 自动判定，可覆盖手动分级

### 14.2 三道门机制

规则 14.2.1: 重要变更必须依次通过三道门：
             第一道 → ai-trading-compliance (合规审查)
             第二道 → dream-pretrade-gatekeeper (交易前门禁)
             第三道 → hermes-shadow-verification-gate (影子验证)

规则 14.2.2: 任意一道门拒绝 → 变更禁止进入下一道门

### 14.3 审计与回滚

规则 14.3.1: 所有合规审查结果必须记录到审计轨迹

规则 14.3.2: 重要变更必须提供 rollback_plan_id
```

---

## 十三、开发状态 (Development Status)

### 13.1 Phase 1 - 基础架构 (✅ 已完成 - 2026-05-06)

- [x] 创建目录结构
- [x] 定义 change_bundle_schema.json
- [x] 定义 compliance_receipt_schema.json
- [x] 创建 compliance_engine.py 主框架
- [x] 创建 r_level_classifier.py 分级器 (框架)
- [x] 创建 hard_gate_checker.py 硬门禁检查器 (框架)
- [x] 创建 rollback_validator.py 回滚验证器 (框架)
- [x] 创建 risk_direction_checker.py 风险方向检查器 (框架)
- [x] 创建 audit_trail.py 审计轨迹管理器 (框架)
- [x] 创建 run_compliance_check.py MVP 可运行版本
- [x] 创建 sample_change_bundle.json 示例
- [x] 测试 MVP 版本 (通过)

### 13.2 Phase 2 - 核心检查器 (⏳ 待开发)

- [ ] 完善 r_level_classifier.py 自动分级逻辑
- [ ] 完善 hard_gate_checker.py 9项硬门禁检查
- [ ] 完善 rollback_validator.py 回滚验证
- [ ] 完善 risk_direction_checker.py 风险方向判定
- [ ] 实现 JSON Schema 验证
- [ ] 单元测试

### 13.3 Phase 3 - 集成与测试 (⏳ 待开发)

- [ ] 与 hermes-shadow-verification-gate 集成
- [ ] 与 dream-pretrade-gatekeeper 集成
- [ ] 与 dream-governance-manager 集成
- [ ] 端到端测试

### 13.4 Phase 4 - 宪法绑定 (⏳ 待开发)

- [ ] 宪法新增 §14
- [ ] 更新 SKILL.md v2.0 (本文件)
- [ ] 集成文档完善

---

## 十四、FAQ (Frequently Asked Questions)

### Q1: 这个 SKILL 和 dream-pretrade-gatekeeper 有什么区别？

**A**: 职责分工不同:
- `ai-trading-compliance`: 审查"变更本身"的合规性 (策略/参数/外联/自动化)
- `dream-pretrade-gatekeeper`: 审查"单笔交易"的合规性 (数据完整性/杠杆/战略/评分)

简单说: 前者审查"规则变更"，后者审查"规则执行"。

### Q2: 如何判断变更是 R0-R3 哪一级？

**A**: 有两个方式:
1. **手动指定**: 在 `change_bundle.json` 中设置 `"change_type": "R2"`
2. **自动分级**: 引擎会自动检测变更内容，可能覆盖手动分级 (更严格)

### Q3: 合规审查失败了怎么办？

**A**: 查看 `compliance_receipt.json` 中的 `blockers` 和 `required_actions`:
1. 修复 blockers 中列出的问题
2. 执行 required_actions 中列出的动作
3. 重新运行合规审查

### Q4: 如何集成到现有 A1-A7 链路？

**A**: 在 A3/A4/A5 执行前添加合规审查步骤:
```python
# A5 执行前
receipt = compliance_engine.process(change_bundle)
if receipt["decision"] != "pass":
    # 禁止执行，返回合规回执
    return receipt
# 通过合规审查，继续执行业务逻辑
```

---

## 十五、更新日志 (Changelog)

### v2.0.0 (2026-05-06) - 可执行化改造

- ✅ 新增 `scripts/` 目录，包含 6 个 Python 脚本
- ✅ 新增 `schemas/` 目录，定义输入/输出 JSON Schema
- ✅ 新增 `audit/` 目录，存储审计轨迹
- ✅ 新增 MVP 可运行版本 (`run_compliance_check.py`)
- ✅ 新增示例使用说明和示例变更包
- ✅ 新增三道门机制说明
- ✅ 新增宪法 §14 绑定计划
- ✅ 从"纸面合规"进化为"可执行、可验证、可审计"

### v1.0.0 (未知日期) - 初始版本

- ✅ 定义合规审查框架
- ✅ 定义输入/输出格式
- ❌ 缺少执行脚本 (纸面合规)

---

**最后更新**: 2026-05-06
**维护者**: 治理管理部
**版本**: v2.0.0 (可执行版本)
