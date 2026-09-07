# Phase 1：引入 Hermes 四角色进化循环 设计文档

> 创建：2026-09-01 | 状态：Draft（待用户review）| 依据：EVOLUTION_BOUNDARY_MAP.md v1.0 §1-5 + Hermes v7.3.0 4角色Cron + VOYAGER 5维自评 + 宪法提案制

---

## 0. 变更摘要与范围

### 0.1 目标
Phase 0 已打通 **C 类（RAG↔认知桥接）verify + annotate 接线** 和 **E 类（调控参数进化）独立 cron**。本阶段在 **B 类（认知流程+Solution Path）** 层引入 Hermes 三核心架构：
1. **EV-T1 四角色 Cron**：Evolution（每12H，DeepSeek-R1 强推理提案）/ Critic（每24H，qwq-32B 怀疑型批评 + **强制宪法校验**）/ Verifier（每6H，保守回测规则为主）/ Gardener（每周一 02:00，修剪）。模型多样性隔离防确认偏误。
2. **EV-T2 宪法自动化**：将 EVOLUTION_BOUNDARY_MAP.md 的 6+2 条红线编码为 `constitution.py` 8 个 `check_*` 函数 + 1 个 `audit_proposal()` 总入口 + PROP-*.md 解析器，Critic 阶段先过宪法再批评。
3. **EV-T3 VOYAGER 模式提取**：`cognitive_loop_entry.record()` 注入 5 维自评（完整性/准确性/效率/深度/可操作性），`verify(success=True)` 对同一 domain+tags 分组连续3次成功且 overall≥0.7 → 自动生成 `APP-DEV-AUTO-*`/`APP-TRD-AUTO-*` 草案到**审核队列**（不直接进正式 solution_paths/，不自动采纳）。

### 0.2 严格遵守 AB 边界（B 类范围内）
- 改动文件全部在 `4-MEMORY/9-工具与接口/`（B 类，符合边界图§3第3条）
- **不触碰**：`11-易经推理系统/`（A类）、`0-元记忆/**/skills/**/SKILL.md`（通用认知原版，红线①）、`3-EVOLUTION/`（实验区，红线⑦）
- B↔A 交互只通过 `4-MEMORY/` 记忆系统（红线⑤），无直接 import 或改 config.json

### 0.3 新增文件清单（不删不改既有，只增）
| 文件 | 职责 | EV-T? |
|:---|:---|:---|
| `4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py` | 四角色 Cron 主入口 | T1 |
| `4-MEMORY/9-工具与接口/constitution.py` | 8 条红线 + PROP.md 解析器 | T2 |
| `4-MEMORY/9-工具与接口/tests/test_phase1_hermes_t1_t2_t3.py` | 3 组 TCs（TDD：先写失败测试） | 全部 |
| `4-MEMORY/artifacts/evolution_pipeline/`（运行时创建） | 四角色状态文件 PROPOSED/CRITIQUED/VALIDATED/APPLIED | T1 |
| `4-MEMORY/artifacts/solution_path_drafts/review_queue/`（运行时创建） | AUTO 草案审核队列 + index | T3 |
| `4-MEMORY/artifacts/voyager_consecutive.jsonl`（运行时创建） | verify 流水，连续成功计数 | T3 |
| `com.dreambuddy.cognitive-evolution.plist`（T1脚本头部内嵌） | launchd 注册说明 + 4 条独立 StartCalendarInterval | T1 |

### 0.4 扩展现有文件（向后字节等价，仅加新关键字参数）
| 文件 | 扩展点 |
|:---|:---|
| `cognitive_loop_entry.py` → `record()` | 加 keyword-only `domain / voyager_scores / enable_voyager_auto`；内部写入 bayesian_memories 扩展字段 voyager_scores |
| `cognitive_loop_entry.py` → `verify()` | 返回结构新增 `voyager` 子键（10字段），触发 3 次连续成功 → AUTO 草案 |

---

## 1. EV-T1 四角色 Cron 框架详解

### 1.1 调度周期与模型多样性

