# SPEC-L0-AGENT-TRAIN-BASE — Agent 训练基座开发 SPEC

> **版本**: v0.1 ｜ **日期**: 2026-11-02 ｜ **状态**: 📋 设计草案，M1 壳落地后立即启动 Phase 0
> **上游**: [评估报告](../../../../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-02-传统金融AI-Agent训练架构对齐评估.md)（训练算法层）· [SPEC-L0-DOMAIN-AGENTS v0.2](./SPEC-L0-DOMAIN-AGENTS-v0.1.md) §4 Phase 0（训练基座补全是壳搭建期间并行推进）· [TECH-L0-MCP v0.1](./TECH-L0-MCP-v0.1.md) §5 已落地工具测试方法
> **依赖前置**: SPEC-L0-MCP-PACKAGING v0.3 M1 基础（壳层 envelope.data 业务体透传稳定）
> **定位**: 训练基座是 MCP 壳和域内 agent 之间的**基础设施**——比 AGENT Phase A-E 更早启动
> **约束**: 单人维护 · 零 GPU · 不引入神经网络权重微调（H2）· 影子验证先行（H3 扩展）· **port 层 Principal 硬门禁（D1）** · **TRAIN-BASE Mandate 感知（D2）** · **kill_switch 语义=告警型非执行型（C2）** · **version 字段重命名（A1）**

---

## §0.5 数据流时序协议 + 核心冲突修复（2026-11-02 审计后补）

> 来源：四路外部调研 + 数据流架构冲突审计（6 Major 修复一次落地）

### 0.5.1 三观察点时序协议（B1）

壳返回体从生成到 agent 消费必须严格按以下顺序——任何 TRAIN-BASE TB1-TB5 模块的行为都必须适配此时序：

```
┌─────────────────────────────────────────────────────────────┐
│ PACKAGING Mandate 拦截（第一观察点：壳层）                      │
│   - 壳拦截所有 write 工具调用                                   │
│   - requires_mandate=true → 检查 envelope.meta.principal       │
│   - FAIL-OPEN：principal 缺失/无权限 → envelope.degraded=true   │
└────────────────────────┬────────────────────────────────────┘
                         │ Mandate 通过
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ COMM-SHADOW observe() 旁路（第二观察点：影子层）                │
│   - 只旁路读 envelope.data 业务体                                │
│   - 记录 trajectory_entry（含 strategy_config_version 快照）    │
│   - 零修改、零延迟（S3 < 1ms）                                   │
│   - envelope.meta.shadow_capable 消费后旁路                      │
└────────────────────────┬────────────────────────────────────┘
                         │ 旁路完成，envelope 不变
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ TRAIN-BASE TB1-TB5 agent 内部（第三观察点：训练层）               │
│   - TB1 PSI + KS 三重漂移检测 + drift_kill_switch（告警型）      │
│   - TB2 verify adapter（version 字段已改 data_schema_version）   │
│   - TB3 AlphaPareto 六维奖励（含 process_reward + Oracle 评分）  │
│   - TB4 Thompson Sampling（regime shift via PSI）                │
│   - TB5 GRPO evolve_step（StrategyConfig mutate）                │
│                                                                 │
│   ⚠️ TB5 mutate StrategyConfig 时必须：                           │
│   (a) 更新 config.version → envelope.meta.config_version       │
│   (b) 不修改 envelope.data 顶层 schema（H1）                     │
│   (c) COMM-SHADOW 影子观察器旁路消费 config_version 做版本对账     │
└─────────────────────────────────────────────────────────────┘
```

### 0.5.2 port 层 Principal 硬门禁（D1）

**问题**：PACKAGING Mandate 只在壳内拦截，跨域 agent 可以绕过壳直接 import port adapter 调用写接口。

**修复**（硬约束，B 级认知已记录）：

```python
# dreambuddy_l0/ports/base.py 新增 PrincipalGate 装饰器
from functools import wraps
from typing import Callable, Optional, Dict

class PrincipalMissingError(Exception):
    """直接 import port adapter 但没带 _principal 的拦截"""
    pass

def require_principal(min_role: str = "user"):
    """Port 层 Principal 硬门禁装饰器
    
    任何通过 port Protocol 调用写接口的代码必须携带 principal 信息。
    壳层自动注入 principal（从 envelope.meta.principal），
    直接 import port adapter 的调用者必须显式提供，否则抛 PrincipalMissingError。
    
    D1 硬约束：此门禁是 port 层 Python 硬门禁，不是壳层治理约束。
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            principal = kwargs.pop("_principal", None)
            if principal is None:
                raise PrincipalMissingError(
                    f"{func.__name__} requires _principal kwarg. "
                    "Agent must pass principal through shell Mandate injection, "
                    "not bypass port directly."
                )
            return func(self, *args, **kwargs)
        return wrapper
    return decorator
```

**各 port 写接口 Principal 门禁表**：

| Port | 写接口 | principal.role 允许值 |
|---|---|---|
| MemoryPort | record / verify | {user, agent_admin, trae} |
| StorePort | put / update | {user, agent_admin} |
| AnalysisPort | verify_beta_adapter（TB2 升级后） | {user, agent_admin, trae} |
| DataPort | （只读） | N/A |
| SearchPort | （只读） | N/A |

### 0.5.3 TRAIN-BASE Mandate 感知（D2）

所有 TRAIN-BASE TB1-TB5 模块签名新增 `_principal` 参数（默认 None，port 层硬门禁消费）。示例——TB1 drift_kill_switch：

```python
def drift_kill_switch(drift_level: str, context: Dict[str, Any],
                      _principal: Optional[Dict] = None) -> Dict[str, Any]:
    """Fail-closed 分层 Kill Switch（告警型，非执行型）
    
    D2: _principal 参数由壳层自动注入，port 层硬门禁消费
    C2: tiers 字段只产告警日志，**不直接执行实盘动作**
        （实盘动作由上层 orchestrator 读取 kill_switch 输出后执行）
    """
    # principal 感知：只有 principal.role ∈ {user, agent_admin} 才允许产 kill_switch
    if _principal and _principal.get("role") not in ("user", "agent_admin"):
        return {"action": "no_op", "level": 0, "reason": "principal unauthorized"}
    # ... 原有逻辑 ...
```

### 0.5.4 kill_switch 语义澄清（C2）

`drift_kill_switch()` 是**告警型函数**，**不直接执行实盘动作**：

- ✅ 做什么：产告警日志 + 返回 `{"action": "kill_switch", "tiers": [...]}` 字典
- ❌ 不做什么：不调用任何交易接口、不执行 reduce_position_50% / pause_new / halt_all
- 谁消费 kill_switch 输出：上层 orchestrator（agent 内部 loop 或人工操作员）读取返回字典后决定下一步

**为什么**：实盘风控（11/yijing/v15/止损）是硬红线，kill_switch 作为 agent 内部函数如果有执行通道会突破红线。告警型设计保留 kill_switch 的信号价值，同时把执行权留在实盘风控域本身。

### 0.5.5 竞态修复（C1）

