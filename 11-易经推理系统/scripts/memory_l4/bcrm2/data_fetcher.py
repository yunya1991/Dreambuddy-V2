"""
数据获取模块 — 从OKX获取K线历史数据

Phase 0: 优先从本地已有数据加载，没有则从OKX API拉取
"""

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd


def _get_okx_client():
    """获取OKX客户端（优先使用系统已有的okx_simulated）"""
    try:
        from ..okx_simulated import OKXSimulatedClient

        return OKXSimulatedClient()
    except Exception:
        pass
    try:
        from okx import OKXClient

        return OKXClient()
    except Exception:
        pass
    return None


def load_kline_from_local(
    symbol: str,
    timeframe: str = "1H",
    data_dir: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """从本地加载K线数据"""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent / "data" / "klines"
    else:
        data_dir = Path(data_dir)

    filepath = data_dir / f"{symbol}_{timeframe}.csv"

    if filepath.exists():
        df = pd.read_csv(filepath)
        if "timestamp" in df.columns:
            # Bug修复: 统一 UTC 时区，避免与其他来源数据的时区冲突
            ts = pd.to_datetime(df["timestamp"])
            if ts.dt.tz is None:
                ts = ts.dt.tz_localize("UTC")
            else:
                ts = ts.dt.tz_convert("UTC")
            df["timestamp"] = ts
            df = df.set_index("timestamp")
        elif "ts" in df.columns:
            ts = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df["timestamp"] = ts
            df = df.set_index("timestamp")
        else:
            # 用第一列当时间索引
            df = df.set_index(df.columns[0])
            ts = pd.to_datetime(df.index)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            df.index = ts
        df.index.name = "timestamp"
        return df
    return None


def fetch_okx_klines(
    symbol: str,
    bar: str = "1H",
    limit: int = 1000,
    max_pages: int = 5,
    after_ts: Optional[int] = None,
) -> pd.DataFrame:
    """
    从OKX获取K线数据

    Args:
        symbol: 交易对，如 BTC-USDT
        bar: K线周期: 1H, 4H, 1D 等
        limit: 每次请求的K线数量 (最大100)
        max_pages: 最大翻页次数
        after_ts: 分页锚点（毫秒）。传入本地最旧 bar 的 ts 时，只补更早历史，
                  用于断点续传补齐 30k 根长历史。

    Returns:
        DataFrame with columns: open, high, low, close, volume
        index = timestamp
    """
    # P0 修复：bcrm2.data_fetcher 里的 requests.get 直接 new 了一个匿名 Session，
    # 没有继承 OKXSimulatedClient.session.proxies 也没有读取 os.environ 代理设置，
    # 导致即使主进程配了 HTTPS_PROXY 仍然走直连 -> Host is down。
    import requests as _requests_mod

    def _build_session():
        s = _requests_mod.Session()
        s.trust_env = True  # 信任环境变量（如果设置了的话）
        proxies = {}
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        all_proxy = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        if https_proxy:
            proxies["https"] = https_proxy
        if http_proxy:
            proxies["http"] = http_proxy
        if all_proxy and not proxies:
            proxies["http"] = all_proxy
            proxies["https"] = all_proxy
        if not proxies:
            # 环境变量未配置时，尝试本地 Clash 默认端口（与 okx_simulated 保持一致）
            for port in (7890, 7891, 14122, 38324):
                try:
                    import socket as _sock

                    with _sock.create_connection(("127.0.0.1", port), timeout=0.3):
                        proxies = {
                            "http": f"http://127.0.0.1:{port}",
                            "https": f"http://127.0.0.1:{port}",
                        }
                        break
                except Exception:
                    continue
        if proxies:
            s.proxies = dict(proxies)
        else:
            s.proxies = {}
        return s

    all_data = []
    after = after_ts  # 分页锚点
    page_size = min(limit, 100)
    if after:
        print(f"  [data_fetcher] 断点续传: 只补更早于 {after} 的 K 线")

    _sess = None
    try:
        _sess = _build_session()
        for page in range(max_pages):
            try:
                url = "https://www.okx.com/api/v5/market/history-candles"
                # P4 修复：XAU/XAUT 在 OKX 上只有 SWAP 合约，没有现货 USDT 交易对，
                # 且 XAUT → XAU 规范化后（polling_trader 内）仍需在这里保持一致：
                # 先请求 {sym}-USDT，若返回 51001 (Instrument ID does not exist)
                # 则自动回退到 {sym}-USDT-SWAP 合约 K线（与 okx_simulated 的持仓/下单
                # 逻辑保持同一合约维度）。
                tried = []

                def _do_request(inst_id: str):
                    params = {
                        "instId": inst_id,
                        "bar": bar,
                        "limit": page_size,
                    }
                    if after:  # noqa: B023
                        params["after"] = str(after)  # noqa: B023
                    return _sess.get(url, params=params, timeout=10)  # noqa: B023

                def _request_with_retry(inst_id: str, attempts: int = 3):
                    """单页最多 3 次指数退避重试；51001 直接返回给候选回退逻辑。"""
                    last_json = {}
                    for k in range(attempts):
                        try:
                            r0 = _do_request(inst_id)
                            j0 = r0.json()
                            code = str(j0.get("code"))
                            if code == "0":
                                return r0, j0
                            last_json = j0
                            if code == "51001":  # instrument 不存在，换 SWAP 候选
                                return r0, j0
                            # 50011: 限频；其他可重试错误
                            time.sleep(1.0 * (2**k))
                        except Exception as e:  # noqa: BLE001
                            last_json = {"code": "EXC", "msg": str(e)}
                            time.sleep(1.0 * (2**k))
                    return None, last_json

                # 构造候选 instId 列表：现货 → SWAP
                base_symbol = (
                    symbol.upper().replace("-USDT", "").replace("USDT", "").replace("-SWAP", "")
                )
                candidates = [f"{base_symbol}-USDT", f"{base_symbol}-USDT-SWAP"]
                resp = None
                data = {}
                for inst_id in candidates:
                    r0, j0 = _request_with_retry(inst_id)
                    tried.append(f"{inst_id}->code={j0.get('code')}")
                    if r0 is not None and j0.get("code") == "0" and j0.get("data"):
                        resp = r0
                        data = j0
                        break
                    # 仅当 51001 / data 为空时继续尝试下一个
                    if str(j0.get("code")) not in ("51001", "0"):
                        data = j0
                        break
                if resp is None:
                    # 只在首次请求时打印尝试过的 instId 序列，后续页不重复打印
                    if after is None or page == 0:
                        print(f"  [data_fetcher] 候选 instId 尝试: {tried} last={data.get('code')}")
                    break

                candles = data.get("data", [])
                if not candles:
                    break

                all_data.extend(candles)

                # 设置下一页锚点 (最后一根K线的ts)
                after = candles[-1][0]

                if page and page % 50 == 0:
                    print(f"  [data_fetcher] 已翻页 {page}，累计 {len(all_data)} 根")

                if len(candles) < page_size:
                    break

                time.sleep(0.25)  # 限频

            except Exception as e:
                print(
                    f"  获取K线失败 (page {page+1}): {e}  proxies={_sess.proxies} "
                    f"已获取={len(all_data)}"
                )
                break
    finally:
        if _sess is not None:
            try:
                _sess.close()
            except Exception:
                pass

    if not all_data:
        return pd.DataFrame()

    # 解析数据
    # OKX K线格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    df = pd.DataFrame(
        all_data,
        columns=[
            "ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "vol_ccy",
            "vol_ccy_quote",
            "confirm",
        ],
    )

    # 类型转换
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["ts"] = df["ts"].astype(int)
    # Bug修复: 统一使用 UTC 时区，避免与其他数据拼接时 datetime64[ns] vs datetime64[ns, UTC] 错误
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df.sort_index()

    # P0 修复：只保留已收盘 K 线（OKX confirm=1），避免未收盘 bar 污染训练/推理
    try:
        _confirm = df["confirm"].astype(str)
        df = df[_confirm.isin(["1", "True", "true"])]
    except Exception:  # noqa: BLE001 字段缺失时保持原行为
        pass

    return df[["open", "high", "low", "close", "volume"]]