| 角色 | 周期 | 时间（UTC+8）| 模型角色 | LLM 不可用时的降级规则 |
|:---|:---|:---|:---|:---|
| Evolution（提案者） | 每12H | 08:00, 20:00 | DeepSeek-R1：强推理，生成提案（prompt优化/流程补洞/反模式识别/记忆结构升级）| 按最近 7 天 `bayesian_memories.json` 中 quality≥B 且 verify_count≥3 的 domain+tags 聚类，生成"增量重申类小提案"（模板填充），至少产出 N=min(3, 已聚类数) 提案避免空转 |
| Critic（批评者） | 每24H | 23:30 | qwq-32B：怀疑型，构造反例/压力测试/**先强制过宪法** | 只跑宪法 check_* + 规则批评（含重复提案检测/引用文件不在 touched_files）|
| Verifier（验证者） | 每6H | 00/06/12/18 整点 | 保守：**规则+回测 80% 权重**（通过 cognitive_backtest 对 P1/P2/P3 跑 replay），必要时模型打分 20% | 只跑回测 replay，不做模型打分 |
| Gardener（修剪者） | 每周 | 周一 02:00 | 规则（不调模型）| 规则删除/合并/归档：① verify_count=0 且 >30d 的 C/D 级记忆 ② domain+tags Jaccard≥0.8 重复 Solution Path 合并 ③ PROP 归档 |

**防确认偏误机制**：
- Evolution 与 Critic 绝不同模型（R1 vs qwq-32B），且不共享 prompt 缓存
- Verifier 不读 Evolution/Critic 的文字论证，只读：提案影响的 `touched_files` + 要改变的字段值 → 回测客观指标
- 三者 proposal_id 关联但各自状态文件独立命名

### 1.2 CLI 与参数

```bash
python 4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py \
  [--role {evolution,critic,verifier,gardener,all}]   # 默认 all（按当前时间智能挑，单角色模式用于测试）
  [--dry-run]                                          # 禁止写 APPLIED + 禁止 Gardener 删除 + 禁止 Verifier 写回质量
  [--work-dir PATH]                                    # 默认 4-MEMORY/artifacts/evolution_pipeline/
  [--report-json PATH]                                 # 输出结构化报告
  [--no-llm]                                           # 强制走规则分支（CI、离线环境）
  [--max-proposals N]                                  # Evolution 限制提案上限（默认 10，dry-run 下默认 3）
  [--help]
```

### 1.3 状态机与管道文件

```
（Evolution输出） PROPOSED/<proposal_id>.json = {
  id, ts, actor="evolution", category（prompt/solution_path/memory_structure/反模式）,
  touched_files, proposed_changes_by_path, rationale, proposed_model_confidence, voyager_scores
}
    │
    ▼ Critic 读取所有未审计的 PROPOSED → 宪法先验
（Critic输出）  CRITIQUED/<proposal_id>.json = {
  id, ts, actor="critic", constitution_audit={passed, rule_results, violations},
  criticism（压力测试/反例/缺失证据）, critique_passed: bool
}
    │ 只有 constitution_audit.passed=True AND critique_passed=True → 进入 Verifier
    ▼
（Verifier输出）VALIDATED/<proposal_id>.json = {
  id, ts, actor="verifier", backtest_reports_by_scope,
  validation_passed: bool, adopted_delta（若可直接patch）, validation_confidence
}
    │ validation_passed=True AND backtest_winrate≥基线+1% AND max_drawdown≤基线
    ▼
（Gardener或下轮Evolution在 ALL 模式时执行APPLY）
                 APPLIED/<proposal_id>.json = {
  id, ts, applied_at, applied_by, files_written, rollback_token（vc_commit id 用于回滚）
}
```
- 单阶段失败提案 → `REJECTED/<proposal_id>.json`，原因归档，不删除（可审计）。
- `--dry-run` 下 **不会出现 APPLIED/** 目录（或写入但最后原子性删除）。

### 1.4 launchd 注册（脚本头部内嵌注释，模板附）

plist 4条 `StartCalendarInterval`（四角色在同一进程内按命令行参数路由分别调用，**不并跑**，防止写冲突）：
```xml
<key>ProgramArguments</key>
<array>
  <string>/bin/bash</string><string>-lc</string>
  <string>cd /path &amp;&amp; /usr/bin/python3 4-MEMORY/9-工具与接口/cognitive_evolution_scheduler.py --role auto --report-json logs/cognitive_evolution.json &gt;&gt; logs/cognitive_evolution_cron.log 2&gt;&amp;1</string>
</array>
<key>StartCalendarInterval</key>
<array>
  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>  <!-- Evolution 08:00 -->
  <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict> <!-- Verifier 12:00 -->
  <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict> <!-- Verifier 18:00 -->
  <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict> <!-- Evolution 20:00 -->
  <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict><!-- Critic 23:30 -->
  <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>0</integer></dict>  <!-- Verifier 00:00 -->
  <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>  <!-- Verifier 06:00 -->
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict> <!-- Gardener 周一 02:00 -->
</array>
```
`--role auto` 模式：脚本按当前时间匹配最近的触发窗口执行对应角色；不匹配则 skip，exit 0。

---

## 2. EV-T2 宪法自动化详解（constitution.py）

### 2.1 红线 ↔ check_* 函数映射

来源：EVOLUTION_BOUNDARY_MAP.md §2.2 红线 + §4 禁止 + §5 检查清单，共计 8 条：

| # | 红线原文 | 函数签名 | severity（违反等级） |
|:---|:---|:---|:---|
| R1 | 通用认知原版 SKILL.md 禁改（L59 **原版内容禁改**） | `check_original_skill_immutable(touched_paths: Set[str]) -> RuleResult` | **CRITICAL**（直接 fail 提案） |
| R2 | 应用认知等级由验证驱动，不手工改（L60） | `check_solution_path_quality_driven(write_patch_by_path: Dict[str, Dict]) -> RuleResult` | HIGH |
| R3 | A类代码不直接写 solution_paths/（L111） | `check_ab_boundary(actor: "A"\|"B", written_paths: Set[str]) -> RuleResult`（actor=A） | **CRITICAL** |
| R4 | B类代码不直接改 config.json 交易参数（L111） | `check_ab_boundary(actor="B", written_paths=...)` | **CRITICAL** |
| R5 | AB 交互只走记忆系统通道（L120 / §4 图） | `check_only_memory_channel_interaction(import_graph: Dict[str,Set[str]]) -> RuleResult` | HIGH |
| R6 | B类修改范围：`4-MEMORY/9-工具与接口/`（L119） | `check_b_mod_scope(touched_paths: Set[str]) -> RuleResult` | HIGH |
| R7 | 3-EVOLUTION/ 是实验区，不放生产改动（L121） | `check_experiment_zone_isolation(touched_paths, is_production_change: bool) -> RuleResult` | HIGH（生产部署标记时升为 CRITICAL） |
| R8 | trading 类 PROP 须走飞书审批（§1 A类提案治理） | `check_proposal_gating(proposal: Dict) -> RuleResult`（category∈{trading_params, trading_risk}） | **CRITICAL** |
| R9*| AUTO 草案未审核不得升入正式 Solution Path（T3写保护2）| `check_auto_draft_not_promoted_without_review(promoted_patch: Dict) -> RuleResult` | **CRITICAL** |

> R9 为 Phase1 新增条款（随宪法 v1.1 加严，遵循宪法本身"只增不改"）

### 2.2 统一数据结构 RuleResult / AuditResult

```python
@dataclass
class Violation:
    rule_id: str            # "R1".."R9"
    severity: str           # CRITICAL / HIGH / MEDIUM / LOW
    file: Optional[str]
    reason: str

@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    violations: List[Violation]

@dataclass
class AuditResult:
    passed: bool                      # 任何 CRITICAL 违规 → False
    proposal_id: str
    rule_results: Dict[str, RuleResult]
    total_violations: int
    severity_counts: Dict[str, int]   # CRITICAL/HIGH/MEDIUM/LOW 计数
    audit_score: float                # 100 - Σ(severity_weight)，用于排序
    constitution_version: str         # "v1.1"
    constitution_hash: str            # 宪法核心字节 hash（防篡改检测）
```

### 2.3 顶部入口

```python
def audit_proposal(
    proposal: Dict[str, Any],
    *,
    import_graph: Optional[Dict[str, Set[str]]] = None,  # R5 需要（可选，不提供则 MEDIUM WARNING 不阻塞）
    proposal_source: str = "PROP-MD",
) -> AuditResult:
```

执行顺序：R1 → R7 → R6 → R3/R4 → R5 → R2 → R8 → R9。按"立即阻塞型先验"排序，尽早发现 CRITICAL。

### 2.4 PROP-*.md 解析器 `parse_proposal_md(md_text_or_path) -> proposal_dict`

解析 section（严格大小写不敏感匹配标题前缀）：
- `# Proposal / # 提案 / ## PROP-` 头部 → 提取 PROP-ID、标题
- `## Scope / 范围 / 变更范围` → actor（A/B，按路径自动归类）、category
- `## Files Touched / 改动文件` → 正则抽取路径，set 去重
- `## Proposed Changes / 变更内容 / ## Diff` → proposed_changes_by_path（按文件标题拆）
- `## Approval / 审批状态` → approvals（"飞书审批单号/审批人/状态"）
- 缺失 section → 填默认值 `_unparsed_section_X`，记 MEDIUM violation，但不 crash（FAIL-OPEN）

### 2.5 宪法自校验（防篡改）

`CONSTITUTION_CORE = (R1..R9 check_* 函数字节流 shasum 计算) + CONSTITUTION_VERSION = "v1.1"`

- 运行每次 `audit_proposal()` 开头对 `R1..R9` 源函数字节重算 hash，与文件顶部常量比对
- 不匹配 → WARNING 写入 AuditResult（不阻塞，否则改宪法本身也会被卡住），但在 Gardener 会生成"宪法漂移审计告警"并推进 Lark alert

---

## 3. EV-T3 VOYAGER 5维自评 + AUTO 草案提取

### 3.1 record() 扩展（向后字节等价，关键字参数保护）

```python
def record(
    self,
    content: str,
    quality_level: str = "C",
    confidence: float = 0.3,
    tags: Optional[List[str]] = None,
    source: str = "trae",
    memory_type: str = "experience",
    *,                                                # keyword-only barrier（防止老代码误传）
    domain: Optional[str] = None,                     # 新：领域标签，如"backtest"/"strategy-research"/"debug"/"cognitive-setup"
    voyager_scores: Optional[Dict[str, float]] = None,# 新：外部（Hermes/Evolution）提供的评分
    enable_voyager_auto: bool = True,                 # 新：None时是否用规则打基础分（默认True）
) -> str:
```

**评分公式（5维 × 权重）**：
| 维度 | 权重 | auto 规则打分（缺 voyager_scores 时）|
|:---|:---|:---|
| completeness 完整性 | 0.20 | "文件/步骤/原因" 三类关键词命中数：0→0/1→0.3/2→0.7/3→1.0 |
| accuracy 准确性 | 0.25 | +0.3 if "验证/passed/✓" 命中；+0.2 if source=git-post-commit；+0.3 if verify_count≥3 已有；上限1.0 |
| efficiency 效率 | 0.15 | content 字符 <500→1.0；每+500→−0.1；下限0.2 |
| depth 深度 | 0.20 | +0.3 if "根因/反模式/为什么/root cause"；+0.4 if 命中不同文件路径≥3；上限1.0 |
| actionability 可操作性 | 0.20 | +0.4 if "步骤/Step/1./①"有序列表标记；+0.3 if 包含 `*/*.py` 路径；上限1.0 |
| **overall** | Σ | = 加权求和，保留 4 位小数 |

写入 bayesian_memories.json 的每条记忆（在其 dict 中新增 `voyager_scores: {C,A,E,D,Ac,overall}` 扩展字段）；同时也写入 memory mapping JSON。

### 3.2 verify() 扩展

返回结构不变，**新增子键 `voyager`**（老消费者忽略即可，字节等价向前兼容）：

```python
{
  ... 原字段 ...
  "voyager": {
    "memory_id": str,
    "domain": str,                         # 从bayesian记忆中取
    "tags": List[str],
    "voyager_overall": float,              # 本记忆的overall
    "consecutive_positive_count": int,     # 同 domain+tags 下连续 success=True 次数（失败重置为0）
    "meets_draft_threshold": bool,         # consecutive≥3 AND overall≥0.7
    "auto_draft_generated": bool,          # 本轮是否生成了草案（去重后）
    "draft_id": Optional[str],             # APP-*-AUTO-<ts>
    "draft_path": Optional[str],           # 审核队列的完整路径
  }
}
```

**连续成功计数器的持久化**：`4-MEMORY/artifacts/voyager_consecutive.jsonl`（每次 verify 追加一行 `{ts, memory_id, domain, tags, success, voyager_overall}`）。GROUP BY domain+tags 按 ts 倒序取最近 N 条 rolling 判定，**避免直接改 bayesian_memories.json 造成并发写冲突**。

### 3.3 AUTO 草案生成（审核队列，不进正式）

**触发**：`meets_draft_threshold=True` 且审核队列过去 7 天**无**同 domain+tags 的未审核重复草案（去重），则生成。

**命名规则**：
- tags 含 `trading/backtest/execution/strategy/pnl/夏普/回撤/okx/polling` 任一 → 前缀 `APP-TRD-AUTO-<epoch_ms>`
- 其他 → 前缀 `APP-DEV-AUTO-<epoch_ms>`

**存储**：
```
4-MEMORY/artifacts/solution_path_drafts/
  ├── review_queue/
  │   ├── APP-DEV-AUTO-1788199900001.json
  │   ├── APP-TRD-AUTO-1788199900002.json
  │   └── ...
  └── review_queue_index.json          # 人工审核时用的聚合索引
