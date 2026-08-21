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
PORT     = int(os.environ.get("DATA_SERVER_PORT", "8765"))

BCRM_REPO = Path(os.environ.get(
    "BCRM_REPO",
    str(Path(__file__).resolve().parent),
))

sys.path.insert(0, str(BASE_DIR))
# 确保 scripts/memory_l4 在 sys.path 最前（bcrm2 包在此目录下）
_BCRM_PKG_DIR = str(BCRM_REPO / "scripts" / "memory_l4")
if _BCRM_PKG_DIR not in sys.path:
    sys.path.insert(0, _BCRM_PKG_DIR)
try:
    from screen_engine import get_all as get_screen_data
    SCREEN_AVAILABLE = True
except ImportError:
    SCREEN_AVAILABLE = False

# Phase B: ShadowLogger 影子模式开关（从 bcrm2.shadow_logger 导入，默认 False）
try:
    from bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED
    _sl_import_ok = True
except ImportError as _e:
    _sl_import_ok = False
    SHADOW_LOGGER_ENABLED = False
    ShadowLogger = None

# Phase C: α blend 前瞻参数上线开关（从 bcrm2.parameter_mapper 导入，默认 False）
try:
    from bcrm2.parameter_mapper import ALPHA_BLEND_ENABLED, ALPHA_BLEND_MAX, DEFAULT_ALPHA_BLEND
    _pm_import_ok = True
except ImportError as _e:
    _pm_import_ok = False
    ALPHA_BLEND_ENABLED = False
    ALPHA_BLEND_MAX = 0.5
    DEFAULT_ALPHA_BLEND = 0.0

USER_A = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"
USER_B = "0x6632da9c91A959eEBf1343f8AFAbf2807414004A"
USER_C = "0x81cA2cf32b57a5790338c2b0d7Ca847abC18838a"  # Agent C 独立钱包（DreamOS 主交易账户）

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


# ── Hyperliquid API 代理 + 缓存 ──
# trust_env=True 让 requests 自动使用系统代理（macOS 系统代理 / HTTPS_PROXY）
_HL_CACHE: dict = {}  # {wallet: {"data": ..., "ts": ...}}
_HL_CACHE_TTL = 300   # 缓存有效期 5 分钟


def _make_session():
    s = requests.Session()
    s.trust_env = True   # 启用系统代理（Clash/mihomo 等）
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
                   json={"type": "clearinghouseState", "user": user}, timeout=10).json()
    except Exception as e:
        # API 不可达时返回缓存数据（如有）
        cached = _HL_CACHE.get(user)
        if cached and (time.time() - cached["ts"] < _HL_CACHE_TTL):
            data = dict(cached["data"])
            data["cached"] = True
            data["error"] = f"API不可达，使用缓存数据: {e}"
            return data
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
                        json={"type": "spotClearinghouseState", "user": user}, timeout=10).json()
            spot_usdc = next(
                (float(b["total"]) for b in r2.get("balances", []) if b.get("coin") == "USDC"), 0
            )
            if spot_usdc > 0:
                equity = spot_usdc
                avail  = spot_usdc
        except Exception:
            pass
    result = {"equity": equity, "avail": avail, "positions": positions}
    # 缓存成功响应
    if equity > 0 or positions:
        _HL_CACHE[user] = {"data": result, "ts": time.time()}
    return result


def get_hl_state():
    a = get_perp_state(USER_A)
    b = get_perp_state(USER_B)
    c = get_perp_state(USER_C)
    return {
        "perp_equity":    a["equity"],
        "perp_avail":     a["avail"],
        "perp_positions": a["positions"],
        "b_equity":       b["equity"],
        "b_avail":        b["avail"],
        "b_positions":    b["positions"],
        "c_equity":       c["equity"],
        "c_avail":        c["avail"],
        "c_positions":    c["positions"],
        "spot_usdc":      0,
        "total_equity":   a["equity"] + b["equity"] + c["equity"],
    }


def _read_yijing_okx_config():
    """从 11-易经推理系统/.env 直接读取 OKX 凭据，返回 config dict。

    不走 os.environ，避免与 V15 capital_manager 写入的 OKX_* 环境变量冲突。
    """
    env_path = Path(__file__).resolve().parent / ".env"
    raw = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                raw[k.strip()] = v.strip()
    return {
        "api_key":          raw.get("OKX_API_KEY", ""),
        "secret_key":       raw.get("OKX_SECRET_KEY", ""),
        "passphrase":       raw.get("OKX_PASSPHRASE", ""),
        "base_url":         raw.get("OKX_BASE_URL", "https://www.okx.com"),
        "simulated":        raw.get("OKX_SIMULATED", "false").lower() in ("true", "1", "yes"),
        "dry_run":          raw.get("OKX_DRY_RUN", "false").lower() in ("true", "1", "yes"),
        "default_inst_id":  raw.get("OKX_DEFAULT_INST_ID", "BTC-USDT-SWAP"),
        "default_usdt_amount": 100,
        "default_leverage": float(raw.get("DEFAULT_LEVERAGE", "5") or 5),
    }


def get_yijing_okx_state():
    """查询易经推理系统的 OKX 实盘账户（持仓 + 余额）

    使用易经推理系统专属的 OKX 凭据（apikey=d988a164...），
    通过 config dict 直接传入 OKXSimulatedClient，不依赖 os.environ，
    避免与 V15 马丁策略的 OKX 凭据（apikey=5af4066c...）冲突。

    返回格式与 get_hl_state() 兼容：
      total_equity / perp_avail / perp_positions (+ b/c 空列表保持兼容)
    """
    try:
        V15_DIR = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略")
        sys.path.insert(0, str(V15_DIR / "lib"))
        from okx_client import OKXSimulatedClient
        # 直接传 config dict，绕过 _load_config() 读 os.environ
        client = OKXSimulatedClient(config=_read_yijing_okx_config())
        bal = client.get_balance()
        if not bal.get("ok"):
            return {"total_equity": 0, "perp_avail": 0, "perp_positions": [],
                    "b_positions": [], "c_positions": [], "error": bal.get("error", "")}
        total_eq = float(bal.get("total_eq", 0) or 0)
        avail = 0.0
        for ccy, asset in (bal.get("assets") or {}).items():
            if ccy == "USDT":
                avail = float(asset.get("avail", 0) or 0)
                break
        pos_r = client.get_all_positions()
        positions = []
        if pos_r.get("ok"):
            for coin, p in (pos_r.get("positions") or {}).items():
                size = float(p.get("pos", 0) or 0)
                if abs(size) < 1e-12:
                    continue
                positions.append({
                    "coin":     coin,
                    "size":     size,
                    "entry_px": float(p.get("avg_px", 0) or 0),
                    "upnl":     float(p.get("upl", 0) or 0),
                    "leverage": float(str(p.get("lever", "1")).replace("x", "") or 1),
                })
        return {
            "total_equity":   total_eq,
            "perp_avail":     avail,
            "perp_positions": positions,
            "b_positions":    [],
            "c_positions":    [],
        }
    except Exception as e:
        return {"total_equity": 0, "perp_avail": 0, "perp_positions": [],
                "b_positions": [], "c_positions": [], "error": str(e)}


