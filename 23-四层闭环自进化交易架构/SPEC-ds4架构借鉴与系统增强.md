# SPEC: ds4 推理引擎架构借鉴与 23-自进化系统增强

> **状态：** Spec（待评审·v1）
> **创建：** 2026-10-04
> **目标：** 将 Redis 之父 antirez 的 ds4 推理引擎七大核心架构设计，经过深度调研和冲突论证后，以模块化开关方式渐进接入 23-四层闭环自进化交易架构，提升系统鲁棒性、资源效率和进化质量。
> **硬约束：** FAIL-OPEN 铁律不可破坏；不改变现有四层闭环/基因库/ShadowRL/Bellman/三系统接入的行为语义；新能力以独立开关接入，默认关闭，验证后渐进开启；所有开关关闭时与当前行为 100% 等价。
> **哲学对齐：** ds4 的"窄而深·把资源花在刀刃上·主动降级而非被动崩溃"与 23 系统的"万物皆数·最小阻力路径·精细管理而非辩论"高度契合。

***

## 零 · ds4 七大维度深度调研（代码级）

### 0.1 维度一：垂直聚焦 + 非对称量化

**ds4 实现**（ds4.c 头部注释 + MODELS.md）：

> "This file is deliberately vertical... Model shape selection is intentionally narrow: validation accepts the known Flash and Pro layouts and fails early for anything else."

- 核心文件 `ds4.c` 一个文件拥有：GGUF 加载 + 固定张量布局 + CPU 内核 + Metal 图驱动 + tokenizer
- **非对称量化**：
  - 路由专家（MoE routed experts）：**IQ2_XXS gate/up + Q2_K down**（激进 2-bit）
  - 共享专家、投影层、输出层：**Q8/F16/F32**（高精度）
  - imatrix 指导量化方向
- 哲学：**"把精度/算力花在真正影响输出的组件上"**

**对 23 的映射**：策略基因分级存储——核心基因完整精度，候选基因简化表示。

### 0.2 维度二：零拷贝 mmap 加载

**ds4 实现**（ds4.c 头部注释）：

> "Loading is mmap based. The loader parses only the GGUF header, metadata table, and tensor directory. Tensor data stays in the kernel page cache until inference touches it, or until Metal wraps slices of the mapping as no-copy MTLBuffers."

- 只解析 header/metadata/tensor directory
- 张量数据留在内核页缓存，按需访问
- Metal 用 `no-copy MTLBuffers` 包装映射切片

**对 23 的映射**：大基因库/历史样本数据用 mmap 或 sqlite 替代全量 JSON 加载。

### 0.3 维度三：KV Cache / Engram 持久化

**ds4 实现**（ds4_engram.h + README）：

- Engram 表用**单独的未缓存文件描述符**，不是 mmap，不全量加载
- `ds4_engram_read_batch` 按行读取，临时存储有界（384 KiB），与表大小和前缀长度无关
- Session KV cache 保存到 `~/.ds4/kvcache`，恢复时直接复用，**避免重新 prefill**
- `/strip` 可移除大 KV payload 只保留文本

**对 23 的映射**：Bellman V(s)、策略权重快照、推理状态持久化到磁盘，重启后快速恢复。

### 0.4 维度四：SSD Streaming 主动优雅降级

**ds4 实现**（ds4_ssd.h + SSD_STREAMING.md）：

```c
typedef struct {
    uint64_t model_target_bytes;
    uint64_t cache_bytes;
    uint64_t effective_cache_bytes;
    uint32_t cache_experts;
} ds4_ssd_cache_plan;

bool ds4_ssd_auto_cache_plan(..., ds4_ssd_cache_plan *out);
```

- 路由专家按需从 GGUF 磁盘加载，有界缓存
- **非路由权重 + KV state 必须常驻内存**
- 自动预算（`ds4_ssd_auto_cache_plan`），启动时报告有效缓存
- 哲学：**"资源不够时主动降级，而不是直接 OOM 失败"**

