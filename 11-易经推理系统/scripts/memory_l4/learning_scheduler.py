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

from scripts.memory_l4 import paths
from scripts.memory_l4.bcrm.engine import BCRMEngine
from scripts.memory_l4.knowledge_bridge import KnowledgeBridge


class LearningScheduler:
    """
    学习调度器

    功能：
    - 定时检查新案例数量
    - 达到阈值时触发两仪引擎重训
    - 触发 QMM 模型重训（如果有足够案例）
    - 持久化学习结果
    - 导入 AB Trading 进化参数作为外部参考
    """

    def __init__(self,
                 bcrm_engine: BCRMEngine,
                 retrain_interval_cases: int = 10,
                 retrain_interval_hours: int = 4,
                 on_retrain_complete: Callable = None,
                 shared_dir=None):
        self.bcrm_engine = bcrm_engine
        self.retrain_interval_cases = retrain_interval_cases
        self.retrain_interval_hours = retrain_interval_hours
        self.on_retrain_complete = on_retrain_complete

        self.learn_dir = paths.memory_l4_dir() / "learning"
        self.learn_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.learn_dir / "scheduler_state.json"

        self.last_retrain_time = 0
        self.last_case_count = 0
        self.retrain_count = 0

        self.knowledge_bridge = KnowledgeBridge(shared_dir=shared_dir)
        self.external_params = {}

        self._lock = threading.Lock()
        self._load_state()
        self._load_external_params()

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

    def _load_external_params(self):
        """
        加载 AB Trading 导出的进化参数作为外部参考
        """
        try:
            result = self.knowledge_bridge.load_ab_evolved_params()
            if result["ok"]:
                self.external_params = result.get("transformed", {})
                print(f"[LearningScheduler] 已加载 {len(self.external_params)} 个外部进化参数")
            else:
                self.external_params = {}
        except Exception as e:
            print(f"[LearningScheduler] 加载外部参数失败: {e}")
            self.external_params = {}

    def _apply_external_params_to_learning(self):
        """
        将外部进化参数应用到学习过程中

        外部参数影响：
        - trend_sensitivity → 调整学习率（灵敏度高时学习率降低，避免过度拟合）
        - risk_aversion → 调整权重学习率（风险厌恶高时更保守）
        - signal_confidence_bias → 调整置信度阈值
        """
        if not self.external_params:
            return

        liangyi = self.bcrm_engine.liangyi_engine

        trend_sensitivity = self.external_params.get("trend_sensitivity", 1.0)
        risk_aversion = self.external_params.get("risk_aversion", 0.5)

        if hasattr(liangyi, "LEARN_RATE") and trend_sensitivity > 1.5:
            liangyi.LEARN_RATE = min(0.3, liangyi.LEARN_RATE * (2.0 - trend_sensitivity / 2.0))
            print(f"[LearningScheduler] 外部灵敏度高，降低学习率至 {liangyi.LEARN_RATE:.4f}")

        if hasattr(liangyi, "WEIGHT_LEARN_RATE") and risk_aversion > 0.8:
            liangyi.WEIGHT_LEARN_RATE = min(0.2, liangyi.WEIGHT_LEARN_RATE * 0.7)
            print(f"[LearningScheduler] 外部风险厌恶高，降低权重学习率至 {liangyi.WEIGHT_LEARN_RATE:.4f}")

    def _count_cases(self) -> int:
        """统计当前案例总数"""
        cases_dir = paths.memory_l4_cases_dir()
        if not cases_dir.exists():
            return 0
        return len(list(cases_dir.glob("*.json")))

    def _load_all_cases(self) -> List[Dict]:
        """加载所有案例"""
        cases_dir = paths.memory_l4_cases_dir()
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

            self._load_external_params()
            self._apply_external_params_to_learning()

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

            # B-1修复：重训完成后自动触发三层自进化检查
            try:
                self._maybe_run_self_evolution(cases)
            except Exception as e:
                print(f"[LearningScheduler] 自进化检查失败: {e}")

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
            save_path = paths.memory_l4_dir() / "liangyi_state.json"
            try:
                liangyi.save_state(str(save_path))
            except Exception:
                pass

        return updated

    def _retrain_qmm(self, cases: List[Dict]) -> bool:
        """重训 QMM 模型并生成快照

        消费真实交易案例，过滤测试案例，生成 QMM 输出快照。

        Returns:
            是否更新成功
        """
        real_cases = [c for c in cases if "qmm_test" not in c.get("case_id", "")]
        if len(real_cases) < 15:
            print(f"[LearningScheduler] QMM 真实案例不足: {len(real_cases)} < 15")
            return False

        print(f"[LearningScheduler] QMM 消费 {len(real_cases)} 个真实案例")

        updated = False

        try:
            from scripts.memory_l4.qmm.engine import run_qmm
            from scripts.memory_l4.distill_engine import load_all_distills

            distills = load_all_distills()
            output = run_qmm(real_cases, distills)

            print(f"[LearningScheduler] QMM 快照生成成功: trend={output.trend_state}, "
                  f"uncertainty={output.uncertainty:.4f}, "
                  f"systems={list(output.system_source_stats.keys())}")
            updated = True
        except Exception as e:
            print(f"[LearningScheduler] QMM 引擎运行异常: {e}")

        try:
            from scripts.memory_l4.qmm.xgb_predictor import QMMPredictor
            predictor = QMMPredictor()
            train_result = predictor.train(real_cases)
            if train_result.get("ok"):
                model_path = paths.memory_l4_dir() / "qmm_model"
                model_path.mkdir(parents=True, exist_ok=True)
                model_file = str(model_path / "qmm_xgb_model.json")
                try:
                    if hasattr(predictor, 'save'):
                        predictor.save(model_file)
                    elif hasattr(predictor, 'save_model'):
                        predictor.save_model(model_file)
                except Exception:
                    pass
                print("[LearningScheduler] QMM XGB 模型训练成功")
                updated = True
        except Exception as e:
            print(f"[LearningScheduler] QMM XGB 训练异常: {e}")

        return updated

    def _maybe_run_self_evolution(self, cases: List[Dict]):
        """B-1修复：重训后自动检查是否需要触发三层自进化。

        从 cases 统计胜率/hold 比例等，传入 SelfEvolutionEngine.should_trigger()。
        如果触发，执行 run_full_cycle()，adopted 提案会自动写回 config.json（B-2）。
        """
        try:
            from scripts.memory_l4.self_evolution_engine import SelfEvolutionEngine
        except Exception:
            return

        # 从 cases 提取统计信息
        total = len(cases)
        if total == 0:
            return

        wins = sum(1 for c in cases
                   if c.get("decision_outcome", {}).get("pnl_pct", 0) > 0)
        win_rate = wins / total

        # hold 比例（近似 hold_streak）
        hold_count = sum(1 for c in cases
                         if "hold" in str(c.get("execution", {}).get("result", "")).lower())
        hold_rate = hold_count / total
        hold_streak = int(hold_rate * 10)

        # 卦象分布
        hexagrams = {}
        for c in cases:
            gua = c.get("environment_snapshot", {}).get("regime", "")
            if gua:
                hexagrams[gua] = hexagrams.get(gua, 0) + 1

        stats = {
            "win_rate": win_rate,
            "hold_rate": hold_rate,
            "hold_streak": hold_streak,
            "top_hexagrams": hexagrams,
            "total_trades": total,
        }

        engine = SelfEvolutionEngine()
        should, reason = engine.should_trigger(stats)

        if should:
            print(f"[LearningScheduler] 触发自进化: {reason}")
            engine.run_full_cycle(stats, cases[:20], force=False)
        else:
            print(f"[LearningScheduler] 自进化未触发: {reason}")

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
