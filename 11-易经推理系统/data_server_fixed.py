#!/usr/bin/env python3
"""
监控页面数据服务器 — 提供 /api/state 接口
启动：python3 data_server.py
访问：http://localhost:8765

优化：
  - 线程池服务器，避免慢请求阻塞
  - 内存缓存 + 后台定时刷新，页面秒开
  - 易经/三屏等慢接口异步刷新，请求直接返回缓存
  - requests 禁用系统代理，避免本地代理干扰
"""
import json, os, requests, warnings, subprocess, sys, threading, time, datetime
from pathlib import Path
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl

warnings.filterwarnings("ignore")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

BASE_DIR = Path(__file__).resolve().parent.parent / "experiments" / "ab-trading"
LOG_A    = BASE_DIR / "logs" / "agent_a"
LOG_B    = BASE_DIR / "logs" / "agent_b"
PORT     = 8765

BCRM_REPO = Path(os.environ.get(
    "BCRM_REPO",
    str(Path(__file__).resolve().parent),
))

sys.path.insert(0, str(BASE_DIR))
try:
    from screen_engine import get_all as get_screen_data
    SCREEN_AVAILABLE = True
except ImportError:
    SCREEN_AVAILABLE = False

USER_A = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"
USER_B = "0x6632da9c91A959eEBf1343f8AFAbf2807414004A"

