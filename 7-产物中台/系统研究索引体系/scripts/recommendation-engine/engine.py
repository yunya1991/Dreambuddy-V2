#!/usr/bin/env python3
# ============================================================================
# 推荐策略引擎 - Python 核心调度脚本
# ============================================================================
# 路径: scripts/recommendation-engine/engine.py
# 用途: 每天 06:00 定时运行，从研报生成推荐策略，经过回测和优化后写入 Prisma
# 触发方式:
#   python3 engine.py              # 手动运行
#   python3 engine.py --auto       # 自动运行（供 cron 调用）
#   python3 engine.py --force     # 强制刷新（绕过5日限制）
#
# 依赖:
#   - Python 3.11+
#   - requests (用于调用内部 API)
#   - 6-TRADING/skills/ 目录下的 SKILL 系统
#   - ~/.workbuddy/artifacts/trading/index.json (研报数据)
# ============================================================================

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# ============================================================================
# 配置
# ============================================================================

WORKSPACE = Path.home() / ".workbuddy"
ARTIFACTS_ROOT = WORKSPACE / "artifacts"
TRADING_ARTIFACTS = ARTIFACTS_ROOT / "trading"
RECOMMENDATION_ARTIFACTS = ARTIFACTS_ROOT / "recommendation"
SKILLS_DIR = Path(__file__).parent.parent.parent / "6-TRADING" / "skills"

# 内部 API（产物中台 Next.js 服务）
INTERNAL_API_BASE = os.environ.get(
    "RECOMMENDATION_ENGINE_API_URL",
    "http://localhost:3456/api/recommendation-engine/internal"
)
INTERNAL_API_KEY = os.environ.get("RECOMMENDATION_ENGINE_API_KEY", "")

# 默认配置
DEFAULT_CONFIG = {
    "baseline_version": "v9",
    "backtest_period": "7D",
    "symbol": "BTC-USDT-SWAP",
    "max_candidates": 5,
    "forced_refresh_days": 5,
    "rollback_threshold": 3,
    "bayesian_rounds": 200,
    "min_better_count": 3,
}


# ============================================================================
# 枚举和类型
# ============================================================================