**问题**：COMM-SHADOW 基线采集和 Phase 1 观察期不在同一个 StrategyConfig 下。

**修复**：

```
TRAIN-BASE Phase 0（TB1-TB5 开发） ────┐
                                       │ 并行但解耦
COMM-SHADOW Phase 0（基线采集） ───────┤
  → 基线采集时读取当前 StrategyConfig     │
  → 记录 config_version = "v0.1-cold"    │
  → 冻结基线（配置版本和指标快照绑定）     │
                                       │
TRAIN-BASE Phase 0 落地后，TB5 mutate ──┘
  → 每次 evolve_step 更新 config.version
  → envelope.meta.config_version 同步
  → COMM-SHADOW 影子观察器做版本对账
  → V-S5 验收：同一 config_version 下的前后指标对比
```

### 0.5.6 version 字段重命名（A1）

**问题**：envelope 顶层有 `version: "0.1"`（envelope schema 版本），TB2 Beta verify 内部有 `"version": "0.2-beta"`（verify 算法版本）—— 同名字段、不同层级、不同语义。

**修复**：

```python
# TB2 _beta_verify_adapter 返回值修改前：
return {..., "version": "0.2-beta", ...}  # 歧义

# 修改后（A1）：
return {..., "data_schema_version": "0.2-beta", ...}  # 清晰表达：data 内部算法版本
```

### 0.5.7 Oracle 验证层（B5，Two Sigma 四层分层概念采纳）

**当前阶段设计**（编码等 Phase A-C agent 产出稳定后）：

```
┌ 域内 Agent 产出 envelope ──────────┐
│   envelope.meta                    │
│     oracle_verifiable: true  ──────┤──→ Oracle Agent 独立 cross-check
│     oracle_confidence: 0.82  ←─────┤      - 不同视角（如 REA dream → 评测 agent 用 PSI 验证）
│     oracle_trace_id: "ora-xxx"     │      - 不修改 agent 输出，只标注可信度
└────────────────────────────────────┘      - FAIL-OPEN（低置信度只告警）
                                             - Oracle 输出本身过 Mandate 门
```

**与 TRAIN-BASE 集成**：TB3 AlphaPareto 六维奖励中的 `citation_diversity` 分量可以吸收 `oracle_confidence`。Oracle 不替代影子模式（影子看壳层行为，Oracle 看 agent 层行为）。

---

## §0 Executive Summary

### 0.1 为什么需要独立训练基座 SPEC

SPEC-L0-DOMAIN-AGENTS v0.2 §4 Phase 0 把训练基座补全定义为"壳搭建期间并行推进"，但五个基座（PSI/Beta verify/AlphaPareto/Thompson Sampling/GRPO）的开发顺序、TDD 验收标准、代码骨架散落在多个文档里。训练基座实际上是**壳后 agent 化的前置依赖**——没有 PSI 漂移监控，评测域 OOD 检测跑不起来；没有 Beta verify，贝叶斯 VaR 验收跑不起来。

本 SPEC 把五个基座的开发按依赖顺序排定，每个基座写清楚目标/位置/TDD 验收/算力预算。

### 0.2 依赖顺序（硬约束，先实现 PSI 才能实现后面）

```
TB1 PSI drift_detector（全域复用，零依赖）
    │
    ▼
TB2 Beta 分布 verify 升级（依赖 TB1 PSI 漂移门控）
    │
    ├──→ TB3 AlphaPareto 六维奖励定义（依赖 TB2 Beta 置信度）
    │
    ├──→ TB4 Thompson Sampling regime gate（依赖 TB1 PSI 漂移检测 regime shift）
    │
    ▼
TB5 GRPO 轻量 RL loop（依赖 TB2 + TB3 + TB4，作为奖励函数组件）
```

### 0.3 与演进路线的位置

```
MCP 壳层 ──── 并行 ──── TB1 PSI → TB2 Beta → TB3/TB4 → TB5 GRPO
    │                                                     │
    ▼                                                     ▼
AGENT Phase A（认知 agent 参数化）←── TB1+TB2 已就绪 ──────┘
    │
    ▼
AGENT Phase B/C/D/E ──→ AgentMail 影子 ──→ 激活
```

---

## §1 TB1：PSI drift_detector.py（全域漂移监控，20 行代码）

### 1.1 目标

PSI（Population Stability Index）小团队友好型漂移监控方案（SPEC-L0-DOMAIN-AGENTS v0.2 H8：阈值硬编码，不得运行时动态调）。全域复用——认知、评测、语义、数据四域 agent 都用同一个 drift_detector.py。

**为什么先做 PSI**：PSI 是 20 行 Python 的纯统计检验，零依赖（只用 numpy），是所有域 agent 漂移检测的基础设施。没有 PSI，评测域 OOD 检测、语义域实体解析监控、数据域质量漂移告警都做不了。

### 1.2 位置

```
4-MEMORY/9-工具与接口/
└── drift_detector.py       # 新增，全域 import 复用
    test_drift_detector.py  # 新增（与实现同目录，绝对 import）
```

### 1.3 代码骨架

```python
# drift_detector.py（~50 行含注释+类型标注）
from __future__ import annotations
from typing import List, Tuple
import numpy as np

# H8 硬编码阈值（不可 env override，不得运行时动态调）
PSI_STABLE = 0.1           # < 0.1: 稳定
PSI_MINOR_DRIFT = 0.25     # 0.1-0.25: 轻微漂移
# > PSI_MINOR_DRIFT: 严重漂移

def psi(expected: List[float], actual: List[float], bins: int = 10) -> float:
    """Population Stability Index — 漂移监控
    
    PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))
    
    H8 硬约束：bins 固定 10，不得动态调
    
    Args:
        expected: 历史基线分布（如历史 verify 置信度分布）
        actual: 当前观测分布（如最近 10 次 verify 置信度分布）
        bins: 直方图分箱数（硬编码 10，不暴露为参数）
    
    Returns:
        PSI 值 ∈ [0, +∞)
    """
    # 直方图分箱
    exp_hist = np.histogram(expected, bins=bins, density=True)[0]
    act_hist = np.histogram(actual, bins=bins, density=True)[0]
    
    # 归一化 → 百分比
    exp_pct = np.clip(exp_hist / exp_hist.sum(), 1e-6, None)
    act_pct = np.clip(act_hist / act_hist.sum(), 1e-6, None)
    
    # PSI 公式
    return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))


def classify_drift(psi_value: float) -> str:
    """PSI 值 → 漂移等级
    
    H8 硬约束：阈值硬编码，不可 env override
    """
    if psi_value < PSI_STABLE:
        return "stable"
    elif psi_value < PSI_MINOR_DRIFT:
        return "minor_drift"
    else:
        return "severe_drift"


# === 外部调研增量 B1：三重漂移检测 + Kill Switch ===
# 来源：Barclays/JPMorgan 金融工程 agent 三重漂移检测（PSI + K-S + VaR）
# 综合评估 §2.1

from scipy.stats import ks_2samp

def ks_test(expected: List[float], actual: List[float], alpha: float = 0.01) -> Tuple[float, bool]:
    """Kolmogorov-Smirnov 两样本检验 — 第二漂移门（外部调研增量 B1）
    
    - 零假设 H0：expected 和 actual 来自同一分布
    - p-value < alpha → 拒绝 H0 → 显著漂移
    
    H8 硬约束：alpha 硬编码 0.01，不可 env override
    """
    statistic, p_value = ks_2samp(expected, actual)
    return float(statistic), p_value < alpha


def classify_drift_triple(psi_value: float, ks_drifted: bool) -> str:
    """三重漂移检测综合判定（PSI + K-S，B1）
    
    PSI stable + KS not drifted → "stable"
    PSI minor + KS not drifted → "minor_drift"  
    PSI severe 或 (PSI minor + KS drifted) → "severe_drift"
    """
    if psi_value < PSI_STABLE and not ks_drifted:
        return "stable"
    elif psi_value >= PSI_MINOR_DRIFT or (psi_value >= PSI_STABLE and ks_drifted):
        return "severe_drift"
    else:
        return "minor_drift"


def drift_kill_switch(drift_level: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Fail-closed 分层 Kill Switch（外部调研增量 B6，行业标准）
    
    触发条件链：
      severe_drift → Kill Switch 触发
      - Level 1 Warning: 日志告警
      - Level 2 Kill Switch: 降仓 → 停新开 → 强平（由调用方消费 action）
    """
    if drift_level == "stable":
        return {"action": "no_op", "level": 0}
    elif drift_level == "minor_drift":
        return {"action": "log_alert", "level": 1, "reason": context.get("reason"), "trace_id": context.get("trace_id")}
    else:
        return {"action": "kill_switch", "level": 2, "tiers": ["reduce_position_50%", "pause_new", "halt_all"], "reason": context.get("reason"), "trace_id": context.get("trace_id")}
```