```

**草案 JSON 结构**（与正式 APP-TRD-* 完全同构，可审核后复制进 `solution_paths/`）：
```json
{
  "template_id": "APP-TRD-AUTO-1788199900001",
  "name": "AUTO DRAFT: <domain>/<tag1,tag2> 连续验证路径",
  "steps": ["<从base_memories抽取前4高频操作>"],
  "description": "<聚合3条base记忆的content摘要，≤280字>",
  "confidence": 0.3,
  "verify_count": 0,
  "quality_level": "C",
  "source": "voyager-auto-draft",
  "tags": ["solution_path", "auto-draft", "review-required", ...原tags...],
  "layer": "applied",
  "parent_template_id": "t?-" + (从tag映射最接近的父skill，t1/t2/debug-skills等，匹配不到标记"none"),
  "metadata": {
    "auto_generated": true,
    "base_memory_ids": ["VM-xxx", "VM-yyy", "VM-zzz"],
    "base_voyager_avg_overall": 0.78,
    "draft_created_at": 1788199900,
    "review_status": "PENDING",                 # PENDING/APPROVED/REJECTED
    "reviewed_by": null,
    "reviewed_at": null,
    "domain": "...",
    "consecutive_positive_count": 3,
  }
}
```

**写保护双保险**：
1. 目录保护：草案永远不写 `4-MEMORY/*-记忆单元/solution_paths/`（由绝对路径白名单在 constitution R9 中校验）
2. 字段保护：`confidence 恒=0.3`、`quality_level 恒=C`、`review_status!=APPROVED` 的 JSON 若被工具误写入正式目录 → constitution R9 会在下轮 Critic 中 FAIL CRITICAL

---

## 4. 验收标准（TDD用例）

### 4.1 EV-T1 TC 清单（test_phase1_* TestEVT1Scheduler，≥6 TC）

| TC# | 场景 | 断言 |
|:---|:---|:---|
| t01 | CLI --help 包含 evolution/critic/verifier/gardener/all/auto/dry-run/no-llm/max-proposals 参数 | 关键字在 stdout |
| t02 | --role evolution --dry-run --no-llm --max-proposals 3 → 生成 3 PROPOSED 文件且非空 | 数量 + 字段结构 + 无 APPLIED 目录生成 |
| t03 | --role critic 读 PROPOSED → CRITIQUED；**含 R1 违规（touched_files=/*/SKILL.md）** → critique_passed=False + constitution_audit.passed=False + R1 CRITICAL violation 存在 | 红线拦截正确 |
| t04 | --role verifier 读 1 个已过 Critic 的 proposal → VALIDATED；--no-llm 下 validation_passed 只看规则（模型没调，不 crash）| FAIL-OPEN |
| t05 | --role gardener --dry-run → 不执行删除（只生成"待修剪列表JSON"），exit=0 | 空跑安全 |
| t06 | plist 模板包含 8 条 StartCalendarInterval（4角色对应时间点）+ Gardener Weekday=1 | 关键字匹配 |
| t07（可选）| 单 --role auto 当前时间匹配 → 执行对应角色（模拟 system time）| 角色选择逻辑正确 |

