#!/usr/bin/env python3
"""
蒸馏调度器 — 定期将应用记忆经验上升为总记忆

功能：
1. 定时扫描各应用记忆的蒸馏候选
2. 根据质量等级阈值筛选
3. 将符合条件的内容蒸馏到总记忆对应单元
4. 更新应用记忆的质量等级

用法：
    # 手动执行一次
    python3 distill_scheduler.py --once
    
    # 定时执行（每小时）
    python3 distill_scheduler.py --interval 3600

集成：
    配合 cron 或 launchd 实现定时调度
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

from bayesian_memory_updater import BayesianMemoryUpdater


class DistillScheduler:
    """
    蒸馏调度器
    
    负责：
    1. 从应用记忆中提取蒸馏候选
    2. 筛选符合上升阈值的内容
    3. 写入总记忆对应单元
    4. 更新来源应用记忆的质量等级
    """
    
    # 上升阈值配置
    QUALITY_THRESHOLDS = {
        "S": {"min_verifies": 10, "min_confidence": 0.95},
        "A": {"min_verifies": 3, "min_confidence": 0.70},
        "B": {"min_verifies": 1, "min_confidence": 0.40},
    }
    
    # 应用记忆到总记忆单元的映射
    MEMORY_ROUTING = {
        "AM-TRD-001": "MU-TRD",  # 交易应用记忆 → 交易记忆单元
        "AM-RSK-001": "MU-TRD",  # 风控应用记忆 → 交易记忆单元
        "AM-OPS-001": "MU-DEV",  # 运维应用记忆 → 开发记忆单元
        "AM-EXP-001": "MU-TRD",  # 实验应用记忆 → 交易记忆单元
    }
    
    def __init__(self, memory_root: Optional[Path] = None):
        """
        初始化蒸馏调度器。
        
        Args:
            memory_root: 记忆系统根目录，默认为 4-MEMORY/
        """
        if memory_root is None:
            memory_root = Path(__file__).parent.parent
        self.memory_root = Path(memory_root)
        
        # 应用记忆接口缓存
        self._app_memory_cache: Dict[str, any] = {}
    
    def _load_app_memory(self, memory_id: str) -> Optional[any]:
        """动态加载应用记忆接口。"""
        if memory_id in self._app_memory_cache:
            return self._app_memory_cache[memory_id]
        
        # 映射到具体模块路径
        module_paths = {
            "AM-TRD-001": "11-易经推理系统/scripts/memory_l4/app_memory_interface.py",
            "AM-RSK-001": "13-通用风控模块/memory/app_memory_interface.py",
            "AM-OPS-001": "15-监控告警系统/memory/app_memory_interface.py",
        }
        
        module_path = module_paths.get(memory_id)
        if not module_path:
            return None
        
        full_path = self.memory_root.parent / module_path
        if not full_path.exists():
            return None
        
        # 动态导入
        import importlib.util
        spec = importlib.util.spec_from_file_location("app_memory", full_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 获取接口类
            interface_class = getattr(module, "RiskMemoryInterface", None) or \
                              getattr(module, "OpsMemoryInterface", None) or \
                              getattr(module, "AppMemoryInterface", None)
            
            if interface_class:
                self._app_memory_cache[memory_id] = interface_class()
                return self._app_memory_cache[memory_id]
        
        return None
    
    def fetch_candidates(self, memory_id: str, min_quality: str = "B") -> List[Dict]:
        """
        从指定应用记忆获取蒸馏候选。
        
        Args:
            memory_id: 应用记忆ID
            min_quality: 最低质量等级
            
        Returns:
            候选列表
        """
        interface = self._load_app_memory(memory_id)
        if not interface:
            print(f"⚠️  无法加载应用记忆: {memory_id}")
            return []
        
        try:
            candidates = interface.distill_candidates(min_quality=min_quality, limit=10)
            return candidates
        except Exception as e:
            print(f"❌ 获取候选失败: {e}")
            return []
    
    def distill_to_global(self, candidate: Dict, source_memory_id: str) -> bool:
        """
        将候选蒸馏到总记忆。
        
        Args:
            candidate: 候选内容
            source_memory_id: 来源应用记忆ID
            
        Returns:
            是否成功
        """
        target_unit = self.MEMORY_ROUTING.get(source_memory_id)
        if not target_unit:
            print(f"⚠️  未找到路由目标: {source_memory_id}")
            return False
        
        # 确定目标记忆单元目录
        unit_dirs = {
            "MU-DEV": "1-开发记忆单元",
            "MU-TRD": "2-交易记忆单元",
            "MU-DOC": "3-文档记忆单元",
            "MU-INF": "4-信息记忆单元",
        }
        unit_dir = self.memory_root / unit_dirs.get(target_unit, "1-开发记忆单元")
        
        # 加载贝叶斯更新器
        updater = BayesianMemoryUpdater(unit_dir)
        
        # 生成记忆ID
        memory_id = f"GM-{target_unit.split('-')[1]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 添加到总记忆
        try:
            entry = updater.add_memory(
                memory_id=memory_id,
                content=candidate.get("content", ""),
                category="lesson",
                initial_confidence=self._quality_to_confidence(candidate.get("quality_level", "C")),
                source=f"distill from {source_memory_id}",
                tags=candidate.get("tags", []),
            )
            print(f"✅ 已蒸馏: {memory_id} → {target_unit}")
            return True
        except Exception as e:
            print(f"❌ 蒸馏失败: {e}")
            return False
    
    def _quality_to_confidence(self, quality: str) -> float:
        """质量等级转置信度。"""
        mapping = {"S": 0.95, "A": 0.80, "B": 0.60, "C": 0.40, "D": 0.20}
        return mapping.get(quality, 0.40)
    
    def run_once(self) -> Dict[str, int]:
        """
        执行一次完整的蒸馏流程。
        
        Returns:
            统计结果
        """
        print(f"\n{'='*60}")
        print(f"🔄 蒸馏调度器 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        stats = {
            "total_candidates": 0,
            "distilled": 0,
            "skipped": 0,
            "failed": 0,
        }
        
        # 遍历所有已注册的应用记忆
        for memory_id in self.MEMORY_ROUTING.keys():
            print(f"\n📂 检查 {memory_id}...")
            
            # 获取候选
            candidates = self.fetch_candidates(memory_id, min_quality="B")
            stats["total_candidates"] += len(candidates)
            
            if not candidates:
                print(f"   ℹ️  无符合条件的候选")
                continue
            
            print(f"   📊 发现 {len(candidates)} 个候选")
            
            # 逐个蒸馏
            for candidate in candidates:
                quality = candidate.get("quality_level", "C")
                
                # 检查是否满足上升阈值
                if quality not in ("S", "A", "B"):
                    print(f"   ⏭️  跳过: {candidate.get('distill_id', 'N/A')} (质量={quality})")
                    stats["skipped"] += 1
                    continue
                
                # 执行蒸馏
                success = self.distill_to_global(candidate, memory_id)
                if success:
                    stats["distilled"] += 1
                else:
                    stats["failed"] += 1
        
        # 汇总
        print(f"\n{'='*60}")
        print(f"📊 蒸馏完成:")
        print(f"   - 候选总数: {stats['total_candidates']}")
        print(f"   - 成功蒸馏: {stats['distilled']}")
        print(f"   - 跳过: {stats['skipped']}")
        print(f"   - 失败: {stats['failed']}")
        print(f"{'='*60}")
        
        return stats
    
    def run_daemon(self, interval_seconds: int = 3600):
        """
        以守护进程方式运行，定期执行蒸馏。
        
        Args:
            interval_seconds: 执行间隔（秒）
        """
        import time
        
        print(f"🚀 蒸馏守护进程启动，间隔: {interval_seconds}秒")
        print(f"   按 Ctrl+C 停止")
        
        try:
            while True:
                self.run_once()
                print(f"\n⏰ 下次执行: {interval_seconds}秒后...")
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print(f"\n\n👋 守护进程已停止")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="蒸馏调度器")
    parser.add_argument("--once", action="store_true", help="执行一次后退出")
    parser.add_argument("--interval", type=int, default=3600, help="定时执行间隔（秒）")
    parser.add_argument("--memory-root", type=str, help="记忆系统根目录")
    
    args = parser.parse_args()
    
    memory_root = Path(args.memory_root) if args.memory_root else None
    scheduler = DistillScheduler(memory_root)
    
    if args.once:
        stats = scheduler.run_once()
        return 0 if stats["failed"] == 0 else 1
    else:
        scheduler.run_daemon(args.interval)
        return 0


if __name__ == "__main__":
    sys.exit(main())