### 1.4 TDD 验收（RED → GREEN → REFACTOR，B1 增量 +3 条用例，共 9 条）

| 步骤 | 测试用例 | 预期 |
|---|---|---|
| **RED 1** | 两组完全相同的分布 `[0.5, 0.5, 0.5, ...]` vs `[0.5, 0.5, 0.5, ...]` | psi ≈ 0.0，classify_drift = "stable" |
| **RED 2** | 轻微漂移 `[0.5, 0.5, 0.5]` vs `[0.45, 0.5, 0.55]` | 0.05 ≤ psi < 0.1，classify = "stable" |
| **RED 3** | 中等漂移 `[0.5, 0.5, 0.5]` vs `[0.3, 0.5, 0.7]` | 0.1 ≤ psi < 0.25，classify = "minor_drift" |
| **RED 4** | 严重漂移 `[0.5, 0.5, 0.5]` vs `[0.1, 0.5, 0.9]` | psi ≥ 0.25，classify = "severe_drift" |
| **RED 5** | 边界测试：psi = 0.1 exactly | classify = "minor_drift"（0.1 严格归入中档；0.099999999 → stable，容差 1e-9，复用 VM-1792148857896） |
| **RED 6** | 边界测试：psi = 0.25 exactly | classify = "severe_drift"（0.25 严格归入重档；0.249999999 → minor_drift，同上） |
| **RED 7** ⭐B1 | KS 检验两组明显不同分布 [0-1] vs [4-5] | p-value < 0.01，ks_drifted = True |
| **RED 8** ⭐B1 | classify_drift_triple(psi=0.15, ks_drifted=True) | "severe_drift"（PSI minor 但 KS drifted → severe） |
| **RED 9** ⭐B6 | drift_kill_switch("severe_drift", {"reason": "PSI=0.3, KS=p=0.001", "trace_id": "t1"}) | action="kill_switch", level=2 |
| **RED 10** ⭐B1 | classify_drift_triple：stable+KS / minor+KS / severe+KS | minor_drift / severe_drift / severe_drift（KS 命中升一档） |
| **RED 11** | 上表 RED 9 的字段级断言（action/level/trace_id + stable→no_op） | action="kill_switch", level=2, trace_id="t1" |

**验收标准**：pytest 12/12 passed，H8 硬约束在代码中明确标注，阈值无 env override 路径。

### 1.5 算力

| 项 | 值 |
|---|---|
| 计算时间（PSI N=100） | < 1ms |
| 计算时间（KS N=100） | < 1ms |
| 内存 | < 100KB |
| GPU | 不需要 |
| 依赖 | numpy + scipy.stats |

---

## §2 TB2：Beta 分布 verify 升级（verify 从二项式 → Beta(α, β)）

### 2.1 目标

当前 `cognitive_loop_entry.verify()` 是二项式更新（success=True → confidence + Δ）。Beta 分布升级后支持**部分成功/部分失败**（如"10 次调用 7 次成功 2 次超时 1 次调用方未处理"），并为 TB3 AlphaPareto 奖励函数和 TB5 PolicySelectLoop 提供置信度分布基础。

**为什么依赖 TB1 PSI**：verify 的历史分布基线需要 PSI 监控——如果 verify 的 Beta 分布漂移了（PSI > 0.25），说明认知系统整体置信度结构变了，应该触发反思。

### 2.2 位置（含 Major #2 修复：adapter 层桥接旧 verify 签名）

```
4-MEMORY/9-工具与接口/
├── cognitive_interfaces.py   # 修改：新增 BetaState / VerifyResult / verify_beta
├── cognitive_loop_entry.py   # 新增 _beta_verify_adapter() + Beta 后验持久化 + verify() 内部调用
├── drift_detector.py         # TB1 新增，import 依赖（不修改）
└── test_beta_verify.py       # 新增（与实现同目录，绝对 import）
```

**adapter 层设计**（Major #2 修复 — 骨架签名 vs 实际代码 `verify(memory_id, success: bool, known_gaps_update)` 的桥接）：

```python
# _beta_verify_adapter（cognitive_loop_entry.py 内部方法，零外部 API 变化）
def _beta_verify_adapter(
    self,
    memory_id: str,
    success: bool,                               # 旧签名 bool → adapter 内部转 float
    known_gaps_update: Optional[List[str]] = None,  # 旧签名透传
    drift_detected: bool = False,               # TB1 新增参数，adapter 内部消费
) -> Dict[str, Any]:
    """Adapter：桥接旧 verify(success: bool) → Beta verify(success_rate: float)
    
    - success=True → success_rate=1.0
    - success=False → success_rate=0.0
    - known_gaps_update 原样透传到 envelope.data（不修改 API）
    - drift_detected 控制 Bayesian reset
    - 返回 Dict[str, Any]（与旧 verify 返回类型一致，零 API 变化）
    """
    success_rate = 1.0 if success else 0.0
    beta_result = verify_beta(
        memory_id=memory_id,
        success_rate=success_rate,
        evidence_confidence=...,       # PoE trust 查询结果
        drift_detected=drift_detected,
    )
    # 包装成旧 verify 返回格式（envelope.data 扩展，H1 壳零感知）
    return {
        "memory_id": memory_id,
        "confidence": beta_result.data["confidence"],
        "known_gaps": known_gaps_update or [],
        "beta_alpha": beta_result.data["beta_alpha"],
        "beta_beta": beta_result.data["beta_beta"],
        "drift_detected": drift_detected,
        "data_schema_version": "0.2-beta",  # A1 重命名：避免与 envelope 顶层 version 歧义
    }
```

