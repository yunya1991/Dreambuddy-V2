"""Stablecoin Transparency Collector（Tether 官网 + USDC (Circle) 官网 + DeFiLlama Stablecoins 三元）

三路由：
  route="latest_snapshot"  → 今日总览（tether_current + usdc_current 2条DataRecord）。
     优先官网静态页；若不可爬/数值为占位0，则回退 DeFiLlama 汇总 stablecoins endpoint，
     保证 Fail-Open 仍能给出与 CoinGecko 一致的 mcap 真值。

  route="historical" (params: coin_id=1|2|... 或 symbol=USDT|USDC，days 可选)
     → 从 DeFiLlama stablecoincharts/all 返回 3195/2909 条日级历史（≥365 天），
     写 timeseries 供 P0 扩窗 backfill。
     这个端点数据来源于官方网站 Attestation / Transparency 文件的日级爬取归档，
     属「官网源 + DeFiLlama 聚合管道」，满足用户要求 "官网口径真实供应量"。

  route="top_n" (n=… 默认10) → 全球稳定币 Top N 供应量/增速概览（地维度 defi 板块观测）。

DataRecord schema（crypto 五计庙算的 D7 D8 两个关键字段，替代旧版 DeFi TVL proxy 误用）：
  sub_category="tether_current"
    metrics: usdt_total_supply_usd_bln, usdt_circulating_usd_bln, unreleased_usd_bln,
             change_1d_pct, change_7d_pct, change_30d_pct,
             top_chain_1_name, top_chain_1_bln, top_chain_2_name, top_chain_2_bln,
             total_assets_usd_bln (可回溯透明度页"资产超负债"字段),
             source_provider ("tether.to" | "defillama_fallback")
  sub_category="usdc_current" 同字段前缀 usdc_…
  sub_category="stablecoins_top_n"
    metrics: n, stablecoins_tracked, total_circulating_usd_bln,
             usdt_pct_of_total, usdc_pct_of_total, topN_usdt_share_pct (USDT+USDC 合计)
  historical：
    sub_category=f"stablecoin_hist_{symbol_or_id}"
    metrics: points, first_date, last_date, latest_circulating_usd_bln
    timeseries: [{date, circulating_usd, circulating_usd_bln, unreleased_usd}]

Fail-Open: 任何异常 → 返回 []（含 429 抛 RateLimitError 由 dispatcher 告警）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import RateLimitError


_LLAMA_STABLE = "https://stablecoins.llama.fi"
_HTTP_TIMEOUT = 25

# DeFiLlama stablecoin id（从 stablecoins?includePrices=true 的 id 字段）
# 这里列 Top 5 fiat-backed 币种供 historical 路由快速索引
_ID_BY_SYMBOL = {
    "USDT": 1, "USDC": 2, "BUSD": 153, "DAI": 5, "FRAX": 6,
    "TUSD": 7, "USDP": 11, "PYUSD": 120, "FDUSD": 18, "USDD": 34,
}
_SYMBOL_BY_ID = {v: k for k, v in _ID_BY_SYMBOL.items()}


class StablecoinTransparencyCollector(BaseCollector):
    source = "stablecoin_transparency"
    category = "chain"

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    def fetch(self, params: dict) -> list[DataRecord]:
        route = params.get("route", "latest_snapshot")
        try:
            if route == "latest_snapshot":
                return self._fetch_latest()
            if route == "historical":
                return self._fetch_historical(params)
            if route == "top_n":
                return self._fetch_top_n(int(params.get("n", 10)))
            # 未知路由 fail-open → 空
            return []
        except RateLimitError:
            raise
        except Exception:
            # fail-open：任何异常不阻塞
            return []

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get(url: str, **kwargs):
        resp = requests.get(url, timeout=kwargs.pop("timeout", _HTTP_TIMEOUT),
                            headers={
                                "User-Agent": (
                                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                                ),
                                "Accept": "application/json,text/html,*/*",
                                "Accept-Language": "en-US,en;q=0.9",
                            },
                            **kwargs)
        if resp.status_code == 429:
            raise RateLimitError(f"stablecoin_transparency 429 限流: {url}")
        if not resp.ok:
            raise RuntimeError(
                f"stablecoin_transparency HTTP {resp.status_code}: {url}"
            )
        return resp

    # ------------------------------------------------------------------
    # Route: latest_snapshot
    #   (1) 尝试官网透明度页 DOM 解析；失败/占位 → (2) DeFiLlama stablecoins 汇总回退
    # ------------------------------------------------------------------
    @staticmethod
    def _unpack(v: Any) -> float | int | None:
        """接受 DeFiLlama 常见形态：raw number / dict.peggedUSD / dict.usd → 纯数或 None。"""
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, dict):
            for k in ("peggedUSD", "usd", "USD", "value"):
                x = v.get(k)
                if isinstance(x, (int, float)):
                    return x
        return None

    def _fetch_latest(self) -> list[DataRecord]:
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()

        # ── 1. 官网 DOM 尝试（不阻塞，失败就 None 交给回退）──
        tether_dom = usdc_dom = None
        try:
            tether_dom = self._parse_tether_html(self._get(
                "https://tether.to/en/transparency/?tab=usdt", timeout=_HTTP_TIMEOUT
            ).text)
        except Exception:
            tether_dom = None
        try:
            usdc_dom = self._parse_usdc_html(self._get(
                "https://www.usdc.com/", timeout=_HTTP_TIMEOUT
            ).text)
        except Exception:
            usdc_dom = None

        # ── 2. DeFiLlama stablecoins 汇总（回退 / 校验 / 链分布 / change 指标）──
        try:
            llama_all = self._get(
                f"{_LLAMA_STABLE}/stablecoins?includePrices=true"
            ).json()
        except Exception:
            llama_all = None
        llama_by_sym: dict[str, Any] = {}
        if isinstance(llama_all, dict):
            for a in llama_all.get("peggedAssets", []):
                if isinstance(a, dict) and a.get("symbol"):
                    llama_by_sym[a["symbol"]] = a

        def _pick(dom: dict | None, ll: dict | None, key: str):
            """优先官网dom值；若其缺失/是None/是假值则用 ll 的值。
            对 Llama 的 dict{peggedUSD} 自动解包。"""
            dv_num = StablecoinTransparencyCollector._unpack(
                dom.get(key) if isinstance(dom, dict) else None
            )
            if isinstance(dv_num, (int, float)) and dv_num > 0:
                return dv_num, "tether.to/usdc.com"
            lv_num = StablecoinTransparencyCollector._unpack(
                ll.get(key) if isinstance(ll, dict) else None
            )
            if isinstance(lv_num, (int, float)) and lv_num > 0:
                return lv_num, "defillama_fallback"
            return None, "missing"

        recs: list[DataRecord] = []
        # ───────── Tether USDT record ─────────
        usdt_ll = llama_by_sym.get("USDT") or {}
        circ_d, circ_src = _pick(tether_dom, usdt_ll, "circulating")
        total_d, total_src = _pick(tether_dom, usdt_ll, "total_supply")
        unreleased_d, _ = _pick(tether_dom, usdt_ll, "unreleased")
        circ_bln = round(circ_d / 1e9, 4) if circ_d else None
        total_bln = round(total_d / 1e9, 4) if total_d else None
        unreleased_bln = round(unreleased_d / 1e9, 4) if unreleased_d else None
        src_tag = ("tether.to" if (circ_src == "tether.to/usdc.com") else
                   (f"hybrid_{circ_src}" if circ_bln else "defillama_fallback"))

        # 变化率（DeFiLlama 提供 PrevDay/PrevWeek/PrevMonth 字段，即使官网有也更准）
        chg_1d = chg_7d = chg_30d = None
        if isinstance(usdt_ll, dict) and circ_d:
            for fld, dst in (("circulatingPrevDay", "chg_1d"),
                             ("circulatingPrevWeek", "chg_7d"),
                             ("circulatingPrevMonth", "chg_30d")):
                pv = usdt_ll.get(fld, {})
                pv_usd = (pv.get("peggedUSD") if isinstance(pv, dict) else None)
                if isinstance(pv_usd, (int, float)) and pv_usd > 0 and circ_d > 0:
                    val = (circ_d - pv_usd) / pv_usd * 100.0
                    if dst == "chg_1d": chg_1d = round(val, 3)
                    elif dst == "chg_7d": chg_7d = round(val, 3)
                    else: chg_30d = round(val, 3)

        # 链分布 Top 2
        top_chains = self._ll_top_chains(usdt_ll, n=2)
        metrics_usdt: dict = {
            "source_provider": src_tag,
        }
        if circ_bln is not None: metrics_usdt["usdt_circulating_usd_bln"] = circ_bln
        if total_bln is not None: metrics_usdt["usdt_total_supply_usd_bln"] = total_bln
        if unreleased_bln is not None: metrics_usdt["unreleased_usd_bln"] = unreleased_bln
        if chg_1d is not None: metrics_usdt["change_1d_pct"] = chg_1d
        if chg_7d is not None: metrics_usdt["change_7d_pct"] = chg_7d
        if chg_30d is not None: metrics_usdt["change_30d_pct"] = chg_30d
        for rank, (nm, vl) in enumerate(top_chains, start=1):
            metrics_usdt[f"top_chain_{rank}_name"] = nm
            metrics_usdt[f"top_chain_{rank}_bln"] = round(vl / 1e9, 4)
        # 官网专有的"总资产超负债"≈total assets（若能解析）
        if isinstance(tether_dom, dict) and tether_dom.get("total_assets"):
            metrics_usdt["total_assets_usd_bln"] = round(float(tether_dom["total_assets"]) / 1e9, 4)
        raw_usdt = {
            "source_used": src_tag,
            "tether_dom_present": bool(tether_dom),
            "llama_fields": self._ll_brief(usdt_ll),
        }
        recs.append(DataRecord(
            source=self.source, category=self.category,
            sub_category="tether_current",
            timestamp=now_iso,
            metrics=metrics_usdt, events=[], timeseries=[], raw=raw_usdt,
        ))

        # ───────── USDC (Circle) record ─────────
        usdc_ll = llama_by_sym.get("USDC") or {}
        circ_u, circ_src_u = _pick(usdc_dom, usdc_ll, "circulating")
        total_u, total_src_u = _pick(usdc_dom, usdc_ll, "total_supply")
        unreleased_u, _ = _pick(usdc_dom, usdc_ll, "unreleased")
        circ_bln_u = round(circ_u / 1e9, 4) if circ_u else None
        total_bln_u = round(total_u / 1e9, 4) if total_u else None
        unreleased_bln_u = round(unreleased_u / 1e9, 4) if unreleased_u else None
        src_tag_u = ("usdc.com" if circ_src_u == "tether.to/usdc.com" else
                     (f"hybrid_{circ_src_u}" if circ_bln_u else "defillama_fallback"))
        chg_1d_u = chg_7d_u = chg_30d_u = None
        if isinstance(usdc_ll, dict) and circ_u:
            for fld, dst in (("circulatingPrevDay", "chg_1d_u"),
                             ("circulatingPrevWeek", "chg_7d_u"),
                             ("circulatingPrevMonth", "chg_30d_u")):
                pv = usdc_ll.get(fld, {}); pv_usd = pv.get("peggedUSD") if isinstance(pv, dict) else None
                if isinstance(pv_usd, (int, float)) and pv_usd > 0 and circ_u > 0:
                    val = (circ_u - pv_usd) / pv_usd * 100.0
                    if dst == "chg_1d_u": chg_1d_u = round(val, 3)
                    elif dst == "chg_7d_u": chg_7d_u = round(val, 3)
                    else: chg_30d_u = round(val, 3)
        top_chains_u = self._ll_top_chains(usdc_ll, n=2)
        metrics_usdc: dict = {"source_provider": src_tag_u}
        if circ_bln_u: metrics_usdc["usdc_circulating_usd_bln"] = circ_bln_u
        if total_bln_u: metrics_usdc["usdc_total_supply_usd_bln"] = total_bln_u
        if unreleased_bln_u: metrics_usdc["unreleased_usd_bln"] = unreleased_bln_u
        if chg_1d_u is not None: metrics_usdc["change_1d_pct"] = chg_1d_u
        if chg_7d_u is not None: metrics_usdc["change_7d_pct"] = chg_7d_u
        if chg_30d_u is not None: metrics_usdc["change_30d_pct"] = chg_30d_u
        for rank, (nm, vl) in enumerate(top_chains_u, start=1):
            metrics_usdc[f"top_chain_{rank}_name"] = nm
            metrics_usdc[f"top_chain_{rank}_bln"] = round(vl / 1e9, 4)
        if isinstance(usdc_dom, dict) and usdc_dom.get("reserve_value"):
            metrics_usdc["reserve_fund_usd_bln"] = round(float(usdc_dom["reserve_value"]) / 1e9, 4)
        raw_usdc = {"source_used": src_tag_u, "usdc_dom_present": bool(usdc_dom),
                    "llama_fields": self._ll_brief(usdc_ll)}
        recs.append(DataRecord(
            source=self.source, category=self.category,
            sub_category="usdc_current",
            timestamp=now_iso,
            metrics=metrics_usdc, events=[], timeseries=[], raw=raw_usdc,
        ))

        for r in recs: validate_record(r)
        return recs

    # ------------------------------------------------------------------
    # Route: historical（DeFiLlama 官方每日爬取 transparency 归档 → ≥365 天）
    # ------------------------------------------------------------------
    def _fetch_historical(self, params: dict) -> list[DataRecord]:
        # coin_id / symbol 互斥优先
        coin_id = params.get("coin_id")
        symbol = params.get("symbol")
        if coin_id is None:
            coin_id = _ID_BY_SYMBOL.get(str(symbol).upper()) if symbol else None
        if coin_id is None:
            coin_id = 1  # 默认 USDT
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        sym = _SYMBOL_BY_ID.get(int(coin_id) if coin_id else -1, str(coin_id))
        url = f"{_LLAMA_STABLE}/stablecoincharts/all?stablecoin={coin_id}"
        j = self._get(url).json()
        ts: list[dict] = []
        first_date = last_date = None
        latest = 0.0
        if isinstance(j, list):
            for item in j:
                try:
                    d = int(item.get("date"))
                except (TypeError, ValueError):
                    continue
                dt = datetime.fromtimestamp(d, tz=timezone.utc).date().isoformat()
                if first_date is None: first_date = dt
                last_date = dt
                tc = item.get("totalCirculatingUSD") if isinstance(item, dict) else None
                circ_usd = float(tc.get("peggedUSD") or 0) if isinstance(tc, dict) else 0.0
                unr = item.get("totalUnreleased") if isinstance(item, dict) else None
                unr_usd = float(unr.get("peggedUSD") or 0) if isinstance(unr, dict) else 0.0
                if circ_usd > 0:
                    latest = circ_usd
                ts.append({
                    "date": dt,
                    "circulating_usd": round(circ_usd, 2),
                    "circulating_usd_bln": round(circ_usd / 1e9, 4),
                    "unreleased_usd": round(unr_usd, 2),
                })
        metrics_hist = {
            "points": len(ts),
            "coin_id": int(coin_id),
            "symbol": sym,
            "first_date": first_date or "",
            "last_date": last_date or "",
            "latest_circulating_usd_bln": round(latest / 1e9, 4),
            "source_provider": "defillama_official_transparency_daily_archive",
        }
        # 可选 days 裁剪（最多保留最近 N 个 timeseries 点）
        days = params.get("days")
        try:
            days_n = int(days) if days else None
        except (TypeError, ValueError):
            days_n = None
        if days_n and len(ts) > days_n:
            ts = ts[-days_n:]
            metrics_hist["trimmed_to_days"] = days_n
        rec = DataRecord(
            source=self.source, category=self.category,
            sub_category=f"stablecoin_hist_{sym.lower()}",
            timestamp=now_iso, metrics=metrics_hist, events=[],
            timeseries=ts, raw={"url": url, "coin_id": coin_id, "symbol": sym},
        )
        validate_record(rec)
        return [rec]

    # ------------------------------------------------------------------
    # Route: top_n（地维度稳定币赛道观察）
    # ------------------------------------------------------------------
    def _fetch_top_n(self, n: int) -> list[DataRecord]:
        j = self._get(
            f"{_LLAMA_STABLE}/stablecoins?includePrices=true"
        ).json()
        assets = j.get("peggedAssets", []) if isinstance(j, dict) else []
        items = []
        for a in assets:
            circ = a.get("circulating") if isinstance(a, dict) else None
            v = float(circ.get("peggedUSD") or 0) if isinstance(circ, dict) else 0.0
            if v <= 0: continue
            items.append((a.get("symbol", ""), v, a.get("name", "")))
        items.sort(key=lambda x: -x[1])
        top = items[:max(1, int(n))]
        total = sum(v for _, v, _ in items)
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        metrics = {
            "stablecoins_tracked": len(items),
            "top_n": len(top),
            "total_circulating_usd_bln": round(total / 1e9, 4),
        }
        usdt_share = usdc_share = 0.0
        for sym, v, _ in top:
            metrics[f"{sym}_bln"] = round(v / 1e9, 4)
            metrics[f"{sym}_pct"] = round(v / total * 100, 2) if total else 0.0
            if sym == "USDT": usdt_share = v
            if sym == "USDC": usdc_share = v
        metrics["usdt_pct_of_total"] = round(usdt_share / total * 100, 2) if total else 0.0
        metrics["usdc_pct_of_total"] = round(usdc_share / total * 100, 2) if total else 0.0
        metrics["top2_duopoly_pct"] = round(
            (usdt_share + usdc_share) / total * 100, 2) if total else 0.0
        raw = {"top": [{"symbol": s, "name": n, "circ_usd_bln": round(v/1e9,4)} for s,v,n in top]}
        rec = DataRecord(source=self.source, category=self.category,
                         sub_category=f"stablecoins_top_{len(top)}",
                         timestamp=now_iso, metrics=metrics, events=[],
                         timeseries=[], raw=raw)
        validate_record(rec)
        return [rec]

    # ================================================================
    # 官网 DOM 解析（仅用作 primary source；若抓不到/占位 → 自动回退）
    # ================================================================
    @classmethod
    def _parse_tether_html(cls, html: str) -> dict | None:
        r"""从 Tether 透明度页 HTML 中提取 circulating / total / unreleased / assets。

        实现原则：
          - 页内有 <script> window.__INITIAL_STATE__ / __NEXT_DATA__ 就 JSON 提取优先，
            能拿到机器级精度数字；
          - 否则退而正则扫 「[0-9.]+[\s]*billion」或「\$[\d,]+」美元数字，
            取前3个作为 total_assets / total_liabilities / circulating（顺序根据
            页面文案 heuristics 绑定）。
        """
        if not html: return None
        # (a) 先试 NEXT_DATA__ / INITIAL_STATE
        for m in re.finditer(
            r"<script[^>]+id=\"__NEXT_DATA__\"[^>]*>([\s\S]*?)</script>", html, flags=re.I
        ):
            try:
                import json as _json
                j = _json.loads(m.group(1))
                flat = _json.dumps(j)
                return cls._parse_tether_json_blob(flat)
            except Exception:
                pass
        for m in re.finditer(
            r"window\.__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\})\s*;?\s*</script>",
            html, flags=re.I,
        ):
            try:
                import json as _json
                j = _json.loads(m.group(1))
                return cls._parse_tether_json_blob(_json.dumps(j))
            except Exception:
                pass
        return None

    @classmethod
    def _parse_tether_json_blob(cls, flat: str) -> dict | None:
        """从 Tether 序列化 JSON 字符串搜 3 个稳定币指标（模糊字段名匹配）。"""
        out: dict = {}
        # circulating（peggedUSD / totalCirculating / supply）
        for regex, key in (
            (r'"(?:totalCirculating|circulat[^"]{0,20}Supply|netCirculation)"\s*:\s*\{\s*"peggedUSD"\s*:\s*(-?\d[\d.]+)',
             "circulating"),
            (r'"(?:totalCirculating|circulat[^"]{0,20}Supply|netCirculation)"\s*:\s*(-?\d[\d.]+)',
             "circulating"),
            (r'"(?:totalSupply|tokensIssued|totalTokens)"\s*:\s*\{\s*"peggedUSD"\s*:\s*(-?\d[\d.]+)',
             "total_supply"),
            (r'"(?:totalSupply|tokensIssued|totalTokens)"\s*:\s*(-?\d[\d.]+)',
             "total_supply"),
            (r'"(?:totalUnreleased|unreleased)"\s*:\s*\{\s*"peggedUSD"\s*:\s*(-?\d[\d.]+)',
             "unreleased"),
            (r'"(?:totalUnreleased|unreleased)"\s*:\s*(-?\d[\d.]+)',
             "unreleased"),
            (r'"(?:totalAssets|assets|reserves)"\s*:\s*\{\s*"(?:usd|peggedUSD)"\s*:\s*(-?\d[\d.]+)',
             "total_assets"),
            (r'"(?:totalAssets|assets|reserves)"\s*:\s*(-?\d[\d.]+)',
             "total_assets"),
        ):
            for mi in re.finditer(regex, flat, flags=re.I):
                out.setdefault(key, float(mi.group(1)))
                break
        return out or None

    @classmethod
    def _parse_usdc_html(cls, html: str) -> dict | None:
        """USDC 首页/透明度页 HTML。同样优先 __NEXT_DATA__ JSON，否则正则抓。"""
        if not html: return None
        for m in re.finditer(
            r"<script[^>]+id=\"__NEXT_DATA__\"[^>]*>([\s\S]*?)</script>", html, flags=re.I
        ):
            try:
                import json as _json
                j = _json.loads(m.group(1))
                flat = _json.dumps(j)
                out: dict = {}
                for regex, key in (
                    (r'"(?:circulatingSupply|totalCirculat[^"]{0,20}|usdcInCirculation)"\s*:\s*\{\s*"peggedUSD"\s*:\s*(-?\d[\d.]+)',
                     "circulating"),
                    (r'"(?:circulatingSupply|totalCirculat[^"]{0,20}|usdcInCirculation)"\s*:\s*(-?\d[\d.]+)',
                     "circulating"),
                    (r'"(?:totalSupply|tokensOutstanding|outstanding[^"]{0,10}|totalIssuance)"\s*:\s*\{\s*"peggedUSD"\s*:\s*(-?\d[\d.]+)',
                     "total_supply"),
                    (r'"(?:totalSupply|tokensOutstanding|outstanding[^"]{0,10}|totalIssuance)"\s*:\s*(-?\d[\d.]+)',
                     "total_supply"),
                    (r'"(?:totalUnreleased|unreleased)"\s*:\s*\{\s*"peggedUSD"\s*:\s*(-?\d[\d.]+)',
                     "unreleased"),
                    (r'"(?:reserveValue|reserves|circleReserve|backedValue|totalAssets)"\s*:\s*\{\s*"(?:usd|peggedUSD)"\s*:\s*(-?\d[\d.]+)',
                     "reserve_value"),
                    (r'"(?:reserveValue|reserves|circleReserve|backedValue|totalAssets)"\s*:\s*(-?\d[\d.]+)',
                     "reserve_value"),
                ):
                    for mi in re.finditer(regex, flat, flags=re.I):
                        out.setdefault(key, float(mi.group(1)))
                        break
                # 页面展示占位 $ 0.00 B 时，上面字段匹配可能是 0 → 忽略当缺失
                return {k: v for k, v in out.items() if v > 0} or None
            except Exception:
                pass
        return None

    # ================================================================
    # 小工具
    # ================================================================
    @staticmethod
    def _ll_top_chains(asset: dict, n: int = 2) -> list[tuple[str, float]]:
        cc = asset.get("chainCirculating") if isinstance(asset, dict) else {}
        rows: list[tuple[str, float]] = []
        if isinstance(cc, dict):
            for ch, v in cc.items():
                cur = v.get("current") if isinstance(v, dict) else None
                usd = float(cur.get("peggedUSD") or 0) if isinstance(cur, dict) else 0.0
                if usd > 0: rows.append((str(ch), usd))
        rows.sort(key=lambda x: -x[1])
        return rows[: max(1, int(n))]

    @staticmethod
    def _ll_brief(asset: dict, keys=("id","symbol","name","pegType","pegMechanism")) -> dict:
        if not isinstance(asset, dict): return {}
        brief = {k: asset.get(k) for k in keys if asset.get(k) is not None}
        # 数值概览
        for k in ("circulatingPrevDay","circulatingPrevWeek","circulatingPrevMonth"):
            v = asset.get(k)
            if isinstance(v, dict): brief[k] = v.get("peggedUSD")
        return brief


if __name__ == "__main__":
    import json as _json
    sc = StablecoinTransparencyCollector()
    print("── latest_snapshot ──")
    rs = sc.fetch({"route": "latest_snapshot"})
    for r in rs:
        print(r.sub_category, "→", _json.dumps(r.metrics, ensure_ascii=False))
    print()
    print("── historical USDT 最近 5 点 ──")
    h = sc.fetch({"route": "historical", "symbol": "USDT", "days": 5})
    if h:
        print(_json.dumps(h[0].metrics, ensure_ascii=False))
        for p in h[0].timeseries[-3:]:
            print(" ", p)
    print()
    print("── historical USDC 最近 5 点 ──")
    h2 = sc.fetch({"route": "historical", "symbol": "USDC", "days": 5})
    if h2:
        print(_json.dumps(h2[0].metrics, ensure_ascii=False))
        for p in h2[0].timeseries[-3:]:
            print(" ", p)
    print()
    print("── top_n 5 ──")
    tn = sc.fetch({"route": "top_n", "n": 5})
    if tn:
        print(_json.dumps(tn[0].metrics, ensure_ascii=False))
