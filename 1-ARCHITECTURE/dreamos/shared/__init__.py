"""
Dreambuddy OS — shared 共享基础层

提供 OS 内核各层共用的基础组件:
    - state:       State / NodeResult / NodeStatus
    - interfaces:  Node / Graph / Edge / Registry / Adapter 接口
    - errors:      错误码体系 + OSError 异常
    - llm_client:  LLM 客户端抽象
    - utils:       工具函数
"""

from .errors import ErrorCode, OSError
from .interfaces import Adapter, Edge, Graph, Node, Registry
from .llm_client import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    get_default_client,
    make_messages,
    set_default_client,
)
from .state import NodeResult, NodeStatus, State, new_state
from .utils import (
    Timer,
    chunk,
    dedupe,
    gen_cycle_id,
    gen_session_id,
    retry,
    safe_get,
    safe_json,
    timed,
)

__all__ = [
    # state
    "State",
    "NodeResult",
    "NodeStatus",
    "new_state",
    # interfaces
    "Node",
    "Graph",
    "Edge",
    "Registry",
    "Adapter",
    # errors
    "ErrorCode",
    "OSError",
    # llm
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "get_default_client",
    "set_default_client",
    "make_messages",
    # utils
    "Timer",
    "timed",
    "gen_cycle_id",
    "gen_session_id",
    "safe_json",
    "safe_get",
    "retry",
    "chunk",
    "dedupe",
]