def save_klines(df: pd.DataFrame, symbol: str, timeframe: str, data_dir: Optional[str] = None):
    """保存K线到本地"""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent / "data" / "klines"
    else:
        data_dir = Path(data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    filepath = data_dir / f"{symbol}_{timeframe}.csv"
    df.to_csv(filepath)
    print(f"  已保存到: {filepath}")


_BAR_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1H": 3_600_000,
    "2H": 7_200_000,
    "4H": 14_400_000,
    "6H": 21_600_000,
    "12H": 43_200_000,
    "1D": 86_400_000,
    "1W": 604_800_000,
}


def _is_fresh(df: pd.DataFrame, timeframe: str, max_age_bars: int) -> bool:
    """判断本地缓存是否新鲜（最后一根 K 线距今不超过 max_age_bars 根）。"""
    dur = _BAR_MS.get(timeframe)
    if not dur or df is None or len(df) == 0:
        return True
    try:
        last = df.index[-1]
        ts_ms = int(last.timestamp() * 1000) if hasattr(last, "timestamp") else int(last)
    except Exception:  # noqa: BLE001
        return True
    return int(time.time() * 1000) - ts_ms <= dur * (max_age_bars + 1)


def get_klines(
    symbol: str,
    timeframe: str = "1H",
    use_cache: bool = True,
    refresh: bool = False,
    max_bars: int = 5000,
    max_age_bars: Optional[int] = None,
) -> pd.DataFrame:
    """
    获取K线数据 (统一入口)

    优先级: 本地缓存 → OKX API

    max_age_bars: 非 None 时启用新鲜度校验；本地缓存最后一根超过该 bar 数则强制拉取。
    """
    sym_usdt = symbol.replace("-USDT", "").replace("USDT", "")
    sym_key = f"{sym_usdt}-USDT"

    # 尝试本地加载（可选的 freshness 校验）
    if use_cache and not refresh:
        df = load_kline_from_local(sym_usdt, timeframe)
        if (
            df is not None
            and len(df) > 100
            and (max_age_bars is None or _is_fresh(df, timeframe, max_age_bars))
        ):
            print(f"  从本地加载: {len(df)}根K线")
            return df.tail(max_bars)

    old = load_kline_from_local(sym_usdt, timeframe) if use_cache else None

    # 本地已覆盖最新但长度不足时，从最旧 bar 继续向上游补历史（断点续传）
    after_ts = None
    if old is not None and len(old) > 0 and len(old) < max_bars and _is_fresh(old, timeframe, 2):
        after_ts = int(old.index[0].timestamp() * 1000)
        print(f"  本地已有 {len(old)} 根且最新，向上游补更早历史")

    # 从OKX拉取
    print(f"  从OKX获取 {sym_key} {timeframe} K线...")
    df = fetch_okx_klines(
        sym_usdt,
        bar=timeframe,
        limit=100,
        max_pages=max_bars // 100 + 1,
        after_ts=after_ts,
    )

    if len(df) > 0:
        print(f"  获取到 {len(df)}根K线")
        if use_cache:
            # 合并旧缓存再落盘，避免 freshness 刷新把长历史覆盖成短窗口
            if old is not None and len(old) > 0:
                df = pd.concat([old, df])
                df = df[~df.index.duplicated(keep="last")].sort_index()
            save_klines(df, sym_usdt, timeframe)
        return df.tail(max_bars)

    # 拉取失败：回退到本地旧缓存（避免整体 fail-closed）
    if old is not None and len(old) > 0:
        print(f"  OKX拉取失败，回退本地缓存: {len(old)}根K线")
        return old.tail(max_bars)
    return pd.DataFrame()