### 4.2 EV-T2 TC 清单（TestEVT2Constitution，≥7 TC）

| TC# | 场景 | 断言 |
|:---|:---|:---|
| t10 | R1 触发：`touched_files={"0-元记忆/superpowers/skills/brainstorming/SKILL.md"}` → RuleResult CRITICAL + AuditResult.passed=False | 红线拦截 |
| t11 | R3 触发：actor=A 写了 `2-交易记忆单元/solution_paths/APP-TRD-*.json` → R3 CRITICAL | AB边界正确 |
| t12 | R4 触发：actor=B 写了 `experiments/ab-trading/data/config.json` → R4 CRITICAL | AB边界正确 |
| t13 | R7 触发：`touched_files={"3-EVOLUTION/pipeline.ts"}` + is_production_change=True → R7 CRITICAL；is_production_change=False → R7 HIGH 但仍 overall passed | severity 正确 |
| t14 | R9 触发：将 review_queue 里 AUTO draft 误移入正式目录 且 review_status=PENDING → R9 CRITICAL | 自动草案写保护 |
| t15 | parse_proposal_md：解析示例 PROP-xxx.md（含 Files Touched + Approval 两段）→ 正确提取 touched_files set + approvals dict | PROP解析正确 |
| t16 | 宪法自校验：patch R1 函数 1 字节 → audit_proposal() WARNING 写入 AuditResult.constitution_mismatch=True 但不阻塞流程（FAIL-OPEN）| 宪法漂移告警但不卡 |

