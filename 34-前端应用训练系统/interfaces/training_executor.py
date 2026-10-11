"""训练执行器协议。

定义训练系统执行训练的统一接口。
SPL的5个层专属训练器（S/DSH/C/G/LLM）通过适配器实现此协议。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from enum import Enum


class TrainingLayer(str, Enum):
    """训练层枚举（对齐SPL 5层）。"""
    S = "S"           # 意图识别层
    DSH = "DSH"       # DSH执行路径层
    C = "C"           # C层反射决策
    G = "G"           # G层图结构
    LLM = "LLM"       # LLM Prompt优化层


class TrainingResult:
    """训练结果。"""

    def __init__(
        self,
        layer: TrainingLayer,
        success: bool,
        metrics: Optional[Dict[str, float]] = None,
        message: str = "",
    ):
        self.layer = layer
        self.success = success
        self.metrics = metrics or {}
        self.message = message


class TrainingExecutor(ABC):
    """训练执行器协议。

    SPL的5个层专属训练器通过适配器实现此协议。
    双模式调度器通过此协议触发训练。
    """

    @abstractmethod
    def get_layer(self) -> TrainingLayer:
        """返回该执行器负责的训练层。"""
        ...

    @abstractmethod
    def get_bucket_threshold(self) -> int:
        """返回该层桶满触发阈值（如 S=100, DSH=50）。"""
        ...

    @abstractmethod
    def get_bucket_count(self) -> int:
        """返回该层当前训练桶中的案例数。"""
        ...

    @abstractmethod
    def add_case(self, case: Any) -> bool:
        """向训练桶中添加一个案例。

        Returns:
            是否成功添加
        """
        ...

    @abstractmethod
    def train(self) -> TrainingResult:
        """执行训练（桶满时调用）。

        Returns:
            训练结果
        """
        ...

    @abstractmethod
    def get_dependencies(self) -> List[TrainingLayer]:
        """返回该层训练依赖的前置层（如 DSH 依赖 [S]）。"""
        ...

    # ========================================================
    # v0.5 可选方法：增量训练 / Checkpoint / Restore / Model
    # 非抽象方法，默认 raise NotImplementedError。
    # TSHTTPTrainingExecutor 已实现，其他执行器可选。
    # ========================================================

    def trigger_incremental(self) -> "TrainingResult":
        """触发增量训练（v0.5）。单案例即可启动，不依赖桶满阈值。"""
        raise NotImplementedError(f"{type(self).__name__} does not support trigger_incremental")

    def checkpoint(self) -> dict:
        """保存模型状态检查点（v0.5）。"""
        raise NotImplementedError(f"{type(self).__name__} does not support checkpoint")

    def restore(self, state: dict) -> dict:
        """恢复模型状态（v0.5）。"""
        raise NotImplementedError(f"{type(self).__name__} does not support restore")

    def get_model(self) -> dict:
        """获取模型状态 JSON（v0.5）。"""
        raise NotImplementedError(f"{type(self).__name__} does not support get_model")
