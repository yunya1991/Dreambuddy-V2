"""拉取真实 BTC close 数据用于 Neural SDE 训练.

从 OKX 公开 API 分页拉取 1H K线 close 序列（~3000 条），
保存为 data/btc_close.json 供训练脚本使用.

使用方式:
  python3 -m dreambuddy_evolution.scripts.fetch_btc_close
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import requests

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"


def fetch_btc_closes(total: int = 3000) -> np.ndarray:
    """从 OKX 公开 API 分页拉取 BTC-USDT-SWAP 1H close 价格.

    Args:
        total: 目标 close 数量（OKX 单次最多 300 条 1H K线）

    Returns:
        升序 close 数组
    """
    inst_id = "BTC-USDT-SWAP"
    bar = "1H"
    batch_size = 300
    all_closes: list[float] = []
    before = ""  # 分页游标（OKX before 参数）

    # 代理设置
    proxies = {}
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if https_proxy:
        proxies["https"] = https_proxy
        proxies["http"] = https_proxy

    session = requests.Session()
    session.trust_env = False
    if proxies:
        session.proxies.update(proxies)

    fetched = 0
    while fetched < total:
        try:
            params: dict = {"instId": inst_id, "bar": bar, "limit": str(batch_size)}
            if before:
                params["before"] = before

            resp = session.get(OKX_CANDLES_URL, params=params, timeout=30)
            r = resp.json()

            if r.get("code") != "0":
                logger.warning("OKX 返回失败: %s", r.get("msg", ""))
                break

            raw_data = r.get("data", [])
            if not raw_data:
                break

            # OKX data 格式: [[ts, o, h, l, c, vol, ...], ...]
            # 降序(新→旧)
            batch_closes = [float(d[4]) for d in raw_data]
            all_closes.extend(batch_closes)
            fetched += len(batch_closes)

            # 更新游标（用最旧一条的 ts）
            oldest_ts = raw_data[-1][0]
            before = str(int(oldest_ts) - 1)
            logger.info("已拉取 %d / %d 条 close", fetched, total)
            time.sleep(0.5)  # 限速

        except Exception as e:
            logger.error("拉取异常: %s", e)
            break

    # OKX 返回降序(新→旧)，反转为升序(旧→新)
    all_closes.reverse()
    return np.array(all_closes, dtype=np.float64)


def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

    logger.info("=== 拉取 BTC-USDT 1H close 数据 ===")
    closes = fetch_btc_closes(total=3000)

    if len(closes) < 100:
        logger.error("拉取数据不足: %d 条（需要 ≥100）", len(closes))
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "btc_close.json"
    out_path.write_text(json.dumps(closes.tolist()), encoding="utf-8")
    logger.info("保存 %d 条 close → %s", len(closes), out_path)
    logger.info("价格范围: %.2f ~ %.2f", float(np.min(closes)), float(np.max(closes)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
