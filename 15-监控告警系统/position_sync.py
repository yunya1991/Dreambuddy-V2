#!/usr/bin/env python3
"""
系统级持仓同步服务

提供轻量级的持仓状态同步功能，用于5分钟监控轮询：
- 对比本地state与交易所真实持仓，检测外部平仓/开仓
- 更新每个持仓的实时盈亏信息（current_price, unrealized_pnl, profit_pct）
- 为各策略系统提供统一的持仓同步接口

设计原则：
- 只读不写：只同步状态，不执行任何交易操作
- 轻量级：不做信号计算，只查仓+对比+更新
- 适配器模式：通过 PositionSyncAdapter 接口支持各策略系统

使用方式：
    from position_sync import PositionSyncService, V15SyncAdapter, YijingSyncAdapter
    
    service = PositionSyncService()
    service.register_adapter("v15", V15SyncAdapter())
    service.sync_all()
    
    # 或单独同步某个系统
    service.sync("v15")
"""
import json
import os
import sys
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from abc import ABC, abstractmethod


BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups" / "position_sync"
LOG_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

CLOSE_CONFIRM_WINDOW_MINUTES = 10
CLOSE_CONFIRM_COUNT = 2
DEFAULT_DRY_RUN = True
MAX_BACKUPS = 20


class PositionSyncAdapter(ABC):
    """持仓同步适配器基类，各策略系统实现此接口"""

    @abstractmethod
    def get_system_name(self) -> str:
        """返回系统名称"""
        pass

    @abstractmethod
    def get_coins(self) -> List[str]:
        """返回系统监控的币种列表"""
        pass

    @abstractmethod
    def load_local_state(self) -> Dict:
        """加载本地持仓状态"""
        pass

    @abstractmethod
    def save_local_state(self, state: Dict):
        """保存更新后的本地状态"""
        pass

    @abstractmethod
    def get_state_positions(self, state: Dict) -> Dict[str, Dict]:
        """从state中提取持仓字典"""
        pass

    @abstractmethod
    def update_position_with_exchange(self, local_pos: Dict, exchange_pos: Dict) -> Dict:
        """用交易所数据更新本地持仓"""
        pass

    @abstractmethod
    def remove_position(self, state: Dict, coin: str) -> Dict:
        """从state中移除指定币种的持仓"""
        pass

    @abstractmethod
    def get_additional_info(self) -> Dict:
        """获取系统额外信息（用于日志）"""
        pass


