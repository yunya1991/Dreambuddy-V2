"""
DreamOS Registry — YAML 配置加载器

支持从 YAML 配置批量注册节点，便于管理和部署。

YAML 配置格式:
    nodes:
      - id: A0
        name: 矛盾论
        chain: A
        adapter: function
        handler: path.to.module:function_name
        tags: [research]
        estimated_tokens: 300

      - id: B1
        name: 外部API
        chain: C
        adapter: api
        endpoint: https://api.example.com/v1/analyze
        method: POST
        estimated_tokens: 0

      - id: S1
        name: SKILL节点
        chain: F
        adapter: skill
        skill_path: 6-TRADING/skills/xxx
        estimated_tokens: 500
"""

from __future__ import annotations

import os
import importlib
from typing import Any, Dict, List, Optional

from dreamos.shared.errors import OSError, ErrorCode
from dreamos.shared.interfaces import Node
from dreamos.adapters import FunctionAdapter, APIAdapter, SkillAdapter, get_default_adapter_registry

from .node_registry import NodeRegistry


class RegistryLoader:
    """从 YAML 配置加载节点到注册表

    用法:
        loader = RegistryLoader(registry)
        loader.load_from_file("nodes.yaml")

    或直接加载字典:
        loader.load_from_config({"nodes": [...]})
    """

    def __init__(self, registry: Optional[NodeRegistry] = None):
        from .node_registry import get_default_registry
        self._registry = registry if registry is not None else get_default_registry()
        self._adapter_registry = get_default_adapter_registry()

    def load_from_file(self, filepath: str) -> int:
        """从 YAML 文件加载

        Returns:
            成功注册的节点数量
        """
        if not os.path.exists(filepath):
            raise OSError(ErrorCode.NODE_003, f"配置文件不存在: {filepath}")

        try:
            import yaml
            with open(filepath, "r") as f:
                config = yaml.safe_load(f)
        except ImportError:
            # 没有 yaml 库，尝试用简单解析
            config = self._parse_simple_yaml(filepath)
        except Exception as e:
            raise OSError(ErrorCode.NODE_003, f"加载配置失败: {e}")

        return self.load_from_config(config)

    def load_from_config(self, config: Dict[str, Any]) -> int:
        """从配置字典加载

        Args:
            config: 配置字典，需包含 "nodes" 列表

        Returns:
            成功注册的节点数量
        """
        nodes = config.get("nodes", [])
        if not nodes:
            return 0

        count = 0
        for node_cfg in nodes:
            try:
                node = self._build_node(node_cfg)
                if node:
                    self._registry.register(node)
                    count += 1
            except OSError:
                # 已存在则跳过
                pass
            except Exception as e:
                print(f"[RegistryLoader] 跳过节点 {node_cfg.get('id', '?')}: {e}")

        return count

    def _build_node(self, cfg: Dict[str, Any]) -> Optional[Node]:
        """根据配置构建节点"""
        adapter_type = cfg.get("adapter", "function")

        if adapter_type == "function":
            return self._build_function_node(cfg)
        elif adapter_type == "api":
            return self._build_api_node(cfg)
        elif adapter_type == "skill":
            return self._build_skill_node(cfg)
        else:
            # 尝试用适配器注册表查找
            adapter = self._adapter_registry.get(adapter_type)
            if adapter:
                return adapter.to_node(cfg)
            raise ValueError(f"未知适配器类型: {adapter_type}")

    def _build_function_node(self, cfg: Dict[str, Any]) -> Node:
        """构建函数节点"""
        handler_ref = cfg.get("handler", "")
        if not handler_ref:
            raise ValueError("function 类型节点必须指定 handler")

        # 从模块路径导入函数
        if callable(handler_ref):
            fn = handler_ref
        else:
            fn = self._import_function(handler_ref)

        adapter = FunctionAdapter()
        node = adapter.wrap(fn, node_id=cfg.get("node_id") or cfg.get("id", ""))
        node.name = cfg.get("name", node.name)
        node.description = cfg.get("description", "")
        node.chain = cfg.get("chain", "")
        node.tags = cfg.get("tags", [])
        node.estimated_tokens = cfg.get("estimated_tokens", 0)
        node.estimated_latency_ms = cfg.get("estimated_latency_ms", 0)
        return node

    def _build_api_node(self, cfg: Dict[str, Any]) -> Node:
        """构建 API 节点"""
        adapter = APIAdapter()
        node = adapter.to_node({
            "node_id": cfg.get("node_id") or cfg.get("id", ""),
            "url": cfg.get("url", cfg.get("endpoint", "")),
            "method": cfg.get("method", "GET"),
            "headers": cfg.get("headers", {}),
            "body": cfg.get("body"),
            "timeout_ms": cfg.get("timeout_ms", 30000),
            "response_path": cfg.get("response_path", ""),
        })
        node.name = cfg.get("name", node.name)
        node.description = cfg.get("description", "")
        node.chain = cfg.get("chain", "")
        node.tags = cfg.get("tags", [])
        return node

    def _build_skill_node(self, cfg: Dict[str, Any]) -> Node:
        """构建 SKILL 节点"""
        adapter = SkillAdapter()
        node = adapter.to_node({
            "node_id": cfg.get("node_id") or cfg.get("id", ""),
            "skill_path": cfg.get("skill_path", ""),
        })
        node.name = cfg.get("name", node.name)
        node.chain = cfg.get("chain", "")
        node.tags = cfg.get("tags", [])
        node.estimated_tokens = cfg.get("estimated_tokens", 0)
        return node

    def _import_function(self, ref: str) -> Any:
        """从 "module.path:function_name" 格式导入函数"""
        if ":" in ref:
            module_path, func_name = ref.rsplit(":", 1)
        else:
            parts = ref.rsplit(".", 1)
            if len(parts) != 2:
                raise ValueError(f"无效的函数引用格式: {ref}")
            module_path, func_name = parts

        module = importlib.import_module(module_path)
        fn = getattr(module, func_name, None)
        if fn is None:
            raise ValueError(f"函数不存在: {ref}")
        if not callable(fn):
            raise ValueError(f"{ref} 不是可调用对象")
        return fn

    def _parse_simple_yaml(self, filepath: str) -> Dict[str, Any]:
        """简单的 YAML 解析 fallback（只支持基础格式）"""
        # 没有 PyYAML 时的降级方案
        raise OSError(
            ErrorCode.NODE_003,
            "需要安装 PyYAML 才能加载 YAML 配置: pip install pyyaml"
        )


# ============================================================
# 便捷函数
# ============================================================

def load_from_yaml(filepath: str, registry: Optional[NodeRegistry] = None) -> int:
    """从 YAML 文件加载节点（便捷函数）"""
    loader = RegistryLoader(registry)
    return loader.load_from_file(filepath)
