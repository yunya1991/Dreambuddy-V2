"""
UnifiedCaseRegistry — 全局交易事件注册中心

定位：监听系统全局交易链路并形成完整闭环沉淀为 TradeCase
支持系统：易经推理模型、三屏趋势模型、马丁策略、Agent A/B、Dream OS

核心功能：
1. 统一入口 register_trade_event() — 接收任何系统的交易事件
2. 标准化转换 build_trade_case() — 将 TradeEvent 转换为 TradeCase v0.3
3. 持久化存储 save_case() — 保存到 L4 案例库
4. 版本兼容 — 支持 v0.2 升级到 v0.3

TradeCase v0.3 标准格式（兼容 v0.2）：
- 保留 thinking_chain 字段（为未来 AI 推理模型预留）
- 新增 system_source、decision_context、risk_events 字段
- 统一 quadrant 为对象格式
- 新增 position_info（杠杆、保证金等）
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_cases_dir, workspace_root
from scripts.memory_l4.trade_event import TradeEvent
from scripts.memory_l4.schema_validator import validate_case, quick_validate


SYSTEM_SOURCES = [
    "yijing_inference",
    "three_screen",
    "martin_v15",
    "agent_a",
    "agent_b",
    "dream_os",
]

# P1-1: 测试数据关键字 — case_id / trade_id 含这些词时标记 is_test=True
_TEST_KEYWORDS = ("test", "qmm_test", "backup", "demo", "sample", "mock")

# P1-2: shared_memory_bus ACL 配置 — 扩展所有 6 个 system_source 的读写权限
_SHARED_BUS_ACL = {
    "yijing_inference": {"publish": True, "read": True},
    "three_screen": {"publish": True, "read": True},
    "martin_v15": {"publish": True, "read": True},
    "agent_a": {"publish": True, "read": True},
    "agent_b": {"publish": True, "read": True},
    "dream_os": {"publish": True, "read": True},
    "bcrm_engine": {"publish": True, "read": True},
}


def _detect_is_test(case_id: str, trade_id: str = "") -> bool:
    """P1-1: 检测案例是否为测试数据

    通过 case_id / trade_id 中是否包含测试关键字来判断。
    下游 ReviewEngine / DistillEngine / l4_stats_adapter 可按 is_test 字段过滤。
    """
    combined = f"{case_id} {trade_id}".lower()
    return any(kw in combined for kw in _TEST_KEYWORDS)


class UnifiedCaseRegistry:
    """全局交易事件注册中心"""

    def __init__(self):
        self.cases_dir = memory_l4_cases_dir()
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self._on_case_registered_hooks: List[Any] = []

    def register_hook(self, hook: Any) -> None:
        """注册案例注册后的回调钩子

        hook 签名: hook(case: Dict[str, Any]) -> None
        用于实现案例产生即处理的实时消费模式
        """
        self._on_case_registered_hooks.append(hook)

    def _notify_hooks(self, case: Dict[str, Any]) -> None:
        """通知所有已注册的钩子"""
        for hook in self._on_case_registered_hooks:
            try:
                hook(case)
            except Exception as e:
                print(f"[UnifiedCaseRegistry] Hook error: {e}")

    def register_trade_event(self, event: TradeEvent) -> Tuple[str, bool]:
        """
        统一入口：接收交易事件，生成、验证并保存 TradeCase

        流程:
        1. build_trade_case — 生成标准 v0.3 格式
        2. validate_case — schema 验证
        3. save_case — 持久化存储
        4. publish_to_shared_bus — P1-2: 双写到 shared_memory_bus 事件流
        5. notify_hooks — 触发实时消费钩子

        Returns:
            (case_id, success)
        """
        case = self.build_trade_case(event)

        # Schema 验证
        is_valid, errors = validate_case(case)
        if not is_valid:
            print(f"[UnifiedCaseRegistry] Schema 验证失败: {case['case_id']}")
            for err in errors[:5]:
                print(f"  - {err}")
            # 验证失败仍保存，但标记问题
            case["_validation_errors"] = errors

        success = self.save_case(case)

        # 触发实时消费钩子
        if success:
            # P1-2: 双写到 shared_memory_bus，实现事件驱动订阅（轻量改造，不改变直接注册流程）
            self._publish_to_shared_bus(event, case)
            self._notify_hooks(case)

        return case["case_id"], success

    def _publish_to_shared_bus(self, event: TradeEvent, case: Dict[str, Any]) -> None:
        """P1-2: 将交易事件发布到 shared_memory_bus 事件流

        轻量双写：在案例持久化成功后，同步发布到事件总线，
        供 ab_bridge / bcrm_engine 等订阅方消费。
        失败不影响案例库写入（总线是事件留痕，非强一致性）。
        """
        try:
            from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event
            publish_shared_memory_event(
                snapshot_ts=event.ts_exit or event.ts_entry or datetime.now(timezone.utc).isoformat(),
                agent_id=event.system_source,
                event_type="trade_case_registered",
                payload={
                    "case_id": case.get("case_id"),
                    "system_source": event.system_source,
                    "symbol": event.symbol,
                    "direction": event.direction,
                    "entry_price": event.entry_price,
                    "exit_price": event.exit_price,
                    "pnl_pct": event.pnl_pct,
                    "is_test": case.get("is_test", False),
                    "l4_status": case.get("l4_status"),
                },
                acl_config=_SHARED_BUS_ACL,
            )
        except Exception as e:
            # 总线写入失败不影响案例库主流程
            print(f"[UnifiedCaseRegistry] shared_memory_bus publish 失败(非致命): {e}")
    
    def build_trade_case(self, event: TradeEvent) -> Dict[str, Any]:
        """
        将 TradeEvent 转换为标准 TradeCase v0.3
        
        保留 thinking_chain 字段（为未来 AI 推理模型预留）
        新增 system_source、decision_context、risk_events
        """
        evt_dict = event.to_dict()
        
        x_val, y_val = self._compute_quadrant(event)
        quadrant_obj = self._build_quadrant_object(x_val, y_val, event)
        
        return {
            "case_id": f"tc_{event.system_source}_{event.trade_id}",
            "version": "v0.3",
            "system_source": event.system_source,
            "source": "live_trading",
            # P1-1: 测试数据标记，下游消费时按 is_test=False 过滤训练集
            "is_test": _detect_is_test(f"tc_{event.system_source}_{event.trade_id}", event.trade_id),

            "ts": event.ts_exit or event.ts_entry,
            "ts_start": event.ts_entry,
            "ts_end": event.ts_exit,
            
            "inst_id": event.symbol,
            "symbol": event.symbol,
            "direction": event.direction,
            
            "position_info": {
                "entry_price": event.entry_price,
                "exit_price": event.exit_price,
                "position_size": event.position_size,
                "leverage": event.leverage,
                "margin_usdt": event.margin_usdt,
            },
            
            "decision_outcome": {
                "is_correct": event.pnl >= 0 if event.pnl is not None else None,
                "pnl": event.pnl,
                "pnl_pct": event.pnl_pct,
                "drawdown": None,
                "exit_reason": event.exit_reason,
                "goal_achieved": None,
            },
            
            "actual_outcome": {
                "is_correct": event.pnl >= 0 if event.pnl is not None else None,
                "pnl_pct": event.pnl_pct,
                "exit_reason": event.exit_reason,
            },
            
            "decision_context": event.decision_context,
            
            "environment_snapshot": self._build_environment_snapshot(event),
            
            "thinking_chain": self._build_thinking_chain(event),
            
            "evidence_chain": {
                "market_data_refs": [],
                "signal_refs": [],
                "strategy_refs": [],
                "historical_refs": [],
                "constraint_refs": [],
            },
            
            "quadrant": quadrant_obj,
            
            "risk_events": event.risk_events,
            
            "tags": ["auto_case", event.system_source],
            
            "l4_status": "M0_CASE_REGISTERED",
            
            "execution": {
                "episode_refs": [],
                "result": "completed" if event.ts_exit else "open",
            },
            
            "review": {
                "summary": "",
                "theory_practice_consistency": "not_reviewed",
                "lessons": [],
                "mistakes": [],
                "successes": [],
                "review_record_id": None,
            },
        }
    
    def _compute_quadrant(self, event: TradeEvent) -> Tuple[float, float]:
        """计算象限坐标 (x, y)"""
        pnl = event.pnl_pct or 0
        
        x_val = 1.0 if pnl > 0 else (-1.0 if pnl < 0 else 0.0)
        
        conf = event.decision_context.get("confidence", 0.5)
        y_val = (conf - 0.5) * 2
        
        return round(x_val, 4), round(y_val, 4)
    
    def _build_quadrant_object(self, x_val: float, y_val: float, event: TradeEvent) -> Dict[str, Any]:
        """构建标准象限对象"""
        return {
            "x": x_val,
            "y": y_val,
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": y_val,
                "y_consistency": 0.0,
                "y_human": 0.0,
                "notes": f"System: {event.system_source}",
            },
        }
    
    def _build_environment_snapshot(self, event: TradeEvent) -> Dict[str, Any]:
        """构建环境快照"""
        snapshot = event.market_snapshot or {}
        return {
            "regime": snapshot.get("regime", "unknown"),
            "volatility": snapshot.get("volatility", 0.03),
            "trend_strength": snapshot.get("trend_strength", 0.5),
            "price_position": snapshot.get("price_position", 0.5),
            "is_ranging": snapshot.get("is_ranging", False),
        }
    
    def _build_thinking_chain(self, event: TradeEvent) -> List[Dict[str, Any]]:
        """
        构建 thinking_chain（为未来 AI 推理模型预留）
        
        当前版本：从 decision_context 提取关键决策信息
        未来版本：AI 推理模型的完整决策链
        """
        ctx = event.decision_context
        chain = []
        
        if event.system_source == "yijing_inference":
            chain.append({
                "stage": "A0",
                "ts": event.ts_entry,
                "decision": f"{event.direction.upper()} {event.symbol}",
                "rationale": f"Hexagram: {ctx.get('hexagram', 'N/A')}, Confidence: {ctx.get('confidence', 0)}",
                "evidence_refs": [],
                "decision_context": ctx,
            })
        
        elif event.system_source == "martin_v15":
            chain.append({
                "stage": "MARTIN",
                "ts": event.ts_entry,
                "decision": f"{event.direction.upper()} {event.symbol}",
                "rationale": f"Martin strategy entry, Addon: {ctx.get('addon_level', 0)}",
                "evidence_refs": [],
                "decision_context": ctx,
            })
        
        elif event.system_source == "three_screen":
            chain.append({
                "stage": "THREE_SCREEN",
                "ts": event.ts_entry,
                "decision": f"{event.direction.upper()} {event.symbol}",
                "rationale": f"Three-screen signal alignment",
                "evidence_refs": [],
                "decision_context": ctx,
            })
        
        elif event.system_source in ("agent_a", "agent_b"):
            chain.append({
                "stage": "AGENT_DECIDE",
                "ts": event.ts_entry,
                "decision": f"{event.direction.upper()} {event.symbol}",
                "rationale": f"{event.system_source.upper()} LLM decision",
                "evidence_refs": [],
                "decision_context": ctx,
            })
        
        else:
            chain.append({
                "stage": "SYSTEM",
                "ts": event.ts_entry,
                "decision": f"{event.direction.upper()} {event.symbol}",
                "rationale": f"System: {event.system_source}",
                "evidence_refs": [],
                "decision_context": ctx,
            })
        
        if event.ts_exit:
            chain.append({
                "stage": "EXIT",
                "ts": event.ts_exit,
                "decision": f"Close {event.direction.upper()} {event.symbol}",
                "rationale": f"Exit reason: {event.exit_reason}, PnL: {event.pnl_pct}%",
                "evidence_refs": [],
                "exit_price": event.exit_price,
            })

        # P2-9: 追加 PREDICTION stage（事前预测快照，若 decision_context 含 prediction）
        prediction = ctx.get("prediction")
        if prediction:
            chain.append({
                "stage": "PREDICTION",
                "ts": event.ts_entry,
                "decision": f"Predict {prediction.get('expected_direction', 'N/A')} "
                            f"target={prediction.get('target_return_pct', 0)}%",
                "rationale": f"horizon={prediction.get('expected_horizon_bars', 0)}bars, "
                             f"stop_prob={prediction.get('stop_loss_prob', 0)}, "
                             f"conf={prediction.get('prediction_confidence', 0)}",
                "evidence_refs": [],
                "prediction_snapshot": prediction,
            })

        return chain
    
    def save_case(self, case: Dict[str, Any], validate: bool = True) -> bool:
        """保存 TradeCase 到 L4 案例库

        Args:
            case: TradeCase 字典
            validate: 保存前是否进行 schema 验证（默认 True）
        """
        case_id = case.get("case_id") or f"tc_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        case["case_id"] = case_id

        if "ts" not in case:
            case["ts"] = datetime.now(timezone.utc).isoformat()

        # Schema 验证（外部传入的案例也需要验证）
        if validate:
            is_valid, errors = validate_case(case)
            if not is_valid:
                print(f"[UnifiedCaseRegistry] save_case 验证失败: {case_id}")
                for err in errors[:5]:
                    print(f"  - {err}")
                case["_validation_errors"] = errors

        filepath = self.cases_dir / f"{case_id}.json"
        try:
            with filepath.open("w", encoding="utf-8") as f:
                json.dump(case, f, ensure_ascii=False, indent=2, default=str)
            return True
        except Exception:
            return False
    
    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 TradeCase"""
        filepath = self.cases_dir / f"{case_id}.json"
        if not filepath.exists():
            return None
        try:
            with filepath.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def update_outcome(self, case_id: str,
                       pnl: Optional[float] = None,
                       pnl_pct: Optional[float] = None,
                       exit_price: Optional[float] = None,
                       exit_reason: Optional[str] = None,
                       ts_exit: Optional[str] = None) -> bool:
        """离场回填：更新已注册案例的实际结果，闭合开仓→离场两阶段闭环

        与 CaseWriter.update_outcome 对齐，支持 auto_trader 等子系统
        开仓时注册案例（ts_exit=None）、离场时回填结果的异步两阶段模式。

        Args:
            case_id: 案例 ID（开仓时由 register_trade_event 返回）
            pnl: 实际盈亏金额
            pnl_pct: 实际盈亏百分比
            exit_price: 离场价格
            exit_reason: 离场原因
            ts_exit: 离场时间 ISO 字符串

        Returns:
            是否更新成功
        """
        case = self.get_case(case_id)
        if case is None:
            print(f"[UnifiedCaseRegistry] update_outcome 案例不存在: {case_id}")
            return False

        is_correct = None
        if pnl is not None:
            is_correct = pnl >= 0
        elif pnl_pct is not None:
            is_correct = pnl_pct >= 0

        # 更新 decision_outcome
        outcome = case.get("decision_outcome", {})
        if pnl is not None:
            outcome["pnl"] = pnl
        if pnl_pct is not None:
            outcome["pnl_pct"] = pnl_pct
        if exit_reason is not None:
            outcome["exit_reason"] = exit_reason
        if is_correct is not None:
            outcome["is_correct"] = is_correct
        outcome["goal_achieved"] = is_correct
        case["decision_outcome"] = outcome

        # 更新 actual_outcome（与 decision_outcome 保持一致）
        actual = case.get("actual_outcome", {})
        if pnl_pct is not None:
            actual["pnl_pct"] = pnl_pct
        if exit_reason is not None:
            actual["exit_reason"] = exit_reason
        if is_correct is not None:
            actual["is_correct"] = is_correct
        case["actual_outcome"] = actual

        # 更新 position_info
        pos_info = case.get("position_info", {})
        if exit_price is not None:
            pos_info["exit_price"] = exit_price
        case["position_info"] = pos_info

        # 更新时间
        if ts_exit:
            case["ts_end"] = ts_exit
            case["ts"] = ts_exit  # ts 取最新时间

        # 追加 thinking_chain EXIT 阶段
        chain = case.get("thinking_chain", [])
        symbol = case.get("symbol", case.get("inst_id", "UNKNOWN"))
        direction = case.get("direction", "UNKNOWN")
        chain.append({
            "stage": "EXIT",
            "ts": ts_exit or datetime.now(timezone.utc).isoformat(),
            "decision": f"Close {direction.upper()} {symbol}",
            "rationale": f"Exit reason: {exit_reason}, PnL: {pnl_pct}%",
            "evidence_refs": [],
            "exit_price": exit_price,
        })

        # P2-9: 计算预测误差（若 case thinking_chain 含 PREDICTION stage）
        prediction_snapshot = None
        for stage in chain:
            if stage.get("stage") == "PREDICTION":
                prediction_snapshot = stage.get("prediction_snapshot")
                break
        if prediction_snapshot:
            try:
                from scripts.memory_l4.prediction_bridge import compute_prediction_error_dict
                actual = {
                    "direction": direction,
                    "return_pct": pnl_pct if pnl_pct is not None else 0.0,
                    "stop_triggered": (exit_reason == "stop_loss") if exit_reason else False,
                }
                prediction_error = compute_prediction_error_dict(prediction_snapshot, actual)
                if prediction_error:
                    case["prediction_error"] = prediction_error
            except Exception:
                pass

        case["thinking_chain"] = chain

        # 更新执行状态
        execution = case.get("execution", {})
        execution["result"] = "completed"
        case["execution"] = execution

        # 更新 L4 状态
        case["l4_status"] = "M1_OUTCOME_UPDATED"

        # 持久化
        filepath = self.cases_dir / f"{case_id}.json"
        try:
            with filepath.open("w", encoding="utf-8") as f:
                json.dump(case, f, ensure_ascii=False, indent=2, default=str)
            return True
        except Exception as e:
            print(f"[UnifiedCaseRegistry] update_outcome 保存失败: {case_id} | {e}")
            return False

    def list_cases(self, system_source: Optional[str] = None) -> List[str]:
        """列出 TradeCase ID"""
        ids = []
        for f in self.cases_dir.glob("*.json"):
            case_id = f.stem
            if system_source:
                if case_id.startswith(f"tc_{system_source}_"):
                    ids.append(case_id)
            else:
                ids.append(case_id)
        return sorted(ids, reverse=True)