### 4.3 EV-T3 TC 清单（TestEVT3Voyager，≥7 TC）

| TC# | 场景 | 断言 |
|:---|:---|:---|
| t20 | record(..., domain="debug", voyager_scores=None) → bayesian_memories 对应记忆项 voyager_scores.overall=Σ(权重×auto分) | 规则自动打分 |
| t21 | record(..., voyager_scores={completeness:1,accuracy:1,efficiency:1,depth:1,actionability:1}) → overall=1.0（不触发auto，使用显式）| 显式优先 |
| t22 | verify() 对 domain+tags="debug/[fix,bug]" 连续注入 3 次 success=True + overall≥0.7 → 返回 voyager.meets_draft_threshold=True，draft_path 在 review_queue/ 且 draft_id 含 APP-DEV-AUTO- | 生成草案正确 |
| t23 | 上一场景后再 verify 1 次相同 domain+tags（即第4次成功，过去7天已有同 domain+tags 的 PENDING 草案）→ auto_draft_generated=False（去重）| 7天去重 |
| t24 | review_queue/ 里 AUTO draft 的 JSON：confidence=0.3，quality_level="C"，metadata.review_status="PENDING"，metadata.base_memory_ids 恰好 3 项 | 严格降级，不污染正式 |
| t25 | verify() 中间插入 1 次 success=False → consecutive_positive_count 重置为 0，即使后续再 2 次 success 也 =2，不触发草案 | 失败重置正确 |
| t26 | bayesian_memories 中 voyager_scores 字段缺失（老记忆）→ verify 不 crash（FAIL-OPEN，consecutive_count 用记忆 confidence*verify_count 近似估计 overall）| 老记忆兼容 |

