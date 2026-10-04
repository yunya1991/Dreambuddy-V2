"""
D4: 核心窄接口定义（借鉴 ds4.h 窄接口边界）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 4
哲学: ds4.h 只暴露两个抽象——engine（不可变模型）+ session（可变推理时间线）。
      CLI/Server 不依赖张量内部实现。"Keep this header narrow."
映射: 定义核心窄接口（Protocol），引擎只依赖这些接口，不依赖具体实现。

设计原则:
  1. 窄接口——只定义核心字段，不包含实现细节
  2. 渐进式——现有 dict-based 代码可继续运行，新代码逐步适配
  3. 运行时可检查——使用 @runtime_checkable，支持 isinstance 结构子类型检查
  4. FAIL-OPEN——接口是可选约束，不满足不影响业务逻辑

核心接口:
  - StrategyGene: 策略基因标准表示
  - TradeSession: 一次交易的完整时间线
  - MarketState: 市场状态快照
  - PathCandidate: 候选交易路径
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StrategyGene(Protocol):
    """策略基因窄接口.

    对应 ds4 的 "engine" 概念——策略基因是不可变的核心实体。
    现有 strategy_gene.py 的基因 dict 可逐步适配此接口。
    """

    gene_id: str
    action_ids: list[str]
    ess: float
    n_samples: int


@runtime_checkable
class TradeSession(Protocol):
    """交易会话窄接口.

    对应 ds4 的 "session" 概念——一次交易的可变时间线。
    包含入场/出场信息，是策略执行的最小单元。
    """

    session_id: str
    symbol: str
    entry_time: float
    exit_time: float | None
    entry_price: float
    exit_price: float | None
    direction: str


@runtime_checkable
class MarketState(Protocol):
    """市场状态快照窄接口.

    市场状态的不可变快照，供策略基因推理使用。
    """

    symbol: str
    price: float
    volatility: float
    timestamp: float


@runtime_checkable
class PathCandidate(Protocol):
    """候选交易路径窄接口.

    路径发现层的输出，供路径评估层消费。
    对应 evolution_pipeline._discover_paths() 的返回结构。
    """

    path_id: str
    source: str
    direction: str
    expected_return: float
    confidence: float
    resistance: float