### 2.3 代码骨架

```python
# Beta 分布状态持久化（per memory）
class BetaState:
    """Beta(α, β) 置信度分布"""
    def __init__(self, alpha: float = 1.0, beta: float = 1.0):
        self.alpha = alpha  # 成功计数
        self.beta = beta    # 失败计数
    
    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)
    
    def update(self, success_rate: float, weight: float = 1.0) -> "BetaState":
        """部分成功更新（核心改进：支持 success_rate ∈ [0, 1]，不只是 bool）
        
        success_rate=1.0 → 全成功（等价旧 verify success=True）
        success_rate=0.0 → 全失败（等价旧 verify success=False）
        success_rate=0.7 → 70% 成功
        """
        delta_alpha = success_rate * weight
        delta_beta = (1.0 - success_rate) * weight
        return BetaState(self.alpha + delta_alpha, self.beta + delta_beta)


# verify 方法升级
def verify_beta(memory_id: str, success_rate: float, 
                evidence_confidence: float = 0.5,
                drift_detected: bool = False) -> VerifyResult:
    """verify 升级为 Beta 分布更新
    
    Args:
        success_rate: [0, 1] 部分成功率（核心改进）
        evidence_confidence: PoE 证据链置信度，修正 success_rate
        drift_detected: TB1 PSI 漂移检测结果 → 漂移时重置先验（Bayesian reset on regime shift）
    """
    # 1. PSI 漂移时重置先验（TB1 依赖）
    if drift_detected:
        beta_state = BetaState(alpha=1.0, beta=1.0)  # 回到无信息先验
    else:
        beta_state = _load_beta_state(memory_id)     # 从认知库加载
    
    # 2. PoE 证据修正 success_rate
    adjusted_rate = success_rate * evidence_confidence
    
    # 3. Beta 分布更新
    new_state = beta_state.update(adjusted_rate)
    
    # 4. 持久化
    _save_beta_state(memory_id, new_state)
    
    # 5. 返回 verify 结果（信封 schema 零变化，H1）
    return VerifyResult(
        ok=True,
        data={
            "confidence": new_state.mean,      # 对外暴露 mean，兼容旧 verify 接口
            "beta_alpha": new_state.alpha,     # 内部细节，envelope.data 扩展
            "beta_beta": new_state.beta,        # 同上
            "drift_detected": drift_detected,   # TB1 依赖回传
            "data_schema_version": "0.2-beta",  # A1 重命名：避免与 envelope 顶层 version 歧义
        }
    )
```

### 2.4 TDD 验收（RED → GREEN → REFACTOR）

| 步骤 | 测试用例 | 预期 |
|---|---|---|
| **RED 1** | 升级前 legacy verify success=True → confidence 0.5 → verify 后 mean ≥ 0.7 | 升级后 verify success=True → Beta mean = alpha/(alpha+beta) ≥ 0.7，**零业务回归** |
| **RED 2** | Beta(1,1) → success_rate=1.0 → Beta(2,1) → mean = 0.667 | 纯 Beta 分布更新正确性 |
| **RED 3** | Beta(2,1) → success_rate=0.7 → 计算 delta_alpha=0.7, delta_beta=0.3 → Beta(2.7,1.3) → mean = 0.675 | 部分成功更新正确性 |
| **RED 4** | drift_detected=True → Beta 状态重置为 Beta(1,1) | PSI 漂移触发 Bayesian reset |
| **RED 5** | PoE evidence_confidence=0.8 → success_rate=0.7 → adjusted_rate=0.56 | PoE 修正正确性 |
| **RED 6** | envelope 返回体与旧 verify schema 兼容（data 字段含 confidence 键） | **H1 壳零感知**：cognitive_mcp_server.py return 行零改动 |
| **RED 7** | 连续两次 verify success=True | 第二次 Beta α 在第一次后验基础上累加（持久化生效） |
| **RED 8** | adapter 桥接 `success=False` + `drift_detected=True` | Beta(1,2)、data_schema_version="0.2-beta" |

**零业务回归实现口径**：无持久化 Beta 后验时，以记忆现有 `confidence` 作为先验种子（伪计数总量=1，即 `Beta(c, 1-c)`），因此 confidence 0.5 + 一次全成功 → `Beta(1.5,0.5)` → mean 0.75 ≥ 0.7（RED 1）；有后验后只做正常 Beta 累加。

**验收标准**：pytest 8/8 passed + 旧 verify 行为零回归（返回字典保留全部旧键）+ envelope schema 零变化。

### 2.5 算力

| 项 | 值 |
|---|---|
| 计算时间（单次 verify） | < 1μs |
| 内存 | 每个记忆 < 100B |
| GPU | 不需要 |
| 依赖 | TB1 drift_detector.py（PSI 漂移检测） |

---

## §3 TB3：AlphaPareto 六维奖励定义（认知/评测共用）

### 3.1 目标

为 TB5 PolicySelectLoop 提供多目标奖励函数，**替代手动权重调优**。六维向量奖励沿 Pareto 前沿优化（AlphaPareto，arXiv 2609.34188；引用编号 2026-11-03 本地联网复核，原 2504 有误）。

**为什么依赖 TB2**：P1（P_verify_success）和 P3（psi_stability）的计算依赖 TB2 Beta verify 的置信度分布和 TB1 PSI 漂移值。

### 3.2 位置

```
4-MEMORY/9-工具与接口/
├── training_reward.py       # 新增，AlphaPareto 六维奖励定义
└── test_alpha_pareto.py     # 新增（与实现同目录，绝对 import）
```

### 3.3 代码骨架

