"""DataBuddy 数据获取中心 — 万能爬虫 + 信息搜集工具。

对外入口：from data_center import DataCenter, DataRecord
"""
from data_center.core.contract import DataRecord
from data_center.core.dispatcher import DataCenter

__all__ = ["DataCenter", "DataRecord", "__version__"]
__version__ = "0.1.0"
