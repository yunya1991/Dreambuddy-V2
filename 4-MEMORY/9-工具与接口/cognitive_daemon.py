#!/usr/bin/env python3
"""
认知守护进程 — CognitiveDaemon

AI工具无关的文件监听daemon。用mtime轮询（零外部依赖）监听代码文件变更，
自动触发认知闭环：变更检测 → 防抖合并 → record → verify。

与git hook的关系：
  - git hook: commit时触发，捕获"为什么变更"（有commit message）
  - daemon: 实时触发，捕获"什么变更了"（有文件列表，无message）
  - 互补：daemon是实时的低粒度补充，git hook是延迟的高粒度主源

用法:
  # 前台运行（调试）
  python3 cognitive_daemon.py --watch . --interval 5

  # 后台运行（生产）
  python3 cognitive_daemon.py --watch . --daemon

  # 仅扫描一次
  python3 cognitive_daemon.py --scan-once --watch .

  # 停止daemon
  python3 cognitive_daemon.py --stop
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import fnmatch
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from cognitive_loop_entry import CognitiveLoopEntry, get_cle

# 延迟导入session manager，避免循环依赖
_session_mgr = None

def _get_session_mgr():
    global _session_mgr
    if _session_mgr is None:
        try:
            from cognitive_session import CognitiveSessionManager
            _session_mgr = CognitiveSessionManager()
        except Exception:
            pass
    return _session_mgr


_skill_loader_instance = None


def _get_skill_loader():
    """SkillLoader 懒加载单例（路径 C 预热用，设计节 3.1）。"""
    global _skill_loader_instance
    if _skill_loader_instance is None:
        try:
            from cognitive_superpowers import SkillLoader
            _skill_loader_instance = SkillLoader()
        except Exception:
            _skill_loader_instance = None
    return _skill_loader_instance


# ============================================================
# 文件过滤
# ============================================================

# 监听的代码文件扩展名
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
    ".md", ".rst", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash", ".zsh",
    ".sql", ".html", ".css", ".scss", ".vue",
}

# 排除的目录（精确匹配路径任一部分）
EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".vscode", ".trae", ".claude", ".cognitive",
    "dist", "build", ".next", ".nuxt", "target",
    ".mypy_cache", ".pytest_cache", ".tox",
    "4-MEMORY/versions",  # 版本控制快照
    # === 运行时产物（非开发行为，记录即噪音）===
    "graph_store",        # dreamos图存储检查点 (39000+文件)
    "checkpoints",        # 工作记忆/交易检查点 (700+文件)
    "scheduler_data",     # 调度器历史
    "artifacts",          # 运行产物目录(.gitkeep除外，但整个目录排更稳)
    "logs", "log",        # 日志目录
    "cache", ".cache",    # 缓存
    ".workbuddy",         # L4 守护进程自动生成的运行态目录（heartbeat/stats等，全目录噪声）
    # === 交易系统自动产生的数据目录（非开发行为，避免数据污染）===
    "a7_gate_logs",       # A7门控日志（每分钟产生多个JSON）
    "episodes",           # 交易episode记录
    "l4_events",          # L4事件流
    "open_positions",     # 持仓快照
    # 注意: memory_l4/cases/evolution/guardian/learning/risk/stats 等歧义目录
    # 已移至 AMBIGUOUS_DATA_DIRS，仅在 data/ 下排除，保留 scripts/ 下的代码文件
    "qmm",                # 量化记忆模型快照
    "qmm_model",          # QMM模型文件
    "strategy_diversity", # 策略多样性统计
    # === 回测/缓存数据目录 ===
    "backtest_cache",     # 回测K线缓存
    "capital_manager",    # 资金管理器运行时状态目录
}

# 排除的文件名模式
EXCLUDE_FILES = {
    ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo", "*.swp",
    # === 运行时状态文件（高频变更但无认知价值）===
    "*.lock", "*.pid",
    "scheduler_history.json",   # 调度器历史
    "execution_feedback.json",  # 执行反馈(高频写入)
    "hyperopt.lock",            # 超参优化锁
    ".4h_dedup.json",           # 去重状态
    "heartbeat.json",           # 守护进程心跳(高频，全是噪声，任何位置都排除)
    ".*_time.json",             # 自动产生的时间戳文件(.trade_time.json等)
    # === 交易系统运行时状态快照（纯运行时数据，无认知价值，易经L4已记录交易事实）===
    "*_state.json",             # v15_state.json / orchestrator_state.json / engine_state.json
    "*_state_*.json",           # v15_state_0.json 等带数字后缀的状态文件
    "*_sltp.json",              # v4_position_sltp.json 持仓止盈止损状态
    "*_sltp_*.json",            # v4_position_sltp_0.json 等变体
    "self_schedule.json",       # 自调度状态
    "bayesian_memories.json",   # 认知系统自身产物（自引用无意义）
    # === 交易系统运行产物 JSON（data/ 下的报告/验证结果，非人工编辑）===
    "config.json",              # okx_sim/config.json 等自动生成的交易所配置
    "account_baseline.json",    # V15 账户基线快照
    "*_backtest_result.json",   # 回测结果产物
    "*_backtest_result_*.json", # 回测结果变体
    "stress_test_*_report.json",# 压力测试报告产物
    "validation_result_*.json", # 验证结果产物
    "verify_landed_report.json",# 验证落地报告产物
    "btc_windvane_*.json",      # V15 btc风向标回测产物
}


def is_code_file(filepath: str) -> bool:
    """判断是否为需要监听的代码文件"""
    p = Path(filepath)

    # 扩展名检查
    if p.suffix.lower() not in CODE_EXTENSIONS:
        return False

    parts = p.parts

    # 排除目录检查（精确路径段匹配）
    # 注意：部分目录名（如 memory_l4）既出现在 data/（运行时数据）也出现在 scripts/（代码），
    # 需区分：data/memory_l4 排除，scripts/memory_l4 保留。因此对这类歧义目录用 data/<dir> 二段匹配。
    AMBIGUOUS_DATA_DIRS = {
        "memory_l4", "cases", "evolution", "learning", "risk", "stats", "guardian",
        # 易经推理系统运行时数据子目录（位于 data/ 下）
        "okx_sim", "polling_trader", "bcrm2", "bcrm2_phase0",
        "self_evolution", "training", "l4_events", "backtest",
        # V15策略运行时数据子目录
        "bayesian_opt",
    }
    # 1) 歧义目录：仅在 data/ 下排除（scripts/memory_l4 保留，data/memory_l4 排除）
    for ambig in AMBIGUOUS_DATA_DIRS:
        for i in range(len(parts) - 1):
            if parts[i] == "data" and parts[i + 1] == ambig:
                return False
    # 2) 普通排除目录：路径段匹配
    for excl in EXCLUDE_DIRS:
        if excl in parts:
            return False

    # 排除文件检查（统一用 fnmatch 通配符，支持 * 在任意位置）
    name = p.name
    for excl in EXCLUDE_FILES:
        if fnmatch.fnmatch(name, excl):
            return False

    return True


# ============================================================
# 文件快照与变更检测
# ============================================================

def _take_snapshot(root: str) -> Dict[str, float]:
    """
    扫描目录，返回 {相对路径: mtime} 的快照。
    只包含代码文件。
    """
    snapshot = {}
    root_path = Path(root)

    for dirpath, dirnames, filenames in os.walk(root):
        # 排除目录
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

        for fname in filenames:
            relpath = os.path.relpath(os.path.join(dirpath, fname), root)
            if not is_code_file(relpath):
                continue
            try:
                mtime = os.path.getmtime(os.path.join(dirpath, fname))
                snapshot[relpath] = mtime
            except OSError:
                pass

    return snapshot


def scan_changed_files(
    root: str,
    prev_snapshot: Optional[Dict[str, float]] = None,
) -> Dict[str, str]:
    """
    扫描变更文件。
    
    Args:
        root: 监听根目录
        prev_snapshot: 上一次的快照。如果为None，返回当前快照（无变更）
    
    Returns:
        如果prev_snapshot为None: 返回当前快照 {path: mtime}
        如果prev_snapshot不为None: 返回变更 {path: "added"|"modified"|"deleted"}
    """
    current = _take_snapshot(root)

    if prev_snapshot is None:
        return current

    changes = {}
    for path, mtime in current.items():
        if path not in prev_snapshot:
            changes[path] = "added"
        elif mtime != prev_snapshot[path]:
            changes[path] = "modified"

    for path in prev_snapshot:
        if path not in current:
            changes[path] = "deleted"

    return changes


# ============================================================
# 变更经验生成
# ============================================================

# 代码文件扩展名（用于语义提取，区别于数据/配置文件）
_CODE_FILE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
                         ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt"}

# 从git diff提取函数/类定义的正则
# 匹配新增行中的 def/function/class/async def 等
_DIFF_FUNC_PATTERN = re.compile(
    r'^\+\s*(?:async\s+def\s+(\w+)|def\s+(\w+)|function\s+(\w+)|class\s+(\w+))',
    re.MULTILINE,
)


def _extract_semantic_from_diff(filepath: str) -> List[str]:
    """
    从git diff提取变更涉及的函数/类名。

    策略：
    1. tracked文件：用 git diff（unstaged + staged）提取新增的函数/类定义
    2. untracked文件：用 git diff --no-index /dev/null 模拟新增，提取全部顶层定义

    Returns:
        函数/类名列表（最多5个）
    """
    try:
        # _SCRIPT_DIR = 4-MEMORY/9-工具与接口/
        # 项目根目录 = _SCRIPT_DIR.parent.parent = dreambuddy-v2/
        repo_root = str(_SCRIPT_DIR.parent.parent)
        abs_path = str(Path(repo_root) / filepath)

        # 检查文件是否被git tracked
        tracked_check = subprocess.run(
            ["git", "ls-files", "--error-unmatch", filepath],
            capture_output=True, text=True, timeout=2,
            cwd=repo_root,
        )
        is_tracked = tracked_check.returncode == 0

        diff_text = ""
        if is_tracked:
            # tracked文件：获取unstaged diff
            result = subprocess.run(
                ["git", "diff", "--", filepath],
                capture_output=True, text=True, timeout=3,
                cwd=repo_root,
            )
            diff_text = result.stdout

            # 如果unstaged无diff，尝试staged diff
            if not diff_text.strip():
                result = subprocess.run(
                    ["git", "diff", "--cached", "--", filepath],
                    capture_output=True, text=True, timeout=3,
                    cwd=repo_root,
                )
                diff_text = result.stdout
        else:
            # untracked文件：用 --no-index 模拟新增diff
            result = subprocess.run(
                ["git", "diff", "--no-index", "/dev/null", abs_path],
                capture_output=True, text=True, timeout=3,
                cwd=repo_root,
            )
            # --no-index 在有差异时返回1，不是错误
            diff_text = result.stdout

        if not diff_text.strip():
            return []

        # 提取新增的函数/类定义
        symbols: List[str] = []
        for m in _DIFF_FUNC_PATTERN.finditer(diff_text):
            for g in m.groups():
                if g:
                    symbols.append(g)
                    break
            if len(symbols) >= 5:
                break

        return symbols
    except Exception:
        return []


def generate_change_experience(changes: Dict[str, str]) -> Optional[str]:
    """
    从变更文件列表生成语义化经验描述。

    改进：不再只记录文件名，而是：
    1. 区分代码文件 vs 数据/配置文件
    2. 对代码文件，用git diff提取变更涉及的函数/类名
    3. 生成结构化描述：[开发活动] 模块 | 符号变更 | 文件列表

    Returns:
        经验描述字符串，空变更返回None
    """
    if not changes:
        return None

    # 分类统计
    added = [f for f, t in changes.items() if t == "added"]
    modified = [f for f, t in changes.items() if t == "modified"]
    deleted = [f for f, t in changes.items() if t == "deleted"]

    # 提取顶层模块名
    top_dirs: List[str] = []
    for f in list(changes.keys())[:5]:
        parts = Path(f).parts
        if parts:
            top = parts[0]
            if top not in top_dirs:
                top_dirs.append(top)
    module_str = ", ".join(top_dirs[:3])

    # 对代码文件提取函数/类名
    code_files = [f for f in list(changes.keys())
                  if Path(f).suffix.lower() in _CODE_FILE_EXTENSIONS]
    symbols_all: List[str] = []
    for f in code_files[:4]:  # 最多检查4个文件，控制耗时
        syms = _extract_semantic_from_diff(f)
        symbols_all.extend(syms)
        if len(symbols_all) >= 8:
            break

    # 去重，最多展示6个
    seen = set()
    symbols_unique = []
    for s in symbols_all:
        if s not in seen:
            seen.add(s)
            symbols_unique.append(s)
            if len(symbols_unique) >= 6:
                break

    # 组装描述
    parts = []
    if added:
        parts.append(f"新增({len(added)}): {', '.join(Path(f).name for f in added[:3])}")
    if modified:
        parts.append(f"修改({len(modified)}): {', '.join(Path(f).name for f in modified[:3])}")
    if deleted:
        parts.append(f"删除({len(deleted)}): {', '.join(Path(f).name for f in deleted[:3])}")

    total = len(changes)
    desc = f"[开发活动] 模块: {module_str} | {' | '.join(parts)}"

    if symbols_unique:
        desc += f" | 符号: {', '.join(symbols_unique)}"

    if total > 5:
        desc += f" | 共{total}个文件"

    return desc


# ============================================================
# 触发认知闭环
# ============================================================

# 交易数据目录关键字 → 数据类型标签映射
_TRADING_DATA_SUBDIR_TAGS = {
    "data": "trading-data",
    "artifacts": "model-artifacts",
    "memory": "app-memory",
    "signal_pool": "signal-database",
    "config": "trading-config",
    "rules": "risk-rules",
    "models": "ml-models",
    "results": "backtest-results",
    "bcrm2": "memory-inference",
    "okx_sim": "simulated-trading",
}

# 交易数据文件名关键字 → 数据类型标签映射
_TRADING_DATA_FILE_TAGS = {
    "kline": "kline-data",
    "candle": "kline-data",
    "ohlcv": "kline-data",
    "state": "strategy-state",
    "config": "config",
    "signal": "trading-signal",
    "position": "position-data",
    "trade": "trade-log",
    "order": "order-log",
    "backtest": "backtest-result",
    "param": "parameter-tuning",
    "model": "ml-model",
    "memory": "memory-update",
    "hyperopt": "hyperopt",
}


def _extract_rich_tags(changes: Dict[str, str]) -> List[str]:
    """
    从变更文件列表提取丰富标签。
    区分：交易系统 / 交易数据(K线/状态/信号) / 记忆系统 / 开发 / 配置等
    """
    tags: List[str] = ["file-change", "daemon"]
    top_dirs: Set[str] = set()
    has_trading_data = False

    for f in list(changes.keys()):
        parts = Path(f).parts
        if not parts:
            continue
        top = parts[0]
        top_dirs.add(top)

        # 交易系统下的子目录细分（K线/状态/信号池等）
        if top in _TRADING_DIRS_FROM_SESSION or top.startswith(("10-", "11-", "12-", "13-", "14-", "15-", "16-", "6-")):
            # 检查二级目录
            if len(parts) >= 2:
                sub = parts[1]
                sub_tag = _TRADING_DATA_SUBDIR_TAGS.get(sub)
                if sub_tag:
                    has_trading_data = True
                    if sub_tag not in tags:
                        tags.append(sub_tag)
            # 检查文件名关键字
            fname = Path(f).name.lower()
            for kw, ftag in _TRADING_DATA_FILE_TAGS.items():
                if kw in fname and ftag not in tags:
                    has_trading_data = True
                    tags.append(ftag)
                    break

    # 顶层目录标签（取前3个避免过多）
    for d in sorted(top_dirs)[:3]:
        if d not in tags:
            tags.append(d)

    # 交易数据总标签
    if has_trading_data and "trading-data" not in tags:
        tags.append("trading-data")

    return tags


def salience_score(changes: Dict[str, str]) -> float:
    """P1-2: 突显网络触发器——计算文件变更的显著性分数。

    对齐 Menon 2011 三大脑网络：SN 检测显著事件触发 DMN↔CEN 切换。
    高显著→即时触发 recall（SN→CEN）；低显著→累积批量触发（DMN 留存）。

    权重表:
      风控文件（13-通用风控模块/a7_gate/熔断）= 1.0
      交易核心（polling_trader/bcrm/exit_system）= 0.8
      记忆系统（4-MEMORY/）= 0.6
      文档（0-系统文档管理 .md）= 0.3
      配置（.json/.yaml）= 0.2
      其余 = 0.4

    Returns:
        [0.0, 1.0] 的显著性分数
    """
    if not changes:
        return 0.0

    max_score = 0.0
    for filepath in changes.keys():
        f = filepath.lower()
        score = 0.0

        # 风控文件 = 1.0
        if "13-通用风控模块" in f or "a7_gate" in f or "熔断" in f or "circuit_breaker" in f:
            score = 1.0
        # 交易核心 = 0.8
        elif "polling_trader" in f or "bcrm" in f or "exit_system" in f or "walk_forward" in f:
            score = 0.8
        # 记忆系统 = 0.6
        elif "4-memory" in f or "cognitive" in f or "superpowers" in f:
            score = 0.6
        # 文档 = 0.3
        elif "0-系统文档管理" in f or (f.endswith(".md") and "2-knowledge" not in f):
            score = 0.3
        # 配置 = 0.2
        elif f.endswith(".json") or f.endswith(".yaml") or f.endswith(".yml"):
            score = 0.2
        # 其余 = 0.4
        else:
            score = 0.4

        if score > max_score:
            max_score = score

    return max_score


# 交易相关顶层目录（与cognitive_session._TRADING_DIRS保持一致，循环导入时本地定义）
_TRADING_DIRS_FROM_SESSION = frozenset([
    "10-经典指标系统", "11-易经推理系统", "12-三屏趋势系统",
    "13-通用风控模块", "14-V15经典马丁策略", "15-监控告警系统",
    "16-调控系统", "6-TRADING",
    "experiments",  # P0: experiments/ab-trading/ 含 A 系列节点代码和回测
])


def _has_code_file(changes: Dict[str, str]) -> bool:
    """检查变更中是否包含代码文件（通过 is_code_file 含排除规则校验）"""
    for f in changes:
        if is_code_file(f):
            return True
    return False


def trigger_change_record(
    changes: Dict[str, str],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    变更触发认知闭环record。

    降噪策略（v3，区分交易记录归属）：
    - 纯数据/配置/状态文件变更不record（交易事实由易经L4记录）
    - 只记录代码文件变更（开发决策语义：策略代码/风控规则/架构演进）
    - 同窗口混合变更时，过滤掉非代码文件，只记录代码文件语义
    - 降低confidence到0.1（未commit的变更，低置信度）

    边界（与易经L4区分）：
    - 交易事实（开仓/平仓/PnL/卦象）→ 易经L4 case/review/episode
    - 开发决策（为什么这样改代码/参数）→ 认知系统 record
    - 运行时状态快照（v15_state等）→ 都不记录（纯噪声）
    """
    # 降噪：无代码文件则不record
    if not _has_code_file(changes):
        return {"dry_run": dry_run, "recorded": False, "memory_id": None,
                "experience": "", "skipped": "no_code_file"}

    # 过滤：只保留通过 is_code_file 校验的代码文件，剔除同窗口的数据/状态文件
    code_changes = {f: t for f, t in changes.items() if is_code_file(f)}
    if not code_changes:
        return {"dry_run": dry_run, "recorded": False, "memory_id": None,
                "experience": "", "skipped": "no_code_file_after_filter"}

    experience = generate_change_experience(code_changes)
    if experience is None:
        return {"dry_run": dry_run, "recorded": False, "memory_id": None, "experience": ""}

    if dry_run:
        return {"dry_run": True, "recorded": False, "memory_id": None, "experience": experience}

    cle = get_cle()

    # 丰富标签：基于过滤后的代码文件变更（不再含数据文件）
    tags = _extract_rich_tags(code_changes)

    memory_id = cle.record(
        content=experience,
        quality_level="C",
        confidence=0.1,  # 更低置信度：未commit的变更，等git hook验证升级
        tags=tags,
        source="cognitive-daemon",
    )

    # verify（文件变更视为一次中性验证，不触发升级）
    # 不调用verify，因为文件变更本身不构成"验证成功"
    # 注意：不调用 cle.close()，get_cle() 返回进程级单例

    return {
        "dry_run": False,
        "recorded": True,
        "memory_id": memory_id,
        "experience": experience,
    }


