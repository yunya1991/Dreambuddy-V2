#!/usr/bin/env python3
"""
WorkBuddy OS 模块注册表加载器 (Python 侧)

位置: experiments/ab-trading/core/modules/module_registry.py

功能:
1. 从 YAML 文件加载模块注册表（双端唯一真相源）
2. JSON Schema 校验
3. 内存缓存 + 索引加速
4. 热更新（文件监听）
5. 统一查询接口（按ID/链/分类/标签/阶段等）

设计原则:
- 单一真相源：1-ARCHITECTURE/registry/module_registry.yaml
- 只读加载：注册表是配置，运行时不修改
- 索引加速：按多种维度建立索引，查询O(1)
- 降级容错：加载失败时使用内置空注册表，不影响核心流程
"""

import os
import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

import yaml

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
REGISTRY_PATH = _PROJECT_ROOT / "1-ARCHITECTURE" / "registry" / "module_registry.yaml"
SCHEMA_PATH = _PROJECT_ROOT / "1-ARCHITECTURE" / "registry" / "module_registry.schema.json"


@dataclass
class ModuleInfo:
    """模块信息（扁平化结构，便于查询）"""
    id: str
    name: str
    description: str
    version: str
    chain: str
    category: str
    tags: List[str]
    lifecycle: Dict
    security_level: str
    estimated_tokens: int
    estimated_latency_ms: int
    confidence_range: List[float]
    applicable_stages: List[str]
    applicable_intents: List[str]
    market_conditions: List[str]
    historical_accuracy: float
    historical_calls: int
    dependencies: List[str]
    adapter: Dict
    fallback: Dict
    domain: str = ""
    category_name: str = ""

    @classmethod
    def from_dict(cls, data: Dict, domain: str = "", category_name: str = "") -> "ModuleInfo":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            version=data["version"],
            chain=data["chain"],
            category=data["category"],
            tags=data.get("tags", []),
            lifecycle=data.get("lifecycle", {}),
            security_level=data.get("security_level", "R1"),
            estimated_tokens=data.get("estimated_tokens", 0),
            estimated_latency_ms=data.get("estimated_latency_ms", 0),
            confidence_range=data.get("confidence_range", [0, 100]),
            applicable_stages=data.get("applicable_stages", []),
            applicable_intents=data.get("applicable_intents", []),
            market_conditions=data.get("market_conditions", []),
            historical_accuracy=data.get("historical_accuracy", 0),
            historical_calls=data.get("historical_calls", 0),
            dependencies=data.get("dependencies", []),
            adapter=data.get("adapter", {}),
            fallback=data.get("fallback", {}),
            domain=domain,
            category_name=category_name,
        )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "chain": self.chain,
            "category": self.category,
            "tags": self.tags,
            "lifecycle": self.lifecycle,
            "security_level": self.security_level,
            "estimated_tokens": self.estimated_tokens,
            "estimated_latency_ms": self.estimated_latency_ms,
            "confidence_range": self.confidence_range,
            "applicable_stages": self.applicable_stages,
            "applicable_intents": self.applicable_intents,
            "market_conditions": self.market_conditions,
            "historical_accuracy": self.historical_accuracy,
            "historical_calls": self.historical_calls,
            "dependencies": self.dependencies,
            "adapter": self.adapter,
            "fallback": self.fallback,
            "domain": self.domain,
            "category_name": self.category_name,
        }


