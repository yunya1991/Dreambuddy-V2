"""
规则注册表
==========
可插拔的风控规则注册与管理机制。

支持三类规则：
    - gate_rules:     事前门禁规则
    - position_rules: 仓位计算规则
    - exit_rules:     离场决策规则

每个规则是一个可调用对象，接收上下文参数，返回检查结果。
"""

from typing import Dict, List, Callable, Any, Optional, Type
from enum import Enum
from dataclasses import dataclass, field


class RuleCategory(str, Enum):
    """规则类别"""
    GATE = "gate"
    POSITION = "position"
    EXIT = "exit"


@dataclass
class RuleInfo:
    """规则元信息"""
    name: str
    category: RuleCategory
    priority: int = 100
    description: str = ""
    enabled: bool = True
    config_schema: Dict[str, Any] = field(default_factory=dict)


class RuleRegistry:
    """风控规则注册表

    用于注册、查找和执行风控规则，支持按类别分组和优先级排序。

    示例:
        registry = RuleRegistry()

        @registry.register_gate("daily_drawdown", priority=10)
        def daily_drawdown_rule(signal, context, config):
            ...

        rules = registry.get_rules(RuleCategory.GATE)
    """

    def __init__(self):
        self._rules: Dict[str, RuleInfo] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(
        self,
        name: str,
        category: RuleCategory,
        handler: Callable,
        priority: int = 100,
        description: str = "",
        config_schema: Optional[Dict[str, Any]] = None,
    ) -> RuleInfo:
        """注册一个规则

        Args:
            name: 规则唯一名称
            category: 规则类别
            handler: 规则处理函数
            priority: 优先级（数字越小越先执行）
            description: 规则描述
            config_schema: 配置参数schema

        Returns:
            RuleInfo 规则元信息
        """
        if name in self._rules:
            raise ValueError(f"规则 '{name}' 已存在")

        info = RuleInfo(
            name=name,
            category=category,
            priority=priority,
            description=description,
            config_schema=config_schema or {},
        )
        self._rules[name] = info
        self._handlers[name] = handler
        return info

    def register_gate(self, name: str, priority: int = 100, description: str = "", **kwargs):
        """门禁规则装饰器"""
        def decorator(func):
            self.register(
                name=name,
                category=RuleCategory.GATE,
                handler=func,
                priority=priority,
                description=description,
                **kwargs
            )
            return func
        return decorator

    def register_position(self, name: str, priority: int = 100, description: str = "", **kwargs):
        """仓位规则装饰器"""
        def decorator(func):
            self.register(
                name=name,
                category=RuleCategory.POSITION,
                handler=func,
                priority=priority,
                description=description,
                **kwargs
            )
            return func
        return decorator

    def register_exit(self, name: str, priority: int = 100, description: str = "", **kwargs):
        """离场规则装饰器"""
        def decorator(func):
            self.register(
                name=name,
                category=RuleCategory.EXIT,
                handler=func,
                priority=priority,
                description=description,
                **kwargs
            )
            return func
        return decorator

    def unregister(self, name: str) -> bool:
        """注销规则"""
        if name in self._rules:
            del self._rules[name]
            del self._handlers[name]
            return True
        return False

    def get_handler(self, name: str) -> Optional[Callable]:
        """获取规则处理函数"""
        return self._handlers.get(name)

    def get_rule(self, name: str) -> Optional[RuleInfo]:
        """获取规则元信息"""
        return self._rules.get(name)

    def get_rules(self, category: Optional[RuleCategory] = None) -> List[RuleInfo]:
        """获取规则列表，按优先级排序

        Args:
            category: 规则类别，None表示全部

        Returns:
            按优先级排序的规则列表
        """
        rules = list(self._rules.values())
        if category is not None:
            rules = [r for r in rules if r.category == category]
        rules.sort(key=lambda r: r.priority)
        return rules

    def get_enabled_rules(self, category: Optional[RuleCategory] = None) -> List[RuleInfo]:
        """获取启用的规则列表"""
        return [r for r in self.get_rules(category) if r.enabled]

    def enable(self, name: str) -> bool:
        """启用规则"""
        if name in self._rules:
            self._rules[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """禁用规则"""
        if name in self._rules:
            self._rules[name].enabled = False
            return True
        return False

    def execute_chain(
        self,
        category: RuleCategory,
        *args,
        config: Optional[Dict[str, Any]] = None,
        stop_on_fail: bool = True,
        **kwargs
    ) -> List[Any]:
        """按优先级顺序执行一类规则

        Args:
            category: 规则类别
            *args: 传递给规则的参数
            config: 规则配置 {rule_name: rule_config}
            stop_on_fail: 遇到失败是否停止执行
            **kwargs: 传递给规则的关键字参数

        Returns:
            规则执行结果列表
        """
        results = []
        config = config or {}

        for rule_info in self.get_enabled_rules(category):
            handler = self._handlers.get(rule_info.name)
            if not handler:
                continue

            rule_config = config.get(rule_info.name, {})

            try:
                result = handler(*args, config=rule_config, **kwargs)
                results.append({
                    "rule_name": rule_info.name,
                    "result": result,
                })

                if stop_on_fail and hasattr(result, "passed") and not result.passed:
                    break
            except Exception as e:
                results.append({
                    "rule_name": rule_info.name,
                    "error": str(e),
                })
                if stop_on_fail:
                    break

        return results

    def list_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """列出所有规则，按类别分组"""
        result = {}
        for category in RuleCategory:
            rules = self.get_rules(category)
            result[category.value] = [
                {
                    "name": r.name,
                    "priority": r.priority,
                    "enabled": r.enabled,
                    "description": r.description,
                }
                for r in rules
            ]
        return result

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, name: str) -> bool:
        return name in self._rules