def _require_nonempty(value: str, field: str) -> str:
    if not value:
        raise ValueError(f"missing required field: {field}")
    return value


def create_case_from_episode_data(episode: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    """从 episode 数据创建 TradeCase（兼容旧接口）

    兼容两种 episode 格式：
    - A0-A9 格式：inst_id/trace_id/pnl_pct 在顶层
    - live_* 格式（_trigger_l4_pipeline_for_trade 生成）：字段在 trades[0] 内
    """
    ts = _require_nonempty(str(episode.get("ts") or ""), "ts")

    # live_* 格式：字段在 trades[0] 内
    trades = episode.get("trades") or []
    first_trade = trades[0] if trades else {}

    inst_id = str(
        episode.get("inst_id")
        or first_trade.get("inst_id")
        or first_trade.get("symbol")
        or ""
    )
    if not inst_id:
        raise ValueError("missing required field: inst_id")

    trace_id = str(
        episode.get("trace_id")
        or first_trade.get("trade_id")
        or case_id
    )

    pnl = episode.get("pnl_pct")
    if pnl is None:
        pnl = first_trade.get("pnl_pct")
    pnl_usdt = episode.get("pnl_usdt")
    if pnl_usdt is None:
        pnl_usdt = first_trade.get("pnl")
    dd = episode.get("drawdown")

    exit_reason = first_trade.get("exit_reason")
    raw_system_source = first_trade.get("system_source", "yijing_inference")
    # 归一化易经推理子系统别名 → yijing_inference
    _YIJING_ALIASES = frozenset({
        "bcrm", "yijing_live", "yijing_engine", "yijing_inference",
        "liangyi", "scale", "bagua", "yijing", "yijing_force",
    })
    _src_norm = str(raw_system_source).strip().lower() or "yijing_inference"
    if _src_norm in _YIJING_ALIASES or _src_norm.startswith("yijing") or _src_norm.startswith("bcrm"):
        system_source = "yijing_inference"
    else:
        system_source = _src_norm
    
    return {
        "case_id": case_id,
        "version": "v0.2",
        "system_source": system_source,
        "ts_start": ts,
        "ts_end": None,
        "inst_id": inst_id,
        "tags": ["auto_case", "episode_ref"],
        "intent": {"question": "", "goal": "", "constraints": []},
        "investigation": {"summary": "", "sources": []},
        "theory_refs": [],
        "environment_snapshot": {"regime": episode.get("regime", "")},
        "thinking_chain": [],
        "evidence_chain": {
            "market_data_refs": [],
            "signal_refs": [],
            "strategy_refs": [],
            "historical_refs": [],
            "constraint_refs": [],
        },
        "decision_outcome": {
            "pnl_pct": float(pnl) if pnl is not None else None,
            "pnl_usdt": float(pnl_usdt) if pnl_usdt is not None else None,
            "drawdown": float(dd) if dd is not None else None,
            "exit_reason": exit_reason,
            "goal_achieved": True if (pnl is not None and pnl > 0) else (False if pnl is not None else None),
        },
        "l4_status": "M0_CASE_REGISTERED",
        "plan": {
            "minimal_change": "",
            "max_future_space": "",
            "steps": ["补全意图/调查/复盘/象限坐标"],
        },
        "execution": {
            "episode_refs": [{"trace_id": trace_id, "path": ""}],
            "result": str(episode.get("status") or episode.get("decision") or ""),
        },
        "online_pressure_test": None,
        "rollout_monitoring": None,
        "backtest": None,
        "review": {
            "summary": "",
            "theory_practice_consistency": "partially_consistent",
            "lessons": [],
            "mistakes": [],
            "successes": [],
            "review_record_id": None,
        },
        "dream_reflection": None,
        "quadrant": {
            "x": 0.0,
            "y": 0.0,
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": 0.0,
                "y_consistency": 0.0,
                "y_human": 0.0,
                "notes": "",
            },
        },
    }


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def derive_case_id_from_episode_path(episode_path: Path) -> str:
    return f"TC_{episode_path.stem}"


