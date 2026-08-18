# Grok Build 借鉴集成设计 · P0 阶段

> **文档版本**：v1.0
> **创建日期**：2026-07-22
> **作者**：dreambuddy-v2
> **状态**：待评审
> **适用范围**：易经推理模型 + Dream OS
> **验证手段**：仅回测验证

---

## 1. 背景与目标

### 1.1 背景

xAI 于 2026-07 开源了 [grok-build](https://github.com/xai-org/grok-build) —— 一个编码领域的 agent harness（agent loop 外面那层壳）。开源的是壳，不是模型。

经过架构对照分析，grok-build 与本项目的 Dream OS / 易经推理系统高度同构：
- **Grok Build** 造的是「编码领域的 harness」
- **本项目** 造的是「交易/推理领域的 harness」

两者面临同样的核心问题：agent loop 的可观测性、context 管理、技能生态扩展。因此参考价值大，但因为语言（Rust vs Python）和领域（编码 vs 交易）差异，**不能直接搬代码，只借鉴架构思想**。

### 1.2 借鉴范围（P0）

经过评估，本项目当前阶段最需要、且能通过回测验证的借鉴点有三个：

| 借鉴点 | 来源概念 | 本项目对应物 | 优先级 |
|:---|:---|:---|:---|
| inspect 诊断命令 | grok inspect | yijing_monitor 扩展 | 高 |
| CBR 分片检索 | 子 Agent 窄 context 并行探 | CBREngine.retrieve | 高 |
| SKILL.md 兼容导入 | 读 Claude/Cursor MCP 配置 | SkillEngine + NodeRegistry | 中 |

P1/P2 阶段（Plan-Do 模式、harness/模型解耦、子 Agent 并行检索）暂缓，等实盘稳定、数据积累足够后再推进。

### 1.3 设计原则

- **纯新增，不侵入**：三个组件各自独立，通过现有接口接入，不修改任何已有交易逻辑
- **可回测验证**：每个组件都有独立的量化验证指标，不依赖实盘
- **渐进式落地**：按 inspect → CBR 分片 → SKILL 导入顺序推进，每步验证后再做下一步

### 1.4 不做的事

- 不移植 Rust harness 到 Python
- 不照搬编码 agent 的工具集（file edit / terminal / search 对交易无意义）
- 不重写现有 agent loop 架构
- 不引入新的外部依赖（仅用项目已有的 numpy/pandas/lightgbm 等）

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    P0 借鉴层（新增）                         │
├─────────────┬───────────────────┬───────────────────────────┤
│  inspect    │  CBR 分片检索     │  SKILL.md 兼容导入        │
│  诊断命令   │  ShardedRetriever │  SkillImporter            │
├─────────────┴───────────────────┴───────────────────────────┤
│                    现有系统（不动）                           │
│  yijing_monitor  │  CBREngine  │  SkillEngine / NodeRegistry│
└─────────────────────────────────────────────────────────────┘
```

**新增模块清单**：

| 模块 | 文件路径 | 依赖的现有模块 |
|:---|:---|:---|
| inspect 诊断命令 | `scripts/memory_l4/inspect.py` | yijing_monitor, polling_trader, kg_store, cbr_engine |
| CBR 分片检索 | `scripts/memory_l4/cbr_sharded_retriever.py` | cbr_engine, cbr_similarity |
| SKILL.md 导入器 | `scripts/skill_importer.py` | skill_engine, NodeRegistry, CapabilityRegistry |

---

## 3. 组件 1：inspect 诊断命令

### 3.1 动机

借鉴 grok-build 的 `grok inspect` 命令——把系统内部状态一次性摊开，快速定位问题。

最近修复的 CBR `price` 变量未定义 bug、`tracker_pos` 未定义 bug，都是「运行时才发现状态错」。如果启动前有个 `inspect` 命令扫一遍，这类问题可以提前发现。

### 3.2 设计

#### 3.2.1 CLI 入口

```bash
# 完整诊断（8 个面板全检查）
python -m scripts.memory_l4.inspect

# 摘要模式（一行一个面板，适合 cron 巡检）
python -m scripts.memory_l4.inspect --brief

# JSON 输出（供脚本消费，如 yijing_monitor 调用）
python -m scripts.memory_l4.inspect --json

# 持续监控（每 60 秒刷新一次，类似 top）
python -m scripts.memory_l4.inspect --watch 60

# 只检查指定面板
python -m scripts.memory_l4.inspect --panels system,positions,knowledge
```

#### 3.2.2 诊断面板

共 8 个面板，每个面板返回 `PanelResult(status, summary, details)`，status 取值为 `ok / warn / error`。

| 面板 ID | 名称 | 检查项 | 失败判定 |
|:---|:---|:---|:---|
| `system` | 🏛️ 系统状态 | 心跳时间、PID、运行时长、cycle 数 | 心跳 > 30min 超时 → error |
| `positions` | 💼 持仓状态 | 本地持仓数、OKX 持仓数、逐项对比 | 本地 ≠ OKX → error |
| `knowledge` | 📦 知识状态 | L4 案例数、CBR 案例数、KG 三元组数、索引更新时间 | CBR 案例 < 10 → warn；索引 > 24h → warn |
| `models` | 🧠 模型状态 | BCRM2 模型文件存在性、L1/L2 样本数、训练时间 | 模型缺失 → error；样本 < 50 → warn |
| `skills` | ⚙️ 技能状态 | SkillsRegistry 注册数、SKILL.md 解析数、失败列表 | 解析失败 > 0 → warn |
| `risk` | 💰 风控状态 | 今日盈亏、连续亏损、是否熔断、仓位比例 | 交易被 halt → error |
| `connections` | 🔗 连接状态 | OKX API 连通性、飞书连通性、SQLite 连通性 | 任一失败 → error |
| `alerts` | ⚠️ 最近告警 | 最近 10 条 WARN/ERROR 日志 | — |

#### 3.2.3 核心类设计

```python
# scripts/memory_l4/inspect.py

@dataclass
class PanelResult:
    panel_id: str
    name: str
    status: str        # "ok" | "warn" | "error"
    summary: str       # 一行摘要
    details: Dict[str, Any]  # 详细信息
    checked_at: str    # ISO 时间戳

class InspectReport:
    """诊断报告聚合"""
    panels: List[PanelResult]
    overall_status: str  # 取最严重的 status

    def to_dict(self) -> Dict: ...
    def to_json(self) -> str: ...
    def to_brief(self) -> str: ...  # 摘要模式输出
    def to_table(self) -> str: ...  # 表格模式输出（默认）

class SystemInspector:
    """系统诊断器 — 编排 8 个面板的检查"""

    PANEL_REGISTRY = {
        "system": SystemPanel,
        "positions": PositionsPanel,
        "knowledge": KnowledgePanel,
        "models": ModelsPanel,
        "skills": SkillsPanel,
        "risk": RiskPanel,
        "connections": ConnectionsPanel,
        "alerts": AlertsPanel,
    }

    def inspect(self, panel_ids: Optional[List[str]] = None) -> InspectReport: ...
```

每个面板是一个独立的类，实现 `check() -> PanelResult` 接口。这样便于单独测试和扩展。

#### 3.2.4 接入点

| 接入点 | 时机 | 行为 |
|:---|:---|:---|
| polling_trader 启动 | `__init__` 末尾 | 调用 `inspect --brief`，关键面板（positions/connections/models）失败则打 WARN 日志，但不中断启动（避免实盘被非关键检查卡住） |
| yijing_monitor 巡检 | 每次 check_status | 调用 `inspect --json`，解析结果，error 面板触发飞书告警 |
| 人工排查 | 手动运行 | `python -m scripts.memory_l4.inspect` 查看完整报告 |

#### 3.2.5 关键面板实现要点

**PositionsPanel（持仓一致性检查）**：
- 调用 `position_tracker.all_open_positions()` 获取本地持仓
- 调用 `okx_client.get_positions(inst_id)` 获取 OKX 持仓（复用 `_sync_existing_positions` 的逻辑）
- 逐 inst_id 对比方向、数量、价格
- **重要**：根据过往经验，持仓同步必须直连 OKX positions 接口，不允许复用带「内部优先/缓存优先」的封装函数，避免自引用导致同步失效

**KnowledgePanel（知识状态检查）**：
- L4 案例数：`len(list(memory_l4_cases_dir().glob("*.json")))`
- CBR 案例数：从 `index/latest.json` 的 `case_features` 统计
- KG 三元组数：`KGStore().get_stats()`
- 索引更新时间：`index/latest.json` 的 `snapshot_ts` 字段

**ModelsPanel（模型状态检查）**：
- BCRM2 模型文件：检查 `.workbuddy/memory_l4/bcrm2/` 下的 l1_model.txt / l2_model.txt
- L1/L2 样本数：从模型文件的 LightGBM header 解析
- 训练时间：模型文件的 mtime

### 3.3 验证方案

| 验证项 | 方法 | 成功指标 |
|:---|:---|:---|
| 异常检出率 | 人工构造 5 种异常场景（持仓不一致、模型缺失、心跳超时、CBR 案例不足、连接失败），验证 inspect 能否正确检测 | 检出率 ≥ 95%（5/5 场景全部检出） |
| 误报率 | 在正常状态下运行 inspect 10 次，统计误报 | 误报率 < 5% |
| 性能 | 完整 8 面板检查耗时 | < 3 秒（不阻塞实盘启动） |
| 输出格式 | 验证 `--brief` / `--json` / `--table` 三种输出 | 格式正确，可被脚本解析 |

---

## 4. 组件 2：CBR 分片检索

### 4.1 动机

借鉴 grok-build 的「子 Agent 窄 context 并行探」思想——大案例库先分片，各分片独立检索，再聚合排序。

**当前问题**（2026-07-22 实测数据）：
- 789 个案例全量线性扫描，每次检索都遍历全部
- 案例数据质量参差：775/789 个案例的 `decision` 字段为 None，噪音大
- 相似度阈值已从 0.3 降到 0.1，仍有大量低质量匹配
- CBR 日志显示「Top-1 相似度=0.25」，区分度不足

### 4.2 设计

#### 4.2.1 分片策略

采用 3 个分片维度，优先级从高到低：

```
Shard 维度 1: inst_id 分片
  → BTC 只在 BTC 案例里找，跨币种不互扰
  → 相同币种的市场结构、波动特性更接近

Shard 维度 2: regime 分片
  → 5 种 regime 各成一片：trend_up / trend_down / ranging_up / ranging_down / sideways
  → 同 regime 的案例决策方向更可比

Shard 维度 3: 质量分片
  → 高质量分片：有 decision + pnl_pct 的案例
  → 低质量分片：decision 或 pnl_pct 为 None 的案例
```

#### 4.2.2 检索流程

```
query (inst_id, regime, decision, confidence, volatility, entry_price)
  │
  ▼
Step 1: 定位主分片 = inst_id_shard ∩ regime_shard ∩ high_quality_shard
  │
  ├─ 案例数 ≥ top_k? → 在主分片内检索，返回 Top-K
  │
  ├─ 案例数 < top_k? → Step 2: 放宽 regime，在同 inst_id 的相邻 regime 分片补充
  │                    相邻规则：trend_up ↔ ranging_up, trend_down ↔ ranging_down, sideways ↔ all
  │
  ├─ 仍不足? → Step 3: 放宽 inst_id，在全局同 regime 分片补充
  │
  ├─ 仍不足? → Step 4: 放宽质量，加入低质量分片
  │
  └─ 仍不足? → Step 5: 全库 fallback（当前行为）
  │
  ▼
聚合去重 + 按相似度排序 + 返回 Top-K
```

#### 4.2.3 核心类设计

```python
# scripts/memory_l4/cbr_sharded_retriever.py

@dataclass
class ShardSpec:
    """分片规格"""
    inst_id: Optional[str] = None      # None 表示全库
    regime: Optional[str] = None       # None 表示所有 regime
    quality: str = "high"              # "high" | "low" | "any"

class ShardedCaseBase:
    """分片案例库 — 替代 CaseBase 的线性扫描"""

    def __init__(self, cases: List[CBRCase]):
        self._shards: Dict[str, List[CBRCase]] = {}
        self._build_shards(cases)

    def _shard_key(self, case: CBRCase, spec: ShardSpec) -> str: ...

    def get_shard(self, spec: ShardSpec) -> List[CBRCase]: ...

    def stats(self) -> Dict[str, int]:
        """返回各分片案例数，供 inspect 面板展示"""

class ShardedRetriever:
    """分片检索器 — 替代 CBREngine 的全库 retrieve"""

    REGIME_NEIGHBORS = {
        "trend_up": ["ranging_up", "sideways"],
        "trend_down": ["ranging_down", "sideways"],
        "ranging_up": ["trend_up", "sideways"],
        "ranging_down": ["trend_down", "sideways"],
        "sideways": ["trend_up", "trend_down", "ranging_up", "ranging_down"],
    }

    def __init__(
        self,
        sharded_base: ShardedCaseBase,
        retriever: CaseSimilarity,   # 复用现有相似度计算
        top_k: int = 5,
        similarity_threshold: float = 0.1,
    ): ...

    def retrieve(self, query: CBRQuery) -> List[RetrievedCase]:
        """5 级降级检索"""
        # Plan 1: inst_id ∩ regime ∩ high_quality
        # Plan 2: inst_id ∩ regime_neighbors ∩ high_quality
        # Plan 3: all inst_ids ∩ regime ∩ high_quality
        # Plan 4: inst_id ∩ regime ∩ any_quality
        # Plan 5: full fallback (当前行为)
```

#### 4.2.4 接入方式

**非侵入式替换**：`CBREngine` 增加一个 `use_sharded` 参数，默认 `False`（保持现有行为）。

```python
class CBREngine:
    def __init__(
        self,
        case_base: Optional[CaseBase] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.1,
        use_sharded: bool = False,    # 新增
    ):
        if use_sharded:
            self._sharded_retriever = ShardedRetriever(...)
        else:
            self._sharded_retriever = None

    def retrieve(self, query: CBRQuery) -> List[RetrievedCase]:
        if self._sharded_retriever:
            return self._sharded_retriever.retrieve(query)
        # ... 现有全库检索逻辑
```

`polling_trader` 中通过配置开关启用：
```python
self.cbr_bridge = CBRToBCRMBridge(use_sharded=True)
```

### 4.3 验证方案

| 验证项 | 方法 | 成功指标 |
|:---|:---|:---|
| 检索质量不退化 | leave-one-out 测试：拿每个历史案例当 query，对比「全库检索」vs「分片检索」的 Top-1 案例的 PnL | 分片检索 Top-1 平均 PnL ≥ 全库检索（不退化） |
| 检索速度提升 | 在 789 个案例上测量单次检索耗时 | 分片检索耗时 ≤ 全库检索的 50% |
| 匹配精度提升 | 对比 Top-1 相似度分布 | 分片检索 Top-1 平均相似度 > 全库检索 |
| 降级机制 | 构造极端 query（罕见 inst_id + 罕见 regime），验证 5 级降级 | 降级路径正确触发，最终总能返回结果（除非库为空） |

**回测脚本设计**：

```python
# scripts/memory_l4/benchmark/cbr_shard_benchmark.py

def run_leave_one_out(cases: List[CBRCase], use_sharded: bool) -> Dict:
    """
    Leave-one-out 测试
    - 每次拿一个案例当 query，其余当库
    - 记录 Top-1 案例的相似度和 PnL
    - 返回聚合统计
    """
    results = []
    for i, test_case in enumerate(cases):
        train_cases = cases[:i] + cases[i+1:]
        query = CBRQuery(...)  # 从 test_case 构造
        engine = CBREngine(use_sharded=use_sharded, ...)
        engine.case_base.cases = train_cases
        retrieved = engine.retrieve(query)
        if retrieved:
            results.append({
                "query_case": test_case.case_id,
                "top1_sim": retrieved[0].similarity,
                "top1_pnl": retrieved[0].case.pnl_pct,
                "top1_decision": retrieved[0].case.decision,
            })
    return aggregate_stats(results)
```

---

## 5. 组件 3：SKILL.md 兼容导入器

### 5.1 动机

借鉴 grok-build 的「读 Claude/Cursor MCP 配置」思路——不重复造轮子，兼容生态已有格式。

**当前状态**：
- 已有 50+ 个 SKILL.md 文件（YAML frontmatter + Markdown body）
- `SkillEngine` 通过代码手动注册 handler，不是从 SKILL.md 自动发现
- Dream OS 的 `NodeRegistry` / `CapabilityRegistry` 是另一套体系
- 两套体系之间没有桥接，同一个 skill 要注册两次

### 5.2 设计

#### 5.2.1 SkillImporter 核心职责

做两件事：
1. **解析 SKILL.md** → 标准化的 `SkillMeta` 对象
2. **双注册**：同时注册到 `SkillEngine`（16-调控系统）和 `NodeRegistry`（Dream OS）

#### 5.2.2 SKILL.md 解析规范

支持两种 frontmatter 格式（本项目风格 + Superpowers/Claude Code 风格），字段别名映射：

| 本项目字段 | Superpowers 字段 | 说明 |
|:---|:---|:---|
| `name` | `name` | skill 名称 |
| `description` | `description` | 描述 |
| `version` | `version` | 版本 |
| `created` | `created` | 创建日期 |
| `updated` | `updated` | 更新日期 |
| `license` | `license` | 许可 |
| `tags` | `tags` | 标签列表 |
| `trigger_words` | `triggers` | 触发词（别名） |
| `supported_intents` | `intents` | 支持的意图（别名） |

Markdown body 解析规则：
- `##` 标题 → 一个 phase
- `###` 标题 → phase 内的子步骤
- 表格（`|...|...|`）→ 参数契约（输入/输出）
- 代码块（```）→ 示例代码，不解析

#### 5.2.3 核心类设计

```python
# scripts/skill_importer.py

@dataclass
class SkillPhase:
    phase_id: str
    name: str
    description: str = ""
    inputs: List[Dict] = field(default_factory=list)   # 输入参数契约
    outputs: List[Dict] = field(default_factory=list)  # 输出参数契约

@dataclass
class SkillMeta:
    """标准化 skill 元数据"""
    skill_name: str
    version: str
    description: str
    tags: List[str]
    trigger_words: List[str]
    supported_intents: List[str]
    phases: List[SkillPhase]
    skill_path: str          # SKILL.md 文件路径
    handler: Optional[Callable] = None  # 代码 handler（如有）
    source_format: str = "native"  # "native" | "superpowers" | "claude"

class SKILLMdParser:
    """SKILL.md 解析器"""

    FIELD_ALIASES = {
        "triggers": "trigger_words",
        "intents": "supported_intents",
    }

    def parse(self, skill_md_path: Path) -> SkillMeta: ...
    def validate(self, skill_meta: SkillMeta) -> List[str]: ...  # 返回错误列表

class SkillImporter:
    """SKILL.md 导入器 — 解析 + 双注册"""

    def __init__(
        self,
        skill_engine: Optional[SkillEngine] = None,
        node_registry: Optional[NodeRegistry] = None,
    ): ...

    def import_one(self, skill_md_path: Path) -> SkillMeta:
        """导入单个 SKILL.md"""
        meta = self.parser.parse(skill_md_path)
        errors = self.parser.validate(meta)
        if errors:
            raise ValueError(f"SKILL.md 校验失败: {errors}")
        self._register_to_skill_engine(meta)
        self._register_to_node_registry(meta)
        return meta

    def scan_and_import(self, skills_dir: Path) -> List[SkillMeta]:
        """扫描目录，批量导入"""
        results = []
        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                meta = self.import_one(skill_md)
                results.append(meta)
            except Exception as e:
                logger.warning(f"导入失败 {skill_md}: {e}")
        return results

    def _register_to_skill_engine(self, meta: SkillMeta): ...
    def _register_to_node_registry(self, meta: SkillMeta): ...
```

#### 5.2.4 CLI 入口

```bash
# 扫描 skills/ 目录，全部导入
python -m scripts.skill_importer scan

# 导入单个 skill
python -m scripts.skill_importer import dream-strategy-research

# 列出已导入的 skill
python -m scripts.skill_importer list

# 校验 SKILL.md 格式（不注册，只检查）
python -m scripts.skill_importer validate skills/1-TRADE/dream-strategy-research/SKILL.md

# 导出为 Superpowers 格式（反向兼容）
python -m scripts.skill_importer export dream-strategy-research --format superpowers
```

#### 5.2.5 NodeRegistry 注册映射

`SkillMeta` → `Node` 的映射规则：

| Node 字段 | 来源 |
|:---|:---|
| `node_id` | `f"SKILL_{skill_name}"` |
| `chain` | 从 tags 推断：含 "TRADE" → "A"；含 "INTELLIGENCE" → "I"；含 "SUPPORT" → "S"；含 "CORE" → "C" |
| `name` | `skill_name` |
| `description` | `meta.description` |
| `tags` | `meta.tags` |
| `handler` | `meta.handler`（如有） |

### 5.3 验证方案

| 验证项 | 方法 | 成功指标 |
|:---|:---|:---|
| 解析成功率 | 扫描现有 50+ SKILL.md，统计解析成功数 | 成功率 ≥ 95% |
| 字段提取准确性 | 抽查 10 个 SKILL.md，人工对比解析结果 | 关键字段（name/version/description/tags）100% 正确 |
| 双注册一致性 | 导入后检查 SkillEngine 和 NodeRegistry 中的注册项 | 两边注册数一致，node_id 可互查 |
| Superpowers 格式兼容 | 用一个标准 Superpowers SKILL.md 测试导入 | 能正确解析，字段别名映射正确 |
| 反向导出 | 导入后再导出为 Superpowers 格式 | 导出文件可被重新导入，字段无丢失 |

---

## 6. 落地计划

### 6.1 实施顺序

```
Step 1: inspect 诊断命令（独立，无依赖）
  │   验证：5 场景异常检出 + 性能 < 3s
  │
  ▼
Step 2: CBR 分片检索（依赖现有 CBREngine）
  │   验证：leave-one-out 回测 + 速度对比
  │   注意：先以 use_sharded=False 上线，回测验证后再切 True
  │
  ▼
Step 3: SKILL.md 兼容导入（依赖现有 SkillEngine + NodeRegistry）
      验证：50+ SKILL.md 批量扫描 + 双注册一致性
```

### 6.2 风险与缓解

| 风险 | 影响 | 缓解措施 |
|:---|:---|:---|
| inspect 误报导致实盘启动被卡 | 交易中断 | 关键面板失败只 WARN 不阻断；非关键面板失败忽略 |
| CBR 分片检索质量退化 | 决策变差 | `use_sharded` 默认 False，回测验证后才切 True；保留全库 fallback |
| SKILL.md 解析失败影响现有技能 | 技能不可用 | 导入是增量操作，不覆盖已注册的 skill；失败的 skill 跳过并记录 |
| 分片后某些分片案例过少 | 检索结果不足 | 5 级降级机制确保最终 fallback 到全库 |

### 6.3 回测验证总览

| 组件 | 验证类型 | 核心指标 | 目标值 |
|:---|:---|:---|:---|
| inspect | 异常场景测试 | 检出率 | ≥ 95% |
| inspect | 性能测试 | 单次检查耗时 | < 3 秒 |
| CBR 分片 | leave-one-out | Top-1 平均 PnL | ≥ 全库检索 |
| CBR 分片 | 性能对比 | 检索耗时 | ≤ 全库的 50% |
| SKILL 导入 | 批量扫描 | 解析成功率 | ≥ 95% |
| SKILL 导入 | 一致性检查 | 双注册数差异 | 0 |

---

## 7. 与 Grok Build 的对应关系

完整对照表，供后续 P1/P2 阶段参考：

| Grok Build 概念 | 本项目对应物 | P0 状态 | P1/P2 计划 |
|:---|:---|:---|:---|
| `grok inspect` | `scripts/memory_l4/inspect.py` | ✅ P0 实现 | — |
| 子 Agent 窄 context 并行探 | `ShardedRetriever` 分片检索 | ✅ P0 实现（检索层） | P2：真正的子 Agent 并行 |
| 读 Claude/Cursor MCP 配置 | `SkillImporter` SKILL.md 兼容导入 | ✅ P0 实现 | P1：MCP 协议兼容 |
| harness（loop 外的壳） | llm_bridge + skill_engine | 不动 | P1：harness/模型解耦 |
| 三脸同环（TUI/headless/ACP） | CLI 优先 | 不动 | P2：ACP 协议研究 |
| Plan 模式 | S 层 intent Spec | 不动 | P1：Plan-Do 模式 |
| skills/plugins/hooks/MCP | SkillsRegistry + SKILL.md | ✅ P0 实现（SKILL.md 解析） | P1：MCP 兼容 |
| context 分区（compact/memory） | L4 记忆体系 M0-M4 | 不动 | P2：子 Agent context 分区 |
| 权限门 / 沙箱 | graph-hitl + 交易风控 | 不动 | P1：沙箱化 |

---

## 8. 附录

### 8.1 相关文件索引

**现有文件（不修改）**：
- [polling_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py) — 实盘交易主执行器
- [yijing_monitor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/yijing_monitor.py) — 监控与自进化
- [cbr_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/cbr_engine.py) — CBR 案例推理引擎
- [cbr_similarity.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/cbr_similarity.py) — 相似度计算
- [kg_store.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/kg_store.py) — 知识图谱存储
- [skill_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/16-调控系统/core/skill_engine.py) — SKILL 执行引擎
- [registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/core/capability/registry.py) — Dream OS 能力域注册表
- [node_registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/registry/node_registry.py) — Dream OS 节点注册表

**新增文件**：
- `scripts/memory_l4/inspect.py` — inspect 诊断命令
- `scripts/memory_l4/cbr_sharded_retriever.py` — CBR 分片检索器
- `scripts/skill_importer.py` — SKILL.md 兼容导入器
- `scripts/memory_l4/benchmark/cbr_shard_benchmark.py` — CBR 分片回测脚本

### 8.2 Grok Build 参考资料

- 仓库：https://github.com/xai-org/grok-build
- 开源内容：harness（agent loop 外壳），非模型
- 语言：Rust
- 核心概念：harness、三脸同环、Plan 模式、子 Agent、inspect、skills/plugins/hooks/MCP/AGENTS.md