**对 23 的映射**：从"异常跳过"升级为"主动降级阶梯"——资源不足时逐步简化推理路径。

### 0.5 维度五：分布式推理（TP/PP）

**ds4 实现**（ds4_distributed.h + DISTRIBUTED.md）：

> "Distributed inference is an engine backend, not a separate frontend API. Programs parse distributed options here, then keep using the normal ds4_session_* calls."

- **作为 engine backend**，不暴露新前端 API，正常 `ds4_session_*` 调用
- **Tensor Parallelism**：两台机器 50/50 分割路由专家，RDMA 交换部分结果
- **Pipeline Parallelism**：按层范围分割（0:19 / 20:output），适合大模型
- 传输精度可调：32-bit / 16-bit / 8-bit activations

**对 23 的映射**：大规模回测/参数搜索跨机器并行，按时间范围或参数空间分割。

### 0.6 维度六：窄接口边界

**ds4 实现**（ds4.h）：

- 只暴露两个抽象：
  - `ds4_engine`：加载的模型（不可变）
  - `ds4_session`：一条可变推理时间线（拥有 KV cache + logits）
- CLI/Server 不依赖张量内部实现
- 头文件注释："Keep this header narrow so HTTP/CLI code does not depend on tensor internals."

**对 23 的映射**：定义核心窄接口（StrategyGene、TradeSession、MarketState），引擎只依赖这些接口。

### 0.7 维度七：集成能力评测

**ds4 实现**（README + ds4-eval）：

- `ds4-eval` 嵌入式能力回归测试：`core` / `hard` / `hard-smoke` 套件
- `--trace` 记录完整推理轨迹，`--regrade-trace` 重评分已有轨迹
- 发布前跑大 QA
- 哲学：**"每次变更后验证核心能力不退化"**

**对 23 的映射**：建立交易能力回归套件，每次策略/参数变更后验证开仓准确率、离场质量、最大回撤、Sharpe 不退化。

***

## 一 · 23 系统现状分析（代码验证）

### 1.1 持久化现状

