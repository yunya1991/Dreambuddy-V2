# SPEC — 架构级 ReverseDeriver（P3-1）

> **前置硬约束**（SPEC-自进化系统逆向解析改进.md v0.3 §4）：P3-1 requires new SPEC。
> 当前 `ReverseDeriver.derive(snapshot, outcome)` 是交易域（从交易结果反推维度判断错），
> 架构域是**新能力**，不能复用交易域接口。本 SPEC 独立设计
> `derive_architecture_debt(evidence_list)`。

## 1. 背景与动机

自进化系统有 `reflection_engine` 反思交易决策，却无反思架构健康度能力。
REA（33-REA逆向解析工程）已能产出架构 Evidence（文件行数/出度/豁口数/git 演化类型），
但缺少"从架构证据反推设计债务"的推导层——即架构域的反向传播。

**类比**：
- 交易域：forward（矛盾系统→预测）→ loss（CS+PnL）→ backward（ReverseDeriver→per_dimension_error）→ SGD（权重更新）
- 架构域：forward（代码结构→架构 Evidence）→ loss（债务超阈值）→ backward（ArchitectureReverseDeriver→debt_growth_dims）→ refactor（触发重构窗口）

## 2. 与交易域 ReverseDeriver 的关系

| 维度 | 交易域 ReverseDeriver | 架构域（本 SPEC） |
|---|---|---|
| 方法 | `derive(snapshot, outcome)` | `derive_architecture_debt(evidence_list)` |
| 输入 | 开仓快照 + 交易结果 | REA 架构 Evidence 列表 |
| 输出 | `ReverseDeriveResult`（wrong_dimensions, root_cause, optimization_action） | `ArchitectureDebtResult`（debt_dims, triggered_windows, refactor_plan） |
| 共享 | Evidence 数据结构（confidence + known_gaps） | 同左 |

**不共享**：接口签名、根因分类、优化动作（架构域的"优化"是触发 refactor 窗口，非权重更新）。

## 3. 接口设计

### 3.1 入口方法

```python
@dataclass
class ArchitectureDebtResult:
    debt_dimensions: dict[str, float]          # 维度→债务评分 0.0-1.0
    triggered_windows: list[str]               # 已触发的 refactor 窗口 ID
    refactor_plan: list[dict[str, Any]]        # 重构建议（优先级排序）
    confidence: float = 0.0                    # 整体置信度
    known_gaps: list[str] = field(default_factory=list)

class ArchitectureReverseDeriver:
    def derive_architecture_debt(self, evidence_list: list[Evidence]) -> ArchitectureDebtResult:
        """从架构 Evidence 反推设计债务。

        Args:
            evidence_list: REA 产出的架构 Evidence 列表

        Returns:
            ArchitectureDebtResult（FAIL-OPEN：空列表或解析失败返回空结果+known_gaps）
        """
```

### 3.2 输入契约：架构 Evidence 的 4 个维度

REA Evidence 通过 `provenance.analysis` 标识维度，`result` 字符串含数值。

| 维度 | provenance.analysis | result 形态 | 硬约束阈值 |
|---|---|---|---|
| 文件行数 | `line_count` / `size_audit` | `"文件 X: 1200 行"` | H-1: >800 触发 refactor |
| 出度 | `dependency_graph` / `out_degree` | `"依赖图: 33 节点, 104 边"` 或 `"出度: 12"` | H-2: >10 触发拆分 |
| 豁口数 | `known_gap_audit` / `fail_open_audit` | `"豁口: 25 项"` | H-3: except pass 需登记 / H-4: SLA 30天 |
| git 演化 | `git_history` | `"演化: 8 feat / 0 refactor"` | H-6: 禁止断裂修复 |

**解析规则**：从 `result` 用正则提取数值；提取失败 → 该维度记为 unknown，不参与债务计算，写入 known_gaps。

### 3.3 债务评分

每个维度的债务评分 = `actual / threshold`，clamp 到 [0.0, 1.0]：
- 文件行数维度：`min(lines / 800, 1.0)`
- 出度维度：`min(out_degree / 10, 1.0)`
- 豁口维度：`min(gaps / 20, 1.0)`（20 为豁口密度阈值）
- git 演化维度：`feat_count / (feat_count + refactor_count)`（无 refactor → 1.0）

**refactor 窗口触发条件**：任一维度评分 ≥ 1.0（即达到或超过阈值）。

### 3.4 输出契约

`ArchitectureDebtResult.refactor_plan` 每项：
```python
{
    "dimension": "file_size" | "out_degree" | "known_gaps" | "git_evolution",
    "target": "具体文件/模块名",
    "score": 0.95,
    "action": "拆分" | "重构" | "补 known_gap 还款" | "增加 refactor 提交",
    "priority": "P0" | "P1" | "P2",  # score≥1.0→P0, ≥0.8→P1, 其余 P2
}
```

## 4. FAIL-OPEN 行为

| 场景 | 行为 |
|---|---|
| evidence_list 为空 | 返回空 debt_dimensions + triggered_windows，known_gaps=["无架构 Evidence 输入"] |
| 单条 Evidence 解析失败 | 跳过该条，known_gaps 记录 evidence_id |
| 某维度无对应 Evidence | 该维度不计算，不触发窗口 |
| 全部解析失败 | 返回空结果，confidence=0.0，known_gaps 含全部失败原因 |

## 5. 与现有组件集成

- **位置**：`engines/reverse_deriver.py` 内新增 `ArchitectureReverseDeriver` 类（同文件两域，共享 Evidence 导入）
- **上游**：REA `investigate()` 产出 evidence 列表 → 传入
- **下游**：`reflection_engine` 架构健康度（P3-3）消费 `ArchitectureDebtResult` → 健康度报告
- **闭环**（P3-2）：post-commit 触发 REA → 本推导器 → 认知 record → 触发 refactor 窗口

## 6. 验收标准

- [ ] `ArchitectureReverseDeriver.derive_architecture_debt` 可导入
- [ ] 输入空列表 → 返回空结果 + known_gaps，不抛异常
- [ ] 4 维度 Evidence 各能正确解析数值并计算债务评分
- [ ] 超阈值维度触发对应 refactor 窗口
- [ ] 解析失败 FAIL-OPEN 不崩溃
- [ ] 与交易域 `ReverseDeriver` 接口隔离（不互相调用）
