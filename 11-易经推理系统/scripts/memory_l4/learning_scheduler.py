#!/usr/bin/env python3
"""
学习调度器：定期重训 LiangyiEngine + QMM
"""
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
from pathlib import Path

from scripts.memory_l4.paths import memory_l4_dir, memory_l4_cases_dir
from scripts.memory_l4.bcrm.engine import BCRMEngine


class LearningScheduler:
    """
    学习调度器

    功能：
    - 定时检查新案例数量
    - 达到阈值时触发两仪引擎重训
    - 触发 QMM 模型重训（如果有足够案例）
    - 持久化学习结果
    """

    def __init__(self,
                 bcrm_engine: BCRMEngine,
                 retrain_interval_cases: int = 10,
                 retrain_interval_hours: int = 4,
                 on_retrain_complete: Callable = None):
        self.bcrm_engine = bcrm_engine
        self.retrain_interval_cases = retrain_interval_cases
        self.retrain_interval_hours = retrain_interval_hours
        self.on_retrain_complete = on_retrain_complete

        self.learn_dir = memory_l4_dir() / "learning"
        self.learn_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.learn_dir / "scheduler_state.json"

        self.last_retrain_time = 0
        self.last_case_count = 0
        self.retrain_count = 0

        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.last_retrain_time = data.get("last_retrain_time", 0)
                self.last_case_count = data.get("last_case_count", 0)
                self.retrain_count = data.get("retrain_count", 0)
            except Exception:
                pass

    def _save_state(self):
        try:
            data = {
                "last_retrain_time": self.last_retrain_time,
                "last_case_count": self.last_case_count,
                "retrain_count": self.retrain_count,
                "last_retrain_time_str": datetime.fromtimestamp(
                    self.last_retrain_time, tz=timezone.utc
                ).isoformat() if self.last_retrain_time else "",
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _count_cases(self) -> int:
        """统计当前案例总数"""
        cases_dir = memory_l4_cases_dir()
        if not cases_dir.exists():
            return 0
        return len(list(cases_dir.glob("*.json")))

    def _load_all_cases(self) -> List[Dict]:
        """加载所有案例"""
        cases_dir = memory_l4_cases_dir()
        if not cases_dir.exists():
            return []
        cases = []
        for f in cases_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    cases.append(json.load(fp))
            except Exception:
                continue
        return cases

    def should_retrain(self) -> Dict:
        """检查是否应该触发重训

        Returns:
            {should: bool, reason: str, case_count: int, new_cases: int, hours_since: float}
        """
        current_count = self._count_cases()
        new_cases = current_count - self.last_case_count
        now = time.time()
        hours_since = (now - self.last_retrain_time) / 3600 if self.last_retrain_time else 999

        if new_cases >= self.retrain_interval_cases:
            return {
                "should": True,
                "reason": f"新增案例 {new_cases} >= {self.retrain_interval_cases}",
                "case_count": current_count,
                "new_cases": new_cases,
                "hours_since": round(hours_since, 2),
            }

        if hours_since >= self.retrain_interval_hours and current_count >= 15:
            return {
                "should": True,
                "reason": f"距上次重训 {hours_since:.1f}h >= {self.retrain_interval_hours}h",
                "case_count": current_count,
                "new_cases": new_cases,
                "hours_since": round(hours_since, 2),
            }

        return {
            "should": False,
            "reason": "未达阈值",
            "case_count": current_count,
            "new_cases": new_cases,
            "hours_since": round(hours_since, 2),
        }

    def trigger_retrain(self, force: bool = False) -> Dict:
        """触发重训

        Args:
            force: 是否强制执行

        Returns:
            {ok: bool, retrained: bool, reason: str, case_count: int, liangyi_updated: bool}
        """
        with self._lock:
            check = self.should_retrain()
            if not force and not check["should"]:
                return {"ok": True, "retrained": False, "reason": check["reason"],
                        "case_count": check["case_count"]}

            cases = self._load_all_cases()
            if len(cases) < 5:
                return {"ok": False, "retrained": False,
                        "reason": f"案例不足 {len(cases)} < 5",
                        "case_count": len(cases)}

            liangyi_updated = False
            try:
                liangyi_updated = self._retrain_liangyi(cases)
            except Exception as e:
                print(f"[LearningScheduler] 两仪重训失败: {e}")

            qmm_updated = False
            try:
                qmm_updated = self._retrain_qmm(cases)
            except Exception as e:
                print(f"[LearningScheduler] QMM 重训失败: {e}")

            self.last_retrain_time = time.time()
            self.last_case_count = len(cases)
            self.retrain_count += 1
            self._save_state()

            if self.on_retrain_complete:
                try:
                    self.on_retrain_complete({
                        "case_count": len(cases),
                        "liangyi_updated": liangyi_updated,
                        "qmm_updated": qmm_updated,
                        "retrain_count": self.retrain_count,
                    })
                except Exception:
                    pass

            return {
                "ok": True,
                "retrained": True,
                "reason": "重训完成",
                "case_count": len(cases),
                "liangyi_updated": liangyi_updated,
                "qmm_updated": qmm_updated,
                "retrain_count": self.retrain_count,
            }

    def _retrain_liangyi(self, cases: List[Dict]) -> bool:
        """重训两仪引擎

        Returns:
            是否有参数更新
        """
        engine = self.bcrm_engine
        liangyi = engine.liangyi_engine

        learnable_cases = []
        for case in cases:
            if not case.get("liangyi_state") or not case.get("actual_outcome"):
                continue
            learnable_cases.append(case)

        if len(learnable_cases) < 3:
            return False

        updated = False
        if hasattr(liangyi, 'learn_from_cases'):
            result = liangyi.learn_from_cases(learnable_cases)
            updated = result.get("updated", False) if isinstance(result, dict) else False

        if hasattr(liangyi, 'save_state'):
            save_path = memory_l4_dir() / "liangyi_state.json"
            try:
                liangyi.save_state(str(save_path))
            except Exception:
                pass

        return updated

    def _retrain_qmm(self, cases: List[Dict]) -> bool:
        """重训 QMM 模型

        Returns:
            是否更新成功
        """
        if len(cases) < 15:
            return False

        try:
            from scripts.memory_l4.qmm.xgb_predictor import QMMPredictor
            predictor = QMMPredictor()
            train_result = predictor.train(cases)
            if train_result.get("ok"):
                model_path = memory_l4_dir() / "qmm_model"
                model_path.mkdir(parents=True, exist_ok=True)
                model_file = str(model_path / "qmm_xgb_model.json")
                try:
                    if hasattr(predictor, 'save'):
                        predictor.save(model_file)
                    elif hasattr(predictor, 'save_model'):
                        predictor.save_model(model_file)
                except Exception:
                    pass
                return True
        except Exception as e:
            print(f"[LearningScheduler] QMM 重训异常: {e}")

        return False

    def get_state(self) -> Dict:
        """获取调度器状态"""
        check = self.should_retrain()
        return {
            "retrain_count": self.retrain_count,
            "last_retrain_time": self.last_retrain_time,
            "last_retrain_time_str": datetime.fromtimestamp(
                self.last_retrain_time, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S") if self.last_retrain_time else "从未",
            "last_case_count": self.last_case_count,
            "current_case_count": check["case_count"],
            "new_cases_since": check["new_cases"],
            "hours_since_last": check["hours_since"],
            "next_retrain_threshold_cases": self.retrain_interval_cases,
            "next_retrain_threshold_hours": self.retrain_interval_hours,
        }