# ============================================================
# 防抖计时器
# ============================================================

class DebounceTimer:
    """
    防抖计时器：窗口内的多次触发合并，窗口过期后标记可执行。
    
    用法:
      dt = DebounceTimer(window_seconds=5)
      if dt.trigger():  # 返回True表示窗口过期，可以执行
          do_something()
    """

    def __init__(self, window_seconds: float = 5.0):
        self.window = window_seconds
        self.last_trigger = 0.0
        self.has_pending = False

    def trigger(self) -> bool:
        """
        记录一次触发。返回True如果窗口已过期且有待处理的变更。
        窗口从首次触发开始计算，窗口内的后续触发不重置计时（固定窗口）。
        """
        now = time.time()
        if not self.has_pending:
            # 首次触发，开始窗口
            self.last_trigger = now
            self.has_pending = True
            return False

        if now - self.last_trigger >= self.window:
            # 窗口过期，标记可执行
            self.has_pending = False
            return True
        else:
            # 窗口内，不重置计时（固定窗口，避免持续变更永不触发）
            return False


# ============================================================
# Daemon主循环
# ============================================================

class CognitiveDaemon:
    """
    认知守护进程。监听文件变更，防抖合并，自动触发认知闭环。
    """

    def __init__(
        self,
        watch_dir: str,
        interval: float = 5.0,
        debounce: float = 10.0,
        verbose: bool = False,
    ):
        self.watch_dir = Path(watch_dir).resolve()
        self.interval = interval
        self.debounce_timer = DebounceTimer(debounce)
        self.verbose = verbose
        self.snapshot: Dict[str, float] = {}
        self.pending_changes: Dict[str, str] = {}
        self._running = False
        self._pid_file = _SCRIPT_DIR / ".cognitive_daemon.pid"
        # P2-7: 静息态反刍（DMN 默认模式网络）
        self._last_activity_ts = time.time()
        self._last_rumination_date = None
        self._rumination_idle_seconds = 1800  # 30 分钟

    def start(self):
        """启动daemon主循环"""
        self._running = True
        self._write_pid()

        # 初始快照
        self.snapshot = scan_changed_files(str(self.watch_dir))
        if self.verbose:
            print(f"[Daemon] 监听目录: {self.watch_dir}")
            print(f"[Daemon] 初始快照: {len(self.snapshot)}个文件")
            print(f"[Daemon] 轮询间隔: {self.interval}s, 防抖窗口: {self.debounce_timer.window}s")
            print(f"[Daemon] PID: {os.getpid()}")

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        while self._running:
            try:
                self._tick()
            except Exception as e:
                if self.verbose:
                    print(f"[Daemon] 错误: {e}", file=sys.stderr)
            time.sleep(self.interval)

    def _tick(self):
        """一次轮询周期"""
        # 检查session超时
        mgr = _get_session_mgr()
        if mgr:
            mgr.check_timeout()

        # 扫描变更
        changes = scan_changed_files(str(self.watch_dir), self.snapshot)

        if changes:
            # 有变更，合并到pending
            self.pending_changes.update(changes)
            # 更新快照
            new_snapshot = scan_changed_files(str(self.watch_dir))
            self.snapshot = new_snapshot

            if self.verbose:
                print(f"[Daemon] 检测到 {len(changes)} 个文件变更: "
                      f"{list(changes.keys())[:3]}")

            # 防抖触发
            if self.debounce_timer.trigger():
                self._flush_changes()

            # P2-7: 有变更更新活动时间
            self._last_activity_ts = time.time()

        else:
            # 无变更，检查防抖窗口是否过期
            if self.pending_changes and self.debounce_timer.trigger():
                self._flush_changes()

            # P2-7: 空闲反刍检测（DMN 默认模式网络）
            idle = time.time() - self._last_activity_ts
            today = datetime.now().strftime("%Y-%m-%d")
            if (idle >= self._rumination_idle_seconds
                    and self._last_rumination_date != today):
                self._ruminate()

    def _ruminate(self):
        """P2-7: 静息态反刍——从近期 episode 提取模式，记录为 C 级假设记忆"""
        try:
            from rumination_engine import RuminationEngine
            from cognitive_loop_entry import get_cle
            engine = RuminationEngine()
            # episodes_dir: 多路径搜索，避免跨包硬编码
            ep_dir = self._find_episodes_dir()
            findings = engine.ruminate(ep_dir)
            cle = get_cle()
            for f in findings:
                cle.record(
                    content=f.finding_text,
                    quality_level="C",
                    confidence=0.3,
                    tags=["rumination", "pattern", f.pattern_key.split("|")[0]],
                    source="rumination",
                )
            self._last_rumination_date = datetime.now().strftime("%Y-%m-%d")
            self._last_activity_ts = time.time()
            if self.verbose and findings:
                print(f"[Daemon] 反刍产出 {len(findings)} 条模式记忆", file=sys.stderr)
            elif self.verbose:
                print(f"[Daemon] 反刍完成，无新模式 (ep_dir={ep_dir})", file=sys.stderr)
        except Exception as e:
            if self.verbose:
                print(f"[Daemon] 反刍失败: {e}", file=sys.stderr)
            self._last_activity_ts = time.time()  # 失败也重置，避免连续重试

    def _find_episodes_dir(self) -> str:
        """多路径搜索 episodes 目录，避免跨包硬编码路径 bug"""
        # 候选路径（按优先级）
        candidates = [
            self.watch_dir / "11-易经推理系统" / ".workbuddy" / "episodes",
            self.watch_dir / ".workbuddy" / "episodes",
        ]
        # 尝试从 paths 模块获取（单一事实源）
        try:
            import sys
            _yijing_scripts = str(self.watch_dir / "11-易经推理系统" / "scripts")
            if _yijing_scripts not in sys.path:
                sys.path.insert(0, _yijing_scripts)
            from memory_l4.paths import episodes_dir as _ep_dir
            candidates.insert(0, _ep_dir())
        except Exception:
            pass

        for p in candidates:
            if p.exists() and p.is_dir():
                return str(p)

        # 兜底：返回第一个候选（即使不存在，让 ruminate_engine 处理空目录）
        return str(candidates[0])

    def on_new_session_created(self, session_id, initial_msg, working_memory=None):
        """设计节 3.1 路径 C：新会话创建时后台预热 process_block。与路径 B 去重。"""
        if working_memory is not None:
            if hasattr(working_memory, "process_block") and working_memory.process_block:
                return {"skipped": True, "reason": "process_block nonempty (path B already warmed)"}
        try:
            loader = _get_skill_loader()
            results = loader.retrieve(initial_msg or "general", top_meta=2, top_applied=2)
            markdown = results.get("process_block_markdown", "")
            injected_count = len(results.get("meta", [])) + len(results.get("applied", []))
            if markdown and working_memory is not None and hasattr(working_memory, "load_process_block"):
                working_memory.load_process_block(markdown)
            if getattr(self, "verbose", False):
                print(f"[Daemon] 路径 C 预热: session={session_id}, injected={injected_count}")
            return {"skipped": False, "injected_count": injected_count, "session_id": session_id}
        except Exception as e:
            if getattr(self, "verbose", False):
                import sys as _sys
                print(f"[Daemon] 路径 C 预热失败: {e}", file=_sys.stderr)
            return {"skipped": False, "injected_count": 0, "error": str(e)}

    def _flush_changes(self):
        """执行待处理的变更记录（P1-1 降噪：daemon 退化为会话追踪器）

        改动说明（2026-07-31）：
        - 保留：通知 session manager 记录行动链（会话追踪，有价值）
        - 移除：trigger_change_record 调用（未 commit 变更 record 到 L1 是噪声源）
        - record 职责交给 git hook（cognitive_hook.py），commit 时一次性记录有语义的经验
        - trigger_change_record 函数本身保留，供 --scan-once CLI 测试用
        """
        if not self.pending_changes:
            return

        changes = self.pending_changes.copy()
        self.pending_changes.clear()

        if self.verbose:
            print(f"[Daemon] 防抖窗口过期，通知 session manager: {len(changes)}个变更")

        # 通知session manager记录行动链（保留：会话追踪有价值）
        mgr = _get_session_mgr()
        if mgr:
            for filepath, change_type in changes.items():
                mgr.on_file_change(filepath, change_type)

        # P1-1 降噪：不再 record 未 commit 的变更到 L1
        # daemon 退化为会话追踪器，record 职责交给 git hook（commit 时一次性记录）
        # 原逻辑：result = trigger_change_record(changes, dry_run=False)
        # 噪声数据：confidence=0.1 的 C 级记忆占 L1 的 98.4%，淹没高价值记忆

    def _handle_signal(self, signum, frame):
        """处理停止信号"""
        if self.verbose:
            print(f"[Daemon] 收到信号 {signum}, 正在停止...")
        self._running = False
        # 刷新剩余变更
        if self.pending_changes:
            self._flush_changes()
        self._remove_pid()

    def _write_pid(self):
        self._pid_file.write_text(str(os.getpid()))

    def _remove_pid(self):
        """幂等删除 pid 文件（防御信号处理与主循环的 TOCTOU 竞态）。"""
        try:
            self._pid_file.unlink()
        except FileNotFoundError:
            pass  # 已被其他路径删除，幂等忽略

    def stop(self):
        """停止daemon"""
        if self._pid_file.exists():
            pid = int(self._pid_file.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"[Daemon] 已发送SIGTERM到PID {pid}")
            except ProcessLookupError:
                print(f"[Daemon] PID {pid} 不存在，清理pid文件")
                self._remove_pid()
        else:
            print("[Daemon] 未找到pid文件，daemon可能未运行")