---

## 5. 风险与回滚

| 风险 | 缓解 | 回滚 |
|:---|:---|:---|
| 宪法过严导致正常修改被误杀 | CRITICAL 仅 R1/R3/R4/R8/R9 5 条；其余 HIGH/MEDIUM 只记不阻；AuditResult 可人工 override | 临时 patch `audit_proposal()` 加一行 `force_whitelist_ids={"PROP-xxxx..."}`，后续提案制化 |
| Evolution 提案爆量，磁盘占用 | --max-proposals 默认 10；Gardener 每月清理 30 天前已 REJECTED 的状态文件 | 删除 `artifacts/evolution_pipeline/*/` 即可，不影响核心记忆 |
| VOYAGER auto 评分整体偏高（全 >0.7 泛滥草案）| 提高门槛（overall≥0.7→≥0.8）或连续成功 3→5；或按 weekly draft 上限 N=20 节流 | 清空 review_queue/ 重设 jsonl 连续计数文件 |
| LLM API 费用激增 | --no-llm 默认给离线用；每角色默认每次调用 ≤5 提案；按配额写文件节流 | 切换 --no-llm；删 LLM 配置 env 即可自动降级 |
| Gardener 误删记忆 | --dry-run 默认 Gardener 只 print 清单，不删；真实删除前 backup 到 .trash/；vc_commit 先留痕 | `vc_rollback` + `.trash/` 恢复 |

---

**End of Draft**
