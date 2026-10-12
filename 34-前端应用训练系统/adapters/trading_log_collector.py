"""子交易系统日志采集器。

从 7 个子交易系统采集日志/交易记录，按子系统名称分类为 intent_type，
为 S 层（意图识别）+ C 层（反思）提供金融交易域训练数据。

7 个子系统:
  1. BCRM2.0        — 技术分析维度（polling_trader 日志关键词 BCRM）
  2. BDSM           — 基本面维度（polling_trader 日志关键词 BDSM/出场巡检）
  3. 战略层         — 宏观基本面（polling_trader 日志关键词 战略层）
  4. 事件驱动       — 突发事件影响（polling_trader 日志关键词 event_boost/Score_B/事件驱动）
  5. 自进化系统     — 矛盾论+Transformer（all_trades_index.jsonl + shadow_rl_samples.jsonl）
  6. 三屏趋势       — 趋势跟踪（12-三屏趋势系统/logs/signal_scanner.log）
  7. V15马丁        — 马丁策略（14-V15/logs/v15_light_poll.log）

设计:
  - 统一采集器，内部按子系统关键词分类
  - polling_trader 日志: BCRM/BDSM/战略层/事件驱动通过 msg 关键词区分
  - 自进化: 从 all_trades_index.jsonl 读取结构化交易记录
  - 三屏/V15: 从纯文本日志按行提取信号
  - 增量采集: 按文件修改时间过滤
  - FAIL-OPEN: 目录不存在/解析失败返回空列表
"""
import json
import os
import re
from datetime import datetime
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# ============================================================
# 数据源路径
# ============================================================

# polling_trader 交易日志（BCRM/BDSM/战略层/事件驱动共用）
_POLLING_TRADER_DIR = os.path.join(
    _PROJECT_ROOT, "11-易经推理系统", "data", "polling_trader"
)

# 自进化系统交易索引
_TRADE_INDEX_PATH = os.path.join(
    _PROJECT_ROOT, "23-四层闭环自进化交易架构",
    ".workbuddy", "trade_index", "all_trades_index.jsonl"
)
# 自进化影子RL样本
_SHADOW_RL_PATH = os.path.join(
    _PROJECT_ROOT, "23-四层闭环自进化交易架构",
    "gene_data", "shadow_rl_samples.jsonl"
)

# 三屏趋势信号日志
_SIGNAL_SCANNER_LOG = os.path.join(
    _PROJECT_ROOT, "12-三屏趋势系统", "logs", "signal_scanner.log"
)
# 三屏趋势 signal_pool
_SIGNAL_POOL_DIR = os.path.join(
    _PROJECT_ROOT, "12-三屏趋势系统", "signal_pool"
)

# V15 马丁策略日志
_V15_LOG_DIR = os.path.join(
    _PROJECT_ROOT, "14-V15经典马丁策略", "logs"
)

# ============================================================
# 子系统关键词分类规则（优先级从高到低）
# ============================================================

_SUBSYSTEM_RULES = [
    # BDSM 最具体（出场巡检），优先匹配
    ("BDSM",          [r"BDSM", r"出场巡检", r"出场检查"]),
    # 战略层（宏观）
    ("strategy_layer", [r"战略层", r"war_state", r"total_score", r"cap_mode", r"mult_mode"]),
    # 事件驱动
    ("event_driven",   [r"event_boost", r"事件驱动", r"Score_E", r"event_score"]),
    # BCRM2.0（技术分析）— 最后匹配，因为 Score_B 不是事件驱动
    ("BCRM2",          [r"BCRM", r"bcrm", r"Score_B", r"ElasticGate", r"方案C", r"三层弹性"]),
]


def classify_subsystem(msg: str) -> Optional[str]:
    """从 polling_trader 日志 msg 字段分类子系统。

    Args:
        msg: 日志消息内容

    Returns:
        子系统标识符（BCRM2/BDSM/strategy_layer/event_driven），
        未匹配返回 None
    """
    if not msg:
        return None
    for label, patterns in _SUBSYSTEM_RULES:
        for p in patterns:
            if re.search(p, msg, re.IGNORECASE):
                return label
    return None


# ============================================================
# 采集器主体
# ============================================================