class ModuleRegistry:
    """
    模块注册表加载器
    
    负责加载、校验、索引和查询模块注册表
    线程安全，支持热更新
    """

    def __init__(self, registry_path: Optional[Path] = None,
                 schema_path: Optional[Path] = None,
                 auto_watch: bool = False):
        self._registry_path = registry_path or REGISTRY_PATH
        self._schema_path = schema_path or SCHEMA_PATH
        
        self._lock = threading.RLock()
        self._modules: Dict[str, ModuleInfo] = {}
        self._raw_data: Dict = {}
        self._last_load_time: float = 0
        self._last_file_mtime: float = 0
        
        self._by_chain: Dict[str, Set[str]] = {}
        self._by_category: Dict[str, Set[str]] = {}
        self._by_domain: Dict[str, Set[str]] = {}
        self._by_stage: Dict[str, Set[str]] = {}
        self._by_tag: Dict[str, Set[str]] = {}
        
        self._watch_thread: Optional[threading.Thread] = None
        self._watch_running: bool = False
        self._watch_interval: float = 5.0
        
        self._load()
        
        if auto_watch:
            self.start_watching()

    def _load(self) -> bool:
        """加载注册表文件并构建索引"""
        try:
            if not self._registry_path.exists():
                print(f"[ModuleRegistry] 注册表文件不存在: {self._registry_path}")
                return False
            
            file_mtime = self._registry_path.stat().st_mtime
            if file_mtime == self._last_file_mtime and self._modules:
                return True
            
            with open(self._registry_path, 'r', encoding='utf-8') as f:
                raw_data = yaml.safe_load(f)
            
            if not raw_data or not isinstance(raw_data, dict):
                print("[ModuleRegistry] 注册表格式错误")
                return False
            
            if _HAS_JSONSCHEMA and self._schema_path.exists():
                try:
                    with open(self._schema_path, 'r', encoding='utf-8') as f:
                        schema = json.load(f)
                    jsonschema.validate(instance=raw_data, schema=schema)
                except jsonschema.ValidationError as e:
                    print(f"[ModuleRegistry] Schema校验失败: {e}")
                except Exception as e:
                    print(f"[ModuleRegistry] Schema校验异常: {e}")
            
            modules: Dict[str, ModuleInfo] = {}
            domains = raw_data.get("domains", {})
            
            for domain_key, domain_data in domains.items():
                categories = domain_data.get("categories", {})
                for cat_key, cat_data in categories.items():
                    mod_map = cat_data.get("modules", {})
                    for mod_key, mod_data in mod_map.items():
                        info = ModuleInfo.from_dict(
                            mod_data,
                            domain=domain_key,
                            category_name=cat_key
                        )
                        modules[info.id] = info
            
            with self._lock:
                self._raw_data = raw_data
                self._modules = modules
                self._last_load_time = time.time()
                self._last_file_mtime = file_mtime
                self._build_indexes()
            
            print(f"[ModuleRegistry] 加载成功，共 {len(modules)} 个模块")
            return True
            
        except Exception as e:
            print(f"[ModuleRegistry] 加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _build_indexes(self) -> None:
        """构建查询索引（调用方需持有锁）"""
        self._by_chain.clear()
        self._by_category.clear()
        self._by_domain.clear()
        self._by_stage.clear()
        self._by_tag.clear()
        
        for mid, mod in self._modules.items():
            if mod.chain not in self._by_chain:
                self._by_chain[mod.chain] = set()
            self._by_chain[mod.chain].add(mid)
            
            if mod.category not in self._by_category:
                self._by_category[mod.category] = set()
            self._by_category[mod.category].add(mid)
            
            if mod.domain not in self._by_domain:
                self._by_domain[mod.domain] = set()
            self._by_domain[mod.domain].add(mid)
            
            for stage in mod.applicable_stages:
                if stage not in self._by_stage:
                    self._by_stage[stage] = set()
                self._by_stage[stage].add(mid)
            
            for tag in mod.tags:
                if tag not in self._by_tag:
                    self._by_tag[tag] = set()
                self._by_tag[tag].add(mid)

    def reload(self) -> bool:
        """强制重新加载"""
        return self._load()

    def check_for_updates(self) -> bool:
        """检查文件是否有更新，有则重新加载"""
        try:
            if not self._registry_path.exists():
                return False
            file_mtime = self._registry_path.stat().st_mtime
            if file_mtime > self._last_file_mtime:
                print(f"[ModuleRegistry] 检测到文件更新，重新加载...")
                return self._load()
            return False
        except Exception:
            return False

    def start_watching(self, interval: float = 5.0) -> None:
        """启动文件监听线程"""
        if self._watch_running:
            return
        
        self._watch_interval = interval
        self._watch_running = True
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="ModuleRegistryWatcher"
        )
        self._watch_thread.start()
        print(f"[ModuleRegistry] 文件监听已启动，间隔 {interval}s")

    def stop_watching(self) -> None:
        """停止文件监听"""
        self._watch_running = False
        if self._watch_thread:
            self._watch_thread.join(timeout=2.0)
            self._watch_thread = None

    def _watch_loop(self) -> None:
        """监听循环"""
        while self._watch_running:
            try:
                self.check_for_updates()
            except Exception:
                pass
            time.sleep(self._watch_interval)

    def get(self, module_id: str) -> Optional[ModuleInfo]:
        """根据ID获取模块"""
        with self._lock:
            return self._modules.get(module_id)

    def has(self, module_id: str) -> bool:
        """检查模块是否存在"""
        with self._lock:
            return module_id in self._modules

    def get_all(self) -> List[ModuleInfo]:
        """获取所有模块"""
        with self._lock:
            return list(self._modules.values())

    def count(self) -> int:
        """获取模块总数"""
        with self._lock:
            return len(self._modules)

    def query(self,
              chain: Optional[str] = None,
              category: Optional[str] = None,
              domain: Optional[str] = None,
              stage: Optional[str] = None,
              tag: Optional[str] = None,
              security_level: Optional[str] = None,
              min_accuracy: Optional[float] = None,
              max_tokens: Optional[int] = None,
              intent: Optional[str] = None,
              market_condition: Optional[str] = None) -> List[ModuleInfo]:
        """
        多条件查询模块
        
        Args:
            chain: 所属链 (A/C/F/G/T)
            category: 分类
            domain: 领域
            stage: 适用阶段
            tag: 标签
            security_level: 安全等级
            min_accuracy: 最低历史准确率
            max_tokens: 最大token消耗
            intent: 适用意图
            market_condition: 适用市场条件
            
        Returns:
            匹配的模块列表
        """
        with self._lock:
            candidates = set(self._modules.keys())
            
            if chain and chain in self._by_chain:
                candidates &= self._by_chain[chain]
            
            if category and category in self._by_category:
                candidates &= self._by_category[category]
            
            if domain and domain in self._by_domain:
                candidates &= self._by_domain[domain]
            
            if stage and stage in self._by_stage:
                candidates &= self._by_stage[stage]
            
            if tag and tag in self._by_tag:
                candidates &= self._by_tag[tag]
            
            results = []
            for mid in candidates:
                mod = self._modules[mid]
                
                if security_level and mod.security_level != security_level:
                    continue
                
                if min_accuracy is not None and mod.historical_accuracy < min_accuracy:
                    continue
                
                if max_tokens is not None and mod.estimated_tokens > max_tokens:
                    continue
                
                if intent and intent not in mod.applicable_intents:
                    continue
                
                if market_condition and market_condition not in mod.market_conditions:
                    continue
                
                results.append(mod)
            
            return results

    def get_by_chain(self, chain: str) -> List[ModuleInfo]:
        """按链查询"""
        return self.query(chain=chain)

    def get_by_domain(self, domain: str) -> List[ModuleInfo]:
        """按领域查询"""
        return self.query(domain=domain)

    def get_dependencies(self, module_id: str) -> List[ModuleInfo]:
        """获取模块的依赖"""
        mod = self.get(module_id)
        if not mod:
            return []
        result = []
        for dep_id in mod.dependencies:
            dep = self.get(dep_id)
            if dep:
                result.append(dep)
        return result

    def get_fallback(self, module_id: str) -> Optional[ModuleInfo]:
        """获取模块的降级模块"""
        mod = self.get(module_id)
        if not mod or not mod.fallback.get("enabled"):
            return None
        fallback_id = mod.fallback.get("fallback_module")
        if not fallback_id:
            return None
        return self.get(fallback_id)

    def get_raw(self) -> Dict:
        """获取原始YAML数据"""
        with self._lock:
            return self._raw_data

    def get_domains(self) -> List[str]:
        """获取所有领域"""
        with self._lock:
            return list(self._by_domain.keys())

    def get_chains(self) -> List[str]:
        """获取所有链"""
        with self._lock:
            return list(self._by_chain.keys())

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        with self._lock:
            return list(self._by_category.keys())

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            stats = {
                "total": len(self._modules),
                "by_chain": {k: len(v) for k, v in self._by_chain.items()},
                "by_domain": {k: len(v) for k, v in self._by_domain.items()},
                "by_category": {k: len(v) for k, v in self._by_category.items()},
                "last_load": self._last_load_time,
            }
            return stats

    def is_active(self, module_id: str) -> bool:
        """检查模块是否处于活跃状态"""
        mod = self.get(module_id)
        if not mod:
            return False
        return mod.lifecycle.get("status") == "active" and not mod.lifecycle.get("deprecated", False)


_global_registry: Optional[ModuleRegistry] = None
_global_lock = threading.Lock()


def get_module_registry(auto_watch: bool = False) -> ModuleRegistry:
    """获取全局模块注册表单例"""
    global _global_registry
    if _global_registry is None:
        with _global_lock:
            if _global_registry is None:
                _global_registry = ModuleRegistry(auto_watch=auto_watch)
    return _global_registry


def reload_registry() -> bool:
    """重新加载全局注册表"""
    registry = get_module_registry()
    return registry.reload()


__all__ = [
    "ModuleInfo",
    "ModuleRegistry",
    "get_module_registry",
    "reload_registry",
    "REGISTRY_PATH",
    "SCHEMA_PATH",
]