```python
# training_reward.py（~40 行 + 注释）
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, List
from cognitive_interfaces import BetaState  # TB2（绝对 import，本目录非包）

# 注：PSI 数值由调用方传入（psi_value），training_reward.py 不直接 import drift_detector


@dataclass
class RewardComponents:
    """AlphaPareto 六维奖励分量（B2 增量：过程奖励 + 转移平滑度 + Oracle 评分吸收）
    
    来源：外部调研 — OpenAI AgentPRM / Meta HiPRAG 实证「过程奖励 > 纯结果奖励」
    来源：外部调研 — Two Sigma Oracle 验证层（B5）吸收 oracle_confidence
    """
    p_verify_success: float      # 维度 1：TB2 Beta verify mean
    p_recall_hit: float          # 维度 2：同类事件 recall 命中率
    psi_stability: float         # 维度 3：1 - PSI(三重检测综合值) → 漂移越小越稳定
    citation_diversity: float    # 维度 4：PoE known_gaps 越少奖励越低 + 跨域引用数加权 + Oracle oracle_confidence 吸收
    process_reward: float        # 维度 5（B2 新增）：中间 step 可验证子目标奖励（Query→Search→Read→Synthesize 每步）
    transition_smoothness: float # 维度 6（B2 新增）：相邻 step 的 state 转移平滑度（transition probability entropy）


def compute_reward(
    beta_state: BetaState,         # TB2 依赖
    psi_value: float,              # TB1 依赖
    recall_hits: int,
    recall_total: int,
    known_gaps_count: int,
    cross_domain_refs: int,
    process_reward: float = 0.0,         # 维度 5：上游 step 奖励（缺省中性）
    transition_smoothness: float = 1.0,  # 维度 6：转移平滑度（缺省最平滑）
) -> RewardComponents:
    """AlphaPareto 六维奖励定义（维度定义唯一事实源；DOMAIN-AGENTS v0.2 §4 只引用不重复定义）
    
    P_verify_success = TB2 Beta mean
    P_recall_hit = recall_hits / recall_total
    psi_stability = 1 - PSI / PSI_MAX_CAP
    citation_diversity = (1 - known_gaps_count / 10) * (1 + 0.1 * cross_domain_refs)
    """
    p_verify = beta_state.mean
    p_recall = recall_hits / max(recall_total, 1)
    psi_cap = 1.0  # PSI > 1.0 按 1.0 算，防极端值
    psi_stab = max(0.0, 1.0 - min(psi_value, psi_cap))
    citation = max(0.0, (1.0 - min(known_gaps_count, 10) / 10.0)) * (1.0 + 0.1 * cross_domain_refs)
    
    return RewardComponents(
        p_verify_success=p_verify,
        p_recall_hit=p_recall,
        psi_stability=psi_stab,
        citation_diversity=citation,
        process_reward=process_reward,
        transition_smoothness=transition_smoothness,
    )


# 初版权重（六维，和=1.0）；影子期按 §6.5 校准协议回测后改常量，禁止运行期动态调整
REWARD_WEIGHTS = (0.25, 0.20, 0.20, 0.15, 0.12, 0.08)


def pareto_score(reward: RewardComponents, weights: Tuple[float, ...] = REWARD_WEIGHTS) -> float:
    """Pareto 前沿综合评分（初版用六维加权和，后续升级为 MAP 流形感知）"""
    components = [reward.p_verify_success, reward.p_recall_hit,
                  reward.psi_stability, reward.citation_diversity,
                  reward.process_reward, reward.transition_smoothness]
    return sum(w * c for w, c in zip(weights, components))
```

### 3.4 TDD 验收（RED → GREEN → REFACTOR）

| 步骤 | 测试用例 | 预期 |
|---|---|---|
| **RED 1** | 理想情况：Beta mean=0.9, PSI=0.05, recall 10/10, known_gaps=0, refs=5 | pareto_score ≥ 0.9 |
| **RED 2** | 差情况：Beta mean=0.3, PSI=0.5, recall 2/10, known_gaps=5, refs=0（process_reward=0.0、transition_smoothness=0.0，六维均取差） | pareto_score ≤ 0.3 |
| **RED 3** | PSI > 1.0 边界 | psi_stability = 0.0（cap 生效） |
| **RED 4** | known_gaps > 10 边界 | citation_diversity 下限 0.0（cap 生效） |
| **RED 5** | recall_total=0 边界 | p_recall_hit = 0.0（除零保护） |
| **RED 6** | 权重完整性：`len(REWARD_WEIGHTS) == 6` 且 `sum(REWARD_WEIGHTS) == 1.0` | 返回 True（容差 1e-9） |

**验收标准**：pytest 6/6 passed（含 RED 6 六维权重完整性）。

### 3.5 算力

| 项 | 值 |
|---|---|
| 计算时间 | < 10μs |
| 内存 | 常量级 |
| 依赖 | TB1 drift_detector + TB2 BetaState |

---

## §4 TB4：Thompson Sampling regime gate（美林时钟四段 = 四 arm）

### 4.1 目标

为 40-周期神经网络系统和 REA 做梦器提供 regime shift 检测 + optimal arm 选择。美林时钟四段（避险/商品/债券/风险）= Thompson Sampling 四个 arm，每个 arm 维持 Beta 分布（TB2 依赖），regime shift 时 PSI 漂移（TB1 依赖）→ 重置先验。

**为什么依赖 TB1 + TB2**：Beta 分布来自 TB2，regime shift 检测来自 TB1 PSI。

### 4.2 位置（含 Major #1 修复：与 TB5 GRPO import 路径统一）

**regime_gate.py 放在 `4-MEMORY/9-工具与接口/`**（与 TB5 PolicySelectLoop 同目录，同目录内一律**绝对 import**），40-周期神经网络系统 通过绝对 import `from cognitive_loop_entry import ThompsonSamplingRegimeGate` 消费。

> **import 规约（2026-11-03 修订，P6 复核连带项）**：`4-MEMORY/9-工具与接口/` **不是 Python 包**（目录下无 `__init__.py`），所有模块一律使用**绝对 import**（如 `from drift_detector import compute_psi`），路径由宿主注入（`cognitive_mcp_server.py` 的函数级 sys.path）或 pytest rootdir prepend 负责。**禁止相对 import**——会报 `ImportError: attempted relative import with no known parent package`。云端现网 `drift_detector.py` 与 `test_drift_detector.py` 已按此约定实现。

```
4-MEMORY/9-工具与接口/
├── drift_detector.py         # TB1（PSI 漂移检测，TB4 依赖）
├── cognitive_loop_entry.py   # TB2（Beta verify 升级）
├── training_reward.py        # TB3（AlphaPareto 六维奖励）
├── regime_gate.py            # TB4 新增，Thompson Sampling regime gate ← 统一位置
└── grpo_evolution.py         # TB5 新增，PolicySelectLoop（`from regime_gate import ...` 绝对 import ✅）
tests/
└── test_regime_gate.py       # 新增
```

### 4.3 代码骨架

```python
# regime_gate.py（~60 行）
from __future__ import annotations
from typing import List, Tuple
import random
import math


# 美林时钟四段 = 四 arm
REGIME_ARMS = ["defensive", "commodity", "bond", "risk"]


class ThompsonSamplingRegimeGate:
    """Thompson Sampling regime gate（美林时钟四段 = 四 arm）
    
    每个 arm 维持 Beta(α, β) 分布：
      α = 该 regime 下策略成功次数
      β = 该 regime 下策略失败次数
    
    选择：random.betavariate(α, β) 对每个 arm 采样，选采样值最高的 arm
    漂移检测：PSI > 0.25 → 所有 arm 重置为 Beta(1, 1)（Bayesian reset）
    """
    
    def __init__(self, arms: List[str] = REGIME_ARMS):
        self.arms = arms
        # 每个 arm 的 Beta 分布：初始无信息先验 Beta(1, 1)
        self.alpha = {arm: 1.0 for arm in arms}
        self.beta = {arm: 1.0 for arm in arms}
    
    def select_regime(self) -> str:
        """Thompson Sampling 选最优 regime"""
        # 对每个 arm 做 Beta 采样
        samples = {
            arm: random.betavariate(self.alpha[arm], self.beta[arm])
            for arm in self.arms
        }
        # 选采样值最高的 arm
        return max(samples, key=samples.get)
    
    def update(self, arm: str, success_rate: float, drift_detected: bool = False) -> None:
        """更新 arm 的 Beta 分布
        
        Args:
            arm: 被选中的 regime
            success_rate: [0, 1] 部分成功率
            drift_detected: TB1 PSI 漂移 → 所有 arm 重置先验
        """
        if drift_detected:
            # TB1 漂移 → Bayesian reset 所有 arm
            for a in self.arms:
                self.alpha[a] = 1.0
                self.beta[a] = 1.0
            return
        
        self.alpha[arm] += success_rate
        self.beta[arm] += (1.0 - success_rate)
    
    def get_confidence(self, arm: str) -> float:
        """arm 的置信度 = Beta mean（TB2 依赖）"""
        return self.alpha[arm] / (self.alpha[arm] + self.beta[arm])
```