def get_full_state():
    # Agent A/B/C 使用 Hyperliquid 实盘账户（本机和云端均为 Hyperliquid）。
    # 易经推理系统的 OKX 持仓通过 /api/yijing-positions 单独查询。
    try:
        hl = get_hl_state()
    except Exception as e:
        print(f"[state] get_hl_state failed: {e}")
        hl = {
            "perp_equity": 0, "perp_avail": 0, "perp_positions": [],
            "b_equity": 0, "b_avail": 0, "b_positions": [],
            "c_equity": 0, "c_avail": 0, "c_positions": [],
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

        # 附加账户与持仓（Screen3 渲染需要，从 Agent C Hyperliquid 钱包拉取）
        try:
            account = {"equity": 0, "available": 0}
            position = None
            try:
                hl_state = get_perp_state(USER_C)
                account["equity"] = hl_state.get("equity", 0)
                account["available"] = hl_state.get("avail", 0)
                for p in (hl_state.get("positions") or []):
                    if str(p.get("coin", "")).upper() == symbol.upper():
                        size = float(p.get("size", 0) or 0)
                        if abs(size) < 1e-12:
                            continue
                        position = {
                            "side": "LONG" if size > 0 else "SHORT",
                            "size": abs(size),
                            "entry_px": float(p.get("entry_px", 0) or 0),
                            "leverage": float(p.get("leverage") or 1),
                            "upnl": float(p.get("upnl", 0) or 0),
                        }
                        break
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
        # ── DreamOS 节点注册表（模块不可用时降级为空列表）──
        registered = []
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
        except Exception:
            pass

        # ── Hyperliquid 实盘账户（Agent C 钱包，DreamOS 主交易账户）──
        # Agent C = USER_C，Hyperliquid 独立钱包，本机和云端均使用 Hyperliquid。
        try:
            hl_state = get_perp_state(USER_C)
            positions = {}
            for p in (hl_state.get("positions") or []):
                coin = str(p.get("coin", "")).upper()
                if not coin:
                    continue
                size = float(p.get("size", 0) or 0)
                if abs(size) < 1e-12:
                    continue
                positions[coin] = {
                    "size":     size,
                    "entry_px": float(p.get("entry_px", 0) or 0),
                    "upnl":     float(p.get("upnl", 0) or 0),
                    "leverage": float(p.get("leverage") or 1),
                    "mark_px":  0,
                    "liq_px":   0,
                    "notional": abs(size) * float(p.get("entry_px", 0) or 0),
                    "side":     "long" if size > 0 else "short",
                }
            account = {
                "ok":        True,
                "equity":    hl_state.get("equity", 0),
                "avail":     hl_state.get("avail", 0),
                "positions": positions,
                "mode":      "hyperliquid",
                "wallet":    USER_C,
            }
        except Exception as e:
            account = {"ok": False, "equity": 0, "avail": 0, "positions": {},
                       "mode": "hyperliquid", "error": str(e)}

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


# ── DreamOS V2 六层闭环 ────────────────────────────────────────────

_dreamos_v2_orch = None

def _get_dreamos_v2():
    """获取或初始化 DreamOS V2 编排器单例"""
    global _dreamos_v2_orch
    if _dreamos_v2_orch is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1-ARCHITECTURE"))
        from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2
        _dreamos_v2_orch = OrchestratorV2(use_hermes=False, seed=42)
    return _dreamos_v2_orch

def _fetch_market_data_for_v2(symbol="BTC"):
    """获取 Hyperliquid 实时市场数据并转换为 V2 格式"""
    try:
        AB_DIR = Path(__file__).resolve().parent.parent / "experiments" / "ab-trading"
        sys.path.insert(0, str(AB_DIR))
        from dotenv import load_dotenv
        load_dotenv(AB_DIR / "config" / ".env")
        from execution.aster_spot import HyperliquidClient, _info_with_retry
        import requests as _req

        client = HyperliquidClient("dream_os")

        # 获取实时价格
        s = _req.Session()
        s.trust_env = False
        mids = _info_with_retry(s, {"type": "allMids"}, None)
        price_str = mids.get(symbol, "0")
        close_price = float(price_str)

        # 获取账户信息（Agent C Hyperliquid 钱包）
        account = client.get_account()
        equity = float(account.get("equity", 0))
        avail = float(account.get("avail", 0))
        positions = account.get("positions", {})

        # 检查是否已有该币种持仓
        has_position = symbol in positions
        pos_data = positions.get(symbol, {})
        pos_size = float(pos_data.get("size", 0))
        pos_entry = float(pos_data.get("entry_px", 0))
        pos_upnl = float(pos_data.get("upnl", 0))

        # 获取 K 线数据计算技术指标（使用 req 包装格式）
        try:
            klines_resp = _info_with_retry(s, {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": "4h",
                    "startTime": int((datetime.datetime.now().timestamp() - 30*4*3600) * 1000),
                    "endTime": int(datetime.datetime.now().timestamp() * 1000),
                },
            }, None)
            candles = klines_resp if isinstance(klines_resp, list) else []
        except Exception:
            candles = []

        # 获取 24h 统计数据
        try:
            meta_resp = _info_with_retry(s, {"type": "metaAndAssetCtxs"}, None)
            meta_ctx = {}
            if isinstance(meta_resp, list) and len(meta_resp) >= 2:
                universe = meta_resp[0].get("universe", [])
                ctxs = meta_resp[1]
                for i, m in enumerate(universe):
                    if m.get("name") == symbol and i < len(ctxs):
                        meta_ctx = ctxs[i]
                        break
        except Exception:
            meta_ctx = {}

        # 从 K线提取收盘价
        closes = []
        for c in candles:
            try:
                closes.append(float(c.get("c", 0)))  # 'c' = close price
            except Exception:
                pass

        if len(closes) >= 5:
            ma5 = sum(closes[-5:]) / 5
        else:
            ma5 = close_price
        if len(closes) >= 10:
            ma10 = sum(closes[-10:]) / 10
        else:
            ma10 = close_price
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
        else:
            ma20 = close_price

        # 计算价格位置（在最近20根K线的高低点中的位置）
        if len(closes) >= 20:
            high_20 = max(closes[-20:])
            low_20 = min(closes[-20:])
            if high_20 > low_20:
                price_position = (close_price - low_20) / (high_20 - low_20)
            else:
                price_position = 0.5
        else:
            price_position = 0.5

        # 计算波动率（最近5根K线的标准差/均值）
        if len(closes) >= 5:
            avg = sum(closes[-5:]) / 5
            var = sum((c - avg) ** 2 for c in closes[-5:]) / 5
            vol = (var ** 0.5) / avg if avg > 0 else 0.3
        else:
            vol = 0.3

        # 计算动量方向
        if len(closes) >= 2:
            if closes[-1] > closes[-2]:
                momentum_direction = "UP"
            elif closes[-1] < closes[-2]:
                momentum_direction = "DOWN"
            else:
                momentum_direction = "FLAT"
        else:
            momentum_direction = "UP"

        # 计算趋势强度（MA 排列一致性）
        if ma5 > ma10 > ma20:
            trend_strength = 0.75
        elif ma5 < ma10 < ma20:
            trend_strength = 0.25
        else:
            trend_strength = 0.50

        # 四维评分（基于实时数据 + 24h 统计）
        # 供需评分：基于价格位置、趋势和未平仓合约
        prev_day_px = float(meta_ctx.get("prevDayPx", close_price))
        open_interest = float(meta_ctx.get("openInterest", 0))
        day_base_vlm = float(meta_ctx.get("dayBaseVlm", 0))
        funding = float(meta_ctx.get("funding", 0))

        # 价格相对前一日的变化
        day_change = (close_price - prev_day_px) / prev_day_px if prev_day_px > 0 else 0.0

        # 供需评分：价格上涨+未平仓增加=多头强势
        supply_demand_score = 0.5 + day_change * 5 + (trend_strength - 0.5) * 0.3
        if funding > 0:
            supply_demand_score += 0.05  # 正资金费率=多头愿意付费
        else:
            supply_demand_score -= 0.05
        supply_demand_score = max(0.1, min(0.9, supply_demand_score))

        # 技术评分：基于 MA 排列、动量和日变化
        if ma5 > ma10 > ma20 and momentum_direction == "UP":
            technical_score = 0.70
        elif ma5 < ma10 < ma20 and momentum_direction == "DOWN":
            technical_score = 0.30
        elif day_change > 0.01:
            technical_score = 0.65
        elif day_change < -0.01:
            technical_score = 0.35
        else:
            technical_score = 0.50

        # 资金流评分：基于可用保证金比例和成交量
        if equity > 0:
            capital_ratio = avail / equity
            capital_flow_score = 0.5 + (capital_ratio - 0.5) * 0.3
        else:
            capital_flow_score = 0.50
        # 成交量大=资金活跃
        if day_base_vlm > 10000:
            capital_flow_score += 0.05
        capital_flow_score = max(0.1, min(0.9, capital_flow_score))

        # 情绪评分：基于波动率反向映射 + 资金费率
        sentiment_score = max(0.2, min(0.8, 0.6 - vol * 1.5))
        if funding > 0.0001:
            sentiment_score = min(0.8, sentiment_score + 0.1)  # 正资金费率=市场偏多
        elif funding < -0.0001:
            sentiment_score = max(0.2, sentiment_score - 0.1)  # 负资金费率=市场偏空

        # 成交量比率（简化）
        volume_ratio = 1.0

        return {
            "symbol": symbol,
            "supply_demand_score": round(supply_demand_score, 4),
            "technical_score": round(technical_score, 4),
            "capital_flow_score": round(capital_flow_score, 4),
            "sentiment_score": round(sentiment_score, 4),
            "trend_strength": round(trend_strength, 4),
            "volatility": round(vol, 4),
            "volume_ratio": volume_ratio,
            "price_position": round(price_position, 4),
            "ma5": round(ma5, 4),
            "ma10": round(ma10, 4),
            "ma20": round(ma20, 4),
            "momentum_direction": momentum_direction,
            "close_price": close_price,
            "entry_price": close_price,
            "equity": equity,
            "avail": avail,
            "has_position": has_position,
            "pos_size": pos_size,
            "pos_entry": pos_entry,
            "pos_upnl": pos_upnl,
        }
    except Exception as e:
        return None