class TradingLogCollector(TrainingDataProvider):
    """子交易系统日志统一采集器。

    从 7 个子交易系统采集日志/交易记录，按子系统名称分类为 intent_type。
    """

    def __init__(self):
        pass

    def get_source_name(self) -> str:
        return "trading_log"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 7 个子交易系统批量获取训练案例。

        按子系统公平分配配额，避免大数据源（polling_trader 37万条）
        占满 limit 导致小数据源无法采集。

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳（ms 字符串），None/"0" 全量

        Returns:
            训练案例列表（FAIL-OPEN）
        """
        since_ms = 0
        if since:
            try:
                since_ms = int(since)
            except (ValueError, TypeError):
                since_ms = 0

        # 4 个数据源公平分配配额
        per_source = max(limit // 4, 10)

        cases: List[TrainingCase] = []

        # 1. polling_trader 日志（BCRM/BDSM/战略层/事件驱动）
        cases.extend(self._collect_polling_trader(since_ms, per_source))

        # 2. 自进化交易索引
        cases.extend(self._collect_self_evolution(since_ms)[:per_source])

        # 3. 三屏趋势日志
        cases.extend(self._collect_trend_3screen(since_ms)[:per_source])

        # 4. V15 马丁日志
        cases.extend(self._collect_v15_martin(since_ms)[:per_source])

        return cases[:limit]

    # --------------------------------------------------------
    # 1. polling_trader 日志采集（BCRM/BDSM/战略层/事件驱动）
    # --------------------------------------------------------

    def _collect_polling_trader(
        self, since_ms: int, limit: int = 0
    ) -> List[TrainingCase]:
        """从 polling_trader trader_*.jsonl 采集 BCRM/BDSM/战略层/事件驱动信号。

        Args:
            since_ms: 增量采集阈值（ms），0 全量
            limit: 最大返回数量（0 表示不限）
        """
        cases: List[TrainingCase] = []
        if not os.path.isdir(_POLLING_TRADER_DIR):
            return cases

        try:
            for fname in sorted(os.listdir(_POLLING_TRADER_DIR), reverse=True):
                if not (fname.startswith("trader_") and fname.endswith(".jsonl")):
                    continue
                fpath = os.path.join(_POLLING_TRADER_DIR, fname)
                cases.extend(self._parse_polling_trader_file(fpath, since_ms))
                if limit and len(cases) >= limit:
                    break
        except Exception:
            pass
        return cases[:limit] if limit else cases

    @staticmethod
    def _parse_polling_trader_file(fpath: str, since_ms: int) -> List[TrainingCase]:
        """解析单个 trader_*.jsonl 文件，提取子系统信号。"""
        cases: List[TrainingCase] = []
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = obj.get("msg", "")
                    ts_str = obj.get("ts", "")
                    level = obj.get("level", "INFO")

                    # 增量过滤: ts 字符串转 ms
                    if since_ms and ts_str:
                        try:
                            ts_ms = int(datetime.strptime(
                                ts_str, "%Y-%m-%d %H:%M:%S"
                            ).timestamp() * 1000)
                            if ts_ms <= since_ms:
                                continue
                        except (ValueError, TypeError):
                            pass

                    # 按关键词分类子系统
                    subsystem = classify_subsystem(msg)
                    if not subsystem:
                        continue

                    cases.append(TrainingCase(
                        intent=subsystem,
                        actions=[msg],
                        outcome_text=msg,
                        learned=[msg],
                        layer_tags=["S", "C"],
                        quality="B",
                        confidence=0.5,
                        source="trading_log",
                        metadata={
                            "ts": ts_str,
                            "level": level,
                            "subsystem": subsystem,
                            "log_file": os.path.basename(fpath),
                        },
                    ))
        except Exception:
            pass
        return cases

    # --------------------------------------------------------
    # 2. 自进化系统采集
    # --------------------------------------------------------

    def _collect_self_evolution(self, since_ms: int) -> List[TrainingCase]:
        """从 all_trades_index.jsonl 采集自进化系统交易记录。"""
        cases: List[TrainingCase] = []
        for fpath in [_TRADE_INDEX_PATH, _SHADOW_RL_PATH]:
            if not os.path.isfile(fpath):
                continue
            cases.extend(self._parse_self_evolution_file(fpath, since_ms))
        return cases

    @staticmethod
    def _parse_self_evolution_file(fpath: str, since_ms: int) -> List[TrainingCase]:
        """解析自进化系统 jsonl 文件。"""
        cases: List[TrainingCase] = []
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # all_trades_index 格式
                    coin = obj.get("coin", "")
                    direction = obj.get("direction", "")
                    pnl = obj.get("pnl", 0)
                    exit_reason = obj.get("exit_reason", "")
                    confidence = obj.get("confidence", 0)
                    source_system = obj.get("source_system", "")

                    # shadow_rl_samples 格式
                    symbol = obj.get("symbol", coin)
                    action = obj.get("action", direction)
                    reward = obj.get("reward", 0)

                    # 增量过滤: exit_time 或文件修改时间
                    exit_time = obj.get("exit_time", "")
                    if since_ms and exit_time:
                        try:
                            ts_ms = int(datetime.fromisoformat(
                                exit_time.replace("Z", "+00:00")
                            ).timestamp() * 1000)
                            if ts_ms <= since_ms:
                                continue
                        except (ValueError, TypeError):
                            pass

                    # 构建训练案例
                    msg = (f"[{symbol or coin}] direction={action or direction} "
                           f"pnl={pnl} reward={reward} exit_reason={exit_reason} "
                           f"confidence={confidence}")
                    cases.append(TrainingCase(
                        intent="self_evolution",
                        actions=[msg],
                        outcome_text=msg,
                        learned=[exit_reason] if exit_reason else [msg],
                        layer_tags=["S", "C"],
                        quality="B",
                        confidence=max(confidence, 0.4),
                        source="trading_log",
                        metadata={
                            "subsystem": "self_evolution",
                            "coin": symbol or coin,
                            "direction": action or direction,
                            "pnl": pnl,
                            "exit_reason": exit_reason,
                            "source_system": source_system,
                            "log_file": os.path.basename(fpath),
                        },
                    ))
        except Exception:
            pass
        return cases

    # --------------------------------------------------------
    # 3. 三屏趋势采集
    # --------------------------------------------------------

    def _collect_trend_3screen(self, since_ms: int) -> List[TrainingCase]:
        """从三屏趋势系统采集信号。"""
        cases: List[TrainingCase] = []

        # 3a. signal_scanner.log
        if os.path.isfile(_SIGNAL_SCANNER_LOG):
            cases.extend(self._parse_text_log(
                _SIGNAL_SCANNER_LOG, "trend_3screen", since_ms
            ))

        # 3b. signal_pool/pool.json（快照格式）
        pool_path = os.path.join(_SIGNAL_POOL_DIR, "pool.json")
        if os.path.isfile(pool_path):
            try:
                mtime_ms = int(os.path.getmtime(pool_path) * 1000)
                if since_ms and mtime_ms <= since_ms:
                    pass
                else:
                    with open(pool_path, encoding="utf-8") as f:
                        pool = json.load(f)
                    if isinstance(pool, list):
                        for item in pool[:50]:
                            coin = item.get("symbol", item.get("coin", ""))
                            signal = item.get("signal", item.get("direction", ""))
                            msg = f"[{coin}] signal={signal}"
                            cases.append(TrainingCase(
                                intent="trend_3screen",
                                actions=[msg],
                                outcome_text=msg,
                                learned=[msg],
                                layer_tags=["S", "C"],
                                quality="B",
                                confidence=0.4,
                                source="trading_log",
                                metadata={"subsystem": "trend_3screen",
                                          "coin": coin, "signal": signal},
                            ))
            except Exception:
                pass
        return cases

    # --------------------------------------------------------
    # 4. V15 马丁采集
    # --------------------------------------------------------

    def _collect_v15_martin(self, since_ms: int) -> List[TrainingCase]:
        """从 V15 马丁策略日志采集。"""
        cases: List[TrainingCase] = []
        log_path = os.path.join(_V15_LOG_DIR, "v15_light_poll.log")
        if os.path.isfile(log_path):
            cases.extend(self._parse_text_log(
                log_path, "v15_martin", since_ms
            ))
        return cases

    # --------------------------------------------------------
    # 通用纯文本日志解析器
    # --------------------------------------------------------

    @staticmethod
    def _parse_text_log(
        fpath: str, intent_type: str, since_ms: int
    ) -> List[TrainingCase]:
        """解析纯文本日志文件（如 signal_scanner.log / v15_light_poll.log）。

        格式: [YYYY-MM-DD HH:MM:SS] message
        或:    message（无时间戳行）
        """
        cases: List[TrainingCase] = []
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # 提取时间戳 [YYYY-MM-DD HH:MM:SS]
                    ts_match = re.match(
                        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", line
                    )
                    if ts_match:
                        ts_str = ts_match.group(1)
                        msg = ts_match.group(2)
                    else:
                        ts_str = ""
                        msg = line

                    # 增量过滤
                    if since_ms and ts_str:
                        try:
                            ts_ms = int(datetime.strptime(
                                ts_str, "%Y-%m-%d %H:%M:%S"
                            ).timestamp() * 1000)
                            if ts_ms <= since_ms:
                                continue
                        except (ValueError, TypeError):
                            pass

                    # 跳过非信号行（纯状态行、空行等）
                    if len(msg) < 5:
                        continue

                    cases.append(TrainingCase(
                        intent=intent_type,
                        actions=[msg],
                        outcome_text=msg,
                        learned=[msg],
                        layer_tags=["S", "C"],
                        quality="B",
                        confidence=0.4,
                        source="trading_log",
                        metadata={
                            "ts": ts_str,
                            "subsystem": intent_type,
                            "log_file": os.path.basename(fpath),
                        },
                    ))
        except Exception:
            pass
        return cases