### 4.4 TDD 验收

| 步骤 | 测试用例 | 预期 |
|---|---|---|
| **RED 1** | 初始 Beta(1,1) → 选 arm → 四 arm 被选中概率 ≈ 0.25（1000 次采样卡方检验 p > 0.05） | 无偏性 |
| **RED 2** | arm "risk" 连续 10 次 success_rate=1.0 → Beta(11, 1) → select_regime 选 "risk" 概率 > 0.8（1000 次采样） | 收敛性 |
| **RED 3** | drift_detected=True → 所有 arm 重置为 Beta(1, 1) | Bayesian reset |
| **RED 4** | success_rate=0.5 部分更新 → Beta(2.5, 1.5) → get_confidence = 0.625 | 部分成功支持 |

**验收标准**：pytest 4/4 passed。

### 4.5 算力

| 项 | 值 |
|---|---|
| 单次 select_regime | < 10μs |
| 单次 update | < 1μs |
| GPU | 不需要 |
| 依赖 | TB1（PSI drift）+ TB2（Beta 分布） |

---

## §5 TB5：PolicySelectLoop（GRPO 借喻；冻结权重，调策略输出格式）

> **术语声明（P3 修订，2026-11-03）**：本节沿用 "GRPO" 仅作**借喻**。TB5 实现为**冻结权重 + 候选策略配置 argmax 选择**（`evaluate_config` → `argmax`），无梯度更新、无策略网络，与业界 GRPO（Group Relative Policy Optimization）定义不同。对外表述统一用 **PolicySelectLoop / ConfigEvolution**；代码类名 `GRPOEvolutionLoop` 为历史兼容保留。

### 5.1 目标

**冻结 LLM 权重，只调策略输出格式**——这是 H2 硬约束（不引入神经网络权重微调）。奖励函数用 TB3 AlphaPareto 六维向量，regime gate 用 TB4 Thompson Sampling，漂移检测用 TB1 PSI。

GRPO（Group Relative Policy Optimization）选择理由：无 critic、训练快、零 GPU、金融友好（Alpha-R1 arXiv 2512.23515 验证市场客观反馈可替代人类偏好；编号 2026-11-03 复核，原 2507 有误）。

### 5.2 位置

```
4-MEMORY/9-工具与接口/
└── grpo_evolution.py        # 新增，GRPO 轻量 RL loop
tests/
└── test_grpo_loop.py        # 新增
```

### 5.3 代码骨架

```python
# grpo_evolution.py（~120 行 + 注释）
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json
from drift_detector import classify_drift, PSI_MINOR_DRIFT, PSI_STABLE  # TB1（绝对 import）
from cognitive_interfaces import BetaState  # TB2
from training_reward import compute_reward, pareto_score, RewardComponents  # TB3
from regime_gate import ThompsonSamplingRegimeGate  # TB4


@dataclass
class StrategyConfig:
    """Agent 策略配置（冻结权重，只调格式）
    
    注意：H2 硬约束 — 这不是神经网络权重，是 JSON 格式的输出偏好配置
    训练算法只调整这些字段的值（reorder / known_gaps 调整）
    """
    field_order: List[str] = field(default_factory=list)          # JSON 字段输出顺序
    known_gaps_threshold: int = 5                                  # known_gaps ≤ 此值才算合格
    evidence_min_confidence: float = 0.5                           # PoE 证据链最低置信度
    max_cross_domain_refs: int = 10                                # 跨域引用上限（防膨胀）
    process_weight: float = 0.3                                    # 维度 5 process_reward 权重（B2 六维奖励）
    transition_weight: float = 0.2                                 # 维度 6 transition_smoothness 权重（B2 六维奖励）
    oracle_weight: float = 0.2                                     # Oracle oracle_confidence 吸收权重（B5）
    version: str = "v0.1"


# === B3 增量：STRATEGY_CONFIG_SCHEMA 完整 JSON schema ===
# 来源：外部调研 Anthropic GRPO 策略输出格式约束
# 完整 JSON schema（用 jsonschema 2020-12 draft，实现时直接 json.dumps 写常量即可）
STRATEGY_CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://dreambuddy-v2.local/schemas/strategy-config.json",
    "title": "Agent Strategy Config Schema v0.1",
    "description": "冻结权重 Agent 的策略输出格式配置（H2 硬约束：不是神经网络权重，是格式偏好）",
    "type": "object",
    "required": [
        "field_order",
        "known_gaps_threshold",
        "evidence_min_confidence",
        "max_cross_domain_refs",
        "process_weight",
        "transition_weight",
        "oracle_weight",
        "version",
    ],
    "additionalProperties": False,  # H2 硬约束扩展：不允许未知字段注入
    "properties": {
        "field_order": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": [
                    "ok",
                    "data",
                    "source",
                    "timestamp",
                    "degraded",
                    "meta",
                    "trace_id",
                    "idempotency_key",
                    "error_code",
                    "data_schema_version",
                ],
            },
            "description": "JSON 字段输出顺序。必须是 SPEC-L0 v0.3 envelope.data 已定义字段的子集。至少 1 个。",
        },
        "known_gaps_threshold": {
            "type": "integer",
            "minimum": 0,
            "maximum": 20,
            "default": 5,
            "description": "PoE known_gaps ≤ 此值才算合格。超过则在 Pareto 计算中被惩罚。0 表示 known_gaps 必须为 0 才算合格。",
        },
        "evidence_min_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.5,
            "description": "PoE 证据链最低置信度（Beta verify mean）。小于此值的 verify 结果在 Pareto 中被降权。精确到 2 位小数。",
        },
        "max_cross_domain_refs": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "default": 10,
            "description": "跨域引用数上限。超过则 citation_diversity 分量封顶，防止引用膨胀。",
        },
        "process_weight": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.3,
            "description": "维度 5 process_reward 在 Pareto 综合评分中的权重。权重加总必须 = 1.0（与其他 5 维）。",
        },
        "transition_weight": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.2,
            "description": "维度 6 transition_smoothness 在 Pareto 综合评分中的权重。",
        },
        "oracle_weight": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.2,
            "description": "Oracle oracle_confidence 吸收权重。Oracle 未启用时自动归零。",
        },
        "version": {
            "type": "string",
            "pattern": "^v(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$",
            "default": "v0.1",
            "description": "策略配置版本号（semver 简化版：v主.次）。TB5 evolve_step 每次 mutate 必须 bump 次版本。",
        },
    },
    # 约束：六个权重加总必须 = 1.0（允许 1e-6 浮点 epsilon）
    # 实现时在 GRPOEvolutionLoop.evaluate_config 里断言，不用 JSON schema 的 oneOf/allOf（太复杂）
}


# === B5 增量：Oracle 验证层完整设计 ===
# 来源：外部调研 Two Sigma 四层 AI 角色分层（Advisory / Oracle / Operational / Agentic）
# 综合评估 §3

class OracleVerificationLayer:
    """Oracle 验证层 — 独立 cross-check agent 输出的只读验证器
    
    与 Two Sigma 四层分层对齐：
      Two Sigma → 我们的架构
      ──────────────────────────
      Advisory 建议层 → 域内 agent 分析层（SPEC-L0-DOMAIN-AGENTS v0.2）
      Oracle 验证层  → 【本类】独立 cross-check（B5 新增）
      Operational    → MCP 壳工具面（SPEC-L0-MCP-PACKAGING v0.3）
      Agentic 协调层 → MCP shell orchestration（TECH-L0-MCP v0.1）
    
    约束：
      - 纯 read-only，不修改 agent 输出
      - FAIL-OPEN：低置信度只告警，不阻塞主流程（H4 约束）
      - Oracle 输出本身过 Mandate 门（D1 约束）
      - oracle_confidence 吸收进 TB3 citation_diversity 奖励分量
      - 不替代 COMM-SHADOW 影子模式（影子看壳层行为，Oracle 看 agent 层行为）
    """
    
    # Oracle 交叉验证视角注册表（可扩展）
    # 每个视角 = 独立的 cross-check 函数
    PERSPECTIVES = {
        "rea_dream_psi_verify": {
            "description": "REA 做梦结论 → 评测 agent 用 PSI 漂移验证",
            "input": "envelope.data.rea_dream_conclusion",
            "verify_with": "eval_agent.run_psi_check",
            "min_confidence": 0.7,  # oracle_confidence < 0.7 → 告警
        },
        "cognitive_recall_consistency": {
            "description": "认知 recall 结果 → Oracle 用独立向量索引交叉检索",
            "input": "envelope.data.recall_results",
            "verify_with": "independent_recall.run",
            "min_confidence": 0.6,
        },
        "semantic_entity_quality": {
            "description": "语义域新实体 → Oracle 用 PSI 验证实体解析质量漂移",
            "input": "envelope.data.new_entities",
            "verify_with": "semantic_agent.run_psi_check",
            "min_confidence": 0.65,
        },
    }
    
    def verify(
        self,
        envelope: Dict,
        agent_id: str,
        _principal: Optional[Dict] = None,  # D2 Mandate 感知
    ) -> Dict[str, Any]:
        """执行 Oracle cross-check
        
        Returns:
            oracle_result = {
                "oracle_confidence": float,        # 0.0 ~ 1.0
                "oracle_trace_id": str,            # 独立 trace，前缀 ora-
                "perspectives_checked": [str],      # 用了哪些视角
                "perspectives_passed": [str],       # 通过哪些视角
                "alert_reason": Optional[str],      # 低置信度时的告警原因
            }
        
        D1/D2: _principal 参数由壳层注入，port 层门禁消费
        FAIL-OPEN: Oracle 自身异常 → oracle_confidence=0.5 + alert_reason="oracle_error"
        """
        pass  # Phase A-C agent 产出稳定后实现

    def should_alert(self, oracle_result: Dict[str, Any],
                     min_confidence: float = 0.65) -> bool:
        """Oracle 结果 → 是否触发告警
        
        告警阈值：oracle_confidence < min_confidence
        告警渠道：cognitive record（tags 含 "oracle_alert"）+ 日志
        不阻塞主流程（FAIL-OPEN）
        """
        return oracle_result["oracle_confidence"] < min_confidence
```