def dreamos_v2_cycle(symbol="BTC"):
    """执行 DreamOS V2 六层闭环完整周期"""
    try:
        orch = _get_dreamos_v2()
        market_data = _fetch_market_data_for_v2(symbol)
        if not market_data:
            # 使用合理的默认值
            market_data = {
                "symbol": symbol,
                "supply_demand_score": 0.55,
                "technical_score": 0.50,
                "capital_flow_score": 0.50,
                "sentiment_score": 0.45,
                "trend_strength": 0.60,
                "volatility": 0.35,
                "volume_ratio": 1.0,
                "price_position": 0.50,
                "ma5": 0.0, "ma10": 0.0, "ma20": 0.0,
                "momentum_direction": "UP",
                "close_price": 0.0,
                "entry_price": 0.0,
            }
        result = orch.run_cycle(market_data)
        return result
    except Exception as e:
        return {"error": str(e)}

def dreamos_v2_status():
    """获取 DreamOS V2 编排器状态"""
    try:
        orch = _get_dreamos_v2()
        status = orch.get_status()
        ctx = orch.reviewer.get_cognitive_context()
        return {
            "orchestrator": status,
            "cognitive": ctx,
            "timestamp": datetime.datetime.now().isoformat() + "Z",
        }
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
    # 本机使用 OKX 实盘（云端 OKX 不可用时才切 Hyperliquid）。
    # 调用 get_yijing_okx_state() 获取易经策略 OKX 账户的持仓和余额。
    okx_positions = []
    okx_balance = {}
    try:
        okx_state = get_yijing_okx_state()
        okx_balance = {
            "total_eq": okx_state.get("total_equity", 0),
            "avail": okx_state.get("perp_avail", 0),
        }
        # OKX 持仓（perp_positions 即主账户持仓）
        for p in (okx_state.get("perp_positions") or []):
            size = float(p.get("size", 0) or 0)
            if abs(size) < 1e-12:
                continue
            okx_positions.append({
                "coin": p.get("coin", ""),
                "inst_id": f"{p.get('coin', '')}-USDT-SWAP",
                "direction": "long" if size > 0 else "short",
                "entry_price": float(p.get("entry_px", 0) or 0),
                "pos_size": abs(size),
                "upl": float(p.get("upnl", 0) or 0),
                "upl_ratio": 0,
                "mark_px": 0,
                "leverage": str(p.get("leverage", "")),
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
    okx_total_eq = float(okx_balance.get("total_eq", okx_balance.get("eq", 0)) or 0) if live_ok else None

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
    # 策略可用资金 = 初始资金 + 累计盈亏（策略自身预算口径）
    strategy_avail = current_balance
    # OKX 账户可用保证金（账户级，仅供参考）
    account_avail = okx_avail
    # OKX 账户总权益（账户级，仅供参考）
    account_total_eq = okx_total_eq

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
        # 策略级：策略自身可用资金 = 初始资金 + 盈亏（主显示）
        "avail_balance": round(strategy_avail, 2),
        "strategy_avail": round(strategy_avail, 2),
        # 账户级：OKX 账户可用保证金（参考显示，标注"账户可用保证金"）
        "account_avail": round(account_avail, 2) if account_avail is not None else None,
        "account_total_eq": round(account_total_eq, 2) if account_total_eq is not None else None,
        # 向后兼容：旧命名字段保留，值为策略级口径（而非账户级）
        # avail_balance 已改为 strategy_avail，与 current_balance 一致
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
    # OKX 账户级可用保证金（参考）
    account_avail = None
    # OKX 账户级总权益（参考）
    account_total_eq = None
    current_okx_eq = None

    try:
        V15_DIR = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略")
        sys.path.insert(0, str(V15_DIR / "lib"))
        from capital_manager import get_account_balance, get_current_positions
        balance = get_account_balance()
        if balance.get("ok"):
            live_ok = True
            current_okx_eq = float(balance.get("total_eq", 0) or 0)
            account_avail = float(balance.get("avail_balance", 0) or 0)
            account_total_eq = current_okx_eq
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

    # 策略可用资金 = 初始资金 + 累计盈亏（策略自身预算口径，主显示）
    strategy_avail = current_balance

    return {
        "strategy": "v15_martin",
        "strategy_name": "V15 经典马丁策略",
        "initial_capital": V15_INITIAL_CAPITAL,
        "baseline_date": baseline.get("baseline_date"),
        "baseline_okx_eq": round(baseline_eq, 2) if baseline_eq is not None else None,
        "baseline_note": baseline_note,
        "current_balance": round(current_balance, 2) if current_balance is not None else None,
        # 策略级：策略自身可用资金 = 初始资金 + 盈亏（主显示）
        "avail_balance": round(strategy_avail, 2) if strategy_avail is not None else None,
        "strategy_avail": round(strategy_avail, 2) if strategy_avail is not None else None,
        # 账户级：OKX 账户可用保证金（参考显示，标注"账户可用保证金"）
        "account_avail": round(account_avail, 2) if account_avail is not None else None,
        "account_total_eq": round(account_total_eq, 2) if account_total_eq is not None else None,
        # 向后兼容：旧 avail_balance 已改为策略级口径，而非账户级
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


def _refresh_global_trade_stats_async():
    """后台异步刷新 global-trade-stats 缓存（遍历 16 万案例文件较重，避免阻塞请求线程）"""
    try:
        data = get_global_trade_stats()
        _cache_set("global_trade_stats", data)
    except Exception:
        pass


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
    fail_streak = 0
    while True:
        try:
            data = get_yijing_state()
            # 仅缓存成功结果（非 error），避免单次超时覆盖掉上次的有效数据
            if isinstance(data, dict) and "error" not in data:
                _cache_set("yijing", data)
        except Exception:
            pass
        okx_ok = True
        try:
            acct = get_yijing_account_overview()
            _cache_set("yijing_account", acct)
            # OKX 不可达时 live_ok=False，连续失败则退避拉长间隔
            if isinstance(acct, dict) and acct.get("live_error") and not acct.get("live_ok"):
                okx_ok = False
        except Exception:
            okx_ok = False
        if okx_ok:
            fail_streak = 0
            sleep_s = interval
        else:
            fail_streak += 1
            # 指数退避：60→120→180→240→300s，封顶 5 分钟，避免反复重试耗 CPU
            sleep_s = min(interval * min(fail_streak, 5), 300)
        time.sleep(sleep_s)


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
        threading.Thread(target=_bg_refresh_l4_status, args=(60,), daemon=True),
    ]
    for t in threads:
        t.start()
    return threads


# ── 市场形态预测 / BCRM 2.0 参数输出 ──────────────────────────────────────────
# 直接调用 bcrm2.ParameterMapper，避免 HTTP 依赖 8092 Flask 服务
_BCRM2_L4_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4"
if _BCRM2_L4_DIR not in sys.path:
    sys.path.insert(0, _BCRM2_L4_DIR)

_MORPH_CACHE = {"key": None, "ts": 0, "data": None}
_MORPH_TTL = 60  # 秒


def get_morph_params(symbol: str = "BTCUSDT"):
    """返回 ParameterMapper 输出：6 全局参数 + 5 板块权重 + identity 基线。

    结构与 8092 Flask 的 /regime/evolution/params 完全一致，确保双前端数据等价。
    """
    cache_key = f"morph_{symbol}"
    now = time.time()
    if (_MORPH_CACHE["key"] == cache_key
            and _MORPH_CACHE["data"] is not None
            and now - _MORPH_CACHE["ts"] < _MORPH_TTL):
        return _MORPH_CACHE["data"]

    try:
        from bcrm2.run_evolution_pipeline import get_storage, _DEFAULT_IDENTITY_BETAS
        from bcrm2.parameter_mapper import ParameterMapper

        storage = get_storage()
        snapshot = storage.get_snapshot(symbol)
        if snapshot is None:
            return {"ok": False, "error": f"symbol={symbol} 无 snapshot，请先运行 run_evolution_pipeline --sqlite-db"}

        L = float(snapshot.get("level_smooth", 0.0))
        T = float(snapshot.get("trend_smooth", 0.0))
        C = float(snapshot.get("consensus", 0.0))

        pm = ParameterMapper()
        global_params = pm.map_global_parameters(L, T, C)
        _sw_full = pm.map_sector_weights(L, T, C, sector_betas=_DEFAULT_IDENTITY_BETAS)
        sector_weights = _sw_full.get("weights", _sw_full) if isinstance(_sw_full, dict) else _sw_full

        identity_global = pm.map_global_parameters(0.0, 0.0, 0.0)
        _isw_full = pm.map_sector_weights(0.0, 0.0, 0.0, sector_betas=_DEFAULT_IDENTITY_BETAS)
        identity_sector = _isw_full.get("weights", _isw_full) if isinstance(_isw_full, dict) else _isw_full

        global_list = [
            {
                "name": name,
                "lo": round(lo, 6),
                "hi": round(hi, 6),
                "center": round((lo + hi) / 2.0, 6),
                "bandwidth": round(hi - lo, 6),
                "identity_center": round((identity_global[name][0] + identity_global[name][1]) / 2.0, 6),
            }
            for name, (lo, hi) in global_params.items()
        ]

        def _safe_sector(sw: dict, n: str, default: float) -> float:
            if isinstance(sw, dict):
                if n in sw:
                    return float(sw[n])
                if "weights" in sw and isinstance(sw["weights"], dict) and n in sw["weights"]:
                    return float(sw["weights"][n])
            return default
        sector_list = [
            {
                "name": name,
                "weight": round(_safe_sector(sector_weights, name, 1.0/5.0), 6),
                "identity_weight": round(_safe_sector(identity_sector, name, 1.0/5.0), 6),
            }
            for name in ("defi", "ai", "rwa", "meme", "l2")
        ]
        # 附加：前端 tab 需要展示板块级 tp/sl 乘数（T3 扩展，形态→止盈止损分别作用）
        if isinstance(_sw_full, dict):
            extra = {}
            if "sector_tp_mult" in _sw_full:
                extra["sector_tp_mult"] = {k: round(float(v),6) for k,v in _sw_full["sector_tp_mult"].items()}
            if "sector_sl_mult" in _sw_full:
                extra["sector_sl_mult"] = {k: round(float(v),6) for k,v in _sw_full["sector_sl_mult"].items()}
            if extra:
                for s in sector_list:
                    if "sector_tp_mult" in extra:
                        s["tp_mult"] = extra["sector_tp_mult"].get(s["name"])
                    if "sector_sl_mult" in extra:
                        s["sl_mult"] = extra["sector_sl_mult"].get(s["name"])

        data = {
            "ok": True,
            "symbol": symbol,
            "snapshot_t": snapshot.get("t", ""),
            "inputs": {
                "level_smooth": round(L, 4),
                "trend_smooth": round(T, 4),
                "consensus": round(C, 4),
            },
            "global_params": global_list,
            "sector_weights": sector_list,
            "sector_weights_sum": round(sum(sector_weights.values()), 6),
            "identity": {
                "global_params": [
                    {
                        "name": name,
                        "lo": round(lo, 6),
                        "hi": round(hi, 6),
                        "center": round((lo + hi) / 2.0, 6),
                    }
                    for name, (lo, hi) in identity_global.items()
                ],
                "sector_weights": [
                    {"name": name, "weight": round(float(identity_sector[name]), 6)}
                    for name in ("defi", "ai", "rwa", "meme", "l2")
                ],
            },
        }
        _MORPH_CACHE.update(key=cache_key, ts=now, data=data)
        return data
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


_MORPH_CYCLE_CACHE = {"key": None, "ts": 0, "data": None}
_MORPH_CYCLE_TTL = 120  # 秒
_MORPH_METRICS_TTL = 60   # 秒
_MORPH_METRICS_CACHE = {"key": None, "ts": 0, "data": None}
_MORPH_PREDICTOR_SINGLETON = None  # MorphCyclePredictor 单例


def _get_predictor():
    """延迟加载 Predictor 单例（首次请求时构造）。"""
    global _MORPH_PREDICTOR_SINGLETON
    if _MORPH_PREDICTOR_SINGLETON is not None:
        return _MORPH_PREDICTOR_SINGLETON
    try:
        from bcrm2.run_evolution_pipeline import get_storage
        from bcrm2.morph_cycle_predictor import MorphCyclePredictor
        _MORPH_PREDICTOR_SINGLETON = MorphCyclePredictor(get_storage())
        return _MORPH_PREDICTOR_SINGLETON
    except Exception:
        return None


def _get_correction_cache_tag(symbol: str, predictor) -> str:
    """把「上次修正时间戳」加入 cache key 后缀，使修正后缓存自动失效。"""
    try:
        if predictor is not None and hasattr(predictor, "storage"):
            state = predictor.storage.get_correction_state(symbol) or {}
            ts = state.get("last_corrected_at") or ""
            count = state.get("correction_count", 0)
            return f"corr@{ts}#{count}"
    except Exception:
        pass
    return "corr@none"


def get_morph_cycle(symbol: str = "BTCUSDT", hist_days: int = 60, forecast_days: int = 20):
    """市场形态周期曲线（Phase A：Predictor.predict()，预测前自动回填+修正，冷却 23h）。"""
    predictor = _get_predictor()
    tag = _get_correction_cache_tag(symbol, predictor)
    cache_key = f"cycle_{symbol}_{hist_days}_{forecast_days}_{tag}"
    now = time.time()
    if (_MORPH_CYCLE_CACHE["key"] == cache_key
            and _MORPH_CYCLE_CACHE["data"] is not None
            and now - _MORPH_CYCLE_CACHE["ts"] < _MORPH_CYCLE_TTL):
        return _MORPH_CYCLE_CACHE["data"]

    try:
        if predictor is None:
            return {"ok": False, "error": "无法构造 MorphCyclePredictor，请检查 bcrm2 模块"}
        result = predictor.predict(symbol, hist_days=hist_days, forecast_days=forecast_days)
        if result.get("ok"):
            # Predictor 可能在 predict() 内部触发了自动修正 → tag 可能已变化 → 用最新 tag 存缓存
            latest_tag = _get_correction_cache_tag(symbol, predictor)
            final_key = f"cycle_{symbol}_{hist_days}_{forecast_days}_{latest_tag}"
            _MORPH_CYCLE_CACHE.update(key=final_key, ts=now, data=result)
        return result
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


def get_morph_metrics(symbol: str = "BTCUSDT", lookback: int = 30):
    """返回预测修正指标（MAE / RMSE / 分 horizon / 修正状态 / 误差历史序列）。"""
    cache_key = f"metrics_{symbol}_{lookback}"
    now = time.time()
    if (_MORPH_METRICS_CACHE["key"] == cache_key
            and _MORPH_METRICS_CACHE["data"] is not None
            and now - _MORPH_METRICS_CACHE["ts"] < _MORPH_METRICS_TTL):
        return _MORPH_METRICS_CACHE["data"]
    try:
        predictor = _get_predictor()
        if predictor is None:
            return {"ok": False, "error": "无法构造 MorphCyclePredictor"}
        metrics = predictor.get_correction_metrics(symbol, lookback=lookback)
        data = {"ok": True, "symbol": symbol, "metrics": metrics}
        _MORPH_METRICS_CACHE.update(key=cache_key, ts=now, data=data)
        return data
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


def trigger_morph_correct(symbol: str = "BTCUSDT", min_samples: int = 3):
    """触发一次误差回填 + 在线学习修正（手动触发）。"""
    try:
        predictor = _get_predictor()
        if predictor is None:
            return {"ok": False, "error": "无法构造 MorphCyclePredictor"}
        result = predictor.evaluate_and_correct(symbol, min_filled_samples=min_samples)
        # 修正后清缓存，下一次请求走新参数
        global _MORPH_CYCLE_CACHE, _MORPH_METRICS_CACHE
        _MORPH_CYCLE_CACHE = {"key": None, "ts": 0, "data": None}
        _MORPH_METRICS_CACHE = {"key": None, "ts": 0, "data": None}
        return {"ok": True, "result": result}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


def get_cycle_bounds(symbol: str = "BTCUSDT"):
    """返回大周期对小周期的弹性边界参数（Spec §3bis.7）。"""
    try:
        from bcrm2.morph_cycle_predictor import cycle4y_theory
        predictor = _get_predictor()
        if predictor is None:
            return {"ok": False, "error": "无法构造 MorphCyclePredictor"}
        storage = predictor.storage
        anchor_state = storage.get_anchor_state(symbol)
        anchor_overrides = anchor_state["anchor_overrides"] if anchor_state else {}
        cycle_4y = cycle4y_theory(today=None, samples=365, anchor_overrides=anchor_overrides)
        bounds = predictor._interp_cycle_bounds(cycle_4y["t_rel_current"])
        return {"ok": True, "symbol": symbol, "cycle_4y": cycle_4y, "bounds": bounds}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


def _get_shadow_logger():
    """构造 ShadowLogger 实例（用于 /api/shadow/report）。

    复用 _get_predictor() 的 storage，避免重复 DB 连接。
    """
    if ShadowLogger is None:
        return None
    predictor = _get_predictor()
    if predictor is None:
        return None
    storage = predictor.storage
    from bcrm2.parameter_mapper import ParameterMapper
    mapper = ParameterMapper()
    return ShadowLogger(storage, predictor, mapper)


def get_shadow_report(symbol: str = "BTC", days: int = 7):
    """返回 Shadow 影子模式评估报告。

    开关关闭时返回 ok=False；开启时返回 ok=True 和 report。
    """
    try:
        if not SHADOW_LOGGER_ENABLED:
            return {"ok": False, "error": "ShadowLogger 未启用（SHADOW_LOGGER_ENABLED=False）"}

        logger = _get_shadow_logger()
        if logger is None:
            return {"ok": False, "error": "无法构造 ShadowLogger，请检查 bcrm2 模块"}

        report = logger.get_comparison_report(symbol, days)
        return {"ok": True, "report": report}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


# ================================================================
# Phase C: α blend 前瞻参数上线 API
# ================================================================

_rollout_manager = None  # 全局 RolloutManager 实例（懒加载）


def _get_rollout_manager():
    """获取全局 RolloutManager 实例（懒加载）。"""
    global _rollout_manager
    if _rollout_manager is not None:
        return _rollout_manager
    try:
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        import os
        state_path = Path(os.environ.get(
            "V15_AI_ROLLOUT_STATE_PATH",
            "data/alpha_rollout_state.json",
        ))
        _rollout_manager = RolloutManager(state_path=state_path)
        return _rollout_manager
    except Exception:
        return None


def get_alpha_status() -> dict:
    """返回当前 α blend 上线状态。

    Returns:
        开关关闭时: {"ok": False, "error": "AlphaBlend 未启用"}
        开关开启时: {"ok": True, "status": {...}}
    """
    if not ALPHA_BLEND_ENABLED:
        return {"ok": False, "error": "AlphaBlend 未启用（ALPHA_BLEND_ENABLED=False）"}
    mgr = _get_rollout_manager()
    if mgr is None:
        return {"ok": False, "error": "无法构造 RolloutManager，请检查 bcrm2 模块"}
    return {"ok": True, "status": mgr.get_status()}


def promote_alpha() -> dict:
    """提升 α（步长 0.1，上限 0.5），并持久化状态。"""
    if not ALPHA_BLEND_ENABLED:
        return {"ok": False, "error": "AlphaBlend 未启用"}
    mgr = _get_rollout_manager()
    if mgr is None:
        return {"ok": False, "error": "无法构造 RolloutManager"}
    try:
        new_alpha = mgr.promote()
        mgr.save()
        return {"ok": True, "new_alpha": new_alpha, "status": mgr.get_status()}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


def rollback_alpha() -> dict:
    """降低 α（步长 0.1，不下穿 0），并持久化状态。"""
    if not ALPHA_BLEND_ENABLED:
        return {"ok": False, "error": "AlphaBlend 未启用"}
    mgr = _get_rollout_manager()
    if mgr is None:
        return {"ok": False, "error": "无法构造 RolloutManager"}
    try:
        new_alpha = mgr.rollback()
        mgr.save()
        return {"ok": True, "new_alpha": new_alpha, "status": mgr.get_status()}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


# ── H3：FMA 弹簧力场 5态差异化过滤 渐进开关 API（与 polling_trader 共享 phase_c_rollout_state.json）
_FMA_ROLLOUT_MGR_CACHE: dict = {"mgr": None}


def _get_fma_rollout_mgr():
    """获取/懒加载 FMA 专属 RolloutManager（使用与 polling_trader AB闸门口 一致的 state_path：data/phase_c_rollout_state.json）"""
    if _FMA_ROLLOUT_MGR_CACHE["mgr"] is not None:
        return _FMA_ROLLOUT_MGR_CACHE["mgr"]
    try:
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        import os
        state_path = Path(os.environ.get(
            "PHASE_C_ROLLOUT_STATE",
            "data/phase_c_rollout_state.json",
        ))
        mgr = RolloutManager(state_path=state_path)
        _FMA_ROLLOUT_MGR_CACHE["mgr"] = mgr
        return mgr
    except Exception as e:
        import traceback
        _FMA_ROLLOUT_MGR_CACHE["_err"] = f"{e} | {traceback.format_exc(limit=1)}"
        return None


def fma_status() -> dict:
    mgr = _get_fma_rollout_mgr()
    if mgr is None:
        return {"ok": False, "error": _FMA_ROLLOUT_MGR_CACHE.get("_err", "无法构造 RolloutManager")}
    return {"ok": True, **mgr.get_status()}


def fma_set(enabled: bool, reason: str = "API手动切换") -> dict:
    mgr = _get_fma_rollout_mgr()
    if mgr is None:
        return {"ok": False, "error": _FMA_ROLLOUT_MGR_CACHE.get("_err", "无法构造 RolloutManager")}
    prev = bool(getattr(mgr, "fma_enabled", False))
    changed = mgr.set_fma_enabled(bool(enabled), reason=reason)
    mgr.save()
    return {"ok": True, "changed": bool(changed),
            "prev_enabled": prev, "new_enabled": bool(mgr.fma_enabled),
            "status": mgr.get_status()}


def fma_eval_now(days: int = 7) -> dict:
    """强制立即执行一次 FMA 渐进评估（忽略 20h 冷却期）。"""
    mgr = _get_fma_rollout_mgr()
    if mgr is None:
        return {"ok": False, "error": _FMA_ROLLOUT_MGR_CACHE.get("_err", "无法构造 RolloutManager")}
    # 拉 7 天所有币种 shadow log
    all_records: list = []
    try:
        from bcrm2.run_evolution_pipeline import get_storage
        storage = get_storage()
        for sym in ["BTC", "SOL", "XAU", "XAG", "NVDA", "GOOGL", "AMZN",
                    "MU", "SNDK", "SPCX", "OKB", "HYPE", "PUMP", "UNI", "SKHYNIX", "ETH"]:
            try:
                all_records.extend(storage.get_shadow_log(sym, days=days))
            except Exception:
                continue
    except Exception as _e:
        import traceback
        return {"ok": False, "error": f"shadow log 加载失败: {_e}", "traceback": traceback.format_exc()}
    prev = bool(mgr.fma_enabled)
    result = mgr.evaluate_fma_toggle(all_records)
    mgr.save()
    return {"ok": True,
            "prev_enabled": prev,
            "new_enabled": bool(mgr.fma_enabled),
            "records_pulled": len(all_records),
            "evaluation": result,
            "status": mgr.get_status()}


# ── T6：Enable Inject 开关持久化 ────────────────────────────────
_INJECT_STATE_PATH: Path | None = None
_INJECT_RUNTIME: dict = {"enabled": None}  # None 表示尚未从文件加载


def _inject_state_path() -> Path:
    global _INJECT_STATE_PATH
    if _INJECT_STATE_PATH is None:
        import os
        _INJECT_STATE_PATH = Path(os.environ.get(
            "V15_AI_INJECT_STATE_PATH",
            "data/enable_inject_state.json",
        ))
    return _INJECT_STATE_PATH


def _load_inject_state() -> bool:
    """首次读取：从磁盘文件加载（默认 False = 字节等价的安全模式）。"""
    if _INJECT_RUNTIME["enabled"] is not None:
        return bool(_INJECT_RUNTIME["enabled"])
    fp = _inject_state_path()
    try:
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            enabled = bool(data.get("enabled", False))
        else:
            enabled = False
            # 首次启动写默认值
            try:
                fp.parent.mkdir(parents=True, exist_ok=True)
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump({"enabled": False, "created_at": time.time()}, f,
                              ensure_ascii=False, indent=2)
            except Exception:
                pass
    except Exception:
        enabled = False
    _INJECT_RUNTIME["enabled"] = enabled
    return enabled


def _save_inject_state(enabled: bool) -> None:
    _INJECT_RUNTIME["enabled"] = bool(enabled)
    fp = _inject_state_path()
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({
                "enabled": bool(enabled),
                "updated_at": time.time(),
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_enable_inject_status() -> dict:
    """返回当前 enable_inject（融合层注入）开关状态。"""
    enabled = _load_inject_state()
    return {
        "ok": True,
        "enabled": enabled,
        "note": "False=完全基线字节等价，True=AI 注入 (T4 融合层生效)",
    }


def set_enable_inject(enabled: bool) -> dict:
    """设置 enable_inject 开关并持久化。"""
    try:
        _save_inject_state(bool(enabled))
        return {
            "ok": True,
            "enabled": bool(enabled),
            "note": "已持久化，下次轮询周期自动生效（进程重启也保留）",
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


# ── T7：双基线评估框架（静态基线 + 动态基线）───────────────────
# 静态基线（v15 策略）：regime 查表，不注入任何 AI 参数 → baseline_*
# 动态基线（当前版本）：当前 enable_inject + alpha_blend 下的 effective_*
# 版本晋升规则：
#   1. AI 版（ai_*）在样本窗口内：
#      - 全局仓位偏差绝对值 ≤ 0.35（不超过 ±35% 激进/保守）
#      - 止盈止损乘数整体分布与 baseline 在同一数量级（0.5×~2.0× 区间内）
#      - 阈值修改方向与 forecast 方向一致性 ≥ 60%
#   2. 比静态基线更好：样本内「激进程度」≤ 125% baseline（或更保守）
#   3. 比动态基线更好：若当前已是 AI 版，新候选必须 ≥ 旧版得分 × 1.05（5% 改善门槛）
#   通过则 allow_promotion=True；否则 False，附带原因列表。

def _shadow_logs_window(days: int) -> list:
    """从 evolution.db 中读取 shadow_param_log 表最近 N 天记录。"""
    try:
        sys.path.insert(0, str(BASE_DIR / "scripts" / "memory_l4"))
        from bcrm2.storage import EvolutionStorageSQLite
        storage = EvolutionStorageSQLite(str(
            BASE_DIR / "scripts" / "memory_l4" / "data" / "evolution.db"
        ))
        try:
            records = storage.get_shadow_log(None, days)  # None=all symbols
        except TypeError:
            # 如果接口只支持 symbol 必传，再兜底 BTC 拉一次 + 其他尝试
            records = storage.get_shadow_log("BTC", days)
        return records or []
    except Exception:
        return []


def _agg_scores(records: list) -> dict:
    """给 shadow records 窗口打分：返回 ai_vs_static / ai_vs_dynamic 得分。"""
    if not records:
        return {"n": 0}
    # 提取三值字段
    pos_diffs_vs_static: list = []   # ai_pos / baseline_pos - 1
    pos_diffs_vs_dynamic: list = []  # ai_pos / effective_pos - 1
    thr_consistency: list = []       # 阈值与 L 方向一致
    tp_inside_ratio: list = []
    sl_inside_ratio: list = []
    for r in records:
        b_pos = float(r.get("baseline_pos_mult") or r.get("reactive_pos_mult") or 1.0)
        a_pos = r.get("ai_pos_mult")
        e_pos = r.get("effective_pos_mult")
        if a_pos is not None and b_pos and abs(b_pos) > 1e-9:
            pos_diffs_vs_static.append(float(a_pos) / b_pos - 1.0)
        if a_pos is not None and e_pos:
            try:
                pos_diffs_vs_dynamic.append(float(a_pos) / float(e_pos) - 1.0)
            except (TypeError, ZeroDivisionError):
                pass
        # tp/sl 范围约束检查 (0.5×~2×)
        for k_v, k_b, buf in [("ai_tp_mult", "baseline_tp_mult", tp_inside_ratio),
                              ("ai_sl_mult", "baseline_sl_mult", sl_inside_ratio)]:
            v = r.get(k_v)
            b = r.get(k_b) or r.get(f"reactive_{k_b.split('_',1)[1]}")
            if v is None or b is None:
                continue
            try:
                ratio = float(v) / float(b)
            except (TypeError, ZeroDivisionError):
                continue
            buf.append(1.0 if 0.5 <= ratio <= 2.0 else 0.0)
        # 阈值方向一致性：forecast_L>=0 且 ai_threshold_mult <= baseline 则一致（降低门槛）
        fL = r.get("forecast_L")
        b_thr = float(r.get("baseline_threshold_mult") or r.get("reactive_threshold") or 1.0)
        a_thr = r.get("ai_threshold_mult")
        if fL is not None and a_thr is not None:
            try:
                fL = float(fL)
                a_thr = float(a_thr)
                ok = ((fL >= 0 and a_thr <= b_thr)
                      or (fL < 0 and a_thr >= b_thr))
                thr_consistency.append(1.0 if ok else 0.0)
            except (TypeError, ValueError):
                pass

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    def _absmean(xs):
        return round(sum(abs(x) for x in xs) / len(xs), 4) if xs else None

    return {
        "n": len(records),
        "ai_vs_static_pos_bias_mean": _mean(pos_diffs_vs_static),
        "ai_vs_static_pos_bias_absmean": _absmean(pos_diffs_vs_static),
        "ai_vs_dynamic_pos_bias_mean": _mean(pos_diffs_vs_dynamic),
        "ai_vs_dynamic_pos_bias_absmean": _absmean(pos_diffs_vs_dynamic),
        "threshold_direction_consistency": _mean(thr_consistency),
        "tp_inside_05x_2x_ratio": _mean(tp_inside_ratio),
        "sl_inside_05x_2x_ratio": _mean(sl_inside_ratio),
    }


def evaluate_version_promotion(records: list,
                               min_samples: int = 30,
                               ) -> dict:
    """判断当前候选版本（ai_injected 计算）是否满足晋升条件。

    Returns:
        {
            "allow_promotion": bool,
            "static_baseline_pass": bool,   # 优于静态 v15 基线
            "dynamic_baseline_pass": bool,  # 优于当前动态基线（若当前是纯基线则自动 True）
            "reasons": [str, ...],
            "scores": {...},
        }
    """
    reasons: list = []
    scores = _agg_scores(records)
    n = scores.get("n", 0)

    # ── 样本量门槛 ──
    if n < min_samples:
        reasons.append(f"样本不足：{n} < {min_samples}（至少需要 {min_samples} 条 shadow 记录）")
        return {
            "allow_promotion": False,
            "static_baseline_pass": False,
            "dynamic_baseline_pass": False,
            "reasons": reasons,
            "scores": scores,
        }

    # ── 1. 静态基线（v15）通过条件 ──
    sb_pass = True
    pos_abs = scores.get("ai_vs_static_pos_bias_absmean")
    if pos_abs is None or pos_abs > 0.35:  # 整体仓位偏差 ≤ 35%
        sb_pass = False
        reasons.append(
            f"静态基线不通过：全局仓位 |偏差|={pos_abs} > 0.35（阈值 ±35%）"
        )
    thr_cons = scores.get("threshold_direction_consistency") or 0.0
    if thr_cons < 0.60:
        sb_pass = False
        reasons.append(
            f"静态基线不通过：阈值与方向一致性={thr_cons:.2%} < 60%"
        )
    tp_ok = scores.get("tp_inside_05x_2x_ratio") or 0.0
    sl_ok = scores.get("sl_inside_05x_2x_ratio") or 0.0
    if min(tp_ok, sl_ok) < 0.90:
        sb_pass = False
        reasons.append(
            f"静态基线不通过：TP/SL 在[0.5x,2x]区间率 tp={tp_ok:.2%} sl={sl_ok:.2%}，都需≥90%"
        )

    # ── 2. 动态基线通过条件（当前运行值 vs AI 注入值）：
    #    如果 enable_inject=False（当前纯基线）→ 动态 = 静态，只要静态过即可，动态条件 auto 通过
    #    如果 enable_inject=True → 要求 AI 相对 effective 偏差 ≤ 静态偏差的 80%（更优）
    db_pass = True
    cur_enabled = _load_inject_state()
    if cur_enabled:
        # 动态要求：ai_vs_dynamic 的 |仓位偏差| 必须 ≤ ai_vs_static 的 80% 且 ≤ 0.25
        dyn_abs = scores.get("ai_vs_dynamic_pos_bias_absmean") or 1.0
        sta_abs = pos_abs or 1.0
        if dyn_abs > 0.25 or dyn_abs > sta_abs * 0.80:
            db_pass = False
            reasons.append(
                f"动态基线不通过：候选 vs 当前版 |pos偏差|={dyn_abs}，"
                f"需 ≤ 0.25 且 ≤ 静态偏差×80%（静态偏差={sta_abs}）"
            )

    if sb_pass and db_pass:
        reasons.insert(0, f"双基线通过（n={n}），允许版本晋升")

    return {
        "allow_promotion": bool(sb_pass and db_pass),
        "static_baseline_pass": bool(sb_pass),
        "dynamic_baseline_pass": bool(db_pass),
        "reasons": reasons,
        "scores": scores,
        "current_enable_inject": cur_enabled,
        "min_samples": min_samples,
    }


def get_dual_baseline_report(days: int = 7) -> dict:
    """返回完整双基线评估报告（T7 对外 API）。"""
    records = _shadow_logs_window(days=days)
    promotion = evaluate_version_promotion(records)
    # 统计 enable_inject 历史比例（评估当前运行模式占比）
    enable_true = 0
    enable_false = 0
    for r in records:
        v = r.get("enable_inject")
        if v is True:
            enable_true += 1
        elif v is False:
            enable_false += 1
    inject_stats = {
        "enable_true": enable_true,
        "enable_false": enable_false,
        "inject_ratio": round(enable_true / max(enable_true + enable_false, 1), 4),
    }
    return {
        "ok": True,
        "days": days,
        "window_records": len(records),
        "inject_run_stats": inject_stats,
        "alpha_status": get_alpha_status(),
        "inject_status": get_enable_inject_status(),
        "evaluation": promotion,
    }


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
            cached = _cache_get("yijing_positions")
            if cached and (time.time() - cached["ts"] < 10):
                self._json(cached["data"])
            else:
                data = get_yijing_positions()
                _cache_set("yijing_positions", data)
                self._json(data)

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
                # 无缓存时返回降级数据，后台异步刷新避免遍历 16 万案例文件阻塞请求
                if not cached:
                    threading.Thread(target=_refresh_global_trade_stats_async, daemon=True).start()
                    self._json({"loading": True, "message": "交易统计加载中，请稍后刷新",
                                "systems": {}, "summary": {}})
                else:
                    # 缓存过期但仍有旧数据，先返回旧数据再后台刷新
                    threading.Thread(target=_refresh_global_trade_stats_async, daemon=True).start()
                    self._json(cached["data"])

        # ── API: L4 认知闭环状态仪表盘 ─────────────────────────────────────
        elif path == "/api/l4-status":
            cached = _cache_get("l4_status")
            if cached and (time.time() - cached["ts"] < 30):
                self._json(cached["data"])
            else:
                # 无缓存时返回降级数据，避免同步遍历 16 万案例文件阻塞请求
                # 后台线程 _bg_refresh_l4_status 会异步刷新缓存
                self._json({"loading": True, "message": "L4 状态加载中，请稍后刷新"})

        # ── API: DreamOS V2 六层闭环 ─────────────────────────────────────
        elif path == "/api/dreamos-v2/cycle":
            symbol = self._get_query_param("symbol") or "BTC"
            try:
                data = dreamos_v2_cycle(symbol)
                self._json(data)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/dreamos-v2/status":
            try:
                data = dreamos_v2_status()
                self._json(data)
            except Exception as e:
                self._json({"error": str(e)})

        # ── API: 市场形态预测 / BCRM 2.0 参数输出 ─────────────────────
        elif path == "/api/morph/params":
            symbol = (self._get_query_param("symbol") or "BTCUSDT").upper()
            self._json(get_morph_params(symbol))

        elif path == "/api/morph/cycle":
            symbol = (self._get_query_param("symbol") or "BTCUSDT").upper()
            hist_days = int(self._get_query_param("hist") or "60")
            forecast_days = int(self._get_query_param("forecast") or "20")
            self._json(get_morph_cycle(symbol, hist_days, forecast_days))

        elif path == "/api/morph/metrics":
            symbol = (self._get_query_param("symbol") or "BTCUSDT").upper()
            lookback = int(self._get_query_param("lookback") or "30")
            self._json(get_morph_metrics(symbol, lookback))

        elif path == "/api/morph/correct":
            symbol = (self._get_query_param("symbol") or "BTCUSDT").upper()
            min_samples = int(self._get_query_param("min") or "3")
            self._json(trigger_morph_correct(symbol, min_samples))

        elif path == "/api/morph/cycle_bounds":
            symbol = (self._get_query_param("symbol") or "BTCUSDT").upper()
            self._json(get_cycle_bounds(symbol))

        # ── API: Shadow 影子模式评估报告 ──────────────────────────────
        elif path == "/api/shadow/report":
            symbol = (self._get_query_param("symbol") or "BTC").upper()
            days = int(self._get_query_param("days") or "7")
            self._json(get_shadow_report(symbol, days))

        # ── API: Phase C α blend 状态查询 ────────────────────────────
        elif path == "/api/alpha/status":
            self._json(get_alpha_status())

        # ── API: Phase C α blend 提升 ────────────────────────────────
        elif path == "/api/alpha/promote":
            self._json(promote_alpha())

        # ── API: Phase C α blend 回退 ────────────────────────────────
        elif path == "/api/alpha/rollback":
            self._json(rollback_alpha())

        # ── API: H3 FMA 渐进开关（状态/开启/关闭/立即评估）────────────
        elif path == "/api/fma/status":
            self._json(fma_status())

        elif path == "/api/fma/on":
            reason = self._get_query_param("reason") or "HTTP /api/fma/on 手动开启"
            self._json(fma_set(True, reason=reason))

        elif path == "/api/fma/off":
            reason = self._get_query_param("reason") or "HTTP /api/fma/off 手动关闭"
            self._json(fma_set(False, reason=reason))

        elif path == "/api/fma/eval":
            days = int(self._get_query_param("days") or "7")
            self._json(fma_eval_now(days=days))

        # ── API: 健康检查（bcrm2 import 状态 + 基线模式核对）─────────
        elif path == "/api/baseline/health":
            self._json({
                "ok": True,
                "shadow_logger_imported": _sl_import_ok,
                "shadow_logger_enabled": bool(SHADOW_LOGGER_ENABLED),
                "param_mapper_imported": _pm_import_ok,
                "alpha_blend_enabled": bool(ALPHA_BLEND_ENABLED),
                "alpha_blend_max": float(ALPHA_BLEND_MAX),
                "default_alpha_blend": float(DEFAULT_ALPHA_BLEND),
                "baseline_equivalent": (
                    # alpha=0 且 enable_inject=false 时字节等价基线
                    float(DEFAULT_ALPHA_BLEND) == 0.0
                ),
            })

        # ── API: T6 Enable Inject 融合层开关状态查询 ─────────────────
        elif path == "/api/inject/status":
            self._json(get_enable_inject_status())

        # ── API: T7 双基线评估报告查询 ───────────────────────────────
        elif path == "/api/eval/baseline":
            try:
                days = int(self._get_query_param("days") or "7")
                self._json(get_dual_baseline_report(days=days))
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

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

        # ── T6: Enable Inject 融合层开关 ────────────────────────────
        elif path == "/api/inject/enable":
            self._json(set_enable_inject(True))

        elif path == "/api/inject/disable":
            self._json(set_enable_inject(False))

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