| 组件 | 持久化方式 | 重启恢复 | 代码位置 |
|------|-----------|---------|---------|
| Shadow RL 样本 | JSONL 追加写 | ✅ load_from_disk | [shadow_rl.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/shadow_rl.py#L84-L91) |
| 矛盾权重 | JSON 读写 | ✅ _load_weight_factors | [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L188-L215) |
| Bellman V(s) | **内存 dict** | ❌ 重启丢失 | [bellman_tracker.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/bellman_tracker.py#L23-L25) |
| Neural SDE 权重 | 有 load 无 save | 部分 | [deep_reasoning_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/deep_reasoning_engine.py#L108-L128) |
| 策略基因库 | JSON 文件全量加载 | ✅ 但全量 | [strategy_gene.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/strategy_gene.py#L32-L172) |

**缺口**：Bellman V(s) 纯内存，重启后 V 值从零开始，影响 ESS 调整的连续性。

### 1.2 降级机制现状

| 层级 | 机制 | 代码位置 |
|------|------|---------|
| DeepReasoningEngine 内部 | 4 级降级链：torchsde → EM → GARCH → GBM | [deep_reasoning_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/deep_reasoning_engine.py#L148-L220) |
| Pipeline 层面 | 开关控制启用/禁用 + try/except FO | [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L112-L124) |
| 最小阻力搜索 | HJB → 变分法 → argmin | [deep_reasoning_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/deep_reasoning_engine.py#L309-L354) |

**特点**：已有模块内降级链，但 pipeline 层面是"开关控制 + 异常跳过"，缺少**资源感知的主动降级**。

### 1.3 接口现状

- `evolution_pipeline.py` 直接 `from dreambuddy_evolution.xxx import Yyy` 导入各引擎
- 引擎间通过 `dict` 传递数据（如 `r_out`、`paths`）
- 无统一的窄接口定义
- 单例模式（`EvolutionPipeline._instance`）供外部组件访问

### 1.4 测试现状

- 52 个测试文件，692 个测试用例
- 以单元测试为主（test_*.py）
- 缺少端到端能力回归测试

***

## 二 · 逐维度冲突论证

### 2.1 维度一：非对称基因分级存储

**借鉴点**：ds4 非对称量化——关键组件高精度，非关键激进压缩。

**设计**：策略基因库三级分级：
- **L0 核心基因库**（实盘验证 Sharpe 正向）：完整 parameters + meta + 历史表现
- **L1 候选基因库**（影子验证中）：仅 gene_id + action_ids + ess + n_samples
- **L2 淘汰基因库**：仅 gene_id + 最终评分 + 淘汰原因

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 现有 load_gene_library() 接口 | ✅ 不冲突 | 分级逻辑在函数内部实现，对外返回结构不变 |
| top_combinations_by_ess() | ✅ 不冲突 | 仍从 combinations 列表计算，数据来源透明 |
| search_genes_by_category() | ✅ 不冲突 | 倒排索引不变 |
| 基因写入路径 | ⚠️ 需适配 | 新基因写入时根据验证状态决定存储级别 |
| 现有测试 | ✅ 不冲突 | 对外接口不变，现有测试全绿 |

**FAIL-OPEN 影响**：分级加载失败时降级为全量加载（当前行为），不影响交易。

### 2.2 维度二：Bellman V(s) 状态持久化

**借鉴点**：ds4 KV Cache 持久化——避免冷启动。

**设计**：BellmanVTracker 增加 `persist_path` + `save()` + `load()` 方法，将 `_v` 和 `_v_regime` 持久化到 JSON。

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| td_update() 接口 | ✅ 不冲突 | 持久化是副作用，不改变返回值 |
| get_v() / get_ess_adjustment() | ✅ 不冲突 | 只读接口不变 |
| 现有调用方 | ✅ 不冲突 | 无新增必填参数 |
| EvolutionPipeline 初始化 | ⚠️ 需适配 | 构造时传入 persist_path，启动时 load |
| 内存 vs 磁盘一致性 | ⚠️ 需设计 | save 时机：每 N 次更新或进程退出时 |

**FAIL-OPEN 影响**：持久化失败不影响内存中的 V 值计算；加载失败时从空 dict 开始（当前行为）。

### 2.3 维度三：主动优雅降级阶梯

**借鉴点**：ds4 SSD streaming——资源不足时主动降级，而非崩溃。

**设计**：在 EvolutionPipeline 层面增加资源感知的主动降级阶梯：

```
Level 0 (资源充足): 完整深度学习推理（签名+SDE+路径积分+HJB）
    ↓ 资源不足（样本<阈值 / 模型未训练 / 超时）
Level 1: 简化推理（签名+GARCH+argmin，跳过路径积分）
    ↓ 进一步不足
Level 2: 规则基线（当前四层闭环规则决策）
    ↓ 完全不可用
Level 3: FAIL-OPEN 中性兜底
```

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| DeepReasoningEngine 内部降级链 | ✅ 不冲突 | 保留现有 4 级链，pipeline 层面是更粗粒度的资源路由 |
| _agi_enhance() 开关机制 | ✅ 不冲突 | 降级阶梯是开关机制的增强，不替代 |
| 现有 _discover_paths() | ⚠️ 需适配 | 增加资源检查，决定是否调用 deep_reasoning |
| 路径评分逻辑 | ✅ 不冲突 | 降级只影响路径来源，不影响评分公式 |

**FAIL-OPEN 影响**：降级阶梯本身就是 FAIL-OPEN 的增强——从"异常跳过"变为"主动选择合适复杂度"。

### 2.4 维度四：窄接口边界

**借鉴点**：ds4.h 只暴露 engine + session。

**设计**：新增 `core/interfaces.py` 定义核心窄接口（Protocol/ABC）：
- `StrategyGene`：策略基因标准表示
- `TradeSession`：一次交易的完整时间线
- `MarketState`：市场状态快照
- `PathCandidate`：候选交易路径

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 现有引擎实现 | ✅ 不冲突 | 新增接口，现有引擎逐步适配，不强制改造 |
| evolution_pipeline.py | ✅ 不冲突 | 可继续用 dict，接口是可选约束 |
| 类型检查 | ✅ 不冲突 | Protocol 不影响运行时 |

**FAIL-OPEN 影响**：无。接口是渐进式的，不强制。

### 2.5 维度五：mmap / 流式加载大文件

**借鉴点**：ds4 mmap 按需访问。

**设计**：对持续增长的 `shadow_rl_samples.jsonl`，引入 sqlite 或 mmap 替代全量 read_text。

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| shadow_rl.py record() | ✅ 不冲突 | 写入接口不变 |
| load_from_disk() | ⚠️ 需适配 | 从全量读取改为流式/索引读取 |
| get_stats() | ✅ 不冲突 | 统计逻辑不变 |
| 现有 JSONL 文件 | ✅ 向后兼容 | 提供迁移脚本，旧文件可导入 |

**FAIL-OPEN 影响**：新存储失败时降级为现有 JSONL 读取。

### 2.6 维度六：分布式回测/搜索

**借鉴点**：ds4 TP/PP 跨机器并行。

**设计**：新增分布式回测模块，按时间范围或参数空间分割到多台机器。

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 现有回测脚本 | ✅ 不冲突 | 新增模块，不修改现有 |
| 实盘交易路径 | ✅ 不冲突 | 分布式仅用于回测/搜索 |
| 现有单机性能 | ✅ 不冲突 | 可选加速，不替代 |

**FAIL-OPEN 影响**：分布式失败降级为单机执行。

### 2.7 维度七：能力回归测试套件

**借鉴点**：ds4-eval 嵌入式能力测试。

**设计**：新增 `tests/capability_regression/` 目录，用真实历史数据验证：
- 开仓信号准确率
- 离场时机质量（盈利交易占比、平均持仓时间）
- 最大回撤控制
- Sharpe 比率

**冲突论证**：

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 现有单元测试 | ✅ 不冲突 | 新增目录，不修改现有 |
| CI 流水线 | ⚠️ 需适配 | 可选步骤，不阻塞 CI |
| 测试数据 | ✅ 不冲突 | 用现有历史数据 |

**FAIL-OPEN 影响**：无。

***

## 三 · 架构设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                  23-四层闭环自进化交易架构（增强版）               │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 新增增强层（默认关闭·模块化开关·FAIL-OPEN）                │  │
│  │                                                           │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐ │  │
│  │  │ 基因分级存储 │  │ V(s)持久化  │  │ 主动降级阶梯     │ │  │
│  │  │ (Dimension1)│  │ (Dimension2)│  │ (Dimension3)     │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────┘ │  │
│  │                                                           │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐ │  │
│  │  │ 窄接口边界  │  │ 流式加载    │  │ 分布式回测       │ │  │
│  │  │ (Dimension4)│  │ (Dimension5)│  │ (Dimension6)     │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────┘ │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │ 能力回归测试套件 (Dimension7)                        │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 现有四层闭环（不变·所有增强开关关闭时 100% 等价）          │  │
│  │  观察→推断→实验→反思→回馈                                  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 各维度模块设计

#### Dimension 1: 基因分级存储

**新增模块**：`core/gene_tiered_storage.py`

```python
class GeneTieredStorage:
    """策略基因分级存储（借鉴 ds4 非对称量化）.
    
    L0 核心基因库: 完整 parameters + meta + 历史表现（实盘验证）
    L1 候选基因库: gene_id + action_ids + ess + n_samples（影子验证）
    L2 淘汰基因库: gene_id + final_score + reason（审计）
    """
    TIER_CORE = "core"        # 实盘验证 Sharpe 正向
    TIER_CANDIDATE = "candidate"  # 影子验证中
    TIER_RETIRED = "retired"  # 已淘汰

    def classify(self, gene: dict) -> str:
        """根据验证状态分级."""
        ...

    def load_tiered(self, root: Path) -> dict:
        """分级加载：L0 全量，L1 元数据，L2 仅 ID.
        
        FAIL-OPEN: 分级失败 → 全量加载（当前行为）.
        """
        ...
```

**接入点**：`strategy_gene.load_gene_library()` 内部调用，对外接口不变。

#### Dimension 2: Bellman V(s) 持久化

**修改模块**：`core/bellman_tracker.py`（增加方法，不改变现有接口）

```python
class BellmanVTracker:
    def __init__(self, ..., persist_path: str | Path | None = None):
        ...
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path:
            self.load()  # 启动时恢复

    def save(self) -> None:
        """持久化 V 值到 JSON. FAIL-OPEN: 失败不影响内存."""
        ...

    def load(self) -> None:
        """从 JSON 恢复 V 值. FAIL-OPEN: 失败从空 dict 开始."""
        ...
```

**接入点**：`EvolutionPipeline.__init__` 传入 persist_path，定期 save。

#### Dimension 3: 主动降级阶梯

**新增模块**：`core/resource_aware_degrader.py`

```python
class ResourceAwareDegrader:
    """资源感知的主动降级阶梯（借鉴 ds4 SSD streaming）.
    
    Level 0: 完整深度学习推理
    Level 1: 简化推理（跳过路径积分）
    Level 2: 规则基线
    Level 3: FAIL-OPEN 中性兜底
    """
    LEVEL_FULL = 0      # 完整推理
    LEVEL_SIMPLIFIED = 1  # 简化推理
    LEVEL_RULE_BASELINE = 2  # 规则基线
    LEVEL_FAIL_OPEN = 3  # 中性兜底

    def assess_level(self, context: dict) -> int:
        """根据资源状态评估当前应使用的推理级别.
        
        评估维度:
          - 有效样本数 (< 2000 → 降级)
          - 模型训练状态 (未训练 → 降级)
          - 最近推理耗时 (超时 → 降级)
          - 系统负载 (高负载 → 降级)
        """
        ...

    def degrade_path(self, paths: list[dict], level: int) -> list[dict]:
        """根据级别过滤/简化路径候选."""
        ...
```

**接入点**：`EvolutionPipeline._discover_paths()` 开头调用 assess_level，决定是否调用 deep_reasoning。

#### Dimension 4: 窄接口边界

**新增模块**：`core/interfaces.py`

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class StrategyGene(Protocol):
    gene_id: str
    action_ids: list[str]
    ess: float
    n_samples: int

@runtime_checkable
class TradeSession(Protocol):
    session_id: str
    symbol: str
    entry_time: float
    ...

@runtime_checkable
class MarketState(Protocol):
    symbol: str
    price: float
    volatility: float
    ...

@runtime_checkable
class PathCandidate(Protocol):
    path_id: str
    direction: str
    expected_return: float
    confidence: float
    resistance: float
```

**接入点**：渐进式，现有引擎可选择性实现 Protocol。

#### Dimension 5: 流式加载大文件

**新增模块**：`core/streaming_sample_store.py`

```python
class StreamingSampleStore:
    """流式样本存储（借鉴 ds4 mmap 按需访问）.
    
    替代 shadow_rl_samples.jsonl 的全量读取.
    支持: 追加写、按索引读、范围查询、统计聚合.
    """
    def append(self, sample: dict) -> None: ...
    def read_range(self, start: int, end: int) -> list[dict]: ...
    def stats(self) -> dict: ...
```

**接入点**：`ShadowRLTracker` 可选择使用 StreamingSampleStore 替代 deque+JSONL。

#### Dimension 6: 分布式回测

**新增模块**：`scripts/distributed_backtest.py`

```python
class DistributedBacktest:
    """分布式回测（借鉴 ds4 Pipeline Parallelism）.
    
    按时间范围分割到多台机器，结果汇总.
    FAIL-OPEN: 分布式失败 → 单机执行.
    """
    def split_by_time(self, start: str, end: str, n_workers: int) -> list[tuple]: ...
    def run_worker(self, time_range: tuple) -> dict: ...
    def aggregate(self, results: list[dict]) -> dict: ...
```

**接入点**：独立脚本，不修改现有回测。

#### Dimension 7: 能力回归测试

**新增目录**：`tests/capability_regression/`

```
tests/capability_regression/
├── test_entry_accuracy.py      # 开仓信号准确率
├── test_exit_quality.py        # 离场时机质量
├── test_drawdown_control.py    # 最大回撤控制
├── test_sharpe_regression.py   # Sharpe 比率
└── conftest.py                 # 共享历史数据 fixture
```

***

## 四 · 开关设计

在 `agi_config.py` 新增以下开关（默认关闭）：

```python
AGI_SWITCHES.update({
    # --- ds4 架构借鉴增强（默认关闭）---
    "enable_gene_tiered_storage": False,     # D1: 基因分级存储
    "enable_bellman_persistence": False,     # D2: Bellman V(s) 持久化
    "enable_resource_aware_degradation": False,  # D3: 主动降级阶梯
    "enable_narrow_interfaces": False,       # D4: 窄接口边界（渐进式）
    "enable_streaming_sample_store": False,  # D5: 流式样本存储
    "enable_distributed_backtest": False,    # D6: 分布式回测
    # D7: 能力回归测试不设开关，始终可运行
})
```

**开关关断时等价性**：所有上述开关关闭时，系统行为与当前完全等价——
- D1 关闭 → load_gene_library 全量加载（当前行为）
- D2 关闭 → BellmanVTracker 纯内存（当前行为）
- D3 关闭 → _discover_paths 按现有逻辑调用 deep_reasoning
- D4 关闭 → 不强制接口约束
- D5 关闭 → ShadowRLTracker 用 deque+JSONL（当前行为）
- D6 关闭 → 回测单机执行（当前行为）

***

## 五 · 硬约束清单

| ID | 硬约束 | 域 |
|----|--------|-----|
| HC-DS4-01 | 所有增强开关关闭时，系统行为与当前 100% 等价 | 等价性域 |
| HC-DS4-02 | 基因分级存储失败 → 降级为全量加载，不阻塞交易热路径 | FAIL-OPEN域 |
| HC-DS4-03 | Bellman V(s) 持久化失败 → 内存 V 值继续工作，不阻塞 | FAIL-OPEN域 |
| HC-DS4-04 | 主动降级阶梯的降级决策必须可观测（日志记录级别和原因） | 可观测性域 |
| HC-DS4-05 | 降级到规则基线时，决策质量不得低于当前四层闭环基线 | 质量下限域 |
| HC-DS4-06 | 流式样本存储必须向后兼容现有 JSONL 文件（提供迁移工具） | 兼容性域 |
| HC-DS4-07 | 分布式回测失败 → 自动降级为单机执行，不阻塞回测流程 | FAIL-OPEN域 |
| HC-DS4-08 | 能力回归测试不得修改实盘交易行为（纯只读验证） | 安全域 |
| HC-DS4-09 | Bellman V(s) 持久化频率 ≤ 每 100 次更新一次，避免 IO 瓶颈 | 性能域 |
| HC-DS4-10 | 基因分级存储的 L0 核心基因必须保持完整精度，不得有损压缩 | 数据完整性域 |

***

## 六 · 验收标准

| 维度 | 验收指标 | 门槛 |
|------|---------|------|
| D1 基因分级 | 分级加载后内存占用 | ≤ 全量加载的 60% |
| D1 基因分级 | 对外接口兼容性 | 现有 692 测试全绿 |
| D2 V(s)持久化 | 重启后 V 值恢复率 | ≥ 99% |
| D2 V(s)持久化 | 持久化耗时 | < 100ms |
| D3 主动降级 | 降级决策可观测性 | 100% 降级事件有日志 |
| D3 主动降级 | 降级后决策质量 | ≥ 规则基线 |
| D4 窄接口 | Protocol 定义完整性 | 核心 4 个接口定义完成 |
| D5 流式加载 | 大文件加载耗时 | ≤ 全量读取的 30% |
| D6 分布式 | 2 机器加速比 | ≥ 1.5x |
| D7 能力回归 | 回归套件覆盖维度 | ≥ 4 个核心能力 |
| 全局 | 所有开关关闭时等价性 | 100% 等价 |

***

## 七 · 分阶段实施计划

```
P0（立即启动·低风险·高价值）:
  ├─ D2: Bellman V(s) 持久化（修改 bellman_tracker.py，增加 save/load）
  └─ D7: 能力回归测试套件（新增 tests/capability_regression/）

P1（P0 完成后·中风险）:
  ├─ D1: 基因分级存储（修改 strategy_gene.py，内部增加分级逻辑）
  └─ D3: 主动降级阶梯（新增 resource_aware_degrader.py，接入 _discover_paths）

P2（P1 完成后·中风险）:
  ├─ D4: 窄接口边界（新增 core/interfaces.py，渐进式适配）
  └─ D5: 流式样本存储（新增 streaming_sample_store.py，ShadowRL 可选切换）

P3（P2 完成后·独立模块）:
  └─ D6: 分布式回测（新增 scripts/distributed_backtest.py）
```

### 阶段间依赖关系

- D2、D7 无依赖，可并行启动
- D1 依赖 D7（需要能力回归验证分级后质量不退化）
- D3 依赖 D1（降级决策需要基因分级信息）
- D4 独立，可与 D1/D3 并行
- D5 依赖 D2（持久化模式需要统一）
- D6 完全独立

***

## 八 · 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 基因分级导致 ESS 计算偏差 | 中 | 中 | D7 能力回归验证；分级失败降级全量 |
| V(s) 持久化数据损坏 | 低 | 中 | JSON 格式 + 校验和；加载失败降级空 dict |
| 主动降级误判导致错过机会 | 中 | 高 | 降级决策可观测；规则基线兜底；A/B 对比验证 |
| 流式存储迁移丢失数据 | 低 | 高 | 迁移前备份；双写过渡期；校验工具 |
| 分布式回测结果不一致 | 中 | 中 | 确定性种子；结果校验；失败降级单机 |

***

## 九 · 不做的事（明确边界）

1. **不重写现有引擎**：所有增强以新增模块或内部逻辑增强方式接入，不重构现有 15+ 引擎
2. **不改变现有接口语义**：`load_gene_library`、`td_update`、`_discover_paths` 等对外接口返回值和语义不变
3. **不引入新的核心依赖**：除 sqlite（标准库）外，不引入新的第三方库
4. **不修改实盘交易热路径的时序**：所有持久化/降级操作不得增加热路径延迟（异步或缓存）
5. **不破坏现有测试**：所有 692 个现有测试必须保持全绿

***

## 十 · 参考来源

- [ds4 GitHub 仓库](https://github.com/antirez/ds4) — antirez 的 DeepSeek V4 推理引擎
- [ds4 SSD_STREAMING.md](https://github.com/antirez/ds4/blob/main/docs/SSD_STREAMING.md) — SSD streaming 设计
- [ds4 DISTRIBUTED.md](https://github.com/antirez/ds4/blob/main/docs/DISTRIBUTED.md) — 分布式推理设计
- [ds4 PERFORMANCE.md](https://github.com/antirez/ds4/blob/main/docs/PERFORMANCE.md) — 性能基准
- ds4 源文件：ds4.c / ds4.h / ds4_ssd.h / ds4_engram.h / ds4_distributed.h
- 23 系统现有代码：evolution_pipeline.py / strategy_gene.py / shadow_rl.py / bellman_tracker.py / deep_reasoning_engine.py / agi_config.py