class GRPOEvolutionLoop:
    """GRPO 轻量 RL 进化 loop（冻结权重，只调策略格式）
    
    依赖：TB1 + TB2 + TB3 + TB4
    算力：零 GPU，秒级
    """
    
    def __init__(
        self,
        candidate_configs: List[StrategyConfig],
        regime_gate: ThompsonSamplingRegimeGate,  # TB4
    ):
        self.candidates = candidate_configs
        self.regime_gate = regime_gate
        self.current_config = candidate_configs[0]  # 初始选第一个
        self.history: List[Dict] = []  # 训练历史
    
    def evaluate_config(
        self,
        config: StrategyConfig,
        beta_state: BetaState,  # TB2
        psi_value: float,       # TB1
        recall_hits: int,
        recall_total: int,
        known_gaps_count: int,
        cross_domain_refs: int,
    ) -> float:
        """评估某个策略配置的 Reward
        
        1. 用配置过滤 known_gaps / evidence_confidence
        2. 用 TB3 AlphaPareto 算六维奖励
        3. 用 pareto_score 加权综合
        """
        # 应用策略配置过滤
        filtered_gaps = min(known_gaps_count, config.known_gaps_threshold)
        filtered_refs = min(cross_domain_refs, config.max_cross_domain_refs)
        
        reward = compute_reward(
            beta_state=beta_state,
            psi_value=psi_value,
            recall_hits=recall_hits,
            recall_total=recall_total,
            known_gaps_count=filtered_gaps,
            cross_domain_refs=filtered_refs,
        )
        return pareto_score(reward)
    
    def evolve_step(
        self,
        beta_state: BetaState,
        psi_value: float,
        recall_hits: int,
        recall_total: int,
        known_gaps_count: int,
        cross_domain_refs: int,
    ) -> Optional[StrategyConfig]:
        """执行一轮 GRPO 进化
        
        Returns:
            改进后的策略配置；如果当前最优则返回 None（保持不劣化）
        
        H4 硬约束：默认 FAIL-OPEN，单轮失败不阻塞主流程
        """
        try:
            # 1. TB1 漂移检测
            drift_level = classify_drift(psi_value)
            
            # 2. TB4 regime gate 选最优 regime
            regime = self.regime_gate.select_regime()
            self.regime_gate.update(
                arm=regime,
                success_rate=beta_state.mean,
                drift_detected=(drift_level != "stable"),
            )
            
            # 3. 候选策略评估（含当前策略，Dream-RSI 不劣化保证）
            all_configs = [self.current_config] + self.candidates
            scores = [
                (c, self.evaluate_config(
                    c, beta_state, psi_value, recall_hits, recall_total,
                    known_gaps_count, cross_domain_refs,
                ))
                for c in all_configs
            ]
            
            # 4. argmax 选最优（Dream-RSI argmax V 选择机制）
            best_config, best_score = max(scores, key=lambda x: x[1])
            current_score = dict(scores)[self.current_config]
            
            # 5. 不劣化保证（核心原则）
            if best_config == self.current_config or best_score >= current_score:
                self.current_config = best_config
                return best_config
            else:
                # 改进策略没有优于当前 → 保持当前
                return None
        
        except Exception as e:
            # H4 硬约束：FAIL-OPEN，策略自动回退上一稳定版本
            self.history.append({"error": str(e), "fallback": True})
            return None