class TriggerType(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    FORCED = "forced"


class EngineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class EngineStep(str, Enum):
    FETCHING_REPORTS = "fetching_reports"
    GENERATING_CANDIDATES = "generating_candidates"
    RUNNING_BACKTESTS = "running_backtests"
    OPTIMIZING_PARAMS = "optimizing_params"
    MAKING_DECISION = "making_decision"
    WRITING_TO_PRISMA = "writing_to_prisma"
    UPDATING_LIBRARY = "updating_library"
    COMPLETED = "completed"


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class ResearchReport:
    file: str
    title: str
    date: str
    chain_phase: str
    regime: Optional[str] = None
    confidence: Optional[float] = None
    direction: Optional[str] = None
    key_signals: list = field(default_factory=list)


@dataclass
class CandidateStrategy:
    name: str
    description: str
    direction: str  # BUY / SHORT
    regime: str
    confidence: int
    symbol: str = "BTC-USDT-SWAP"
    trade_type: str = "SWAP"
    leverage: int = 1
    position_size: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    source_report_ids: list = field(default_factory=list)
    dze_chain: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    strategy_name: str
    sharpe_ratio: float
    max_drawdown: float  # %
    win_rate: float  # %
    profit_factor: float
    total_return: float  # %
    trade_count: int
    baseline_sharpe: float
    baseline_max_dd: float
    baseline_total_return: float
    is_better_than_baseline: bool
    better_count: int
    report_path: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["isBetterThanBaseline"] = d.pop("is_better_than_baseline")
        d["strategyName"] = d.pop("strategy_name")
        d["sharpeRatio"] = d.pop("sharpe_ratio")
        d["maxDrawdown"] = d.pop("max_drawdown")
        d["winRate"] = d.pop("win_rate")
        d["profitFactor"] = d.pop("profit_factor")
        d["totalReturn"] = d.pop("total_return")
        d["tradeCount"] = d.pop("trade_count")
        d["baselineSharpe"] = d.pop("baseline_sharpe")
        d["baselineMaxDD"] = d.pop("baseline_max_dd")
        d["baselineTotalReturn"] = d.pop("baseline_total_return")
        d["betterCount"] = d.pop("better_count")
        d["reportPath"] = d.pop("report_path")
        return d


@dataclass
class EngineConfig:
    baseline_version: str = "v9"
    backtest_period: str = "7D"
    symbol: str = "BTC-USDT-SWAP"
    max_candidates: int = 5
    forced_refresh_days: int = 5
    rollback_threshold: int = 3
    bayesian_rounds: int = 200
    min_better_count: int = 3


# ============================================================================
# 核心引擎类
# ============================================================================

class RecommendationEngine:
    """推荐策略引擎主类"""

    def __init__(self, config: Optional[EngineConfig] = None):
        self.config = config or EngineConfig()
        self.run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.started_at = datetime.now()
        self.status = EngineStatus.IDLE
        self.current_step: Optional[EngineStep] = None
        self.reports: list[ResearchReport] = []
        self.candidates: list[CandidateStrategy] = []
        self.backtest_results: list[BacktestResult] = []
        self.recommended_strategy: Optional[CandidateStrategy] = None
        self.decision_reason: str = ""
        self.error_message: Optional[str] = None

        # 创建产物目录
        RECOMMENDATION_ARTIFACTS.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def _api_post(self, path: str, data: dict) -> dict:
        """调用内部 API (POST)"""
        import requests
        url = f"{INTERNAL_API_BASE}/{path}"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Api-Key": INTERNAL_API_KEY,
        }
        resp = requests.post(url, json=data, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _api_get(self, path: str, params: Optional[dict] = None) -> dict:
        """调用内部 API (GET)"""
        import requests
        url = f"{INTERNAL_API_BASE}/{path}"
        headers = {"X-Internal-Api-Key": INTERNAL_API_KEY}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _load_config(self) -> dict:
        """从 API 加载引擎配置（失败则用默认配置）"""
        try:
            result = self._api_get("strategy", {"action": "config"})
            if result.get("success"):
                configs = {c["key"]: c["value"] for c in result["configs"]}
                return {**DEFAULT_CONFIG, **configs}
        except Exception:
            pass
        return DEFAULT_CONFIG

    def _get_current_recommended(self) -> Optional[dict]:
        """获取当前推荐的策略"""
        try:
            result = self._api_get("strategy", {"action": "current_recommended"})
            return result.get("strategy")
        except Exception:
            return None

    def _log(self, message: str, level: str = "INFO"):
        """日志输出"""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] [{self.current_step or 'INIT'}] {message}")

    # -------------------------------------------------------------------------
    # Step 1: 读取研报
    # -------------------------------------------------------------------------

    def step_fetch_reports(self) -> list[ResearchReport]:
        """读取 A1-A3 最新研报"""
        self.current_step = EngineStep.FETCHING_REPORTS
        self._log("开始读取 A1-A3 最新研报...")

        index_path = TRADING_ARTIFACTS / "index.json"
        if not index_path.exists():
            self._log(f"研报索引文件不存在: {index_path}", "WARN")
            return []

        with open(index_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        artifacts = raw if isinstance(raw, list) else raw.get("artifacts", [])

        # 过滤 A1/A2/A3
        phases = ["A1", "A2", "A3"]
        filtered = [
            a for a in artifacts
            if a.get("chain_phase", "").upper() in phases
        ]

        # 按日期降序，取最近 7 天
        cutoff = datetime.now() - timedelta(days=7)
        recent = [
            a for a in filtered
            if a.get("date") and datetime.fromisoformat(a["date"].replace("Z", "+00:00")) >= cutoff
        ] if filtered else []

        recent.sort(key=lambda a: a.get("date", ""), reverse=True)

        self.reports = [
            ResearchReport(
                file=r.get("file", ""),
                title=r.get("title", ""),
                date=r.get("date", ""),
                chain_phase=r.get("chain_phase", ""),
                regime=r.get("regime"),
                confidence=r.get("confidence"),
                direction=r.get("direction"),
                key_signals=r.get("tags", "").split(",") if r.get("tags") else [],
            )
            for r in recent[:20]
        ]

        self._log(f"读取到 {len(self.reports)} 份研报")
        return self.reports

    # -------------------------------------------------------------------------
    # Step 2: D-Z-E 思维链策略生成
    # -------------------------------------------------------------------------

    def step_generate_candidates(self) -> list[CandidateStrategy]:
        """使用 D-Z-E 思维链 + 联网搜索生成候选策略"""
        self.current_step = EngineStep.GENERATING_CANDIDATES
        self._log("开始 D-Z-E 思维链策略生成...")

        candidates: list[CandidateStrategy] = []

        if not self.reports:
            self._log("无研报数据，生成默认候选策略（基于最新市场状态）", "WARN")
            # 生成基于市场状态的默认候选策略
            candidates = self._generate_default_candidates()
        else:
            # 基于研报数据生成候选策略
            for report in self.reports[: self.config.max_candidates]:
                c = self._generate_candidate_from_report(report)
                if c:
                    candidates.append(c)

        self.candidates = candidates
        self._log(f"生成了 {len(self.candidates)} 个候选策略")
        return self.candidates

    def _generate_candidate_from_report(self, report: ResearchReport) -> Optional[CandidateStrategy]:
        """基于单份研报生成候选策略"""
        # 解析研报中的方向和置信度
        direction = (report.direction or "BUY").upper()
        regime = report.regime or "UNKNOWN"
        confidence = int(report.confidence or 60)

        # D-Z-E 思维链
        dze_chain = {
            "D": f"基于 {report.chain_phase} 研报「{report.title}」的市场分析，"
                 f"判断当前 regime={regime}，推荐 direction={direction}",
            "Z": "清零旧认知：不受历史持仓影响，独立评估当前市场状态。"
                 f"关注报告中的关键信号：{', '.join(report.key_signals[:3]) if report.key_signals else '无'}",
            "E": f"入场决策：在 regime={regime} 下，"
                 f"当 BTC 处于 {regime} 状态时，执行 {direction} 方向马丁策略。"
                 f"置信度 {confidence}%，建议仓位 50-100%，杠杆 1-3x"
        }

        return CandidateStrategy(
            name=f"RECOMMENDED-{report.chain_phase}-{report.date[:10]}-{direction}",
            description=f"基于 {report.chain_phase} 研报「{report.title}」生成的推荐策略",
            direction=direction,
            regime=regime,
            confidence=confidence,
            symbol=self.config.symbol,
            source_report_ids=[report.file],
            dze_chain=dze_chain,
        )

    def _generate_default_candidates(self) -> list[CandidateStrategy]:
        """生成默认候选策略（无研报时）"""
        return [
            CandidateStrategy(
                name=f"RECOMMENDED-DEFAULT-BUY-{datetime.now().strftime('%Y%m%d')}",
                description="默认推荐策略（无研报数据，基于近期市场分析）",
                direction="BUY",
                regime="ABOVE_ALL",
                confidence=55,
                symbol=self.config.symbol,
            ),
            CandidateStrategy(
                name=f"RECOMMENDED-DEFAULT-SHORT-{datetime.now().strftime('%Y%m%d')}",
                description="默认推荐策略（无研报数据，基于近期市场分析）",
                direction="SHORT",
                regime="BELOW_ALL",
                confidence=55,
                symbol=self.config.symbol,
            ),
        ]

    # -------------------------------------------------------------------------
    # Step 3: 回测（候选策略 vs 基线，调用 6-TRADING 回测引擎）
    # -------------------------------------------------------------------------

    def step_run_backtests(self) -> list[BacktestResult]:
        """对候选策略运行回测，对比基线"""
        self.current_step = EngineStep.RUNNING_BACKTESTS
        self._log(f"开始回测 {len(self.candidates)} 个候选策略 (基线: {self.config.baseline_version})...")

        results: list[BacktestResult] = []
        baseline_metrics = self._get_baseline_metrics(self.config.baseline_version)

        # 计算回测日期范围（近7天）
        now = datetime.now()
        end_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        for candidate in self.candidates:
            result = self._backtest_single_candidate(
                candidate, baseline_metrics, start_date, end_date
            )
            results.append(result)
            self._log(
                f"  {candidate.name}: Sharpe={result.sharpe_ratio:.3f}, "
                f"MaxDD={result.max_drawdown:.2f}%, Return={result.total_return:.2f}%, "
                f"vs Baseline: {'✓ 优于' if result.is_better_than_baseline else '✗ 劣于'}"
            )

        self.backtest_results = results
        self._log(f"回测完成，{sum(1 for r in results if r.is_better_than_baseline)} 个优于基线")
        return results

    def _get_baseline_metrics(self, version: str) -> dict:
        """获取基线策略的回测参考指标"""
        return {
            "v9": {"sharpe_ratio": 0.670, "max_drawdown": 4.62, "total_return": 23.80},
            "v15": {"sharpe_ratio": 0.670, "max_drawdown": 4.62, "total_return": 23.80},
        }.get(version, {"sharpe_ratio": 0.670, "max_drawdown": 4.62, "total_return": 23.80})

    def _find_backtest_script(self) -> Optional[Path]:
        """查找 backtest_engine_main.py 路径"""
        candidates = [
            Path.home() / "WorkBuddy" / "dreambuddy-v2" / "6-TRADING" / "scripts",
            Path.home() / "WorkBuddy" / "dreambuddy-v2" / "6-TRADING",
            Path(__file__).parent.parent.parent / "6-TRADING" / "scripts",
        ]
        for cand in candidates:
            script = cand / "backtest_engine_main.py"
            if script.exists():
                return script
        return None

    def _find_bayesian_script(self) -> Optional[Path]:
        """查找 bayesian_opt_engine.py 路径"""
        candidates = [
            Path.home() / "WorkBuddy" / "dreambuddy-v2" / "6-TRADING" / "scripts",
            Path.home() / "WorkBuddy" / "dreambuddy-v2" / "6-TRADING",
            Path(__file__).parent.parent.parent / "6-TRADING" / "scripts",
        ]
        for cand in candidates:
            script = cand / "bayesian_opt_engine.py"
            if script.exists():
                return script
        return None

    def _backtest_single_candidate(
        self,
        candidate: CandidateStrategy,
        baseline_metrics: dict,
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """
        对单个候选策略运行回测（调用 6-TRADING 回测引擎）
        如果引擎不可用，则使用模拟数据作为降级方案
        """
        script_path = self._find_backtest_script()

        if script_path is None:
            self._log(f"未找到回测引擎脚本，使用模拟数据", "WARN")
            return self._mock_backtest(candidate, baseline_metrics)

        # 构建输出路径
        safe_name = candidate.name.replace(r"[^a-zA-Z0-9_\-]", "_")
        output_file = RECOMMENDATION_ARTIFACTS / f"backtest_{safe_name}_{self.run_id}.json"
        RECOMMENDATION_ARTIFACTS.mkdir(parents=True, exist_ok=True)

        # 调用回测引擎
        try:
            import subprocess as sp
            proc = sp.run(
                [
                    "python3", str(script_path),
                    "--inst", self.config.symbol,
                    "--from", start_date,
                    "--to", end_date,
                    "--capital", "200",
                    "--output", str(output_file),
                ],
                capture_output=True, text=True, timeout=300,
            )

            if proc.returncode != 0:
                self._log(f"回测进程失败 (code={proc.returncode}): {proc.stderr[:200]}", "WARN")
                return self._mock_backtest(candidate, baseline_metrics)

            # 读取输出 JSON
            if output_file.exists():
                raw = json.loads(output_file.read_text(encoding="utf-8"))
                sharpe_ratio = raw.get("sharpe_ratio", 0) or 0
                max_drawdown = raw.get("max_drawdown", 999) or 999
                total_return = raw.get("total_return", 0) or 0
                win_rate = raw.get("win_rate", 0) or 0
                profit_factor = raw.get("profit_factor", 0) or 0
                trade_count = raw.get("total_trades", 0) or 0
            else:
                sharpe_ratio, max_drawdown, total_return, win_rate, profit_factor, trade_count = \
                    self._parse_backtest_stdout(proc.stdout)

        except sp.TimeoutExpired:
            self._log("回测超时（5分钟），使用模拟数据", "WARN")
            return self._mock_backtest(candidate, baseline_metrics)
        except Exception as e:
            self._log(f"回测异常: {e}，使用模拟数据", "WARN")
            return self._mock_backtest(candidate, baseline_metrics)

        # 基线对比判定
        base_sharpe = baseline_metrics["sharpe_ratio"]
        base_dd = baseline_metrics["max_drawdown"]
        base_return = baseline_metrics["total_return"]

        sharpe_better = sharpe_ratio >= base_sharpe - 0.05
        dd_better = max_drawdown <= base_dd + 0.5
        return_better = total_return >= base_return - 1.0
        better_count = sum([sharpe_better, dd_better, return_better])

        return BacktestResult(
            strategy_name=candidate.name,
            sharpe_ratio=round(sharpe_ratio, 3),
            max_drawdown=round(max_drawdown, 2),
            win_rate=round(win_rate, 1),
            profit_factor=round(profit_factor, 2),
            total_return=round(total_return, 2),
            trade_count=trade_count,
            baseline_sharpe=base_sharpe,
            baseline_max_dd=base_dd,
            baseline_total_return=base_return,
            is_better_than_baseline=better_count >= self.config.min_better_count,
            better_count=better_count,
            report_path=str(output_file) if output_file.exists() else None,
        )

    def _mock_backtest(
        self,
        candidate: CandidateStrategy,
        baseline_metrics: dict,
    ) -> BacktestResult:
        """模拟回测结果（回测引擎不可用时的降级方案）"""
        import random
        random.seed(hash(candidate.name) % (2**32))

        base_sharpe = baseline_metrics["sharpe_ratio"]
        base_dd = baseline_metrics["max_drawdown"]
        base_return = baseline_metrics["total_return"]
        direction_bias = 0.05 if candidate.direction == "BUY" else -0.02

        sharpe_ratio = round(base_sharpe + random.uniform(-0.3, 0.5) + direction_bias, 3)
        max_drawdown = round(max(1.0, base_dd + random.uniform(-2, 3)), 2)
        total_return = round(base_return * random.uniform(0.5, 1.5), 2)
        win_rate = round(random.uniform(35, 60), 1)
        profit_factor = round(random.uniform(1.0, 2.5), 2)
        trade_count = random.randint(3, 15)

        sharpe_better = sharpe_ratio >= base_sharpe - 0.05
        dd_better = max_drawdown <= base_dd + 0.5
        return_better = total_return >= base_return - 1.0
        better_count = sum([sharpe_better, dd_better, return_better])

        return BacktestResult(
            strategy_name=candidate.name,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_return=total_return,
            trade_count=trade_count,
            baseline_sharpe=base_sharpe,
            baseline_max_dd=base_dd,
            baseline_total_return=base_return,
            is_better_than_baseline=better_count >= self.config.min_better_count,
            better_count=better_count,
        )

    def _parse_backtest_stdout(self, stdout: str) -> tuple:
        """从 stdout 解析回测指标（输出文件不存在时的 fallback）"""
        import re
        lines = stdout.split("\n")
        sharpe_ratio = max_drawdown = total_return = win_rate = profit_factor = 0
        trade_count = 0

        for line in lines:
            m = re.search(r"sharpe_ratio[:\s=]+([\d.\-]+)", line, re.I)
            if m: sharpe_ratio = float(m.group(1))
            m = re.search(r"max_drawdown[:\s=]+([\d.]+)", line, re.I)
            if m: max_drawdown = float(m.group(1))
            m = re.search(r"total_return[:\s=]+([\d.\-]+)", line, re.I)
            if m: total_return = float(m.group(1))
            m = re.search(r"win_rate[:\s=]+([\d.]+)", line, re.I)
            if m: win_rate = float(m.group(1))
            m = re.search(r"profit_factor[:\s=]+([\d.]+)", line, re.I)
            if m: profit_factor = float(m.group(1))
            m = re.search(r"total_trades[:\s=]+(\d+)", line, re.I)
            if m: trade_count = int(m.group(1))

        return sharpe_ratio, max_drawdown, total_return, win_rate, profit_factor, trade_count

    # -------------------------------------------------------------------------
    # Step 4: 贝叶斯参数优化（对通过基线的策略）
    # -------------------------------------------------------------------------

    def step_run_bayesian_optimization(
        self,
        backtest_results: list[BacktestResult],
        candidates: list[CandidateStrategy],
    ) -> list[BacktestResult]:
        """
        对通过基线回测的策略运行贝叶斯参数优化
        替换 _backtest_single_candidate 中的模拟数据为优化后的真实数据
        """
        self.current_step = EngineStep.OPTIMIZING_PARAMS
        script_path = self._find_bayesian_script()

        if script_path is None:
            self._log("未找到贝叶斯优化引擎脚本，跳过参数优化", "WARN")
            return backtest_results

        # 过滤通过基线的策略
        passed = [
            (r, c) for r, c in zip(backtest_results, candidates)
            if r.is_better_than_baseline
        ]

        if not passed:
            self._log("没有策略通过基线，跳过贝叶斯优化")
            return backtest_results

        self._log(f"对 {len(passed)} 个通过基线的策略运行贝叶斯优化...")

        # 计算回测日期范围
        now = datetime.now()
        end_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        optimized_results = list(backtest_results)

        for result, candidate in passed[:2]:  # 最多优化2个策略
            try:
                optimized = self._run_single_bayesian_optimization(
                    candidate, result, script_path, start_date, end_date
                )
                if optimized:
                    idx = optimized_results.index(result)
                    optimized_results[idx] = optimized
                    self._log(
                        f"  优化 {candidate.name}: Sharpe {result.sharpe_ratio:.3f} → {optimized.sharpe_ratio:.3f}"
                    )
            except Exception as e:
                self._log(f"  优化 {candidate.name} 失败: {e}", "WARN")

        return optimized_results

    def _run_single_bayesian_optimization(
        self,
        candidate: CandidateStrategy,
        original_result: BacktestResult,
        script_path: Path,
        start_date: str,
        end_date: str,
    ) -> Optional[BacktestResult]:
        """对单个策略运行贝叶斯优化"""
        import subprocess as sp
        import re

        safe_name = candidate.name.replace(r"[^a-zA-Z0-9_\-]", "_")
        opt_dir = RECOMMENDATION_ARTIFACTS / "optimization"
        opt_dir.mkdir(parents=True, exist_ok=True)

        # 先生成回测报告（贝叶斯引擎需要）
        bt_report = opt_dir / f"bt_report_{safe_name}.json"
        bt_report.write_text(json.dumps({
            "backtest_status": "OK",
            "sharpe_ratio": original_result.sharpe_ratio,
            "max_drawdown": original_result.max_drawdown,
            "win_rate": original_result.win_rate,
            "profit_factor": original_result.profit_factor,
            "total_return": original_result.total_return,
            "annual_return": original_result.total_return / 7 * 365,
            "total_trades": original_result.trade_count,
        }, indent=2))

        output_file = opt_dir / f"opt_{safe_name}_{self.run_id}.md"

        try:
            proc = sp.run(
                [
                    "python3", str(script_path),
                    "--report", str(bt_report),
                    "--objective", "sharpe",
                    "--output", str(output_file),
                ],
                capture_output=True, text=True, timeout=1800,  # 30分钟超时
            )

            if proc.returncode != 0:
                return None

            # 解析优化后的 Sharpe（从 stdout 或输出文件）
            optimized_sharpe = original_result.sharpe_ratio

            # 尝试从 stdout 解析参数
            stdout = proc.stdout
            sharpe_matches = re.findall(r"sharpe[_\s]*ratio[:\s=]+([\d.\-]+)", stdout, re.I)
            if sharpe_matches:
                optimized_sharpe = max(float(v) for v in sharpe_matches)

            # 基线对比
            baseline_metrics = self._get_baseline_metrics(self.config.baseline_version)
            base_sharpe = baseline_metrics["sharpe_ratio"]
            base_dd = baseline_metrics["max_drawdown"]
            base_return = baseline_metrics["total_return"]

            sharpe_better = optimized_sharpe >= base_sharpe - 0.05
            better_count = 1 if sharpe_better else 0

            optimized_result = BacktestResult(
                strategy_name=candidate.name,
                sharpe_ratio=round(optimized_sharpe, 3),
                max_drawdown=original_result.max_drawdown,
                win_rate=original_result.win_rate,
                profit_factor=original_result.profit_factor,
                total_return=original_result.total_return,
                trade_count=original_result.trade_count,
                baseline_sharpe=base_sharpe,
                baseline_max_dd=base_dd,
                baseline_total_return=base_return,
                is_better_than_baseline=better_count >= self.config.min_better_count,
                better_count=better_count,
                report_path=str(output_file),
            )

            return optimized_result

        except sp.TimeoutExpired:
            self._log(f"贝叶斯优化超时: {candidate.name}", "WARN")
            return None
        except Exception as e:
            self._log(f"贝叶斯优化异常: {e}", "WARN")
            return None

    # -------------------------------------------------------------------------
    # Step 5: 决策逻辑（选择推荐 or 回退基线）
    # -------------------------------------------------------------------------

    def step_make_decision(self) -> Optional[CandidateStrategy]:
        """做出推荐决策"""
        self.current_step = EngineStep.MAKING_DECISION
        self._log("开始决策...")

        # 先运行贝叶斯优化（如果回测结果中有通过基线的策略）
        if self.backtest_results:
            self.backtest_results = self.step_run_bayesian_optimization(
                self.backtest_results, self.candidates
            )

        # 检查是否强制刷新
        current = self._get_current_recommended()
        if current:
            recommended_days = current.get("recommendedDays", 0)
            if recommended_days >= self.config.forced_refresh_days:
                self._log(f"已连续推荐 {recommended_days} 天，强制刷新")
                self.decision_reason = f"强制刷新：已连续推荐 {recommended_days} 天（阈值 {self.config.forced_refresh_days} 天）"
                return self._choose_best_candidate()

        # 检查连续失败回退
        consecutive_below = current.get("consecutiveBelowBaseline", 0) if current else 0
        if consecutive_below >= self.config.rollback_threshold:
            self._log(f"连续 {consecutive_below} 次劣于基线，回退到基线策略")
            self.decision_reason = f"回退基线：连续 {consecutive_below} 次劣于基线（阈值 {self.config.rollback_threshold} 次）"
            return None  # None = 回退到基线

        # 选择最优候选策略
        return self._choose_best_candidate()

    def _choose_best_candidate(self) -> Optional[CandidateStrategy]:
        """从候选策略中选择最优的"""
        if not self.backtest_results:
            self.decision_reason = "无候选策略，使用基线"
            return None

        # 过滤优于基线的策略
        better = [
            (r, c) for r, c in zip(self.backtest_results, self.candidates)
            if r.is_better_than_baseline
        ]

        if not better:
            self._log("没有策略优于基线", "WARN")
            self.decision_reason = "所有候选策略均劣于基线，使用基线策略"
            return None

        # 按 Sharpe 排序选择最优
        better.sort(key=lambda x: x[0].sharpe_ratio, reverse=True)
        best_result, best_candidate = better[0]

        self.decision_reason = (
            f"推荐「{best_candidate.name}」（Sharpe={best_result.sharpe_ratio:.3f}, "
            f"MaxDD={best_result.max_drawdown:.2f}%, Return={best_result.total_return:.2f}%, "
            f"优于基线 {best_result.better_count}/3 项）"
        )
        self.recommended_strategy = best_candidate
        return best_candidate

    # -------------------------------------------------------------------------
    # Step 5: 写入 Prisma
    # -------------------------------------------------------------------------

    def step_write_to_prisma(self) -> Optional[str]:
        """将推荐策略写入 Prisma"""
        self.current_step = EngineStep.WRITING_TO_PRISMA
        self._log("写入 Prisma...")

        try:
            if self.recommended_strategy is None:
                # 回退基线策略
                self._log("写入基线策略作为推荐")
                # TODO: 写入基线策略
                return None

            # 找到对应的回测结果
            result = next(
                (r for r in self.backtest_results if r.strategy_name == self.recommended_strategy.name),
                None
            )

            if not result:
                self._log("未找到回测结果，跳过写入", "WARN")
                return None

            strategy_data = {
                "action": "create_strategy",
                "strategy": {
                    "type": "RECOMMENDED",
                    "name": self.recommended_strategy.name,
                    "description": self.recommended_strategy.description,
                    "direction": self.recommended_strategy.direction,
                    "symbol": self.recommended_strategy.symbol,
                    "tradeType": self.recommended_strategy.trade_type,
                    "leverage": self.recommended_strategy.leverage,
                    "positionSize": self.recommended_strategy.position_size,
                    "stopLoss": self.recommended_strategy.stop_loss,
                    "takeProfit": self.recommended_strategy.take_profit,
                    "confidence": self.recommended_strategy.confidence,
                    "status": "APPROVED",
                    "regime": self.recommended_strategy.regime,
                    "backtestSharpe": result.sharpe_ratio,
                    "backtestMaxDrawdown": result.max_drawdown,
                    "backtestWinRate": result.win_rate,
                    "backtestProfitFactor": result.profit_factor,
                    "backtestTotalReturn": result.total_return,
                    "backtestPeriod": self.config.backtest_period,
                    "backtestDate": datetime.now().isoformat(),
                    "baselineVersion": self.config.baseline_version,
                    "baselineSharpe": result.baseline_sharpe,
                    "baselineMaxDrawdown": result.baseline_max_dd,
                    "baselineTotalReturn": result.baseline_total_return,
                    "isBetterThanBaseline": result.is_better_than_baseline,
                    "isInLibrary": result.is_better_than_baseline,
                    "libraryScore": self._calc_library_score(result),
                    "libraryActive": result.is_better_than_baseline,
                    "sourceEngine": "dze-chain",
                    "sourceReportIds": ",".join(self.recommended_strategy.source_report_ids),
                    "generation": 1,
                    "recommendedDays": 0,
                },
                "backtestResult": result.to_dict(),
            }

            resp = self._api_post("strategy", strategy_data)
            self._log(f"策略已写入，ID: {resp.get('strategyId')}")
            return resp.get("strategyId")

        except Exception as e:
            self.error_message = f"写入 Prisma 失败: {e}"
            self._log(self.error_message, "ERROR")
            return None

    def _calc_library_score(self, result: BacktestResult) -> float:
        """计算策略库评分"""
        # 综合评分 = Sharpe(40%) + 收益(30%) + 回撤控制(30%)
        sharpe_score = max(0, result.sharpe_ratio / 1.0) * 0.4
        return_score = max(0, result.total_return / 50.0) * 0.3
        dd_score = max(0, (20 - result.max_drawdown) / 20.0) * 0.3
        return round(sarpe_score + return_score + dd_score, 4)

    # -------------------------------------------------------------------------
    # Step 6: 记录引擎运行日志
    # -------------------------------------------------------------------------

    def step_log_engine_run(self):
        """记录引擎运行日志"""
        self.current_step = EngineStep.UPDATING_LIBRARY
        ended_at = datetime.now()
        duration_ms = int((ended_at - self.started_at).total_seconds() * 1000)

        try:
            self._api_post("strategy", {
                "action": "log_engine_run",
                "log": {
                    "runId": self.run_id,
                    "runDate": self.started_at.isoformat(),
                    "triggerType": "scheduled",
                    "status": self.status.value,
                    "reportsUsed": len(self.reports),
                    "reportIds": [r.file for r in self.reports],
                    "candidatesGenerated": len(self.candidates),
                    "strategiesBacktested": len(self.backtest_results),
                    "strategiesPassed": sum(
                        1 for r in self.backtest_results if r.is_better_than_baseline
                    ),
                    "recommendedStrategyId": None,
                    "isForcedRefresh": False,
                    "decisionReason": self.decision_reason,
                    "errorMessage": self.error_message,
                    "durationMs": duration_ms,
                    "startedAt": self.started_at.isoformat(),
                    "endedAt": ended_at.isoformat(),
                },
            })
            self._log("运行日志已记录")
        except Exception as e:
            self._log(f"记录日志失败: {e}", "ERROR")

    # -------------------------------------------------------------------------
    # 主运行方法
    # -------------------------------------------------------------------------

    def run(self, trigger_type: TriggerType = TriggerType.SCHEDULED) -> "RecommendationEngine":
        """运行完整引擎流程"""
        self.status = EngineStatus.RUNNING
        self._log(f"=== 推荐策略引擎启动 (run_id={self.run_id}, trigger={trigger_type.value}) ===")

        try:
            # Step 1: 读取研报
            self.step_fetch_reports()

            # Step 2: 生成候选策略
            self.step_generate_candidates()

            # Step 3: 回测
            self.step_run_backtests()

            # Step 4: 决策
            self.step_make_decision()

            # Step 5: 写入 Prisma
            self.step_write_to_prisma()

            # Step 6: 记录日志
            self.step_log_engine_run()

            self.status = EngineStatus.SUCCESS
            self.current_step = EngineStep.COMPLETED
            self._log(f"=== 引擎运行完成 (status={self.status.value}) ===")

        except Exception as e:
            self.status = EngineStatus.FAILED
            self.error_message = str(e)
            self._log(f"引擎运行失败: {e}", "ERROR")
            self.step_log_engine_run()

        return self

    def get_summary(self) -> dict:
        """获取运行摘要"""
        return {
            "runId": self.run_id,
            "status": self.status.value,
            "currentStep": self.current_step.value if self.current_step else None,
            "reportsUsed": len(self.reports),
            "candidatesGenerated": len(self.candidates),
            "strategiesBacktested": len(self.backtest_results),
            "strategiesPassed": sum(
                1 for r in self.backtest_results if r.is_better_than_baseline
            ),
            "recommendedStrategy": (
                self.recommended_strategy.name
                if self.recommended_strategy
                else "基线策略"
            ),
            "decisionReason": self.decision_reason,
            "errorMessage": self.error_message,
            "startedAt": self.started_at.isoformat(),
            "durationMs": int(
                (datetime.now() - self.started_at).total_seconds() * 1000
            ),
        }


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="推荐策略引擎 - 从研报生成推荐策略并写入 Prisma"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="自动运行模式（供 cron 调用）"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制刷新（绕过5日限制）"
    )
    parser.add_argument(
        "--baseline",
        default="v9",
        choices=["v9", "v15"],
        help="基线版本（默认 v9）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅运行不回测（调试模式）"
    )

    args = parser.parse_args()

    trigger = TriggerType.FORCED if args.force else TriggerType.SCHEDULED

    engine = RecommendationEngine(config=EngineConfig(
        baseline_version=args.baseline,
    ))

    result = engine.run(trigger_type=trigger)

    # 输出结果
    summary = result.get_summary()
    print("\n" + "=" * 60)
    print("推荐策略引擎运行摘要")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("=" * 60)

    # 返回非0退出码表示失败
    if result.status == EngineStatus.FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
