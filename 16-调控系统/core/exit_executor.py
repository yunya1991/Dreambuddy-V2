"""离场执行器 — 16-调控系统 Phase 3+

将离场评估结果转化为实际交易执行动作。

执行流程：
  离场评估 → 权限检查 → 执行决策 → 记录结果 → 反馈进化系统

安全设计：
1. 模拟模式（dry_run）默认开启，需要显式开启实盘
2. 每笔执行都有权限检查
3. 执行日志完整记录，便于审计
4. 最大执行数量限制，防止极端情况下批量砸盘
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum

# L4 TradeEvent 注册（跨系统统一交易记录）
try:
    _L4_ROOT = Path(__file__).resolve().parents[2] / "11-易经推理系统"
    if str(_L4_ROOT) not in sys.path:
        sys.path.insert(0, str(_L4_ROOT))
    from scripts.memory_l4.trade_event import TradeEvent
    from scripts.memory_l4.case_registry import UnifiedCaseRegistry
    _L4_ENABLED = True
except Exception as _e:
    _L4_ENABLED = False


EXECUTION_LOG_DIR = Path(__file__).parent.parent / "artifacts" / "execution_logs"
EXECUTION_LOG_DIR.mkdir(parents=True, exist_ok=True)


class ExecutionMode(str, Enum):
    """执行模式"""
    DRY_RUN = "dry_run"          # 模拟执行，不下单
    SIMULATED = "simulated"      # 模拟盘
    REAL = "real"                # 实盘


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"


@dataclass
class ExitExecution:
    """一次离场执行记录"""
    execution_id: str
    timestamp: str
    strategy_id: str
    system_name: str
    symbol: str
    direction: str
    
    action: str           # CLOSE / REDUCE / HOLD / OBSERVE
    confidence: float
    urgency: str
    
    # 执行控制
    mode: str             # dry_run / simulated / real
    allowed: bool         # 权限检查结果
    rejection_reason: str = ""
    
    # 执行结果
    status: str = ExecutionStatus.PENDING.value
    order_id: str = ""
    executed_size: float = 0.0
    execution_price: float = 0.0
    actual_pnl: float = 0.0
    error_message: str = ""
    
    # 上下文
    position_size: float = 0.0
    entry_price: float = 0.0
    reduce_fraction: float = 0.0
    fusion_mode: str = ""


class ExitExecutor:
    """离场执行器
    
    负责将离场评估结果转化为实际交易动作。
    """
    
    def __init__(
        self,
        mode: str = "dry_run",
        max_executions_per_cycle: int = 5,
        min_position_usdt: float = 1.0,
    ):
        """
        Args:
            mode: 执行模式 dry_run / simulated / real
            max_executions_per_cycle: 每个周期最多执行多少笔（防止极端情况）
            min_position_usdt: 最小执行仓位（USDT 价值）
        """
        self.mode = mode
        self.max_executions_per_cycle = max_executions_per_cycle
        self.min_position_usdt = min_position_usdt
        self._okx_client = None
    
    def execute_evaluations(
        self,
        fused_evaluations: List[Dict],
    ) -> List[Dict]:
        """执行一批离场评估
        
        Args:
            fused_evaluations: 融合后的评估结果列表
        
        Returns:
            执行结果列表
        """
        results = []
        executed_count = 0
        
        for ev in fused_evaluations:
            pos = ev.get("position", {})
            action = ev.get("recommended_action", "HOLD")
            
            # 过滤掉不需要执行的动作
            if action in ("HOLD", "OBSERVE", "RAISE_TP"):
                results.append(self._make_skipped(ev, "无需执行的动作"))
                continue
            
            # 限制每周期执行数量
            if executed_count >= self.max_executions_per_cycle:
                results.append(self._make_skipped(ev, f"达到单周期执行上限 ({self.max_executions_per_cycle})"))
                continue
            
            # 执行
            result = self._execute_single(ev)
            results.append(result)
            
            if result["status"] == ExecutionStatus.SUCCESS.value:
                executed_count += 1
        
        # 记录执行日志
        self._save_execution_log(results)
        
        return results
    
    def _execute_single(self, evaluation: Dict) -> Dict:
        """执行单条离场建议"""
        pos = evaluation.get("position", {})
        perm_check = evaluation.get("permission_check", {})
        action = evaluation.get("recommended_action", "HOLD")
        params = evaluation.get("parameters", {})
        strategy_ctx = evaluation.get("strategy_context", {})
        
        execution_id = (
            f"exit_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_"
            f"{pos.get('system', '')}_{pos.get('symbol', '')}"
        )
        
        exec_record = ExitExecution(
            execution_id=execution_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            strategy_id=pos.get("strategy_id", ""),
            system_name=pos.get("system", ""),
            symbol=pos.get("symbol", ""),
            direction=pos.get("direction", ""),
            action=action,
            confidence=evaluation.get("confidence", 0),
            urgency=evaluation.get("urgency", "LOW"),
            mode=self.mode,
            allowed=perm_check.get("can_execute", False),
            position_size=float(pos.get("size", 0)),
            entry_price=float(pos.get("entry_price", 0)),
            reduce_fraction=float(params.get("reduce_fraction", 0.3)),
            fusion_mode=evaluation.get("fusion_mode", ""),
        )
        
        # 权限检查
        if not perm_check.get("can_execute", False):
            exec_record.status = ExecutionStatus.REJECTED.value
            exec_record.rejection_reason = perm_check.get("reason", "权限不足")
            return asdict(exec_record)
        
        # 最小仓位检查
        pos_value = self._calc_position_value(pos)
        if pos_value < self.min_position_usdt:
            exec_record.status = ExecutionStatus.SKIPPED.value
            exec_record.rejection_reason = f"仓位价值 ${pos_value:.2f} 低于最小执行金额 ${self.min_position_usdt}"
            return asdict(exec_record)
        
        # 执行交易
        try:
            exec_record.status = ExecutionStatus.EXECUTING.value
            
            if self.mode == "dry_run":
                # 模拟执行
                exec_record = self._dry_run_execute(exec_record, pos)
            else:
                # 实盘/模拟盘执行
                exec_record = self._real_execute(exec_record, pos)
            
            # 注册到 L4（执行成功时）
            if _L4_ENABLED and exec_record.status == ExecutionStatus.SUCCESS.value:
                try:
                    trade_id = f"dream_os_{int(datetime.now(timezone.utc).timestamp())}_{exec_record.symbol}"
                    event = TradeEvent(
                        event_id=TradeEvent.generate_event_id(),
                        system_source="dream_os",
                        trade_id=trade_id,
                        ts_entry=datetime.now(timezone.utc).isoformat(),
                        ts_exit=datetime.now(timezone.utc).isoformat(),
                        symbol=f"{exec_record.symbol}-USDT-SWAP",
                        direction=exec_record.direction.lower(),
                        entry_price=exec_record.entry_price,
                        exit_price=exec_record.execution_price,
                        position_size=exec_record.executed_size,
                        pnl=exec_record.actual_pnl,
                        pnl_pct=(exec_record.actual_pnl / (exec_record.entry_price * exec_record.executed_size) * 100) if exec_record.entry_price > 0 and exec_record.executed_size > 0 else 0,
                        exit_reason=f"dream_os_{exec_record.action.lower()}_{exec_record.urgency}",
                        decision_context={
                            "strategy_id": exec_record.strategy_id,
                            "system_name": exec_record.system_name,
                            "fusion_mode": exec_record.fusion_mode,
                            "urgency": exec_record.urgency,
                            "mode": self.mode,
                        },
                    )
                    registry = UnifiedCaseRegistry()
                    case_id, success = registry.register_trade_event(event)
                    if success:
                        print(f"[Dream OS] L4 案例已注册: {case_id}")
                except Exception as e:
                    print(f"[Dream OS] L4 注册异常: {e}")
            
        except Exception as e:
            exec_record.status = ExecutionStatus.FAILED.value
            exec_record.error_message = str(e)
        
        return asdict(exec_record)
    
    def _dry_run_execute(self, record: ExitExecution, pos: Dict) -> ExitExecution:
        """模拟执行（dry run）"""
        record.status = ExecutionStatus.SUCCESS.value
        record.order_id = f"dry_{record.execution_id}"
        
        # 模拟成交价格（用当前市场价）
        record.execution_price = float(pos.get("entry_price", 0)) * (1 + 0.001)  # 假设滑点 0.1%
        
        # 模拟执行数量
        if record.action == "CLOSE":
            record.executed_size = record.position_size
        elif record.action == "REDUCE":
            record.executed_size = record.position_size * record.reduce_fraction
        
        # 模拟盈亏
        record.actual_pnl = float(pos.get("unrealized_pnl", 0))
        
        return record
    
    def _real_execute(self, record: ExitExecution, pos: Dict) -> ExitExecution:
        """真实执行（模拟盘或实盘）"""
        try:
            client = self._get_okx_client()
            if not client:
                record.status = ExecutionStatus.FAILED.value
                record.error_message = "OKX 客户端未初始化"
                return record
            
            symbol = record.symbol
            direction = record.direction.lower()
            inst_id = f"{symbol}-USDT-SWAP"
            
            if record.action == "CLOSE":
                # 平仓
                side = "sell" if direction == "long" else "buy"
                pos_side = direction
                sz = str(record.position_size)
                
                result = client.place_order(
                    inst_id=inst_id,
                    side=side,
                    pos_side=pos_side,
                    sz=sz,
                    ord_type="market",
                )
                
                if result.get("success"):
                    record.status = ExecutionStatus.SUCCESS.value
                    record.order_id = str(result.get("order_id", ""))
                    record.executed_size = record.position_size
                    record.execution_price = float(result.get("avg_price", 0))
                    record.actual_pnl = float(result.get("realized_pnl", 0))
                else:
                    record.status = ExecutionStatus.FAILED.value
                    record.error_message = result.get("error", "下单失败")
            
            elif record.action == "REDUCE":
                # 减仓
                side = "sell" if direction == "long" else "buy"
                pos_side = direction
                reduce_size = record.position_size * record.reduce_fraction
                sz = str(reduce_size)
                
                result = client.place_order(
                    inst_id=inst_id,
                    side=side,
                    pos_side=pos_side,
                    sz=sz,
                    ord_type="market",
                )
                
                if result.get("success"):
                    record.status = ExecutionStatus.SUCCESS.value
                    record.order_id = str(result.get("order_id", ""))
                    record.executed_size = reduce_size
                    record.execution_price = float(result.get("avg_price", 0))
                    record.actual_pnl = float(result.get("realized_pnl", 0))
                else:
                    record.status = ExecutionStatus.FAILED.value
                    record.error_message = result.get("error", "下单失败")
            
        except Exception as e:
            record.status = ExecutionStatus.FAILED.value
            record.error_message = f"执行异常: {str(e)}"
        
        return record
    
    def _get_okx_client(self):
        """获取 OKX 客户端（懒加载）"""
        if self._okx_client is not None:
            return self._okx_client
        
        try:
            import sys
            from pathlib import Path
            v15_lib = Path(__file__).parent.parent.parent / "14-V15经典马丁策略" / "lib"
            sys.path.insert(0, str(v15_lib))
            from okx_client import OKXSimulatedClient
            
            config = {
                "api_key": os.environ.get("OKX_API_KEY", ""),
                "secret_key": os.environ.get("OKX_SECRET_KEY", ""),
                "passphrase": os.environ.get("OKX_PASSPHRASE", ""),
                "simulated": self.mode == "simulated",
                "dry_run": self.mode == "dry_run",
                "base_url": "https://www.okx.com",
                "default_inst_id": "BTC-USDT-SWAP",
                "default_usdt_amount": 100,
                "default_leverage": 5.0,
            }
            self._okx_client = OKXSimulatedClient(config=config)
            return self._okx_client
        except Exception as e:
            print(f"[离场执行器] OKX 客户端初始化失败: {e}")
            return None
    
    def _calc_position_value(self, pos: Dict) -> float:
        """计算仓位价值（USDT）"""
        size = float(pos.get("size", 0))
        # 简单估算：用 entry_price 近似，实际应该用市场价
        entry_price = float(pos.get("entry_price", 0))
        return size * entry_price
    
    def _make_skipped(self, evaluation: Dict, reason: str) -> Dict:
        """创建跳过记录"""
        pos = evaluation.get("position", {})
        return {
            "execution_id": f"skip_{int(datetime.now(timezone.utc).timestamp())}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_id": pos.get("strategy_id", ""),
            "system_name": pos.get("system", ""),
            "symbol": pos.get("symbol", ""),
            "direction": pos.get("direction", ""),
            "action": evaluation.get("recommended_action", "HOLD"),
            "confidence": evaluation.get("confidence", 0),
            "urgency": evaluation.get("urgency", "LOW"),
            "mode": self.mode,
            "allowed": True,
            "status": ExecutionStatus.SKIPPED.value,
            "rejection_reason": reason,
            "position_size": float(pos.get("size", 0)),
            "fusion_mode": evaluation.get("fusion_mode", ""),
        }
    
    def _save_execution_log(self, results: List[Dict]):
        """保存执行日志"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_file = EXECUTION_LOG_DIR / f"exit_execution_{timestamp}.json"
        
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "total_evaluations": len(results),
            "success_count": sum(1 for r in results if r["status"] == "success"),
            "failed_count": sum(1 for r in results if r["status"] == "failed"),
            "skipped_count": sum(1 for r in results if r["status"] == "skipped"),
            "rejected_count": sum(1 for r in results if r["status"] == "rejected"),
            "executions": results,
        }
        
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def create_executor_from_env() -> ExitExecutor:
    """从环境变量创建执行器"""
    mode = os.environ.get("EXIT_MODE", "dry_run").lower()
    max_exec = int(os.environ.get("MAX_EXECUTIONS", "5"))
    min_pos = float(os.environ.get("MIN_POSITION_USDT", "1.0"))
    
    valid_modes = [m.value for m in ExecutionMode]
    if mode not in valid_modes:
        print(f"[警告] 未知执行模式 {mode}，使用 dry_run")
        mode = "dry_run"
    
    return ExitExecutor(
        mode=mode,
        max_executions_per_cycle=max_exec,
        min_position_usdt=min_pos,
    )