class PositionSyncService:
    """系统级持仓同步服务

    安全机制:
    - dry_run: 只读模式，只检测不修改 state 文件
    - 外部平仓二次确认: 连续 2 次（默认 10 分钟窗口内）都确认已平仓才真正删除
    - API 故障保护: OKX API 失败时跳过所有删除操作
    - 自动备份: 修改前自动备份 state 文件，最多保留 20 份
    """

    def __init__(self, okx_client=None, dry_run: bool = None,
                 close_confirm_count: int = None, close_confirm_window_minutes: int = None,
                 max_backups: int = None, skip_close_on_api_error: bool = None):
        self.adapters: Dict[str, PositionSyncAdapter] = {}
        self.okx_client = okx_client
        self._init_okx_client()

        sync_cfg = _get_sync_config()
        if dry_run is None:
            dry_run = sync_cfg["dry_run"]
        if close_confirm_count is None:
            close_confirm_count = sync_cfg["close_confirm_count"]
        if close_confirm_window_minutes is None:
            close_confirm_window_minutes = sync_cfg["close_confirm_window_minutes"]
        if max_backups is None:
            max_backups = sync_cfg["max_backups"]
        if skip_close_on_api_error is None:
            skip_close_on_api_error = sync_cfg["skip_close_on_api_error"]

        self.dry_run = dry_run
        self.close_confirm_count = close_confirm_count
        self.close_confirm_window_minutes = close_confirm_window_minutes
        self.max_backups = max_backups
        self.skip_close_on_api_error = skip_close_on_api_error
        self._pending_closes: Dict[str, Dict[str, str]] = {}
        if dry_run:
            print(f"[PositionSync] 🛡️  只读模式（dry_run=True）— 仅检测，不修改 state 文件")

    def _init_okx_client(self):
        """初始化OKX客户端（延迟加载）"""
        if self.okx_client is not None:
            return

        try:
            v15_lib_path = Path(__file__).parent.parent / "14-V15经典马丁策略" / "lib"
            if str(v15_lib_path) not in sys.path:
                sys.path.insert(0, str(v15_lib_path))
            from okx_client import OKXSimulatedClient
            self.okx_client = OKXSimulatedClient()
        except Exception as e:
            print(f"[PositionSync] OKX客户端初始化失败: {e}")
            self.okx_client = None

    def register_adapter(self, name: str, adapter: PositionSyncAdapter):
        """注册持仓同步适配器"""
        self.adapters[name] = adapter
        self._pending_closes[name] = {}
        print(f"[PositionSync] 注册适配器: {name} -> {adapter.get_system_name()}")

    def register_default_adapters(self):
        """注册所有默认适配器"""
        adapters = {
            "v15": V15SyncAdapter(),
            "yijing": YijingSyncAdapter(),
            "screen": ScreenSyncAdapter(),
        }
        for name, adapter in adapters.items():
            self.register_adapter(name, adapter)

    def _backup_state_file(self, adapter: PositionSyncAdapter, adapter_name: str):
        """备份 state 文件（修改前调用）"""
        try:
            state_file = getattr(adapter, '_state_file', None)
            if not state_file:
                return
            if not state_file.exists():
                return
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_name = f"{adapter_name}_{state_file.stem}_{ts}.json"
            backup_path = BACKUP_DIR / backup_name
            shutil.copy2(str(state_file), str(backup_path))

            backups = sorted(BACKUP_DIR.glob(f"{adapter_name}_*.json"))
            if len(backups) > self.max_backups:
                for old in backups[:-self.max_backups]:
                    try:
                        old.unlink()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[PositionSync] ⚠️  备份失败 ({adapter_name}): {e}")

    def get_exchange_positions(self, coins: List[str]) -> Dict[str, Dict]:
        """查询交易所真实持仓

        返回: (positions_dict, api_healthy)
        api_healthy=False 表示 API 调用有异常，不应执行删除操作
        """
        if self.okx_client is None:
            return {}, False

        exchange_positions = {}
        has_error = False
        success_count = 0

        for coin in coins:
            try:
                inst_id = f"{coin}-USDT-SWAP"
                resp = self.okx_client.get_positions(inst_id)
                if resp.get("ok"):
                    success_count += 1
                    for p in resp.get("positions", []):
                        if float(p.get("pos", 0)) != 0:
                            exchange_positions[coin] = p
                else:
                    has_error = True
                    print(f"[PositionSync] ⚠️  {coin} 查询返回非ok: {resp.get('msg', 'unknown')}")
            except Exception as e:
                has_error = True
                print(f"[PositionSync] ⚠️  {coin} 查询异常: {e}")

        api_healthy = (not has_error) and success_count > 0
        return exchange_positions, api_healthy

    def _check_close_confirmation(self, adapter_name: str, coin: str) -> bool:
        """检查外部平仓是否达到确认次数

        机制:
        - 第 1 次检测到平仓: 记录时间，不删除
        - 第 N 次（在确认窗口内）检测到平仓: 确认，允许删除
        - 超过确认窗口: 重置计数
        """
        now = datetime.now(timezone.utc)
        pending = self._pending_closes.get(adapter_name, {})

        if coin in pending:
            first_ts = datetime.fromisoformat(pending[coin].split("|")[0] if "|" in pending[coin] else pending[coin])
            count_str = pending[coin].split("|")[1] if "|" in pending[coin] else "1"
            count = int(count_str)
            elapsed = (now - first_ts).total_seconds() / 60

            if elapsed <= self.close_confirm_window_minutes:
                count += 1
                if count >= self.close_confirm_count:
                    print(f"  ✅ 确认通过（{count}/{self.close_confirm_count}次，首次检测 {elapsed:.0f} 分钟前），允许删除")
                    del pending[coin]
                    return True
                else:
                    pending[coin] = f"{first_ts.isoformat()}|{count}"
                    print(f"  ⏳ 已检测 {count}/{self.close_confirm_count} 次（首次 {elapsed:.0f} 分钟前），继续等待")
                    return False
            else:
                print(f"  ⏳ 首次检测已超过 {self.close_confirm_window_minutes} 分钟，重置确认计数")
                pending[coin] = f"{now.isoformat()}|1"
                return False
        else:
            pending[coin] = f"{now.isoformat()}|1"
            print(f"  ⏳ 第 1/{self.close_confirm_count} 次检测到平仓，等待二次确认（{self.close_confirm_window_minutes} 分钟窗口内）")
            return False

    def sync(self, adapter_name: str) -> Dict:
        """同步指定系统的持仓"""
        if adapter_name not in self.adapters:
            return {"status": "error", "message": f"适配器 {adapter_name} 未注册"}

        adapter = self.adapters[adapter_name]
        system_name = adapter.get_system_name()

        print(f"\n[PositionSync] 开始同步: {system_name}")

        if self.okx_client is None:
            return {"status": "error", "message": "OKX客户端不可用", "system": system_name}

        state = adapter.load_local_state()
        if not state:
            return {"status": "error", "message": f"{system_name} 本地状态加载失败", "system": system_name}

        local_positions = adapter.get_state_positions(state)
        coins = adapter.get_coins()
        exchange_positions, api_healthy = self.get_exchange_positions(coins)

        local_keys = set(local_positions.keys())
        exchange_keys = set(exchange_positions.keys())

        externally_closed = local_keys - exchange_keys
        externally_opened = exchange_keys - local_keys
        synced_positions = []
        confirmed_closed = []
        pending_closed = []

        skipped_close_due_to_api = False

        for coin in sorted(externally_closed):
            pos = local_positions[coin]
            print(f"[{coin}] ⚠️  检测到外部平仓: entry={pos.get('entry_price', 0):.4f} sz={pos.get('sz', 0)}")

            if not api_healthy and self.skip_close_on_api_error:
                print(f"  🛡️  API 不健康，跳过删除（防止误删）")
                skipped_close_due_to_api = True
                continue

            if self._check_close_confirmation(adapter_name, coin):
                confirmed_closed.append(coin)
                if not self.dry_run:
                    state = adapter.remove_position(state, coin)
                else:
                    print(f"  🛡️  只读模式，不执行删除")
            else:
                pending_closed.append(coin)

        for coin in sorted(externally_opened):
            p = exchange_positions[coin]
            print(f"[{coin}] ℹ️  检测到外部开仓: avg_px={p.get('avg_px', 0):.4f} pos={p.get('pos', 0)} upl={p.get('upl', 0):.2f}")

        for coin in sorted(local_keys & exchange_keys):
            p = exchange_positions[coin]
            pos = local_positions[coin]
            if self.dry_run:
                print(f"[{coin}] ℹ️  同步盈亏（只读模式不改写文件）")
            else:
                updated_pos = adapter.update_position_with_exchange(pos, p)
                synced_positions.append(coin)

                pnl = updated_pos.get("unrealized_pnl", 0)
                pnl_pct = updated_pos.get("profit_pct", 0)
                print(f"[{coin}] ✅ 同步完成: mark=${updated_pos.get('current_price', 0):.4f} pnl=${pnl:.2f} ({pnl_pct:+.2%})")

        if not self.dry_run and (confirmed_closed or synced_positions):
            self._backup_state_file(adapter, adapter_name)
            state["last_sync"] = datetime.now(timezone.utc).isoformat()
            adapter.save_local_state(state)
        elif self.dry_run:
            state["last_sync_dry_run"] = datetime.now(timezone.utc).isoformat()
        else:
            state["last_sync"] = datetime.now(timezone.utc).isoformat()
            adapter.save_local_state(state)

        remaining = adapter.get_state_positions(state)
        result = {
            "status": "success",
            "system": system_name,
            "dry_run": self.dry_run,
            "total_positions": len(remaining),
            "externally_closed_total": len(externally_closed),
            "externally_closed_confirmed": len(confirmed_closed),
            "externally_closed_pending": len(pending_closed),
            "skipped_close_due_to_api": skipped_close_due_to_api,
            "externally_opened": len(externally_opened),
            "synced": len(synced_positions),
            "coins": list(remaining.keys()),
            "api_healthy": api_healthy,
        }

        summary = (
            f"持仓:{len(remaining)} "
            f"待确认平仓:{len(pending_closed)} "
            f"已确认平仓:{len(confirmed_closed)} "
            f"外部开仓:{len(externally_opened)} "
            f"已同步:{len(synced_positions)}"
        )
        if skipped_close_due_to_api:
            summary += " ⚠️ API异常"
        if self.dry_run:
            summary += " (只读)"
        print(f"[PositionSync] {system_name} 同步完成 | {summary}")
        return result

    def sync_all(self) -> List[Dict]:
        """同步所有已注册系统的持仓"""
        if not self.adapters:
            self.register_default_adapters()

        results = []
        for name in self.adapters:
            result = self.sync(name)
            results.append(result)

        total_positions = sum(r.get("total_positions", 0) for r in results if r.get("status") == "success")
        print(f"\n[PositionSync] 全部同步完成 | 总持仓:{total_positions}")
        return results


