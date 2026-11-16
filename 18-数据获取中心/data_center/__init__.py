"""DataBuddy 数据获取中心 — 万能爬虫 + 信息搜集工具。

对外入口：from data_center import DataCenter, DataRecord

注意：这里保持「懒加载」。dispatcher 会连带加载清洗/语义模型等重依赖，
若在包初始化时 eager import，任何子模块（如新闻采集器）都会付出模型加载
成本（实测约 2 分钟），定时任务会无谓变慢。
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from data_center.core.contract import DataRecord
    from data_center.core.dispatcher import DataCenter

__all__ = ["DataCenter", "DataRecord", "__version__"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name == "DataRecord":
        from data_center.core.contract import DataRecord

        return DataRecord
    if name == "DataCenter":
        from data_center.core.dispatcher import DataCenter

        return DataCenter
    raise AttributeError(f"module 'data_center' has no attribute {name!r}")
