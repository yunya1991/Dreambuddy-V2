#!/usr/bin/env python3
"""
A7 实践论门禁 — 纯代码驱动，不依赖大模型。

基于《实践论》核心思想："真理的标准只能是社会的实践"，
在交易执行前进行代码级门禁检查，拦截未经实践验证的决策。

检查项（全部代码驱动）：
  1. 认识来源充分性 — BCRM 信号是否有效（非 fail_closed）
  2. 实践验证充分性 — CBR 案例库中同类信号的历史样本数
  3. 真理标准明确性 — 同类信号的历史胜率是否达标
  4. 风险可控性 — 当前风控状态（日亏损/连亏/总仓位）
  5. 执行纪律 — 止损止盈参数是否合理
  6. A0 矛盾预警 — A0 矛盾分析是否有极端预警
"""
import os
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class GateCheckResult:
    """单项检查结果"""
    name: str
    passed: bool
    score: float          # 0-1
    details: str = ""
    severity: str = "info"  # info / warn / error


@dataclass
class A7GateReport:
    """A7 门禁报告"""
    gate_type: str = ""
    timestamp: str = ""
    checks: List[GateCheckResult] = field(default_factory=list)
    passed: bool = False
    pass_rate: float = 0.0
    blocking_reasons: List[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "gate_type": self.gate_type,
            "timestamp": self.timestamp,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 4),
            "checks": [
                {"name": c.name, "passed": c.passed, "score": round(c.score, 4),
                 "details": c.details, "severity": c.severity}
                for c in self.checks
            ],
            "blocking_reasons": self.blocking_reasons,
            "recommendation": self.recommendation,
        }