def _to_repo_relative_path(path: Path) -> str:
    root = workspace_root()
    try:
        return str(path.resolve().relative_to(root.resolve()).as_posix())
    except Exception:
        return str(path.as_posix())


def create_case_from_episode_file(episode_path: Path, out_path: Optional[Path] = None) -> Path:
    episode = load_json(episode_path)
    case_id = derive_case_id_from_episode_path(episode_path)
    if out_path is None:
        out_path = memory_l4_cases_dir() / f"{case_id}.json"
    
    data = create_case_from_episode_data(episode, case_id=case_id)
    data["execution"]["episode_refs"][0]["path"] = _to_repo_relative_path(episode_path)
    
    save_json(out_path, data)
    return out_path


def upgrade_case_to_v03(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """将 v0.2 case 升级为 v0.3 格式"""
    if case_data.get("version") == "v0.3":
        return case_data
    
    case_data["version"] = "v0.3"
    
    if "system_source" not in case_data:
        case_data["system_source"] = "unknown"
    
    if "decision_context" not in case_data:
        case_data["decision_context"] = {}
    
    if "risk_events" not in case_data:
        case_data["risk_events"] = []
    
    if "position_info" not in case_data:
        case_data["position_info"] = {
            "entry_price": None,
            "exit_price": None,
            "position_size": 0.0,
            "leverage": 1.0,
            "margin_usdt": 0.0,
        }
    
    quadrant = case_data.get("quadrant")
    if isinstance(quadrant, str):
        q_map = {"q1": (1.0, 0.5), "q2": (-1.0, 0.5), "q3": (-1.0, -0.5), "q4": (1.0, -0.5)}
        x, y = q_map.get(quadrant, (0.0, 0.0))
        case_data["quadrant"] = {
            "x": x,
            "y": y,
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": y,
                "y_consistency": 0.0,
                "y_human": 0.0,
                "notes": f"Upgraded from v0.2, quadrant: {quadrant}",
            },
        }
    
    if "thinking_chain" not in case_data:
        case_data["thinking_chain"] = []
    
    if "evidence_chain" not in case_data:
        case_data["evidence_chain"] = {
            "market_data_refs": [],
            "signal_refs": [],
            "strategy_refs": [],
            "historical_refs": [],
            "constraint_refs": [],
        }
    
    if "decision_outcome" not in case_data:
        case_data["decision_outcome"] = {
            "is_correct": None,
            "pnl": None,
            "pnl_pct": None,
            "drawdown": None,
            "exit_reason": None,
            "goal_achieved": None,
        }
    
    if "actual_outcome" not in case_data:
        case_data["actual_outcome"] = {
            "is_correct": None,
            "pnl_pct": None,
            "exit_reason": None,
        }
    
    review = case_data.get("review") or {}
    review.setdefault("mistakes", [])
    review.setdefault("successes", [])
    review.setdefault("review_record_id", None)
    case_data["review"] = review
    
    return case_data