```

### 5.4 TDD 验收

| 步骤 | 测试用例 | 预期 |
|---|---|---|
| **RED 1** | 初始 config + 5 个候选 → 理想数据（Beta mean=0.9, PSI=0.05）→ evolve_step | 选出 pareto_score 最高的 config，可能是当前 config（不劣化） |
| **RED 2** | 次优 config 迭代后 pareto_score 从 0.7 → 0.85 → evolve_step 选它 | 策略进化方向正确 |
| **RED 3** | PSI > 0.25 → classify_drift = "severe_drift" → regime gate 重置先验 | TB1 漂移 → TB4 Bayesian reset 链 |
| **RED 4** | evolve_step 内部抛异常（如 beta_state=None）→ 返回 None + history 记录 fallback | H4 FAIL-OPEN |
| **RED 5** | 所有候选 config pareto_score 均 < 当前 → evolve_step 返回 None | 不劣化保证成立 |

**验收标准**：pytest 5/5 passed + H2（无 .train()/.backward()/.backprop）+ H4（FAIL-OPEN fallback）硬约束在代码中明确标注。

### 5.5 算力

| 项 | 值 |
|---|---|
| 单次 evolve_step | < 50ms（含 5 个候选 × AlphaPareto） |
| 内存 | < 1MB |
| GPU | 不需要 |
| 依赖 | TB1 + TB2 + TB3 + TB4 |

---

## §6 实施计划与验收标准

### 6.1 开发顺序（硬约束依赖链）

```
TB1 PSI drift_detector ── 1 天 ──→ TDD 验收 6/6 passed
    │
    ▼
TB2 Beta verify 升级 ── 2 天 ──→ TDD 验收 6/6 passed + 零业务回归
    │
    ├──→ TB3 AlphaPareto  ── 1 天 ──→ TDD 验收 6/6 passed
    │
    └──→ TB4 Thompson Sampling ── 1 天 ──→ TDD 验收 4/4 passed
    │
    ▼
TB5 GRPO loop ── 2 天 ──→ TDD 验收 5/5 passed + H2/H4 硬约束验证
    │
    ▼
影子验证合并跑 ── 1 天 ──→ TB1-TB5 全部 shadow_run 一轮
    │
    ▼
总代码量预算：~470 行 Python + pytest 用例
总时间预算：7 天（壳搭建期间并行）
```

### 6.2 验收标准总览

| TB | 硬约束验证 | TDD | 业务回归 | 算力 |
|---|---|---|---|---|
| TB1 PSI | H8 阈值硬编码，无 env override | 6/6 | 不涉及 | 1ms |
| TB2 Beta | H1 壳零感知，envelope schema 零变化 | 6/6 | 旧 verify 零回归 | 1μs |
| TB3 AlphaPareto | — | 6/6 | 不涉及 | 10μs |
| TB4 Thompson | — | 4/4 | 不涉及 | 10μs |
| TB5 GRPO | H2 无 .train()/.backward() + H4 FAIL-OPEN | 5/5 | 不涉及 | 50ms |
| **全局** | H1/H2/H4/H8 全覆盖 | **27/27** | verify 零回归 | 零 GPU |

### 6.3 影子验证（与 AgentMail 影子合并）

训练基座本身也需要影子验证——TB1-TB5 实现后，先跑一轮 shadow_run：

| 影子测试 | 做什么 | 产出 |
|---|---|---|
| TB1 PSI shadow | 用最近 20 次 verify 置信度算 PSI，看 classify_drift 结果是否合理 | shadow_report_TB1.md |
| TB2 Beta shadow | 把最近 10 次 verify 升级为 Beta 分布，看 mean vs 旧 confidence 值差异 < 0.1 | shadow_report_TB2.md |
| TB3 AlphaPareto shadow | 算最近 10 次交互的 pareto_score，看 0.3-0.9 分布是否合理 | shadow_report_TB3.md |
| TB5 GRPO shadow | 5 个候选 config 跑一轮 evolve_step，看是否选出有意义的改进（或保持当前） | shadow_report_TB5.md |

影子验证**不阻塞**壳落地主线，但阻塞 AGENT Phase A（认知 agent 参数化需要 TB1+TB2）。

---

## §6.5 影子期校准协议（P5 修订，2026-11-03）

**适用对象**（本文与关联 SPEC 中的初版拍定值）：

| 参数 | 初值 | 位置 | 校准指标 |
|---|---|---|---|
| AlphaPareto 六维权重 | 0.25 / 0.20 / 0.20 / 0.15 / 0.12 / 0.08 | 本文 §3.3 `REWARD_WEIGHTS` | 影子期人机复核一致率 ≥ 0.8（高分/低分结论吻合） |
| PSI 三档 | <0.1 稳定 / 0.1–0.25 轻微 / >0.25 严重 | 本文 §1、DOMAIN-AGENTS §4 | 对人工标注漂移事件的 ROC-AUC ≥ 0.75 |
| H5 贝叶斯 VaR 阈值 | <0.3 拦截 / <0.5 降为建议 | DOMAIN-AGENTS §5.1 | 误拦截率 ≤ 5% 且漏拦截率 ≤ 10% |
| V 函数 λ / 跨域加成 | λ=0.1 / +0.1 × refs | COMM-SHADOW §3 | 与人工排序 Spearman ρ ≥ 0.7 |

**流程（离线校准，非运行期自调）**：

1. 影子期（≥2 周且 ≥200 条 agent 结论）只观察不写回，原始数据落 `47-MCP管理系统/registry/calibration/shadow_YYYYMMDD.jsonl`
2. 每两周产出校准报告 `registry/calibration/report_YYYYMMDD.md`（样本量 + 上表指标 + 建议新权值/阈值）
3. 人工评审通过后，**改源码常量并补回归测试（一次提交）**；禁止运行期动态调整参数（H8 硬约束不变）
4. 校准报告与代码 commit 双向链接，作为 V-S 系列影子判据之外的补充证据

**门禁**：样本量 < 200 或指标未达标时，禁止改初值，只能延长影子期并记录原因。

---

## §7 与演进路线的衔接

| 演进阶段 | TRAIN-BASE 依赖 | TRAIN-BASE 产出给演进阶段 |
|---|---|---|
| ① MCP 壳层 | 壳层 envelope.data 业务体透传稳定（观察） | 零依赖 |
| ② AGENT 域内 agent | TB1-TB5 是 Phase A-E 的前置 | TB1 PSI → 评测 OOD；TB2 Beta → 贝叶斯 VaR；TB3 六维奖励 → 所有 agent 训练评估；TB4 regime gate → REA/周期神经网络；TB5 PolicySelectLoop → agent 自进化 |
| ③ 单独算法训练 | — | TRAIN-BASE **就是单独算法训练的基础设施层** |
| ④ 底层通信升级 | AgentMail 影子需要 TB1 PSI 做跨域交互轨迹的漂移评估 | TB1 PSI + TB3 pareto_score → 跨域通信 V 函数的 components |