# ============================================================
# 日志重定向（P2a 可观测性修复）
# ============================================================

def _default_log_path() -> str:
    """默认日志路径：<项目根>/logs/cognitive_daemon.log"""
    project_root = _SCRIPT_DIR.parent.parent
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir / "cognitive_daemon.log")


class _TeeStream:
    """同时写入文件和原始 stdout/stderr 的 Tee 流"""

    def __init__(self, file_handle, original_stream):
        self._file = file_handle
        self._orig = original_stream
        self._closed = False

    def write(self, data):
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass
        try:
            if self._orig and not getattr(self._orig, "closed", False):
                self._orig.write(data)
                self._orig.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self._file.flush()
        except Exception:
            pass
        try:
            if self._orig and not getattr(self._orig, "closed", False):
                self._orig.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._file.close()
            except Exception:
                pass


def _setup_log_redirect(log_path: Optional[str], verbose: bool):
    """设置 stdout/stderr 重定向到日志文件。
    返回 (prev_stdout, prev_stderr) 用于恢复。
    """
    import sys as _sys
    prev_stdout = _sys.stdout
    prev_stderr = _sys.stderr

    if not log_path:
        return prev_stdout, prev_stderr

    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        fh = open(log_path, "a", encoding="utf-8", buffering=1)
        if verbose:
            fh.write(f"\n=== Daemon 启动 PID={os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            fh.flush()
        _sys.stdout = _TeeStream(fh, prev_stdout)
        _sys.stderr = _TeeStream(fh, prev_stderr)
    except Exception as e:
        sys.stderr.write(f"[Daemon] 警告：日志重定向失败 {e}，回退无日志模式\n")
        return prev_stdout, prev_stderr

    return prev_stdout, prev_stderr


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="认知守护进程 — AI工具无关的文件监听")
    parser.add_argument("--watch", "-w", default=".", help="监听目录（默认当前目录）")
    parser.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒数（默认5）")
    parser.add_argument("--debounce", type=float, default=10.0, help="防抖窗口秒数（默认10）")
    parser.add_argument("--daemon", action="store_true", help="后台运行")
    parser.add_argument("--stop", action="store_true", help="停止daemon")
    parser.add_argument("--scan-once", action="store_true", help="仅扫描一次")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--log-file", default=None,
                        help=f"日志文件路径（默认前台不写，后台={_default_log_path()}）；指定后 stdout/stderr Tee 到文件")
    args = parser.parse_args()

    # 解析最终日志路径：显式指定优先；--daemon 无显式则用默认；前台无显式则不重定向
    resolved_log_path: Optional[str] = args.log_file
    if not resolved_log_path and args.daemon:
        resolved_log_path = _default_log_path()

    # 日志重定向（任何输出之前设置，保证启动信息落盘）
    _prev_stdout, _prev_stderr = _setup_log_redirect(resolved_log_path, args.verbose)

    if args.stop:
        daemon = CognitiveDaemon(args.watch)
        daemon.stop()
        return

    if args.scan_once:
        changes = scan_changed_files(args.watch)
        if isinstance(changes, dict) and changes:
            snap1 = changes
            print(f"[扫描] 初始快照: {len(snap1)}个文件")
            print("[扫描] 等待5秒后再次扫描...")
            time.sleep(5)
            changes = scan_changed_files(args.watch, snap1)
            if changes:
                print(f"[扫描] 检测到变更: {len(changes)}个")
                for f, t in changes.items():
                    print(f"  {t}: {f}")
                result = trigger_change_record(changes, dry_run=args.dry_run)
                print(f"[扫描] 结果: {json.dumps(result, ensure_ascii=False)}")
            else:
                print("[扫描] 无变更")
        else:
            print(f"[扫描] 当前快照: {len(changes)}个文件")
        return

    daemon = CognitiveDaemon(
        watch_dir=args.watch,
        interval=args.interval,
        debounce=args.debounce,
        verbose=args.verbose,
    )

    if args.daemon:
        import subprocess
        cmd = [
            sys.executable, str(_SCRIPT_DIR / "cognitive_daemon.py"),
            "--watch", args.watch,
            "--interval", str(args.interval),
            "--debounce", str(args.debounce),
        ]
        if args.verbose:
            cmd.append("--verbose")
        # 子进程继承 --log-file（显式传），避免二次进入 --daemon 分支
        subproc_log = resolved_log_path or _default_log_path()
        cmd.extend(["--log-file", subproc_log])
        # P2a 修复：子进程 stdout 不丢到 DEVNULL，内部 _setup_log_redirect 负责写文件
        proc = subprocess.Popen(
            cmd,
            stdout=None,
            stderr=None,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"[Daemon] 后台启动成功, PID: {proc.pid}")
        print(f"[Daemon] 日志: {subproc_log}")
        print(f"[Daemon] 停止: python3 cognitive_daemon.py --stop")
    else:
        print("[Daemon] 前台运行 (Ctrl+C停止)")
        daemon.start()


if __name__ == "__main__":
    main()