# ── 加载 dreamos/.env 中的 Aster 分离凭证 ─────────────────────────────────
# P1 修复: ml_trade_service._aster_env_get_for_owner 对钱包地址类型的 owner
# 直接读取全局 os.environ["ASTER_USER"]，导致 Dream OS 和趋势策略查询返回
# 相同持仓。正确做法是用 owner="trend" 关键字，读取 ASTER_USER_TREND 等分离变量。
# dreamos/.env 已定义 ASTER_USER_TREND/SIGNER_TREND/PRIVATE_KEY_TREND，这里加载到进程环境。
_DREAMOS_ENV_FILE = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/.env")
if _DREAMOS_ENV_FILE.exists():
    with open(_DREAMOS_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip()
            # 只加载 ASTER_* 相关变量（包括 _TREND 后缀），避免污染其他配置
            if _k.startswith("ASTER_"):
                os.environ.setdefault(_k, _v)

# 易经推理策略固定初始资金（USDT）—— 小额观测实际表现
YIJING_INITIAL_CAPITAL = 150.0

_cache = {}


def _json_default(obj):
    """JSON 序列化兜底：处理 numpy 类型（screen_engine 等模块返回的数据可能含 int64/float64）

    标准库 json.dumps 无法序列化 numpy.int64 / numpy.float64 / numpy.ndarray，
    不加此兜底会让 /api/screen-trade 等端点抛 TypeError 后连接被强制关闭，
    浏览器表现为「数据不显示」。
    """
    try:
        import numpy as _np
        if isinstance(obj, _np.integer):
            return int(obj)
        if isinstance(obj, _np.floating):
            return float(obj)
        if isinstance(obj, _np.bool_):
            return bool(obj)
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    return str(obj)


def _load_yijing_baseline():
    """加载或创建易经策略每日基准快照（从今天起以 150 为基准）

    基准值 = 今天起始时 performance.json 的累计已实现盈亏 total_pnl
    从今天起已实现盈亏 = 当前 total_pnl - 基准 total_pnl
    """
    baseline_file = Path(__file__).parent / ".workbuddy" / "memory_l4" / "stats" / "account_baseline.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    baseline = None
    if baseline_file.exists():
        try:
            with open(baseline_file) as fp:
                baseline = json.load(fp)
        except Exception:
            baseline = None
    # 读取当前累计已实现盈亏作为基准候选
    perf_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "stats" / "performance.json"
    current_realized = None
    if perf_path.exists():
        try:
            with open(perf_path) as fp:
                current_realized = float(json.load(fp).get("total_pnl", 0) or 0)
        except Exception:
            pass
    # 日期变更或不存在 → 初始化新基准
    if not baseline or baseline.get("baseline_date") != today:
        baseline = {
            "baseline_date": today,
            "initial_capital": YIJING_INITIAL_CAPITAL,
            "realized_pnl_baseline": current_realized,  # 可能为 None（performance 未生成）
            "created_at": datetime.datetime.now().isoformat(),
        }
        try:
            with open(baseline_file, "w") as fp:
                json.dump(baseline, fp, indent=2, ensure_ascii=False)
        except Exception:
            pass
    elif baseline.get("realized_pnl_baseline") is None and current_realized is not None:
        # 补填基准（首次创建时 performance 未就绪）
        baseline["realized_pnl_baseline"] = current_realized
        try:
            with open(baseline_file, "w") as fp:
                json.dump(baseline, fp, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return baseline
_cache_lock = threading.Lock()


def _cache_get(key):
    with _cache_lock:
        return _cache.get(key)


def _cache_set(key, value):
    with _cache_lock:
        _cache[key] = {"data": value, "ts": time.time()}


def _make_session():
    s = requests.Session()
    s.trust_env = False
    return s


def load_logs(log_dir: Path, limit: int = 30):
    logs = []
    if not log_dir.exists():
        return logs
    for f in sorted(log_dir.glob("*.json"))[-limit:]:
        try:
            with open(f) as fp:
                d = json.load(fp)
                if "coin" not in d and d.get("entry_price"):
                    pass
                logs.append(d)
        except Exception:
            pass
    return logs


def get_perp_state(user: str) -> dict:
    s = _make_session()
    try:
        r = s.post("https://api.hyperliquid.xyz/info",
                   json={"type": "clearinghouseState", "user": user}, timeout=8).json()
    except Exception as e:
        return {"equity": 0, "avail": 0, "positions": [], "error": str(e)}
    m = r.get("marginSummary", {})
    positions = []
    for p in r.get("assetPositions", []):
        pos = p.get("position", {})
        if float(pos.get("szi", 0)) != 0:
            positions.append({
                "coin":     pos.get("coin"),
                "size":     float(pos.get("szi", 0)),
                "entry_px": float(pos.get("entryPx") or 0),
                "upnl":     float(pos.get("unrealizedPnl") or 0),
                "leverage": float((pos.get("leverage") or {}).get("value", 1)),
            })
    equity = float(m.get("accountValue", 0))
    avail  = float(m.get("marginAvailable") or 0)
    if equity == 0:
        try:
            r2 = s.post("https://api.hyperliquid.xyz/info",
                        json={"type": "spotClearinghouseState", "user": user}, timeout=8).json()
            spot_usdc = next(
                (float(b["total"]) for b in r2.get("balances", []) if b.get("coin") == "USDC"), 0
            )
            if spot_usdc > 0:
                equity = spot_usdc
                avail  = spot_usdc
        except Exception:
            pass
    return {"equity": equity, "avail": avail, "positions": positions}


def get_hl_state():
    a = get_perp_state(USER_A)
    b = get_perp_state(USER_B)
    return {
        "perp_equity":    a["equity"],
        "perp_avail":     a["avail"],
        "perp_positions": a["positions"],
        "b_equity":       b["equity"],
        "b_avail":        b["avail"],
        "b_positions":    b["positions"],
        "spot_usdc":      0,
        "total_equity":   a["equity"] + b["equity"],
    }


def get_full_state():
    try:
        hl = get_hl_state()
    except Exception as e:
        print(f"[state] get_hl_state failed: {e}")
        hl = {
            "perp_equity": 0, "perp_avail": 0, "perp_positions": [],
            "b_equity": 0, "b_avail": 0, "b_positions": [],
            "spot_usdc": 0, "total_equity": 0,
            "hl_error": str(e),
        }
    try:
        logs_a = load_logs(LOG_A)
    except Exception as e:
        print(f"[state] load_logs A failed: {e}")
        logs_a = []
    try:
        logs_b = load_logs(LOG_B)
    except Exception as e:
        print(f"[state] load_logs B failed: {e}")
        logs_b = []
    return {
        **hl,
        "logs_a": logs_a,
        "logs_b": logs_b,
    }


def _extract_json_from_stdout(stdout: str):
    """从可能混入日志行的子进程 stdout 中提取首个可解析的 JSON 对象

    ab_bridge yijing-status 会在 stdout 混入 OKX 代理探测等日志行
    （如 "[OKX 代理探测/OK] ... proxies={'http':...}"），直接
    json.loads 会因前缀日志行抛异常。这里用 raw_decode 逐个尝试
    每个 '{' 起点，跳过非法片段（如单引号 dict repr），直到命中
    真正的 JSON 对象。
    """
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(stdout):
        pos = stdout.find("{", idx)
        if pos == -1:
            break
        try:
            data, _ = decoder.raw_decode(stdout[pos:])
            return data
        except json.JSONDecodeError:
            idx = pos + 1
    return None


def get_yijing_state():
    try:
        # 使用 anaconda python3 绝对路径（与 data_server 进程一致），
        # 避免系统 python3 与 anaconda 环境差异；超时从 45s 提升到 90s
        # 留足余量（实测 yijing-status 耗时 20-25s，含 BCRM 推理+对比学习）
        result = subprocess.run(
            [sys.executable, "-m", "scripts.memory_l4.ab_bridge", "yijing-status"],
            capture_output=True, text=True, timeout=90,
            cwd=str(BCRM_REPO),
            env={**os.environ, "NO_PROXY": "localhost,127.0.0.1",
                 "no_proxy": "localhost,127.0.0.1"},
        )
        if result.returncode == 0:
            # ab_bridge stdout 可能混入日志行，用 raw_decode 提取首个 JSON
            data = _extract_json_from_stdout(result.stdout)
            if data is not None:
                return data
            # stdout 无合法 JSON 时回退到 stderr 提示
            return {"error": f"stdout 无合法 JSON: {result.stdout[:300]}"}
        return {"error": result.stderr[:500]}
    except Exception as e:
        return {"error": str(e)}


def get_screen_state():
    if not SCREEN_AVAILABLE:
        return {"error": "screen_engine not available"}
    try:
        return get_screen_data()
    except Exception as e:
        return {"error": str(e)}


# ── 三屏趋势策略数据（前端 /api/trend-screen 调用） ────────────────────────
# 前端 monitor.html 的 "三屏趋势" Tab 实际请求 /api/trend-screen?symbol=BTC
# screen_engine.compute_full_trading_signal() 已包含 trend_consistency /
# bayesian_confidence / freqtrade_signals / technical_fundamental_fusion /
# final_signal 等字段，但 final_signal 缺少 action/position/decision_reason
# 等战术层字段；本函数补充这些字段并附加账户/持仓数据，使前端 Screen2/3
# 不再因字段缺失而报错。
def get_trend_screen_state(symbol: str = "BTC"):
    if not SCREEN_AVAILABLE:
        return {"error": "screen_engine not available"}
    try:
        spot_inst = f"{symbol}-USDT"
        is_btc = (symbol.upper() == "BTC")
        # screen_engine.compute_full_trading_signal 是模块级函数，
        # 返回 trend_consistency / bayesian_confidence / freqtrade_signals /
        # technical_fundamental_fusion / final_signal 等字段。
        import screen_engine as _se
        result = _se.compute_full_trading_signal(spot_inst=spot_inst, is_btc=is_btc)
        if not result or result.get("error"):
            return result or {"error": "compute_full_trading_signal failed"}

        # 补充 final_signal 的战术层字段（Screen2 渲染需要）
        fs = result.setdefault("final_signal", {})
        direction = fs.get("direction", "NEUTRAL")
        confidence = fs.get("confidence", 0)
        if "action" not in fs:
            fs["action"] = "ENTER_LONG" if direction == "BULL" else \
                           "ENTER_SHORT" if direction == "BEAR" else "WAIT"
        if "position" not in fs:
            # 置信度→仓位映射（与前端 renderTrendScreen2 显示规则一致）
            if confidence >= 85:
                pct, tier = 0.60, "T1"
            elif confidence >= 75:
                pct, tier = 0.45, "T2"
            elif confidence >= 65:
                pct, tier = 0.30, "T3"
            elif confidence >= 55:
                pct, tier = 0.15, "T4"
            elif confidence >= 45:
                pct, tier = 0.05, "T5"
            else:
                pct, tier = 0.0, "--"
            fs["position"] = {"position_pct": pct, "tier": tier}
        if "decision_reason" not in fs:
            tf = result.get("technical_fundamental_fusion", {}) or {}
            fs["decision_reason"] = (
                f"方向={direction} 置信度={confidence:.1f}% "
                f"趋势一致={fs.get('trend_consistent')} "
                f"融合一致={fs.get('fusion_consistent')} "
                f"Freqtrade一致={fs.get('freqtrade_consistent')} "
                f"技术面={tf.get('technical', {}).get('direction', '--')} "
                f"基本面={tf.get('fundamental', {}).get('direction', '--')}"
            )

        # 附加账户与持仓（Screen3 渲染需要，从趋势策略专用 Aster 钱包拉取）
        # P1 修复: 用 owner="trend" 关键字查询，ml_trade_service 会读取
        # ASTER_USER_TREND / ASTER_SIGNER_TREND / ASTER_SIGNER_PRIVATE_KEY_TREND
        # 这三个分离环境变量（已在模块顶部从 dreamos/.env 加载），
        # 避免与 Dream OS 的全局 ASTER_USER 冲突，确保查询到的是趋势策略独立钱包。
        try:
            account = {"equity": 0, "available": 0}
            position = None
            try:
                sys.path.insert(0, CLASSIC_DIR)
                import ml_trade_service as _ml
                # owner="trend" → 读取 ASTER_USER_TREND 等，查到 0x6632da9c... 钱包
                positions_raw, _ = _ml._aster_fetch_positions(owner="trend")
                for p in (positions_raw or []):
                    if str(p.get("coin", "")).upper() == symbol.upper():
                        amt = float(p.get("position_amt", 0) or 0)
                        if abs(amt) < 1e-12:
                            continue
                        position = {
                            "side": "LONG" if amt > 0 else "SHORT",
                            "size": abs(amt),
                            "entry_px": float(p.get("entry_px", 0) or 0),
                            "leverage": float(p.get("leverage") or 1),
                            "upnl": float(p.get("unrealized_pnl_u", 0) or 0),
                        }
                        break
                summary = _ml._aster_fetch_account_summary(owner="trend")
                if summary.get("ok"):
                    s = summary.get("summary", {}) or {}
                    account["equity"] = float(s.get("totalWalletBalance", s.get("totalMarginBalance", 0)) or 0)
                    account["available"] = float(s.get("availableBalance", 0) or 0)
            except Exception:
                pass
            result["account"] = account
            result["position"] = position
        except Exception:
            pass

        return result
    except Exception as e:
        return {"error": str(e)}


# ── V4+波浪互斥融合策略（主力策略线：实盘可用） ──────────────────────────────
# 主线策略：V4减半周期策略（定方向）+ 波浪理论（择时加仓）+ 物理引擎（信号评估）
# 9年回测验证：V4年化 53.34%，V4+波浪互斥融合年化 56.43%
# 融合规则：同向叠加、异向以V4为主、V4空仓时波浪轻仓抄底（上限50%）
# 物理增强：弱趋势(η<0.10)时启用物理置信度调节仓位
V4_WAVE_BASE_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统"

def get_v4_wave_strategy(symbol: str = "BTC"):
    try:
        import sys, json, os
        sys.path.insert(0, V4_WAVE_BASE_DIR)

        symbol_upper = symbol.upper()
        is_btc = (symbol_upper == "BTC")

        # 加载本地历史数据（优先使用 730d 文件）
        data_path = os.path.join(V4_WAVE_BASE_DIR, f"data/historical/{symbol_upper}_1D_730d.json")
        if not os.path.exists(data_path):
            data_path = os.path.join(V4_WAVE_BASE_DIR, f"data/historical/{symbol_upper}_1D_365d.json")
        if not os.path.exists(data_path):
            return {"error": f"未找到 {symbol_upper} 历史数据文件"}

        with open(data_path) as f:
            data = json.load(f)
        import pandas as pd
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("timestamp")
        daily_df = df[["o", "h", "l", "c", "vol"]].rename(
            columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
        )
        current_price = float(daily_df["close"].iloc[-1])
        data_days = len(daily_df)

        # 加载 BTC 数据（非BTC币种需要）
        btc_daily_df = None
        if not is_btc:
            btc_path = os.path.join(V4_WAVE_BASE_DIR, "data/historical/BTC_1D_730d.json")
            if os.path.exists(btc_path):
                with open(btc_path) as f:
                    btc_data = json.load(f)
                btc_df = pd.DataFrame(btc_data)
                btc_df["timestamp"] = pd.to_datetime(btc_df["ts"], unit="ms")
                btc_df = btc_df.set_index("timestamp")
                btc_daily_df = btc_df[["o", "h", "l", "c", "vol"]].rename(
                    columns={"o": "open", "h": "high", "l": "low", "c": "close", "vol": "volume"}
                )

        # === 1. V4 主策略 ===
        v4_result = None
        if is_btc:
            from ml.halving_top_exit_strategy import HalvingTopExitStrategy
            v4_strategy = HalvingTopExitStrategy(symbol=symbol_upper, is_btc=True, btc_prices=daily_df)
            strategy_name = "HalvingTopExitStrategy_v4"
        else:
            from ml.altcoin_trend_strategy import AltcoinTrendStrategy
            v4_strategy = AltcoinTrendStrategy(symbol=symbol_upper, btc_prices=btc_daily_df)
            strategy_name = "AltcoinTrendStrategy"

        v4_position_series = v4_strategy.generate_signals(daily_df)
        v4_pos_arr = v4_position_series.values if hasattr(v4_position_series, 'values') else v4_position_series
        v4_current_pos = float(v4_pos_arr[-1]) if len(v4_pos_arr) > 0 else 0.0

        if v4_current_pos > 0.01:
            v4_action = "ENTER_LONG"
            v4_direction = "BULL"
            v4_position_pct = abs(v4_current_pos)
        elif v4_current_pos < -0.01:
            v4_action = "ENTER_SHORT"
            v4_direction = "BEAR"
            v4_position_pct = abs(v4_current_pos)
        else:
            v4_action = "WAIT"
            v4_direction = "NEUTRAL"
            v4_position_pct = 0.0

        v4_result = {
            "strategy_name": strategy_name,
            "is_btc": is_btc,
            "action": v4_action,
            "direction": v4_direction,
            "position_pct": round(v4_position_pct, 4),
            "raw_position": round(v4_current_pos, 4),
            "state": getattr(v4_strategy, "current_state", "N/A"),
        }

        # === 2. 波浪策略（互斥融合）===
        wave_result = None
        from ml.ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig
        wave_adapter = EWaveStrategyAdapter(WaveConfig())
        wave_result = wave_adapter.evaluate(
            daily_df=daily_df,
            v4_action=v4_action,
            v4_direction=v4_direction,
            v4_position_pct=v4_position_pct,
            symbol=symbol,
        )

        # === 3. 物理置信度评估 ===
        physics_result = None
        try:
            import numpy as np
            from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
            from ml.pitd_kinematics_engineer import KinematicsEngineer
            from ml.pitd_dynamics_engineer import DynamicsEngineer

            kin_fe = KinematicsEngineer()
            dyn_fe = DynamicsEngineer()
            kin_feats = kin_fe.extract_series(daily_df)
            dyn_feats = dyn_fe.extract_series(daily_df, kin_feats)
            eta_series = dyn_feats["dyn_coupling_eta"].values
            current_eta = float(eta_series[-1]) if len(eta_series) > 0 else 0.0

            weights = ConfidenceWeights(
                w_eta=0.211, w_reversal=0.368,
                w_support=0.211, w_kinetic=0.211,
                position_lower=0.6, position_scale=1.0,
            )
            scorer = PhysicsConfidenceScorer(weights)
            ml_preds = np.full(len(daily_df), 0.5)
            if v4_action == "ENTER_LONG":
                ml_preds[-1] = 0.75
            elif v4_action == "ENTER_SHORT":
                ml_preds[-1] = 0.25

            conf_arr, components = scorer.score_signals(prices=daily_df, ml_predictions=ml_preds)
            current_conf = float(conf_arr[-1])

            physics_result = {
                "enabled": True,
                "weak_trend": current_eta < 0.10,
                "current_eta": round(current_eta, 4),
                "physics_confidence": round(current_conf, 4),
                "components": {
                    "trend_score": round(float(components["trend_score"][-1]), 4),
                    "reversal_score": round(float(components["reversal_score"][-1]), 4),
                    "support_score": round(float(components["support_score"][-1]), 4),
                    "kinetic_score": round(float(components["kinetic_score"][-1]), 4),
                },
                "weights": {"w_eta": 0.211, "w_reversal": 0.368, "w_support": 0.211, "w_kinetic": 0.211},
            }
        except Exception as e:
            physics_result = {"enabled": False, "error": str(e)}

        # === 4. 最终决策 ===
        final_action = wave_result.get("final_action", v4_action) if wave_result else v4_action
        final_direction = wave_result.get("final_direction", v4_direction) if wave_result else v4_direction
        final_position = wave_result.get("total_position_pct", v4_position_pct) if wave_result else v4_position_pct

        # 物理调节（仅弱趋势）
        adjusted_position = final_position
        if physics_result.get("enabled") and physics_result.get("weak_trend") and final_action in ("ENTER_LONG", "ENTER_SHORT"):
            base_pos_arr = np.array([final_position])
            conf_arr = np.array([physics_result["physics_confidence"]])
            adjusted_arr = scorer.adjust_position(base_pos_arr, conf_arr)
            adjusted_position = float(adjusted_arr[0])

        # === 5. 账户与持仓（趋势策略专用钱包 owner="trend" → ASTER_USER_TREND）===
        # P1 修复: 之前用 AsterExecutor() 会读取全局 os.environ["ASTER_USER"]，
        # 该变量被 dreamos/.env 加载时污染为 Dream OS 钱包 (0x93842F...)。
        # 改用 owner="trend" 关键字查询，读取 ASTER_USER_TREND 等
        # 分离环境变量，确保查到的是趋势策略独立钱包 (0x6632da9c...)。
        account = {"equity": 0, "available": 0}
        position = None
        all_positions = []
        try:
            sys.path.insert(0, CLASSIC_DIR)
            import ml_trade_service as _ml
            # 账户摘要
            try:
                summary = _ml._aster_fetch_account_summary(owner="trend")
                if summary and summary.get("ok"):
                    s = summary.get("summary", {}) or {}
                    account["equity"] = float(s.get("totalWalletBalance", s.get("totalMarginBalance", 0)) or 0)
                    account["available"] = float(s.get("availableBalance", 0) or 0)
            except Exception:
                pass
            # 持仓查询：遍历所有持仓，匹配当前 symbol + 收集全部持仓
            try:
                positions_raw, _ = _ml._aster_fetch_positions(owner="trend")
                for p in (positions_raw or []):
                    coin = str(p.get("coin", "")).upper()
                    amt = float(p.get("position_amt", 0) or p.get("positionAmt", 0) or 0)
                    if abs(amt) < 1e-12:
                        continue
                    pos_item = {
                        "coin": coin,
                        "side": "LONG" if amt > 0 else "SHORT",
                        "size": abs(amt),
                        "entry_px": float(p.get("entry_px", 0) or p.get("entryPrice", 0) or 0),
                        "leverage": float(p.get("leverage") or 1),
                        "upnl": float(p.get("unrealized_pnl_u", 0) or p.get("unRealizedProfit", 0) or 0),
                        "mark_px": float(p.get("mark_px", 0) or p.get("markPrice", 0) or 0),
                    }
                    all_positions.append(pos_item)
                    if coin == symbol_upper:
                        position = pos_item
            except Exception:
                pass
        except Exception:
            pass

        return {
            "symbol": symbol_upper,
            "spot_inst": f"{symbol_upper}-USDT",
            "current_price": round(current_price, 2),
            "data_days": data_days,
            "generated_at": datetime.datetime.now().isoformat(),
            "v4_strategy": v4_result,
            "wave_strategy": wave_result,
            "physics_assessment": physics_result,
            "final_decision": {
                "action": final_action,
                "direction": final_direction,
                "position_pct": round(final_position, 4),
                "adjusted_position_pct": round(adjusted_position, 4),
                "fusion_rule": wave_result.get("fusion_rule", "no_wave") if wave_result else "no_wave",
            },
            "account": account,
            "position": position,
            "all_positions": all_positions,
            "strategy_line": "MAIN",
            "mode": "live_trading_available",
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


def get_executor_state():
    try:
        from screen_executor import get_executor_state
        return get_executor_state()
    except Exception as e:
        return {"error": str(e)}


def get_orchestrator_state():
    try:
        from screen_orchestrator import get_orchestrator_state
        return get_orchestrator_state()
    except Exception as e:
        return {"error": str(e)}


def get_reports_state():
    try:
        from report_loader import get_all_reports
        return get_all_reports()
    except Exception as e:
        return {"error": str(e)}


# ── Dream OS 状态 ──────────────────────────────────────────────────────────
ARCH_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE"
PROJECT_ROOT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
CLASSIC_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统"
# Dream OS 实盘账户 owner（Aster 平台）
# 注意：必须显式指定，避免被 12-三屏趋势系统的 AsterExecutor 导入时污染全局 ASTER_USER
DREAMOS_ASTER_OWNER_RAW = os.environ.get("DREAMOS_ASTER_OWNER", "").strip()
DREAMOS_ASTER_OWNER = DREAMOS_ASTER_OWNER_RAW if DREAMOS_ASTER_OWNER_RAW else "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"


def get_dreamos_state():
    """获取 Dream OS 状态（节点注册表 + 账户 + 记忆）

    持仓查询：Dream OS 实盘在 Aster 平台运行（owner=quant），
    不再查询 Hyperliquid Agent B。
    """
    try:
        sys.path.insert(0, ARCH_DIR)
        from dreamos.nodes import list_available_nodes, register_all
        from dreamos.registry import get_default_registry

        registry = get_default_registry()
        register_all(registry)
        nodes = registry.list_nodes()
        registered = [{"node_id": n.node_id, "name": getattr(n, "name", ""),
                       "chain": getattr(n, "chain", ""), "description": getattr(n, "description", "")}
                      for n in nodes]

        # ── Aster 实盘账户（Dream OS 实际下单平台）──
        # 注意：必须临时覆盖环境变量，因为 12-三屏趋势系统的 AsterExecutor 导入时已污染全局 ASTER_USER
        DREAMOS_ENV_FILE = Path(ARCH_DIR) / "dreamos" / ".env"
        _original_env = {}
        _dreamos_env_vars = ["ASTER_USER", "ASTER_SIGNER", "ASTER_SIGNER_PRIVATE_KEY"]
        if DREAMOS_ENV_FILE.exists():
            with open(DREAMOS_ENV_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k in _dreamos_env_vars:
                        _original_env[k] = os.environ.get(k)
                        os.environ[k] = v
        try:
            account = {"ok": False, "equity": 0, "avail": 0, "positions": {}, "mode": "aster"}
            try:
                sys.path.insert(0, CLASSIC_DIR)
                import ml_trade_service as _ml
                # 持仓列表 → 转为 coin 为 key 的字典（兼容前端 renderDreamOS）
                positions_raw, pos_err = _ml._aster_fetch_positions(owner=DREAMOS_ASTER_OWNER)
                positions = {}
                for p in (positions_raw or []):
                    coin = str(p.get("coin", "")).upper()
                    if not coin:
                        continue
                    amt = float(p.get("position_amt", 0) or 0)
                    if abs(amt) < 1e-12:
                        continue
                    positions[coin] = {
                        "size":     amt,                    # 正=多, 负=空
                        "entry_px": float(p.get("entry_px", 0) or 0),
                        "upnl":     float(p.get("unrealized_pnl_u", 0) or 0),
                        "leverage": float(p.get("leverage") or 1),
                        "mark_px":  float(p.get("mark_px", 0) or 0),
                        "liq_px":   float(p.get("liq_px", 0) or 0),
                        "notional": float(p.get("notional_usdc", 0) or 0),
                        "side":     p.get("side", "long" if amt > 0 else "short"),
                    }
                # 账户摘要
                summary = _ml._aster_fetch_account_summary(owner=DREAMOS_ASTER_OWNER)
                equity = 0.0
                avail = 0.0
                if summary.get("ok"):
                    s = summary.get("summary", {}) or {}
                    equity = float(s.get("totalWalletBalance", s.get("totalMarginBalance", 0)) or 0)
                    avail = float(s.get("availableBalance", 0) or 0)
                account = {
                    "ok":        True,
                    "equity":    equity,
                    "avail":     avail,
                    "positions": positions,
                    "mode":      "aster",
                    "owner":     DREAMOS_ASTER_OWNER,
                    "pos_error": pos_err,
                }
            except Exception as e:
                account = {"ok": False, "equity": 0, "avail": 0, "positions": {},
                           "mode": "aster", "error": str(e)}
        finally:
            # 恢复原始环境变量
            for k, v in _original_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        memory = {}
        try:
            sys.path.insert(0, PROJECT_ROOT)
            from experiments.agent_c.agent_c import AgentC
            agent_c = AgentC(agent_id='b')
            memory = agent_c.get_memory()
        except Exception:
            pass

        return {
            "nodes": registered,
            "total_nodes": len(registered),
            "account": account,
            "memory": memory,
            "timestamp": datetime.datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_dreamos_history():
    """获取 Dream OS 调度历史"""
    try:
        history_dir = BASE_DIR / "data" / "agent_c_b"
        logs = []
        if history_dir.exists():
            for f in sorted(history_dir.glob("*.json"))[-20:]:
                try:
                    with open(f) as fp:
                        logs.append(json.load(fp))
                except Exception:
                    pass
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        return {"error": str(e)}


def get_dreamos_scenarios():
    """获取 36 场景编排记忆表 + 执行反馈 + 进化触发列表

    返回前端 monitor.html dosLoadScenarios() 所需结构：
      { stats, scenarios:[{scenario_id,covered,inferred,confidence,
                          best_pattern,sample_count,score}],
        feedback:{scenario_id:{total_trades,...}},
        trigger_evolution:[{scenario_id,...}],
        covered, total_scenarios }
    """
    try:
        sys.path.insert(0, ARCH_DIR)
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory
        from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector

        memory = OrchestrationMemory()
        memory.load()

        # ── 场景列表 ──
        scenarios_out = []
        for entry in memory.list_scenarios():
            scenarios_out.append({
                "scenario_id":  entry.get("scenario_id", ""),
                "covered":      not entry.get("sparse", True),
                "inferred":     bool(entry.get("inferred", False)),
                "confidence":   entry.get("confidence", "low"),
                "best_pattern": entry.get("best_pattern", ""),
                "sample_count": int(entry.get("sample_count", 0) or 0),
                "score":        float(entry.get("score", 0.0) or 0.0),
            })

        # ── 反馈统计 + 触发进化 ──
        collector = ExecutionFeedbackCollector(memory=memory)
        feedback_out = {}
        trigger_list = []
        for sid in collector.get_all_scenario_ids():
            try:
                feedback_out[sid] = collector.get_stats(sid)
            except Exception:
                pass
        for fb in collector.get_all_feedbacks():
            if fb.trigger_evolution:
                trigger_list.append({
                    "scenario_id":        fb.scenario_id,
                    "pattern_used":       fb.pattern_used,
                    "direction_accuracy": fb.direction_accuracy,
                    "actual_sharpe":      fb.actual_sharpe,
                    "expected_sharpe":    fb.expected_sharpe,
                    "deviation":          fb.deviation,
                })

        stats = memory.get_stats()
        return {
            "stats":             stats,
            "scenarios":         scenarios_out,
            "feedback":          feedback_out,
            "trigger_evolution": trigger_list,
            "covered":           stats.get("covered_scenarios", len(scenarios_out)),
            "total_scenarios":   stats.get("total_scenarios", 36) or 36,
            "timestamp":         datetime.datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "scenarios": [], "feedback": {},
                "trigger_evolution": [], "covered": 0, "total_scenarios": 36}


def get_token_signals():
    """聚合 9 个候选币种的最终交易信号，供 monitor.html signals tab 展示

    使用 screen_engine.compute_full_trading_signal（重接口，单币种约 3-6 秒）。
    推荐由后台 _bg_refresh_token_signals() 定时刷新，请求直接返回缓存。
    """
    try:
        sys.path.insert(0, str(BASE_DIR))
        from screen_engine import compute_full_trading_signal, CANDIDATE_COINS

        ENTRY_CONFIDENCE_THRESHOLD = 45  # 与 screen_executor.py 入场阈值一致

        signals = []
        for coin in CANDIDATE_COINS:
            try:
                full = compute_full_trading_signal(
                    spot_inst=coin.get("spot", f"{coin['symbol']}-USDT"),
                    is_btc=coin.get("is_btc", False),
                )
                if not full or "error" in full:
                    continue
                fs = full.get("final_signal", {}) or {}
                ft = full.get("freqtrade_signals", {}) or {}
                direction = fs.get("direction", "NEUTRAL")
                confidence = int(round(float(fs.get("confidence", 0) or 0), 0))
                trend_consistent = bool(fs.get("trend_consistent", False))
                freqtrade_consistent = bool(fs.get("freqtrade_consistent", False))
                entry_ready = (
                    trend_consistent
                    and freqtrade_consistent
                    and direction != "NEUTRAL"
                    and confidence >= ENTRY_CONFIDENCE_THRESHOLD
                )
                ft4h = ft.get("4h", {}) or {}
                ft1h = ft.get("1h", {}) or {}
                signals.append({
                    "symbol":               full.get("symbol", coin.get("symbol", "")),
                    "price":                float(full.get("price", 0) or 0),
                    "direction":            direction,
                    "confidence":           confidence,
                    "trend_consistent":     trend_consistent,
                    "freqtrade_consistent": freqtrade_consistent,
                    "entry_ready":          entry_ready,
                    "freqtrade_4h":         ft4h.get("signal", ""),
                    "freqtrade_4h_conf":    int(ft4h.get("confidence", 0) or 0),
                    "freqtrade_1h":         ft1h.get("signal", ""),
                    "freqtrade_1h_conf":    int(ft1h.get("confidence", 0) or 0),
                })
            except Exception:
                continue

        return {
            "bull_count":    sum(1 for s in signals if s["direction"] == "BULL"),
            "bear_count":    sum(1 for s in signals if s["direction"] == "BEAR"),
            "neutral_count": sum(1 for s in signals if s["direction"] == "NEUTRAL"),
            "signals":       signals,
            "timestamp":     datetime.datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "signals": [],
                "bull_count": 0, "bear_count": 0, "neutral_count": 0}


def dreamos_analyze(symbol="BTC"):
    """执行一次 Dream OS 分析"""
    try:
        sys.path.insert(0, ARCH_DIR)
        sys.path.insert(0, PROJECT_ROOT)
        from experiments.agent_c.agent_c import AgentC

        agent_c = AgentC(agent_id='b')
        mkt_data = agent_c.fetch_market_data(symbol)
        if not mkt_data:
            return {"error": f"无法获取 {symbol} 的市场数据"}

        decision = agent_c.analyze(symbol, mkt_data)

        # 保存历史
        history_dir = BASE_DIR / "data" / "agent_c_b"
        history_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        history_file = history_dir / f"{ts}_{symbol}.json"
        with open(history_file, 'w') as f:
            json.dump(decision, f, indent=2, default=str)

        return decision
    except Exception as e:
        return {"error": str(e)}


def get_yijing_positions():
    """读取易经推理系统的当前持仓（本地跟踪 + OKX实盘查询）"""
    pos_dir = Path(__file__).parent / ".workbuddy" / "memory_l4" / "open_positions"
    risk_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "risk" / "risk_state.json"
    hb_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "guardian" / "heartbeat.json"
    perf_path = Path(__file__).parent / ".workbuddy" / "memory_l4" / "stats" / "performance.json"

    # ── 本地跟踪持仓 ──
    local_positions = []
    if pos_dir.exists():
        for f in sorted(pos_dir.glob("*.json")):
            try:
                with open(f) as fp:
                    d = json.load(fp)
                    local_positions.append({
                        "coin": d.get("coin", ""),
                        "inst_id": d.get("inst_id", ""),
                        "direction": d.get("direction", ""),
                        "entry_price": d.get("entry_price", 0),
                        "entry_time": d.get("entry_time", ""),
                        "confidence": d.get("confidence", 0),
                        "hexagram": d.get("hexagram", ""),
                        "pnl": d.get("pnl", 0),
                        "pnl_pct": d.get("pnl_pct", 0),
                        "trade_id": d.get("trade_id", ""),
                        "source": "local",
                    })
            except Exception:
                pass

    # ── OKX 实盘持仓查询 ──
    okx_positions = []
    okx_balance = {}
    try:
        sys.path.insert(0, str(Path(__file__).parent / "scripts" / "memory_l4"))
        from okx_simulated import OKXSimulatedClient, _load_config, CONFIG_DIR
        env_keys = ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE",
                    "OKX_BASE_URL", "OKX_SIMULATED", "OKX_DRY_RUN",
                    "OKX_DEFAULT_INST_ID", "DEFAULT_LEVERAGE"]
        saved_env = {}
        for k in env_keys:
            if k in os.environ:
                saved_env[k] = os.environ.pop(k)
        try:
            client = OKXSimulatedClient()
        finally:
            for k, v in saved_env.items():
                os.environ[k] = v

        # 查询账户余额
        bal = client.get_balance()
        if bal.get("ok"):
            okx_balance = {
                "total_eq": bal.get("total_eq", 0),
                "avail": bal.get("assets", {}).get("USDT", {}).get("avail", 0),
            }

        # 查询所有币种持仓
        coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
        for coin in coins:
            inst_id = f"{coin}-USDT-SWAP"
            r = client.get_positions(inst_id)
            if not r.get("ok"):
                continue
            for p in r.get("positions", []):
                okx_positions.append({
                    "coin": coin,
                    "inst_id": inst_id,
                    "direction": p.get("pos_side", ""),
                    "entry_price": p.get("avg_px", 0),
                    "pos_size": p.get("pos", 0),
                    "upl": p.get("upl", 0),
                    "upl_ratio": p.get("upl_ratio", 0),
                    "mark_px": p.get("mark_px", 0),
                    "leverage": p.get("lever", ""),
                    "source": "okx_live",
                })
    except Exception as e:
        okx_positions = [{"error": str(e)}]

    risk_state = {}
    if risk_path.exists():
        try:
            with open(risk_path) as fp:
                risk_state = json.load(fp)
        except Exception:
            pass

    heartbeat = {}
    if hb_path.exists():
        try:
            with open(hb_path) as fp:
                heartbeat = json.load(fp)
        except Exception:
            pass

    performance = {}
    if perf_path.exists():
        try:
            with open(perf_path) as fp:
                performance = json.load(fp)
        except Exception:
            pass

    return {
        "positions": local_positions,
        "okx_live_positions": okx_positions,
        "okx_balance": okx_balance,
        "count": len(okx_positions),
        "local_count": len(local_positions),
        "risk_state": risk_state,
        "heartbeat": heartbeat,
        "performance": performance,
    }


def get_yijing_account_overview():
    """易经推理策略账户总览：从今天起以 150 USDT 为基准

    复用 get_yijing_positions() 的持仓数据（与页面持仓同源）：
      - 基准日 = 今天，初始资金 = 150
      - 从今天起已实现盈亏 = 当前 performance.total_pnl - 基准日 total_pnl
      - 未实现盈亏 = 当前持仓 upl 之和（OKX 实时优先，降级用本地跟踪 pnl）
      - 总盈亏 = 从今天起已实现 + 未实现
      - 当前余额 = 150 + 总盈亏
      - 涨跌幅 = 总盈亏 / 150 × 100%
    """
    # ── 基准快照（从今天起）──
    baseline = _load_yijing_baseline()
    realized_baseline = baseline.get("realized_pnl_baseline")
    baseline_date = baseline.get("baseline_date")

    # ── 复用持仓查询（与页面持仓数据同源，避免重复调 OKX）──
    pos_data = get_yijing_positions()
    okx_balance = pos_data.get("okx_balance", {}) or {}
    okx_positions = pos_data.get("okx_live_positions", []) or []
    local_positions = pos_data.get("positions", []) or []
    performance = pos_data.get("performance", {}) or {}

    # ── 累计已实现盈亏 + 从今天起已实现盈亏 ──
    cumulative_realized = float(performance.get("total_pnl", 0) or 0)
    total_trades = int(performance.get("total_trades", 0) or 0)
    win_count = int(performance.get("win_count", 0) or 0)
    win_rate = float(performance.get("win_rate", 0) or 0)

    if realized_baseline is not None:
        realized_pnl = cumulative_realized - realized_baseline
    else:
        # 基准未建立（performance 未就绪）：当作 0
        realized_pnl = 0.0

    # ── OKX 连接状态 ──
    live_ok = bool(okx_balance)
    live_error = ""
    okx_avail = float(okx_balance.get("avail", 0) or 0) if live_ok else None

    if okx_positions and isinstance(okx_positions[0], dict) and "error" in okx_positions[0]:
        live_error = str(okx_positions[0].get("error", ""))
        okx_positions = []

    # 持仓明细 + 未实现盈亏
    positions_detail = []
    unrealized_pnl = 0.0
    open_positions_count = 0

    # 优先 OKX 实时持仓的 upl
    for p in okx_positions:
        try:
            upl = float(p.get("upl", 0) or 0)
            if abs(float(p.get("pos_size", p.get("pos", 0)) or 0)) > 0 or upl != 0:
                unrealized_pnl += upl
                open_positions_count += 1
                positions_detail.append({
                    "coin": p.get("coin", ""),
                    "inst_id": p.get("inst_id", ""),
                    "direction": p.get("direction", p.get("pos_side", "")),
                    "upl": upl,
                    "upl_ratio": float(p.get("upl_ratio", 0) or 0),
                    "mark_px": float(p.get("mark_px", 0) or 0),
                    "entry_price": float(p.get("entry_price", p.get("avg_px", 0)) or 0),
                    "source": "okx_live",
                })
        except Exception:
            continue

    # OKX 无持仓数据时，降级用本地跟踪持仓的 pnl
    if open_positions_count == 0 and local_positions:
        for p in local_positions:
            try:
                upl = float(p.get("pnl", 0) or 0)
                unrealized_pnl += upl
                open_positions_count += 1
                positions_detail.append({
                    "coin": p.get("coin", ""),
                    "inst_id": p.get("inst_id", ""),
                    "direction": p.get("direction", ""),
                    "upl": upl,
                    "upl_ratio": float(p.get("pnl_pct", 0) or 0),
                    "mark_px": 0,
                    "entry_price": float(p.get("entry_price", 0) or 0),
                    "source": "local",
                })
            except Exception:
                continue

    # ── 盈亏计算（从今天起，基于基准差值）──
    total_pnl = realized_pnl + unrealized_pnl
    current_balance = YIJING_INITIAL_CAPITAL + total_pnl
    pnl_pct = (total_pnl / YIJING_INITIAL_CAPITAL) * 100 if YIJING_INITIAL_CAPITAL > 0 else 0
    avail_balance = okx_avail if okx_avail is not None else current_balance

    # 基准状态提示
    if realized_baseline is not None:
        baseline_note = f"基准日 {baseline_date} 起累计已实现 {round(realized_baseline, 2)}"
    else:
        baseline_note = "今日基准尚未建立（performance 未就绪）"

    return {
        "strategy": "yijing",
        "strategy_name": "易经推理策略",
        "initial_capital": YIJING_INITIAL_CAPITAL,
        "baseline_date": baseline_date,
        "baseline_realized_pnl": round(realized_baseline, 2) if realized_baseline is not None else None,
        "baseline_note": baseline_note,
        "current_balance": round(current_balance, 2),
        "avail_balance": round(avail_balance, 2) if avail_balance is not None else None,
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_trades": total_trades,
        "win_count": win_count,
        "win_rate": round(win_rate, 4),
        "win_rate_pct": round(win_rate * 100, 2),
        "open_positions": open_positions_count,
        "positions_detail": positions_detail,
        "live_ok": live_ok,
        "live_error": live_error,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# 马丁策略固定初始资金（USDT）
V15_INITIAL_CAPITAL = 150.0


def _load_v15_baseline():
    """加载或创建V15马丁策略每日基准快照（从今天起以150为基准）"""
    baseline_file = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/data/account_baseline.json")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    baseline = None
    if baseline_file.exists():
        try:
            with open(baseline_file) as f:
                baseline = json.load(f)
        except Exception:
            baseline = None
    if not baseline or baseline.get("baseline_date") != today:
        baseline = {
            "baseline_date": today,
            "initial_capital": V15_INITIAL_CAPITAL,
            "okx_total_eq_baseline": None,
            "v15_state_equity_baseline": None,
            "created_at": datetime.datetime.now().isoformat(),
        }
        try:
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            with open(baseline_file, "w") as fp:
                json.dump(baseline, fp, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return baseline


def _save_v15_baseline(baseline):
    try:
        baseline_file = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/data/account_baseline.json")
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        with open(baseline_file, "w") as fp:
            json.dump(baseline, fp, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_v15_account_overview():
    """V15 马丁策略账户总览：从今天起以 150 USDT 为基准

    优先从 v15_state.json 读取本地跟踪数据（策略已维护该文件），
    OKX 实时数据作为增强（若可用则填充 live_ok / avail_balance 等字段）。
    """
    baseline = _load_v15_baseline()
    v15_state_file = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/data/v15_state.json")

    # ── 从 v15_state.json 读取核心数据 ──
    total_trades = 0
    total_wins = 0
    consecutive_losses = 0
    current_state_equity = None
    state_updated_at = None
    positions_detail = []
    unrealized_pnl_sum = 0.0
    open_positions_count = 0

    if v15_state_file.exists():
        try:
            with open(v15_state_file) as f:
                v15_state = json.load(f)
            total_trades = int(v15_state.get("total_trades", 0) or 0)
            total_wins = int(v15_state.get("total_wins", 0) or 0)
            consecutive_losses = int(v15_state.get("consecutive_losses", 0) or 0)
            current_state_equity = v15_state.get("total_equity")
            if current_state_equity is not None:
                current_state_equity = float(current_state_equity or 0)
            state_updated_at = v15_state.get("last_poll")

            # 首次读取到 state_equity 时写入基准
            if baseline.get("v15_state_equity_baseline") is None and current_state_equity is not None:
                baseline["v15_state_equity_baseline"] = current_state_equity
                _save_v15_baseline(baseline)

            raw_positions = v15_state.get("positions", {}) or {}
            for coin, p in raw_positions.items():
                upl = float(p.get("unrealized_pnl", 0) or 0)
                mark_price = float(p.get("current_price", p.get("mark_px", 0)) or 0)
                unrealized_pnl_sum += upl
                open_positions_count += 1
                positions_detail.append({
                    "coin": coin,
                    "symbol": coin,
                    "inst_id": p.get("inst_id", f"{coin}-USDT-SWAP"),
                    "direction": p.get("direction", "LONG"),
                    "upl": upl,
                    "unrealized_pnl": upl,
                    "upl_ratio": float(p.get("upl_ratio", 0) or 0),
                    "mark_px": mark_price,
                    "mark_price": mark_price,
                    "current_price": mark_price,
                    "entry_price": float(p.get("entry_price", 0) or 0),
                    "sz": float(p.get("sz", 0) or 0),
                    "lever": p.get("lever", ""),
                    "source": p.get("source", "v15_state"),
                    "open_time": p.get("open_time", ""),
                    "addons": int(p.get("addons", 0) or 0),
                    "profit_pct": float(p.get("profit_pct", 0) or 0),
                    "confidence": int(p.get("confidence", 0) or 0),
                    "take_profit_pct": float(p.get("take_profit_pct", 0) or 0),
                    "stop_loss_price": p.get("stop_loss_price"),
                    "stop_loss_type": p.get("stop_loss_type"),
                })
        except Exception:
            pass

    # ── 尝试 OKX 实时数据增强 ──
    live_ok = False
    live_error = ""
    avail_balance = None
    current_okx_eq = None

    try:
        V15_DIR = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略")
        sys.path.insert(0, str(V15_DIR / "lib"))
        from capital_manager import get_account_balance, get_current_positions
        balance = get_account_balance()
        if balance.get("ok"):
            live_ok = True
            current_okx_eq = float(balance.get("total_eq", 0) or 0)
            avail_balance = float(balance.get("avail_balance", 0) or 0)
            # 首次成功获取 OKX 权益时写入基准
            if baseline.get("okx_total_eq_baseline") is None:
                baseline["okx_total_eq_baseline"] = current_okx_eq
                _save_v15_baseline(baseline)
            # OKX 实时持仓覆盖本地持仓
            try:
                okx_positions = get_current_positions() or []
                if okx_positions:
                    new_detail = []
                    new_upl_sum = 0.0
                    new_count = 0
                    for p in okx_positions:
                        sz = float(p.get("pos_sz", p.get("sz", 0)) or 0)
                        if abs(sz) < 1e-12:
                            continue
                        upl = float(p.get("unrealized_pnl", 0) or 0)
                        mark_price = float(p.get("mark_price", p.get("mark_px", 0)) or 0)
                        coin = p.get("coin", p.get("symbol", ""))
                        new_upl_sum += upl
                        new_count += 1
                        new_detail.append({
                            "coin": coin,
                            "symbol": coin,
                            "inst_id": p.get("inst_id", ""),
                            "direction": p.get("direction", ""),
                            "upl": upl,
                            "unrealized_pnl": upl,
                            "upl_ratio": float(p.get("upl_ratio", 0) or 0),
                            "mark_px": mark_price,
                            "mark_price": mark_price,
                            "current_price": mark_price,
                            "entry_price": float(p.get("entry_price", 0) or 0),
                            "sz": sz,
                            "lever": p.get("lever", ""),
                            "source": "okx_live",
                            "open_time": p.get("open_time", ""),
                            "addons": 0,
                        })
                    if new_count > 0:
                        positions_detail = new_detail
                        unrealized_pnl_sum = new_upl_sum
                        open_positions_count = new_count
            except Exception:
                pass
        else:
            live_error = balance.get("error", "OKX 连接失败")
    except Exception as _e:
        live_error = str(_e)[:120]

    baseline_eq = baseline.get("okx_total_eq_baseline")
    baseline_state_eq = baseline.get("v15_state_equity_baseline")

    # ── 盈亏计算 ──
    total_pnl = None
    current_balance = None
    pnl_pct = None
    realized_pnl = None

    # 优先 OKX 基准差值（策略自身收益）
    if current_okx_eq is not None and baseline_eq is not None:
        total_pnl = current_okx_eq - baseline_eq
        current_balance = V15_INITIAL_CAPITAL + total_pnl
        pnl_pct = (total_pnl / V15_INITIAL_CAPITAL) * 100 if V15_INITIAL_CAPITAL > 0 else 0
        realized_pnl = total_pnl - unrealized_pnl_sum
    # 降级用 v15_state.json 的 total_equity
    elif current_state_equity is not None and baseline_state_eq is not None:
        total_pnl = current_state_equity - baseline_state_eq
        current_balance = V15_INITIAL_CAPITAL + total_pnl
        pnl_pct = (total_pnl / V15_INITIAL_CAPITAL) * 100 if V15_INITIAL_CAPITAL > 0 else 0
        realized_pnl = total_pnl - unrealized_pnl_sum
    # 再降级：只用浮动盈亏估算（基准尚未建立时）
    else:
        total_pnl = unrealized_pnl_sum if unrealized_pnl_sum != 0 else 0.0
        current_balance = V15_INITIAL_CAPITAL + total_pnl
        pnl_pct = (total_pnl / V15_INITIAL_CAPITAL) * 100 if V15_INITIAL_CAPITAL > 0 else 0
        realized_pnl = None

    win_rate = (total_wins / total_trades) if total_trades > 0 else 0.0
    win_rate_pct = round(win_rate * 100, 2)

    # 基准状态提示
    baseline_note = ""
    if baseline_eq is not None:
        baseline_note = f"基准日 {baseline.get('baseline_date')} 起 OKX 权益 {round(baseline_eq, 2)}"
    elif baseline_state_eq is not None:
        baseline_note = f"基准日 {baseline.get('baseline_date')} 起策略权益 {round(baseline_state_eq, 2)}（本地）"
    else:
        baseline_note = "今日基准尚未建立（等待首次数据采样）"

    if avail_balance is None:
        avail_balance = current_balance

    return {
        "strategy": "v15_martin",
        "strategy_name": "V15 经典马丁策略",
        "initial_capital": V15_INITIAL_CAPITAL,
        "baseline_date": baseline.get("baseline_date"),
        "baseline_okx_eq": round(baseline_eq, 2) if baseline_eq is not None else None,
        "baseline_note": baseline_note,
        "current_balance": round(current_balance, 2) if current_balance is not None else None,
        "avail_balance": round(avail_balance, 2) if avail_balance is not None else None,
        "total_pnl": round(total_pnl, 2) if total_pnl is not None else None,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "realized_pnl": round(realized_pnl, 2) if realized_pnl is not None else None,
        "unrealized_pnl": round(unrealized_pnl_sum, 2),
        "total_trades": total_trades,
        "win_count": total_wins,
        "win_rate": round(win_rate, 4),
        "win_rate_pct": win_rate_pct,
        "consecutive_losses": consecutive_losses,
        "open_positions": open_positions_count,
        "positions_detail": positions_detail,
        "live_ok": live_ok,
        "live_error": live_error,
        "state_updated_at": state_updated_at,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def get_l4_status():
    """获取 L4 认知闭环状态"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from scripts.memory_l4.l4_status_api import get_l4_status as _get_l4_status
        return _get_l4_status()
    except Exception as e:
        return {"error": str(e)}


def get_global_trade_stats():
    """获取跨系统交易统计：从 L4 案例库读取各系统的胜率、PnL 等指标"""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from scripts.memory_l4.case_registry import UnifiedCaseRegistry
        
        registry = UnifiedCaseRegistry()
        cases_dir = registry.cases_dir
        
        stats = {
            "total_cases": 0,
            "systems": {},
            "summary": {},
            "timestamp": datetime.datetime.now().isoformat(),
        }
        
        # 主系统定义（顺序决定前端展示顺序）
        system_names = {
            "yijing_inference": "易经推理",
            "martin_v15": "马丁策略 V15",
            "three_screen": "三屏趋势",
            "agent_a": "Agent A",
            "agent_b": "Agent B",
            "dream_os": "Dream OS",
            "unknown": "未知来源",
        }

        # 归一化映射：旧/别名 → 主 system_source
        # 任何落入本表的 source 都会合并到主桶，避免前端出现"影子系统"
        _SOURCE_NORMALIZE = {
            "bcrm": "yijing_inference",
            "yijing_live": "yijing_inference",
            "yijing_engine": "yijing_inference",
            "yijing_force": "yijing_inference",
            "liangyi": "yijing_inference",
            "scale": "yijing_inference",
            "bagua": "yijing_inference",
            "yijing": "yijing_inference",
            "three_screen_trend": "three_screen",
            "martin_v15_live": "martin_v15",
            "martin": "martin_v15",
            "dreamos": "dream_os",
            "dreamos_trading": "dream_os",
            "agent_a_live": "agent_a",
            "agent_b_live": "agent_b",
        }

        def normalize_source(src: str) -> str:
            if not src:
                return "unknown"
            s = str(src).strip().lower()
            return _SOURCE_NORMALIZE.get(s, s)
        
        for source, name in system_names.items():
            stats["systems"][source] = {
                "name": name,
                "total_trades": 0,
                "win_count": 0,
                "lose_count": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "max_win": 0.0,
                "max_lose": 0.0,
                "cases": [],
            }
        
        all_cases = []
        if cases_dir.exists():
            for f in sorted(cases_dir.glob("*.json")):
                try:
                    with open(f) as fp:
                        case = json.load(fp)
                    # 跳过非交易案例：记忆条目（lesson/test 等）缺少
                    # decision_outcome 字段，不属于任何系统的交易记录。
                    if not case.get("decision_outcome"):
                        continue
                    raw_source = case.get("system_source") or "unknown"
                    source = normalize_source(raw_source)

                    # 动态建桶（未知来源也能展示，避免遗漏）
                    if source not in stats["systems"]:
                        display_name = system_names.get(source, source)
                        stats["systems"][source] = {
                            "name": display_name,
                            "total_trades": 0,
                            "win_count": 0,
                            "lose_count": 0,
                            "win_rate": 0.0,
                            "total_pnl": 0.0,
                            "avg_pnl": 0.0,
                            "max_win": 0.0,
                            "max_lose": 0.0,
                            "cases": [],
                        }
                    
                    do = case.get("decision_outcome", {})
                    pnl_pct = do.get("pnl_pct", 0)
                    is_correct = do.get("is_correct", False)
                    
                    stats["systems"][source]["total_trades"] += 1
                    stats["systems"][source]["total_pnl"] += pnl_pct
                    stats["systems"][source]["cases"].append(case)
                    
                    if pnl_pct > 0:
                        stats["systems"][source]["win_count"] += 1
                        if pnl_pct > stats["systems"][source]["max_win"]:
                            stats["systems"][source]["max_win"] = pnl_pct
                    elif pnl_pct < 0:
                        stats["systems"][source]["lose_count"] += 1
                        if pnl_pct < stats["systems"][source]["max_lose"]:
                            stats["systems"][source]["max_lose"] = pnl_pct
                    
                    all_cases.append(case)
                except Exception:
                    continue
        
        for source, data in stats["systems"].items():
            if data["total_trades"] > 0:
                data["win_rate"] = data["win_count"] / data["total_trades"]
                data["avg_pnl"] = data["total_pnl"] / data["total_trades"]
            data["win_rate_pct"] = round(data["win_rate"] * 100, 2)
            data["total_pnl"] = round(data["total_pnl"], 2)
            data["avg_pnl"] = round(data["avg_pnl"], 4)
            data["max_win"] = round(data["max_win"], 2)
            data["max_lose"] = round(data["max_lose"], 2)
            data["cases"] = []
        
        stats["total_cases"] = len(all_cases)
        
        overall_total = 0
        overall_win = 0
        overall_pnl = 0.0
        for data in stats["systems"].values():
            overall_total += data["total_trades"]
            overall_win += data["win_count"]
            overall_pnl += data["total_pnl"]
        
        stats["summary"] = {
            "total_systems": len(stats["systems"]),
            "total_trades": overall_total,
            "win_count": overall_win,
            "win_rate": overall_win / overall_total if overall_total > 0 else 0.0,
            "win_rate_pct": round((overall_win / overall_total * 100) if overall_total > 0 else 0, 2),
            "total_pnl": round(overall_pnl, 2),
            "avg_pnl": round(overall_pnl / overall_total, 4) if overall_total > 0 else 0.0,
        }
        
        best_system = None
        best_win_rate = 0
        best_pnl = float('-inf')
        for source, data in stats["systems"].items():
            if data["total_trades"] >= 1:
                if data["avg_pnl"] > best_pnl:
                    best_pnl = data["avg_pnl"]
                    best_system = source
        
        stats["top_performer"] = best_system
        
        return stats
    except Exception as e:
        return {"error": str(e), "systems": {}, "summary": {}}


def _bg_refresh_l4_status(interval: int = 10):
    """后台定时刷新 L4 认知闭环状态"""
    while True:
        try:
            data = get_l4_status()
            _cache_set("l4_status", data)
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_state(interval: int = 5):
    while True:
        try:
            data = get_full_state()
            _cache_set("state", data)
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_yijing(interval: int = 60):
    while True:
        try:
            data = get_yijing_state()
            # 仅缓存成功结果（非 error），避免单次超时覆盖掉上次的有效数据
            if isinstance(data, dict) and "error" not in data:
                _cache_set("yijing", data)
        except Exception:
            pass
        try:
            _cache_set("yijing_account", get_yijing_account_overview())
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_screen(interval: int = 30):
    while True:
        try:
            _cache_set("screen_trade", get_screen_state())
        except Exception:
            pass
        try:
            _cache_set("screen_executor", get_executor_state())
        except Exception:
            pass
        try:
            _cache_set("screen_orchestrator", get_orchestrator_state())
        except Exception:
            pass
        try:
            _cache_set("reports", get_reports_state())
        except Exception:
            pass
        try:
            sys.path.insert(0, str(BASE_DIR))
            from classic_executor import get_executor_state as _get_classic_state
            _cache_set("classic_executor", _get_classic_state())
        except Exception:
            pass
        try:
            sys.path.insert(0, str(BASE_DIR))
            from mode_manager import get_current_state
            _cache_set("mode_status", get_current_state())
        except Exception:
            pass
        try:
            sys.path.insert(0, str(BASE_DIR))
            from fundamental_bridge import get_fundamental_signals
            _cache_set("fundamental_signals_BTC", get_fundamental_signals("BTC"))
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_dreamos(interval: int = 15):
    while True:
        try:
            _cache_set("dreamos", get_dreamos_state())
        except Exception:
            pass
        try:
            _cache_set("dreamos_history", get_dreamos_history())
        except Exception:
            pass
        try:
            _cache_set("dreamos_scenarios", get_dreamos_scenarios())
        except Exception:
            pass
        time.sleep(interval)


def _bg_refresh_token_signals(interval: int = 300):
    """代币信号聚合接口较慢（9 币种 × compute_full_trading_signal），5 分钟刷新一次"""
    # 启动后立即拉一次，避免页面长时间等待
    try:
        _cache_set("token_signals", get_token_signals())
    except Exception:
        pass
    while True:
        try:
            _cache_set("token_signals", get_token_signals())
        except Exception:
            pass
        time.sleep(interval)


def _start_bg_refresh():
    threads = [
        threading.Thread(target=_bg_refresh_state, args=(5,), daemon=True),
        threading.Thread(target=_bg_refresh_yijing, args=(60,), daemon=True),
        threading.Thread(target=_bg_refresh_screen, args=(30,), daemon=True),
        threading.Thread(target=_bg_refresh_dreamos, args=(15,), daemon=True),
        threading.Thread(target=_bg_refresh_token_signals, args=(300,), daemon=True),
        threading.Thread(target=_bg_refresh_l4_status, args=(10,), daemon=True),
    ]
    for t in threads:
        t.start()
    return threads


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/state":
            cached = _cache_get("state")
            data = cached["data"] if cached else get_full_state()
            self._json(data)

        elif path == "/api/yijing":
            cached = _cache_get("yijing")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "yijing data loading, please wait"})

        elif path == "/api/screen-trade":
            cached = _cache_get("screen_trade")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "screen data loading"})

        elif path == "/api/screen-executor":
            cached = _cache_get("screen_executor")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "executor data loading"})

        elif path == "/api/screen-orchestrator":
            cached = _cache_get("screen_orchestrator")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "orchestrator data loading"})

        # ── 三屏趋势策略（前端 "三屏趋势" Tab 实际请求的端点） ─────────────
        # compute_full_trading_signal 调用较慢（OKX K线+Freqtrade 信号），
        # 按 symbol 做 60s 缓存避免每次切换 tab 都重新计算。
        elif path == "/api/trend-screen":
            symbol = (self._get_query_param("symbol") or "BTC").upper()
            cache_key = f"trend_screen_{symbol}"
            cached = _cache_get(cache_key)
            if cached and (time.time() - cached["ts"] < 60):
                self._json(cached["data"])
            else:
                try:
                    data = get_trend_screen_state(symbol)
                    _cache_set(cache_key, data)
                    self._json(data)
                except Exception as e:
                    self._json({"error": str(e)})

        # ── V4+波浪互斥融合策略（主力策略线） ──────────────────────────────────
        # 主线策略：V4减半周期策略（定方向）+ 波浪理论（择时加仓）+ 物理引擎（信号评估）
        # 支持实盘交易，按 symbol 做 60s 缓存
        elif path == "/api/v4-wave-strategy":
            symbol = (self._get_query_param("symbol") or "BTC").upper()
            cache_key = f"v4_wave_{symbol}"
            cached = _cache_get(cache_key)
            if cached and (time.time() - cached["ts"] < 60):
                self._json(cached["data"])
            else:
                try:
                    data = get_v4_wave_strategy(symbol)
                    _cache_set(cache_key, data)
                    self._json(data)
                except Exception as e:
                    import traceback
                    self._json({"error": str(e), "traceback": traceback.format_exc()})

        elif path == "/api/reports":
            cached = _cache_get("reports")
            if cached:
                self._json(cached["data"])
            else:
                self._json({"error": "reports loading"})

        elif path == "/api/yijing-positions":
            self._json(get_yijing_positions())

        elif path == "/api/yijing/account-overview":
            cached = _cache_get("yijing_account")
            if cached:
                self._json(cached["data"])
            else:
                self._json(get_yijing_account_overview())

        # ── V15-CT 马丁策略 API ────────────────────────────────────────
        elif path == "/api/v15-ct/account-overview":
            try:
                self._json(get_v15_account_overview())
            except Exception as e:
                self._json({"error": str(e), "strategy": "v15_martin",
                             "initial_capital": 150.0})

        elif path == "/api/v15-ct/decision":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_executor import _v15_real_decision
                coin = self._get_query_param("coin") or "BTC"
                screen1 = {"spot_inst": f"{coin}-USDT"}
                decision = _v15_real_decision(screen1, {})
                self._json(decision)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/v15-ct/decisions":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from screen_executor import _v15_real_decision
                coins_param = self._get_query_param("coins") or "BTC,ETH,SOL,ARB,OP,UNI,HYPE,OKB"
                coins = [c.strip() for c in coins_param.split(",") if c.strip()]
                decisions = []
                for coin in coins:
                    try:
                        screen1 = {"spot_inst": f"{coin}-USDT"}
                        d = _v15_real_decision(screen1, {})
                        d["symbol"] = coin
                        decisions.append(d)
                    except Exception:
                        decisions.append({"symbol": coin, "action": "WAIT", "confidence": 0, "reasons": ["获取失败"]})
                self._json({"decisions": decisions})
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/v15-ct/backtest":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from v15_backtest import run_backtest, fetch_klines
                coin = self._get_query_param("coin") or "BTC"
                klines = fetch_klines(coin, "4h", 1500)
                result = run_backtest(coin=coin, klines=klines)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/v15-ct/status":
            try:
                # V15 马丁策略状态直接从 v15_state.json 读取（由 v15_trader.py 维护）
                v15_state_file = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略/data/v15_state.json")
                total_trades = 0
                total_wins = 0
                win_rate = 0.0
                coins_monitored = []
                total_equity = 0.0
                consecutive_losses = 0
                positions = []
                state_updated_at = None
                if v15_state_file.exists():
                    try:
                        with open(v15_state_file) as f:
                            v15_state = json.load(f)
                        total_trades = v15_state.get("total_trades", 0)
                        total_wins = v15_state.get("total_wins", 0)
                        win_rate = round(total_wins / total_trades, 4) if total_trades > 0 else 0.0
                        total_equity = v15_state.get("total_equity", 0.0)
                        consecutive_losses = v15_state.get("consecutive_losses", 0)
                        state_updated_at = v15_state.get("last_poll")
                        # 从 v15_state.json 构建持仓列表
                        raw_positions = v15_state.get("positions", {}) or {}
                        for coin, p in raw_positions.items():
                            entry_price = float(p.get("entry_price", 0) or 0)
                            sz = float(p.get("sz", 0) or 0)
                            mark_price = float(p.get("current_price", p.get("mark_px", 0)) or 0)
                            upl = float(p.get("unrealized_pnl", 0) or 0)
                            positions.append({
                                # 原始字段
                                "coin": coin,
                                "symbol": coin,  # ← 前端用 pos.symbol
                                "inst_id": p.get("inst_id", f"{coin}-USDT-SWAP"),
                                "direction": p.get("direction", "LONG"),
                                "entry_price": entry_price,
                                "sz": sz,
                                "open_time": p.get("open_time", ""),
                                "per_coin_budget": float(p.get("per_coin_budget", 0) or 0),
                                "addons": int(p.get("addons", 0) or 0),
                                "current_price": mark_price,
                                "mark_price": mark_price,  # ← 前端用 pos.mark_price
                                "mark_px": mark_price,
                                "unrealized_pnl": upl,
                                "upl": upl,  # ← 前端用 pos.upl
                                "upl_ratio": float(p.get("upl_ratio", 0) or 0),
                                "profit_pct": float(p.get("profit_pct", 0) or 0),
                                "confidence": int(p.get("confidence", 0) or 0),
                                "take_profit_pct": float(p.get("take_profit_pct", 0) or 0),
                                "stop_loss_price": p.get("stop_loss_price"),
                                "stop_loss_type": p.get("stop_loss_type"),
                                "lever": p.get("lever", ""),
                                "source": "v15_state",
                            })
                        coins_monitored = list(raw_positions.keys())
                    except Exception:
                        pass

                self._json({
                    "strategy_mode": "v15_martin",
                    "auto_execute": True,
                    "positions": positions,
                    "v15_ct_positions": positions,
                    "total_trades": total_trades,
                    "total_wins": total_wins,
                    "win_rate": win_rate,
                    "coins_monitored": coins_monitored,
                    "capital": {"equity": total_equity},
                    "consecutive_losses": consecutive_losses,
                    "risk_level": "MEDIUM",
                    "state_updated_at": state_updated_at,
                })
            except Exception as e:
                self._json({"error": str(e)})

        # ── 资金管理 API ────────────────────────────────────────────────
        elif path == "/api/capital/allocation":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import calculate_capital_allocation
                allocation = calculate_capital_allocation()
                self._json(allocation)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/capital/balance":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_account_balance
                balance = get_account_balance()
                self._json(balance)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/capital/positions":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_current_positions
                positions = get_current_positions()
                self._json(positions)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/capital/signal-trigger":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from capital_manager import get_signal_trigger_status
                status = get_signal_trigger_status()
                self._json(status)
            except Exception as e:
                self._json({"error": str(e)})

        # ── Dream OS API ──────────────────────────────────────────────
        elif path == "/api/dreamos":
            cached = _cache_get("dreamos")
            if cached:
                self._json(cached["data"])
            else:
                self._json(get_dreamos_state())

        elif path == "/api/dreamos/history":
            cached = _cache_get("dreamos_history")
            if cached:
                self._json(cached["data"])
            else:
                self._json(get_dreamos_history())

        elif path == "/api/dreamos/nodes":
            try:
                sys.path.insert(0, ARCH_DIR)
                from dreamos.nodes import list_available_nodes
                nodes = list_available_nodes()
                self._json(nodes)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/dreamos/analyze":
            symbol = self._get_query_param("symbol") or "BTC"
            self._json(dreamos_analyze(symbol))

        elif path == "/api/dreamos/scenarios":
            cached = _cache_get("dreamos_scenarios")
            if cached:
                self._json(cached["data"])
            else:
                data = get_dreamos_scenarios()
                _cache_set("dreamos_scenarios", data)
                self._json(data)

        elif path == "/api/token-signals":
            cached = _cache_get("token_signals")
            if cached:
                self._json(cached["data"])
            else:
                # 首次请求时缓存尚未就绪，同步返回（前端有 60s 超时）
                self._json({"error": "token_signals loading, please retry in a moment",
                            "signals": [], "bull_count": 0,
                            "bear_count": 0, "neutral_count": 0})

        elif path == "/api/screen-trigger":
            try:
                from screen_executor import check_and_execute
                result = check_and_execute()
                _cache_set("screen_executor", get_executor_state())
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/screen-orchestrator/trigger":
            try:
                from screen_orchestrator import main
                main()
                _cache_set("screen_orchestrator", get_orchestrator_state())
                self._json({"ok": True, "state": _cache_get("screen_orchestrator")["data"]})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 模式状态查询 ──────────────────────────────────────────
        elif path == "/api/mode/status":
            cached = _cache_get("mode_status")
            if cached:
                self._json(cached["data"])
            else:
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from mode_manager import get_current_state
                    state = get_current_state()
                    _cache_set("mode_status", state)
                    self._json(state)
                except Exception as e:
                    self._json({"error": str(e)})

        # ── API: 模式切换历史 ─────────────────────────────────────────
        elif path == "/api/mode/history":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import get_mode_history
                limit = int(self._get_query_param("limit") or "20")
                history = get_mode_history(limit)
                self._json({"history": history, "count": len(history)})
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: AI 指令查询 ──────────────────────────────────────────
        elif path == "/api/mode/ai-directive":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import get_ai_directive
                directive = get_ai_directive()
                self._json(directive)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 基本面参考信号 ────────────────────────────────────────
        elif path == "/api/fundamental-signals":
            symbol = self._get_query_param("symbol") or "BTC"
            cached = _cache_get(f"fundamental_signals_{symbol}")
            if cached:
                self._json(cached["data"])
            else:
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from fundamental_bridge import get_fundamental_signals
                    data = get_fundamental_signals(symbol)
                    _cache_set(f"fundamental_signals_{symbol}", data)
                    self._json(data)
                except Exception as e:
                    self._json({"error": str(e)})

        # ── API: 经典指标执行器状态 ────────────────────────────────────
        elif path == "/api/classic-executor":
            cached = _cache_get("classic_executor")
            if cached:
                self._json(cached["data"])
            else:
                try:
                    sys.path.insert(0, str(BASE_DIR))
                    from classic_executor import get_executor_state
                    state = get_executor_state()
                    _cache_set("classic_executor", state)
                    self._json(state)
                except Exception as e:
                    self._json({"error": str(e)})

        # ── API: 经典指标信号（指定币种） ──────────────────────────────
        elif path == "/api/classic-executor/signals":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from classic_executor import generate_signals
                symbol = self._get_query_param("symbol") or "BTC"
                signals = generate_signals(symbol)
                self._json(signals)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 全局交易统计（跨系统胜率/PnL对比） ────────────────────────
        elif path == "/api/global-trade-stats":
            cached = _cache_get("global_trade_stats")
            if cached and (time.time() - cached["ts"] < 30):
                self._json(cached["data"])
            else:
                data = get_global_trade_stats()
                _cache_set("global_trade_stats", data)
                self._json(data)

        # ── API: L4 认知闭环状态仪表盘 ─────────────────────────────────────
        elif path == "/api/l4-status":
            cached = _cache_get("l4_status")
            if cached and (time.time() - cached["ts"] < 10):
                self._json(cached["data"])
            else:
                data = get_l4_status()
                _cache_set("l4_status", data)
                self._json(data)

        elif path == "/" or path == "/index.html":
            self._file(BASE_DIR / "monitor.html", "text/html")
        else:
            self.send_response(404)
            self.end_headers()

    def _get_query_param(self, name: str) -> str:
        params = urlparse(self.path).query
        qs = dict(parse_qsl(params))
        return qs.get(name)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body) if body else {}
        except Exception:
            return {}

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/mode/switch":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import set_mode_override
                content = self._read_json_body()
                mode = content.get("mode") or self._get_query_param("mode")
                reason = content.get("reason") or "API手动切换"
                if not mode:
                    self._json({"error": "缺少 mode 参数"}, status=400)
                    return
                result = set_mode_override(mode, reason)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/mode/check":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import check_and_switch_mode
                result = check_and_switch_mode()
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/mode/set-ai-directive":
            try:
                sys.path.insert(0, str(BASE_DIR))
                from mode_manager import set_ai_directive
                content = self._read_json_body()
                if not content:
                    self._json({"error": "缺少请求体"}, status=400)
                    return
                result = set_ai_directive(content)
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=_json_default).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, mime: str):
        if not path.exists():
            self.send_response(404); self.end_headers(); return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print("正在初始化数据缓存...")
    _start_bg_refresh()
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"监控服务已启动: http://localhost:{PORT}")
    print(f"  - /api/state         5s 刷新")
    print(f"  - /api/yijing       60s 刷新")
    print(f"  - /api/screen-*     30s 刷新")
    print(f"  - /api/dreamos      15s 刷新")
    print(f"  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
        server.shutdown()