class V15SyncAdapter(PositionSyncAdapter):
    """V15经典马丁策略持仓同步适配器"""

    def __init__(self):
        self.base_dir = Path(__file__).parent.parent / "14-V15经典马丁策略"
        self._state_file = self.base_dir / "data" / "v15_state.json"

    def get_system_name(self) -> str:
        return "V15经典马丁策略"

    def get_coins(self) -> List[str]:
        env_file = self.base_dir / "config" / ".env.v15"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith("V15_COINS="):
                        return [c.strip() for c in line.split("=")[1].split(",") if c.strip()]
        return ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]

    def load_local_state(self) -> Dict:
        if self._state_file.exists():
            with open(self._state_file) as f:
                return json.load(f)
        return {}

    def save_local_state(self, state: Dict):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(state, f, indent=2)

    def get_state_positions(self, state: Dict) -> Dict[str, Dict]:
        return state.get("positions", {})

    def update_position_with_exchange(self, local_pos: Dict, exchange_pos: Dict) -> Dict:
        local_pos["current_price"] = exchange_pos.get("mark_px", 0)
        local_pos["unrealized_pnl"] = exchange_pos.get("upl", 0)
        local_pos["upl_ratio"] = exchange_pos.get("upl_ratio", 0)

        entry = local_pos.get("entry_price", 0)
        mark = exchange_pos.get("mark_px", 0)
        if entry > 0 and mark > 0:
            direction = local_pos.get("direction", "LONG")
            if direction == "SHORT":
                profit_pct = (entry - mark) / entry
            else:
                profit_pct = (mark - entry) / entry
            local_pos["profit_pct"] = profit_pct

        return local_pos

    def remove_position(self, state: Dict, coin: str) -> Dict:
        if "positions" in state and coin in state["positions"]:
            del state["positions"][coin]
        return state

    def get_additional_info(self) -> Dict:
        return {"system": "v15", "path": str(self.base_dir)}


