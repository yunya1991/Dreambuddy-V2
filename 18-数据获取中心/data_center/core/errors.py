"""data_center 统一异常体系 — 对齐 TECHNICAL_DESIGN.md §8.1。

M1/T2 阶段仅定义 ContractError；SourceUnavailable/RateLimit/Parse/Network
在 T3 由测试驱动补全。
"""


class DataCenterError(Exception):
    """所有 data_center 异常基类。"""


class ContractError(DataCenterError):
    """DataRecord 契约违规（字段缺失/类型非法/嵌套对象等）。"""


class SourceUnavailableError(DataCenterError):
    """数据源不可用（API Key 缺失/源下线/未注册）。"""


class RateLimitError(DataCenterError):
    """上游限流（HTTP 429 / 配额超限）。"""


class ParseError(DataCenterError):
    """上游响应解析失败（结构变更/字段缺失）。"""


class NetworkError(DataCenterError):
    """网络层失败（超时/连接错误）。"""