def main() -> None:
    import argparse
    
    parser = argparse.ArgumentParser(description="UnifiedCaseRegistry - Global Trade Event Registry")
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("list", help="List all cases")
    
    parser_register = subparsers.add_parser("register", help="Register trade event")
    parser_register.add_argument("--source", required=True, choices=SYSTEM_SOURCES)
    parser_register.add_argument("--trade-id", required=True)
    parser_register.add_argument("--symbol", required=True)
    parser_register.add_argument("--direction", required=True, choices=["long", "short"])
    parser_register.add_argument("--entry-price", type=float, required=True)
    parser_register.add_argument("--exit-price", type=float)
    parser_register.add_argument("--pnl", type=float)
    parser_register.add_argument("--pnl-pct", type=float)
    parser_register.add_argument("--exit-reason")
    parser_register.add_argument("--entry-time")
    parser_register.add_argument("--exit-time")
    
    args = parser.parse_args()
    
    registry = UnifiedCaseRegistry()
    
    if args.command == "list":
        cases = registry.list_cases()
        for case_id in cases:
            print(case_id)
    
    elif args.command == "register":
        event = TradeEvent(
            event_id=TradeEvent.generate_event_id(),
            system_source=args.source,
            trade_id=args.trade_id,
            ts_entry=args.entry_time or datetime.now(timezone.utc).isoformat(),
            ts_exit=args.exit_time,
            symbol=args.symbol,
            direction=args.direction,
            entry_price=args.entry_price,
            exit_price=args.exit_price,
            pnl=args.pnl,
            pnl_pct=args.pnl_pct,
            exit_reason=args.exit_reason,
        )
        case_id, success = registry.register_trade_event(event)
        if success:
            print(f"Registered: {case_id}")
        else:
            print(f"Failed to register: {case_id}")
    
    elif args.command is None:
        parser.print_help()


if __name__ == "__main__":
    main()