class YijingSyncAdapter(PositionSyncAdapter):
    """易经推理系统持仓同步适配器"""

    def __init__(self):
        self.base_dir = Path(__file__).parent.parent / "11-易经推理系统"
        self._state_file = self.base_dir / "data" / "okx_sim" / "config.json"
        self._fallback_file = self.base_dir / ".workbuddy" / "memory_l4" / "risk" / "risk_state.json"

    def get_system_name(self) -> str:
        return "易经推理系统"

    def get_coins(self) -> List[str]:
        return ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]

    def load_local_state(self) -> Dict:
        if self._state_file.exists():
            with open(self._state_file) as f:
                return json.load(f)

        if self._fallback_file.exists():
            with open(self._fallback_file) as f:
                return json.load(f)

        return {}

    def save_local_state(self, state: Dict):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(state, f, indent=2)

    def get_state_positions(self, state: Dict) -> Dict[str, Dict]:
        positions = state.get("positions", {})
        if isinstance(positions, list):
            result = {}
            for p in positions:
                coin = p.get("symbol", "").replace("-USDT-SWAP", "").replace("-USDT", "")
                if coin:
                    result[coin] = p
            return result
        return positions

    def update_position_with_exchange(self, local_pos: Dict, exchange_pos: Dict) -> Dict:
        local_pos["current_price"] = exchange_pos.get("mark_px", 0)
        local_pos["unrealized_pnl"] = exchange_pos.get("upl", 0)
        local_pos["upl_ratio"] = exchange_pos.get("upl_ratio", 0)

        entry = local_pos.get("entry_price", local_pos.get("avg_px", 0))
        mark = exchange_pos.get("mark_px", 0)
        if entry > 0 and mark > 0:
            direction = local_pos.get("direction", "LONG")
            if direction == "SHORT":
                profit_pct = (entry - mark) / entry
            else:
                profit_pct = (mark - entry) / entry
            local_pos["profit_pct"] = profit_pct

        return local_pos

    def remove_position(self, state: Dict, coin: str) -> Dict:
        positions = state.get("positions", {})
        if isinstance(positions, dict):
            if coin in positions:
                del positions[coin]
        elif isinstance(positions, list):
            state["positions"] = [p for p in positions if p.get("symbol", "").find(coin) == -1]
        return state

    def get_additional_info(self) -> Dict:
        return {"system": "yijing", "path": str(self.base_dir)}