class A7PracticeGate:
    """A7 实践论门禁 — 纯代码驱动"""

    # 门禁阈值
    MIN_CBR_SAMPLES = 3          # CBR 最少样本数
    MIN_WIN_RATE = 0.40          # 最低历史胜率
    MAX_DAILY_LOSS_PCT = 0.05    # 最大日亏损比例
    MAX_CONSECUTIVE_LOSS = 3     # 最大连续亏损次数
    MIN_SL_ATR_MULT = 1.0        # 最小止损 ATR 倍数
    MAX_POSITION_RATIO = 0.8     # 最大仓位占用比例

    def __init__(self, workspace_root: str = ""):
        """初始化，不再硬编码旧路径"""
        if not workspace_root:
            # 自动推断项目根目录
            current = os.path.dirname(os.path.abspath(__file__))
            workspace_root = os.path.dirname(os.path.dirname(current))
        self.workspace_root = workspace_root
        self.gate_logs_dir = os.path.join(workspace_root, "data", "a7_gate_logs")
        os.makedirs(self.gate_logs_dir, exist_ok=True)

        # 运行时统计
        self._gate_stats = {
            "total_checks": 0,
            "total_blocked": 0,
            "block_reasons": {},
        }

    def check_before_execute(
        self,
        inference: Dict[str, Any],
        risk_manager=None,
        cbr_engine=None,
        current_equity: float = 0.0,
        max_positions: int = 3,
        current_positions: int = 0,
    ) -> A7GateReport:
        """
        执行前门禁检查（代码驱动，不依赖大模型）。

        Args:
            inference: BCRM2 推理结果
            risk_manager: RiskManager 实例
            cbr_engine: CBR 引擎实例
            current_equity: 当前权益
            max_positions: 最大持仓数
            current_positions: 当前持仓数
        """
        report = A7GateReport(
            gate_type="A7_pre_execution",
            timestamp=datetime.now().isoformat(),
        )

        direction = inference.get("direction", "FLAT")
        confidence = inference.get("confidence", 0.0)
        fail_closed = inference.get("fail_closed", False)
        a0_analysis = inference.get("a0_analysis", {})
        a0_warnings = inference.get("a0_warnings", [])
        volatility = inference.get("volatility", 0.03)

        # 检查1: 认识来源充分性 — BCRM 信号是否有效
        c1 = self._check_signal_validity(direction, confidence, fail_closed)
        report.checks.append(c1)

        # 检查2: 实践验证充分性 — CBR 案例库样本数
        c2 = self._check_cbr_samples(inference, cbr_engine)
        report.checks.append(c2)

        # 检查3: 真理标准 — 同类信号历史胜率
        c3 = self._check_historical_win_rate(inference, cbr_engine)
        report.checks.append(c3)

        # 检查4: 风险可控性 — 风控状态
        c4 = self._check_risk_status(risk_manager, current_equity)
        report.checks.append(c4)

        # 检查5: 执行纪律 — 止损参数 + 仓位限制
        c5 = self._check_execution_discipline(
            volatility, current_positions, max_positions, inference
        )
        report.checks.append(c5)

        # 检查6: A0 矛盾预警
        c6 = self._check_a0_warnings(a0_analysis, a0_warnings)
        report.checks.append(c6)

        # 检查7: 三角校验（BCRM2 × 力学引擎 × A0）
        triangle = inference.get("triangle_verification")
        c7 = self._check_triangle_verification(triangle)
        report.checks.append(c7)

        # 汇总判定
        passed_checks = sum(1 for c in report.checks if c.passed)
        total_checks = len(report.checks)
        report.pass_rate = passed_checks / total_checks if total_checks > 0 else 0

        # 关键检查项必须通过（信号有效性 + 风险可控 + A0预警 + 三角校验）
        critical_checks = [c1, c4, c6, c7]
        report.passed = all(c.passed for c in critical_checks)

        # 收集阻断原因
        for c in report.checks:
            if not c.passed and c.severity in ("error", "warn"):
                report.blocking_reasons.append(f"{c.name}: {c.details}")

        if report.passed:
            report.recommendation = "门禁通过，可以执行"
        else:
            report.recommendation = f"门禁拦截: {'; '.join(report.blocking_reasons)}"

        # 更新统计
        self._gate_stats["total_checks"] += 1
        if not report.passed:
            self._gate_stats["total_blocked"] += 1
            for reason in report.blocking_reasons:
                key = reason.split(":")[0]
                self._gate_stats["block_reasons"][key] = \
                    self._gate_stats["block_reasons"].get(key, 0) + 1

        # 保存报告
        self._save_report(report)

        logger.info(
            f"[A7门禁] {'PASS' if report.passed else 'BLOCK'} "
            f"pass_rate={report.pass_rate:.0%} "
            f"checks={passed_checks}/{total_checks} "
            f"reasons={report.blocking_reasons}"
        )

        return report

    # ================================================================
    # 检查1: 信号有效性
    # ================================================================
    def _check_signal_validity(self, direction, confidence, fail_closed) -> GateCheckResult:
        """检查 BCRM 信号是否有效"""
        if fail_closed:
            return GateCheckResult(
                "信号有效性", False, 0.0,
                "BCRM fail_closed=True，信号无效", "error"
            )
        if direction == "FLAT":
            return GateCheckResult(
                "信号有效性", False, 0.0,
                "方向为FLAT，无可执行信号", "error"
            )
        if confidence < 0.3:
            return GateCheckResult(
                "信号有效性", False, 0.2,
                f"置信度过低({confidence:.2f}<0.30)", "error"
            )
        score = min(confidence, 1.0)
        return GateCheckResult(
            "信号有效性", True, score,
            f"方向={direction} 置信度={confidence:.2f}", "info"
        )

    # ================================================================
    # 检查2: CBR 样本充分性
    # ================================================================
    def _check_cbr_samples(self, inference, cbr_engine) -> GateCheckResult:
        """检查 CBR 案例库中同类信号的样本数"""
        if cbr_engine is None:
            # CBR 引擎不可用时不阻断，但降分
            return GateCheckResult(
                "实践验证充分性", True, 0.5,
                "CBR引擎未接入，跳过样本检查（降分）", "warn"
            )

        try:
            case_base = getattr(cbr_engine, "case_base", None)
            if case_base is None:
                return GateCheckResult(
                    "实践验证充分性", True, 0.5,
                    "案例库未加载，跳过", "warn"
                )

            total_cases = len(case_base.cases)
            if total_cases < self.MIN_CBR_SAMPLES:
                return GateCheckResult(
                    "实践验证充分性", False, 0.2,
                    f"案例库样本不足({total_cases}<{self.MIN_CBR_SAMPLES})",
                    "warn"
                )

            score = min(total_cases / 50.0, 1.0)
            return GateCheckResult(
                "实践验证充分性", True, score,
                f"案例库样本{total_cases}个", "info"
            )
        except Exception as e:
            return GateCheckResult(
                "实践验证充分性", True, 0.3,
                f"CBR检查异常: {e}", "warn"
            )

    # ================================================================
    # 检查3: 历史胜率
    # ================================================================
    def _check_historical_win_rate(self, inference, cbr_engine) -> GateCheckResult:
        """检查同类信号的历史胜率"""
        if cbr_engine is None:
            return GateCheckResult(
                "真理标准验证", True, 0.5,
                "CBR引擎未接入，跳过胜率检查", "warn"
            )

        try:
            cbr_bridge = getattr(inference, "get", lambda *a: None)("cbr_result") or {}
            win_rate = cbr_bridge.get("cbr_historical_win_rate", None)

            if win_rate is None:
                return GateCheckResult(
                    "真理标准验证", True, 0.5,
                    "无CBR增强数据，跳过胜率检查", "warn"
                )

            if win_rate < self.MIN_WIN_RATE:
                return GateCheckResult(
                    "真理标准验证", False, win_rate,
                    f"历史胜率过低({win_rate:.1%}<{self.MIN_WIN_RATE:.0%})",
                    "warn"
                )

            return GateCheckResult(
                "真理标准验证", True, win_rate,
                f"历史胜率{win_rate:.1%}", "info"
            )
        except Exception:
            return GateCheckResult(
                "真理标准验证", True, 0.5,
                "胜率检查异常，跳过", "warn"
            )

    # ================================================================
    # 检查4: 风险可控性
    # ================================================================
    def _check_risk_status(self, risk_manager, current_equity) -> GateCheckResult:
        """检查风控状态"""
        if risk_manager is None:
            return GateCheckResult(
                "风险可控性", True, 0.5,
                "风控管理器未接入，跳过", "warn"
            )

        try:
            risk_check = risk_manager.can_trade(current_equity)
            if not risk_check.get("allowed", True):
                return GateCheckResult(
                    "风险可控性", False, 0.0,
                    f"风控拦截: {risk_check.get('reason', '未知')}",
                    "error"
                )

            # 检查日亏损
            daily_loss = getattr(risk_manager, "daily_pnl_pct", 0)
            if daily_loss < -self.MAX_DAILY_LOSS_PCT:
                return GateCheckResult(
                    "风险可控性", False, 0.1,
                    f"日亏损{daily_loss:.2%}超限({-self.MAX_DAILY_LOSS_PCT:.0%})",
                    "error"
                )

            # 检查连续亏损
            consec_loss = getattr(risk_manager, "consecutive_losses", 0)
            if consec_loss >= self.MAX_CONSECUTIVE_LOSS:
                return GateCheckResult(
                    "风险可控性", False, 0.2,
                    f"连续亏损{consec_loss}次，触发熔断",
                    "error"
                )

            return GateCheckResult(
                "风险可控性", True, 0.8,
                f"风控通过 (日亏损={daily_loss:.2%} 连亏={consec_loss})",
                "info"
            )
        except Exception as e:
            return GateCheckResult(
                "风险可控性", True, 0.3,
                f"风控检查异常: {e}", "warn"
            )

    # ================================================================
    # 检查5: 执行纪律
    # ================================================================
    def _check_execution_discipline(
        self, volatility, current_positions, max_positions, inference
    ) -> GateCheckResult:
        """检查止损参数和仓位限制"""
        issues = []

        # 仓位限制检查
        if current_positions >= max_positions:
            issues.append(f"已达最大持仓({current_positions}/{max_positions})")

        # 波动率检查：极端波动时不允许开仓
        if volatility > 0.08:
            issues.append(f"波动率极高({volatility:.4f})")

        # 止损参数检查
        sl_atr = inference.get("sl_atr", 1.5)
        if sl_atr < self.MIN_SL_ATR_MULT:
            issues.append(f"止损倍数过低({sl_atr:.1f}<{self.MIN_SL_ATR_MULT})")

        if issues:
            return GateCheckResult(
                "执行纪律", False, 0.3,
                "; ".join(issues), "warn"
            )

        return GateCheckResult(
            "执行纪律", True, 0.8,
            f"vol={volatility:.4f} pos={current_positions}/{max_positions} sl_atr={sl_atr}",
            "info"
        )

    # ================================================================
    # 检查6: A0 矛盾预警
    # ================================================================
    def _check_a0_warnings(self, a0_analysis, a0_warnings) -> GateCheckResult:
        if not a0_analysis:
            return GateCheckResult(
                "A0矛盾预警", True, 0.5,
                "A0分析未执行，跳过", "warn"
            )

        # 创伤信号 → 阻断
        if a0_analysis.get("trauma_signal", False):
            return GateCheckResult(
                "A0矛盾预警", False, 0.0,
                "A0创伤信号：连续3次同方向错误", "error"
            )

        # 极端张力 → 阻断
        overall_tension = a0_analysis.get("overall_tension", 0)
        if overall_tension > 0.7:
            return GateCheckResult(
                "A0矛盾预警", False, 0.1,
                f"A0综合张力极高({overall_tension:.2f})", "error"
            )

        # 有预警但未到极端 → 降分但不阻断
        if a0_warnings:
            return GateCheckResult(
                "A0矛盾预警", True, 0.4,
                f"A0有预警: {a0_warnings}", "warn"
            )

        direction_bias = a0_analysis.get("direction_bias", 0)
        score = 1.0 - abs(direction_bias) * 0.5
        return GateCheckResult(
            "A0矛盾预警", True, score,
            f"张力={overall_tension:.2f} 偏置={direction_bias:+.2f}", "info"
        )

    # ================================================================
    # 检查7: 三角校验（BCRM2 × 力学引擎 × A0）
    # ================================================================
    def _check_triangle_verification(self, triangle: Optional[dict]) -> GateCheckResult:
        """检查三角校验结果"""
        if not triangle:
            return GateCheckResult(
                "三角校验", True, 0.5,
                "三角校验未执行，跳过", "warn"
            )

        verdict = triangle.get("verdict", "")
        agreement = triangle.get("agreement_score", 0)
        reversal_alert = triangle.get("reversal_alert", False)
        should_fail = triangle.get("should_fail_closed", False)

        # 严重分歧 → 阻断
        if should_fail or verdict == "CONFLICT":
            return GateCheckResult(
                "三角校验", False, 0.0,
                f"三源严重分歧({verdict})，一致性={agreement:.0%}", "error"
            )

        # 强反转预警 → 阻断
        if reversal_alert:
            strength = triangle.get("reversal_strength", 0)
            return GateCheckResult(
                "三角校验", False, 0.1,
                f"强反转预警(强度={strength:.2f})", "error"
            )

        # 分歧 → 降分但不阻断
        if verdict == "DIVERGENT":
            return GateCheckResult(
                "三角校验", True, 0.3,
                f"三源分歧({verdict})，一致性={agreement:.0%}", "warn"
            )

        # 多数一致
        if verdict == "MAJORITY_AGREE":
            return GateCheckResult(
                "三角校验", True, 0.7,
                f"多数一致({verdict})，一致性={agreement:.0%}", "info"
            )

        # 完全一致
        if verdict == "STRONG_AGREE":
            return GateCheckResult(
                "三角校验", True, 1.0,
                f"三源完全一致({verdict})", "info"
            )

        return GateCheckResult(
            "三角校验", True, 0.5,
            f"校验结果: {verdict}", "info"
        )

    # ================================================================
    # 报告保存
    # ================================================================
    def _save_report(self, report: A7GateReport):
        """保存门禁报告"""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(self.gate_logs_dir, f"a7_gate_{ts}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_stats(self) -> dict:
        """获取门禁统计"""
        return self._gate_stats.copy()