class ScreenSyncAdapter(PositionSyncAdapter):
    """三屏趋势系统持仓同步适配器"""

    def __init__(self):
        self.base_dir = Path(__file__).parent.parent / "12-三屏趋势系统"
        self._state_file = self.base_dir / "data" / "screen_trade_state.json"

    def get_system_name(self) -> str:
        return "三屏趋势系统"

    def get_coins(self) -> List[str]:
        return ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]

    def load_local_state(self) -> Dict:
        if self._state_file.exists():
            with open(self._state_file) as f:
                return json.load(f)
        return {}

    def save_local_state(self, state: Dict):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w") as f:
            json.dump(state, f, indent=2)

    def get_state_positions(self, state: Dict) -> Dict[str, Dict]:
        symbol = state.get("active_symbol", "")
        if not symbol:
            return {}

        coin = symbol.replace("-USDT-SWAP", "").replace("-USDT", "")
        if not coin:
            return {}

        return {
            coin: {
                "direction": state.get("direction", "LONG"),
                "entry_price": state.get("entry_price", 0),
                "sz": state.get("total_size", 0),
                "current_price": state.get("current_price", 0),
                "unrealized_pnl": state.get("unrealized_pnl", 0),
                "profit_pct": state.get("profit_pct", 0),
            }
        }

    def update_position_with_exchange(self, local_pos: Dict, exchange_pos: Dict) -> Dict:
        local_pos["current_price"] = exchange_pos.get("mark_px", 0)
        local_pos["unrealized_pnl"] = exchange_pos.get("upl", 0)
        local_pos["upl_ratio"] = exchange_pos.get("upl_ratio", 0)

        entry = local_pos.get("entry_price", 0)
        mark = exchange_pos.get("mark_px", 0)
        if entry > 0 and mark > 0:
            direction = local_pos.get("direction", "LONG")
            if direction == "SHORT":
                profit_pct = (entry - mark) / entry
            else:
                profit_pct = (mark - entry) / entry
            local_pos["profit_pct"] = profit_pct

        return local_pos

    def remove_position(self, state: Dict, coin: str) -> Dict:
        state["active"] = False
        state["active_symbol"] = ""
        state["direction"] = "NONE"
        state["total_size"] = 0
        state["entry_price"] = 0
        return state

    def get_additional_info(self) -> Dict:
        return {"system": "screen", "path": str(self.base_dir)}


def _load_config() -> Dict:
    """加载配置文件"""
    config_path = CONFIG_DIR / "monitor_config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _get_sync_config() -> Dict:
    """获取持仓同步配置"""
    cfg = _load_config().get("position_sync", {})
    return {
        "dry_run": cfg.get("dry_run", DEFAULT_DRY_RUN),
        "close_confirm_count": cfg.get("close_confirm_count", CLOSE_CONFIRM_COUNT),
        "close_confirm_window_minutes": cfg.get("close_confirm_window_minutes", CLOSE_CONFIRM_WINDOW_MINUTES),
        "max_backups": cfg.get("max_backups", MAX_BACKUPS),
        "skip_close_on_api_error": cfg.get("skip_close_on_api_error", True),
    }


def run_position_sync():
    """执行持仓同步（用于定时调度）"""
    sync_cfg = _get_sync_config()

    service = PositionSyncService(dry_run=sync_cfg["dry_run"])
    service.register_default_adapters()
    results = service.sync_all()

    for result in results:
        if result.get("status") != "success":
            print(f"[PositionSync] {result.get('system')} 同步失败: {result.get('message')}")


if __name__ == "__main__":
    run_position_sync()
