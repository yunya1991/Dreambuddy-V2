from pathlib import Path
import re


_CURRENT_FILE = Path(__file__).resolve()
_SOURCE_FILE = _CURRENT_FILE.with_name("_embedded_ml_trade_service_source.py")

if not _SOURCE_FILE.exists():
    raise FileNotFoundError(str(_SOURCE_FILE))

_code = compile(_SOURCE_FILE.read_text(encoding="utf-8"), str(_CURRENT_FILE), "exec")
_globals = globals()
_globals["__file__"] = str(_CURRENT_FILE)
_globals["__name__"] = "_fundamental_embedded_service"
exec(_code, _globals)
_globals["__name__"] = "__main__"

_orig__fundamental_narrative_compact_fields = globals().get("_fundamental_narrative_compact_fields")


def _fundamental_narrative_compact_fields(record: dict, history_row: dict | None = None) -> dict:
    rec = record if isinstance(record, dict) else {}
    contract = (rec.get("contract") or {}) if isinstance(rec.get("contract"), dict) else {}
    scores_obj = contract.get("scores")
    scores = (scores_obj or {}) if isinstance(scores_obj, dict) else {}
    stress_obj = (scores.get("narrative_stress") or {}) if isinstance(scores.get("narrative_stress"), dict) else {}
    q_obj = contract.get("quality") if isinstance(contract.get("quality"), dict) else (rec.get("quality") if isinstance(rec.get("quality"), dict) else {})
    quality = q_obj if isinstance(q_obj, dict) else {}
    coverage = _fundamental_flows_num(quality.get("coverage"))
    if coverage is None and isinstance(history_row, dict):
        coverage = _fundamental_flows_num(history_row.get("quality_coverage"))
    missing_data = [str(x) for x in (quality.get("missing_disclosure") or []) if str(x or "").strip()]
    if not contract and "narrative_contract" not in missing_data:
        missing_data.append("narrative_contract")
    if not scores and "narrative_scores" not in missing_data:
        missing_data.append("narrative_scores")
    if coverage is None:
        if "coverage_missing" not in missing_data:
            missing_data.append("coverage_missing")
        coverage = 0.0
    if isinstance(coverage, float) and coverage < 0.5 and "coverage_below_threshold" not in missing_data:
        missing_data.append("coverage_below_threshold")
    level = _fundamental_flows_num(scores.get("community_effective_score"))
    slope = _fundamental_flows_num(scores.get("community_impulse"))
    if level is None and "community_effective_score" not in missing_data:
        missing_data.append("community_effective_score")
    if slope is None and isinstance(history_row, dict):
        slope = _fundamental_flows_num(history_row.get("community_impulse"))
    if slope is None and "community_impulse" not in missing_data:
        missing_data.append("community_impulse")
    stress = str(stress_obj.get("stress_level") or "unknown").strip().lower()
    if stress not in ("low", "med", "high"):
        stress = "unknown"
    tp = _fundamental_turning_point_state(
        level=level,
        slope=slope,
        stress=stress,
        coverage=coverage,
        missing_data=missing_data,
        confirm_bars=2,
    )
    evidence_refs = contract.get("evidence_refs") if isinstance(contract.get("evidence_refs"), list) else []
    quality_overall = str(quality.get("overall_quality") or "").strip()
    if not quality_overall and isinstance(history_row, dict):
        quality_overall = str(history_row.get("quality_overall") or "").strip()
    if not quality_overall:
        quality_overall = str(_fundamental_quality_overall(coverage=coverage, counts={"missing": (1 if missing_data else 0)}, critical_missing_sources=missing_data)).strip()
    return {
        "generated_at": str(rec.get("generated_at") or contract.get("generated_at") or rec.get("timestamp") or "").strip(),
        "quality": quality_overall,
        "coverage": coverage,
        "missing_data": missing_data,
        "turning_point_state": str(tp.get("turning_point_state") or "unknown"),
        "trigger_reasons": list(tp.get("trigger_reasons") or []) + [str(x) for x in (stress_obj.get("trigger_reasons") or []) if str(x or "").strip()],
        "confirm_bars": int(tp.get("confirm_bars") or 2),
        "turning_point_detail": {
            "level": level,
            "slope": slope,
            "stress": stress,
        },
        "evidence_refs": evidence_refs,
        "execution_gate": str(contract.get("execution_gate") or rec.get("execution_gate") or "readonly_advisory").strip() or "readonly_advisory",
        "stress_state": stress,
        "monitoring_clocks": _fundamental_monitoring_clocks("narrative"),
    }



def _fundamental_research_doc_path() -> Path:
    base = Path(__file__).resolve().parent
    return base / "基本面研究文档.md"


def _md_extract_heading_block(raw: str, heading: str, max_chars: int = 60000) -> dict:
    sk = str(heading or "").strip()
    if not sk:
        return {"ok": False, "error": "missing_heading"}
    try:
        patt = re.compile(r"^(#+)\s+" + re.escape(sk) + r"(?:\s+|$)(.*)$")
    except Exception:
        return {"ok": False, "error": "bad_pattern"}
    lines = str(raw or "").replace("\r\n", "\n").split("\n")
    start_i = -1
    level = 0
    for i, line in enumerate(lines):
        m = patt.match(str(line or ""))
        if not m:
            continue
        start_i = int(i)
        level = len(str(m.group(1) or ""))
        break
    if start_i < 0:
        return {"ok": False, "error": "heading_not_found"}
    end_i = len(lines)
    next_patt = re.compile(r"^(#{1,%d})\s+" % int(level))
    for j in range(start_i + 1, len(lines)):
        if next_patt.match(str(lines[j] or "")):
            end_i = int(j)
            break
    text_full = "\n".join(lines[start_i:end_i]).strip()
    truncated = False
    text = text_full
    if int(max_chars) > 0 and len(text) > int(max_chars):
        text = text[: int(max_chars)]
        truncated = True
    return {
        "ok": True,
        "heading": sk,
        "start_line": int(start_i + 1),
        "end_line": int(end_i),
        "text": text,
        "truncated": bool(truncated),
    }


def _fundamental_min_resistance_latest_payload() -> dict:
    now_ts = int(_now_ms())
    def _as_rec(x: object) -> dict:
        if x and isinstance(x, dict):
            return x
        return {}

    def _as_list(x: object) -> list:
        if isinstance(x, list):
            return x
        return []

    def _as_float(x: object) -> float | None:
        try:
            v = float(x)  # type: ignore[arg-type]
        except Exception:
            return None
        if v != v:
            return None
        return v

    def _parse_iso_ms(s: str) -> int | None:
        t = str(s or "").strip()
        if not t:
            return None
        try:
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            return int(datetime.fromisoformat(t).timestamp() * 1000)
        except Exception:
            return None

    regime_q = _fundamental_flows_pick_regime_file("")
    if not isinstance(regime_q, Path) or (not regime_q.exists()):
        return {
            "ok": True,
            "ts": now_ts,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "quality": "missing",
            "coverage": 0.0,
            "lr_total": 0.0,
            "lr_state": "UNKNOWN",
            "dominant_driver_layer": "NO_FLOW_REGIME",
            "dominant_driver_contribution": None,
            "dominant_driver_pct": None,
            "evidence_summary": "flow_regime_not_found",
            "execution_gate": "readonly_advisory",
            "layer_scores": [],
            "missing_metrics": [],
            "coverage_by_layer": [],
            "lr_total_history": [],
            "btc_price_history": [],
            "free_source_catalog": [],
            "research_markdown": "",
            "research_truncated": False,
            "source_path": None,
        }

    try:
        obj = json.loads(regime_q.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        obj = {}
    rec = obj if isinstance(obj, dict) else {}

    regime_output = _as_rec(rec.get("regime_output"))
    bias = str(regime_output.get("bias") or "").strip()
    lr_state = (bias or "UNKNOWN")

    composite = _as_float(rec.get("composite"))
    lr_total = float(composite) if composite is not None else 0.0

    quality_obj = _as_rec(rec.get("quality"))
    coverage = _as_float(quality_obj.get("coverage"))
    coverage = float(coverage) if coverage is not None else 0.0
    if coverage >= 0.80:
        quality = "ok"
    elif coverage >= 0.50:
        quality = "stale"
    else:
        quality = "missing"

    diagnostics = _as_rec(rec.get("diagnostics"))
    data_quality = _as_rec(diagnostics.get("data_quality"))
    checks = [x for x in _as_list(data_quality.get("checks")) if isinstance(x, dict)]
    critical_missing = [str(x or "").strip() for x in _as_list(data_quality.get("critical_missing_sources")) if str(x or "").strip()]
    missing_metrics: list[dict] = []
    coverage_by_layer: dict[str, dict[str, int]] = {}
    for c in checks:
        layer = str(c.get("layer") or "unknown").strip() or "unknown"
        status = str(c.get("status") or "").strip().lower() or "unknown"
        base = str(c.get("name") or "").strip() or "unknown"
        reasons = [str(x or "").strip() for x in _as_list(c.get("status_reasons")) if str(x or "").strip()]
        degrade = "; ".join(reasons)[:240] if reasons else (str(c.get("error") or "").strip()[:240] or "")
        if status != "ok":
            missing_metrics.append({
                "layer": layer,
                "base": base,
                "quality_status": status,
                "degrade": degrade,
            })
        bucket = coverage_by_layer.setdefault(layer, {"ok": 0, "total": 0})
        bucket["total"] = int(bucket.get("total") or 0) + 1
        if status == "ok":
            bucket["ok"] = int(bucket.get("ok") or 0) + 1

    coverage_rows = []
    for layer, agg in sorted(coverage_by_layer.items(), key=lambda kv: kv[0]):
        total = int(agg.get("total") or 0)
        ok_n = int(agg.get("ok") or 0)
        cov = (float(ok_n) / float(total)) if total > 0 else 0.0
        coverage_rows.append({
            "layer_key": layer,
            "layer_label": layer,
            "ok_metrics": ok_n,
            "total_metrics": total,
            "coverage": cov,
        })

    signal_map = _as_rec(rec.get("layer_signals_for_composite") or rec.get("layer_signals"))
    layer_order = ["exogenous", "onchain", "leverage"]
    label_map = {
        "exogenous": "外生/宏观",
        "onchain": "链上",
        "leverage": "杠杆/衍生品",
    }
    layer_scores = []
    cov_by_layer_value = {str(r.get("layer_key") or "").strip(): _as_float(r.get("coverage")) for r in coverage_rows if isinstance(r, dict)}
    for k in layer_order:
        if k not in signal_map:
            continue
        v = _as_float(signal_map.get(k))
        if v is None:
            continue
        layer_scores.append({
            "layer_key": k,
            "layer_label": label_map.get(k, k),
            "signal": float(v),
            "contribution": float(v),
            "coverage": (float(cov_by_layer_value.get(k) or 0.0)),
        })

    dom_layer = "-"
    dom_contrib: float | None = None
    dom_pct: float | None = None
    if layer_scores:
        abs_sum = sum(abs(float(x.get("contribution") or 0.0)) for x in layer_scores) or 0.0
        top = max(layer_scores, key=lambda x: abs(float(x.get("contribution") or 0.0)))
        dom_layer = str(top.get("layer_label") or top.get("layer_key") or "-")
        dom_contrib = _as_float(top.get("contribution"))
        if abs_sum > 0 and dom_contrib is not None:
            dom_pct = abs(float(dom_contrib)) / abs_sum

    regime_paths = []
    try:
        regime_paths = _fundamental_flows_pick_regime_files(limit=120)
    except Exception:
        regime_paths = []
    lr_total_history = []
    for fp in regime_paths:
        if not isinstance(fp, Path):
            continue
        try:
            robj = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        rrec = robj if isinstance(robj, dict) else {}
        comp2 = _as_float(rrec.get("composite"))
        if comp2 is None:
            continue
        ts_ms = _parse_iso_ms(str(rrec.get("timestamp") or "")) or int(fp.stat().st_mtime * 1000)
        lr_total_history.append({"ts_ms": int(ts_ms), "lr_total": float(comp2)})

    evidence_summary = f"bias={bias or 'unknown'}; filter={str(regime_output.get('filter') or '').strip() or 'unknown'}"
    if critical_missing:
        evidence_summary = evidence_summary + f"; critical_missing={','.join(critical_missing[:8])}"

    return {
        "ok": True,
        "ts": now_ts,
        "generated_at": str(rec.get("timestamp") or datetime.utcnow().isoformat() + "Z"),
        "quality": quality,
        "coverage": float(coverage),
        "lr_total": float(lr_total),
        "lr_state": lr_state,
        "dominant_driver_layer": dom_layer,
        "dominant_driver_contribution": dom_contrib,
        "dominant_driver_pct": dom_pct,
        "evidence_summary": evidence_summary,
        "execution_gate": "readonly_advisory",
        "layer_scores": layer_scores,
        "missing_metrics": missing_metrics[:200],
        "coverage_by_layer": coverage_rows,
        "lr_total_history": lr_total_history,
        "btc_price_history": [],
        "free_source_catalog": [],
        "research_markdown": "",
        "research_truncated": False,
        "source_path": str(regime_q),
    }


def _fundamental_gate_briefing_build(time_range: str, coin: str | None = None, topic: str | None = None) -> dict:
    now_ts = int(_now_ms())
    rank_payload = _skill_binance_web3_crypto_market_rank({
        "chainId": "56",
        "limit": 10,
        "include_trending": True,
        "include_top_search": True,
        "include_inflow": True,
        "include_top_traders": False,
    })
    ranks = rank_payload.get("ranks") if isinstance(rank_payload, dict) else {}
    trending = ranks.get("trending") if isinstance(ranks, dict) and isinstance(ranks.get("trending"), list) else []
    top_search = ranks.get("top_search") if isinstance(ranks, dict) and isinstance(ranks.get("top_search"), list) else []
    inflow = ranks.get("smart_money_inflow") if isinstance(ranks, dict) and isinstance(ranks.get("smart_money_inflow"), list) else []

    def _as_str(x: object) -> str:
        return str(x or "").strip()

    def _brief_parse_top_points(md: str, generated_at: str, limit: int = 5) -> list[dict]:
        if not md:
            return []
        m = re.search(r"^##\s+.*今日要点.*$", md, flags=re.MULTILINE)
        if not m:
            return []
        start = m.end()
        rest = md[start:]
        end_m = re.search(r"^##\s+", rest, flags=re.MULTILINE)
        block = rest[: end_m.start()] if end_m else rest
        out: list[dict] = []
        for line in block.splitlines():
            s = str(line or "").strip()
            if not s:
                continue
            m2 = re.match(r"^\d+\.\s+\*\*\[(.+?)\]\*\*\s*-\s*(.+)$", s)
            if not m2:
                continue
            title = _as_str(m2.group(1))
            if title.lower() == "no data":
                continue
            tail = _as_str(m2.group(2))
            url_m = re.search(r"来源=([^）\)\s]+)", tail)
            url = _as_str(url_m.group(1)) if url_m else ""
            details = tail
            cut_m = re.search(r"（可信度=|\(可信度=|（来源=|\(来源=", details)
            if cut_m:
                details = details[: cut_m.start()].strip()
            out.append({
                "title": title,
                "time": (generated_at or None),
                "impact": None,
                "involved": "brief_top",
                "details": (details[:280] if details else None),
                "source": (url or None),
            })
            if len(out) >= int(limit):
                break
        return out

    def _brief_parse_news_items(md: str, generated_at: str, limit_total: int = 14) -> dict:
        out: dict[str, list[dict]] = {
            "market_trading": [],
            "projects_technology": [],
            "regulation_policy": [],
            "defi_nft": [],
        }
        if not md:
            return out
        lines = md.splitlines()
        in_block = False
        cur: dict = {}
        items: list[dict] = []
        for line in lines:
            s = str(line or "").rstrip("\n")
            if (not in_block) and re.match(r"^##\s+.*新闻分类明细\s*$", s):
                in_block = True
                continue
            if in_block and re.match(r"^##\s+", s):
                break
            if not in_block:
                continue
            m3 = re.match(r"^####\s+\d+\.\s+(.*)$", s.strip())
            if m3:
                if cur:
                    items.append(cur)
                cur = {"title": _as_str(m3.group(1))}
                continue
            if not cur:
                continue
            s2 = s.strip()
            if s2.startswith("- 类别:"):
                cur["category"] = _as_str(s2.split(":", 1)[-1])
            elif s2.startswith("- 来源:"):
                cur["url"] = _as_str(s2.split(":", 1)[-1])
            elif s2.startswith("- 事实:"):
                cur["fact"] = _as_str(s2.split(":", 1)[-1])
        if cur:
            items.append(cur)

        def _bucket_for_category(cat_raw: str) -> str:
            c = str(cat_raw or "").strip().lower()
            if c in ("geopolitics", "fed", "inflation", "macro", "rate", "cpi", "ppi", "employment", "policy", "regulation"):
                return "regulation_policy"
            if c in ("defi", "nft", "stablecoin", "protocol", "dex", "lending", "yield", "security"):
                return "defi_nft"
            if c in ("project_update", "technology", "ecosystem", "listing", "airdrop", "hack", "partnership"):
                return "projects_technology"
            if "project" in c:
                return "projects_technology"
            return "market_trading"

        for it in items:
            title = _as_str(it.get("title"))
            if (not title) or title.lower() == "no data":
                continue
            bucket = _bucket_for_category(_as_str(it.get("category")))
            row = {
                "title": title,
                "summary": (_as_str(it.get("fact"))[:240] or None),
                "time": (generated_at or None),
                "url": (_as_str(it.get("url")) or None),
            }
            out[bucket].append(row)
            if sum(len(v) for v in out.values()) >= int(limit_total):
                break
        return out

    major_events: list[dict] = []
    trending_news: dict[str, list[dict]] = {"market_trading": [], "projects_technology": [], "regulation_policy": [], "defi_nft": []}
    briefing_used = False
    brief_meta: dict = {}
    try:
        bq = _fundamental_news_pick_file(name="")
        if isinstance(bq, Path) and bq.exists() and bq.is_file():
            try:
                md = bq.read_text(encoding="utf-8", errors="replace")[:260000]
            except Exception:
                md = ""
            b_gen = _as_str(_fundamental_news_extract_generated_at(md) or "")
            if not b_gen:
                b_gen = datetime.utcnow().isoformat() + "Z"
            top_points = _brief_parse_top_points(md, b_gen, limit=5)
            news_items = _brief_parse_news_items(md, b_gen, limit_total=14)
            if top_points:
                major_events = top_points
                briefing_used = True
            if isinstance(news_items, dict):
                trending_news = news_items
                if any(len(v) for v in trending_news.values()):
                    briefing_used = True
            brief_meta = {"name": bq.name, "path": str(bq), "generated_at": b_gen, "mtime_ms": int(bq.stat().st_mtime * 1000)}
    except Exception:
        major_events = major_events

    if not major_events:
        ledger_path = _fundamental_news_pick_event_ledger_file(name="")
        if isinstance(ledger_path, Path):
            try:
                with open(ledger_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        s = str(line or "").strip()
                        if not s:
                            continue
                        try:
                            rec = json.loads(s)
                        except Exception:
                            continue
                        if not isinstance(rec, dict):
                            continue
                        title = str(rec.get("title") or "").strip()
                        if not title:
                            continue
                        major_events.append({
                            "title": title,
                            "time": str(rec.get("timestamp") or rec.get("published_at") or rec.get("ts") or "").strip() or None,
                            "impact": str(rec.get("expectation_bucket") or rec.get("risk_action_proposal") or "").strip() or None,
                            "involved": str(rec.get("event_type") or "").strip() or None,
                            "details": str(rec.get("fact_text") or rec.get("analysis_text") or "").strip()[:280] or None,
                            "source": str(rec.get("source_url") or rec.get("source") or "").strip() or None,
                        })
                        if len(major_events) >= 5:
                            break
            except Exception:
                major_events = []

    pct_vals: list[float] = []
    for row in trending[:8]:
        if not isinstance(row, dict):
            continue
        try:
            v = float(row.get("percentChange24h"))
        except Exception:
            continue
        if v == v:
            pct_vals.append(v)
    avg_pct = (sum(pct_vals) / len(pct_vals)) if pct_vals else 0.0
    overall_sentiment = "bullish" if avg_pct > 1.0 else ("bearish" if avg_pct < -1.0 else "neutral")
    hot_n = len(trending) + len(top_search)
    discussion_volume = "high" if hot_n >= 12 else ("medium" if hot_n >= 5 else "low")

    topic_set: list[str] = []
    for row in (trending[:5] + top_search[:5]):
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if sym and sym not in topic_set:
            topic_set.append(sym)
    worth_watching: list[str] = []
    for row in inflow[:5]:
        if not isinstance(row, dict):
            continue
        token = str(row.get("tokenName") or row.get("symbol") or "").strip().upper()
        chg = row.get("priceChangeRate")
        inflow_v = row.get("inflow")
        if token:
            worth_watching.append(f"{token}: inflow={inflow_v}, change={chg}")

    return {
        "ok": True,
        "ts": now_ts,
        "time_range": str(time_range or "24h"),
        "coin": (None if not coin else str(coin)),
        "topic": (None if not topic else str(topic)),
        "major_events": major_events,
        "trending_news": trending_news,
        "social_sentiment": {
            "overall_sentiment": overall_sentiment,
            "discussion_volume": discussion_volume,
            "trending_topics": topic_set[:8],
            "kol_focus": (topic_set[0] if topic_set else ""),
            "top_coins": [],
        },
        "worth_watching": worth_watching[:8],
        "generated_at": (str(brief_meta.get("generated_at") or "").strip() or datetime.utcnow().isoformat() + "Z"),
        "error": (None if (major_events or topic_set or worth_watching) else "mcp_no_data"),
        "source": {
            "skill": "crypto-market-rank",
            "rank_ok": bool(rank_payload.get("ok")) if isinstance(rank_payload, dict) else False,
            "rank_errors": (rank_payload.get("errors") if isinstance(rank_payload, dict) else {}),
            "brief_used": bool(briefing_used),
            "brief": (brief_meta if isinstance(brief_meta, dict) else {}),
        },
    }


if not any(getattr(r, "rule", "") == "/fundamental/news/gate_briefing/latest" for r in app.url_map.iter_rules()):
    @app.route("/fundamental/news/gate_briefing/latest", methods=["GET"])
    def fundamental_news_gate_briefing_latest():
        time_range = str(request.args.get("time_range") or "24h").strip() or "24h"
        coin = (str(request.args.get("coin") or "").strip() or None)
        topic = (str(request.args.get("topic") or "").strip() or None)
        try:
            payload = _fundamental_gate_briefing_build(time_range=time_range, coin=coin, topic=topic)
            return jsonify(_json_sanitize(payload))
        except Exception as e:
            return jsonify({
                "ok": False,
                "ts": int(_now_ms()),
                "time_range": str(time_range),
                "coin": coin,
                "topic": topic,
                "major_events": [],
                "trending_news": {},
                "social_sentiment": {"overall_sentiment": "neutral", "discussion_volume": "low", "trending_topics": [], "kol_focus": ""},
                "worth_watching": [],
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "error": str(e),
            }), 200


if not any(getattr(r, "rule", "") == "/fundamental/flows/history" for r in app.url_map.iter_rules()):
    @app.route("/fundamental/flows/history", methods=["GET"])
    def fundamental_flows_history():
        try:
            limit_raw = int(request.args.get("limit", 120))
        except Exception:
            limit_raw = 120
        limit = max(1, min(500, int(limit_raw)))
        files = _fundamental_flows_pick_regime_files(limit=max(limit, 1))
        items: list[dict] = []
        monitoring_clocks: dict | None = None
        for fp in files:
            if not isinstance(fp, Path):
                continue
            try:
                obj = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            rec = obj if isinstance(obj, dict) else {}
            compact = _fundamental_flows_compact_fields(rec, fp.name)
            ts_ms = int(fp.stat().st_mtime * 1000)
            item = {
                "name": fp.name,
                "generated_at": compact.get("generated_at"),
                "ts_ms": int(ts_ms),
                "asof": compact.get("generated_at"),
                "quality": compact.get("quality"),
                "coverage": compact.get("coverage"),
                "missing_data": compact.get("missing_data"),
                "turning_point_state": compact.get("turning_point_state"),
                "trigger_reason": compact.get("trigger_reasons"),
                "confirm_bars": compact.get("confirm_bars"),
                "turning_point_detail": compact.get("turning_point_detail"),
                "execution_gate": compact.get("execution_gate"),
                "composite": _fundamental_flows_num(rec.get("composite")),
                "confidence": _fundamental_flows_num(rec.get("confidence")),
            }
            items.append(item)
            if monitoring_clocks is None:
                mc = compact.get("monitoring_clocks")
                monitoring_clocks = mc if isinstance(mc, dict) else {}
        items.sort(key=lambda x: int(x.get("ts_ms") or 0), reverse=True)
        return jsonify({
            "ok": True,
            "items": _json_sanitize(items[:limit]),
            "monitoring_clocks": _json_sanitize(monitoring_clocks or {}),
            "ts": int(_now_ms()),
        })
    # def fundamental_flows_history


if not any(getattr(r, "rule", "") == "/fundamental/flows/min_resistance/latest" for r in app.url_map.iter_rules()):
    @app.route("/fundamental/flows/min_resistance/latest", methods=["GET"])
    def fundamental_flows_min_resistance_latest():
        try:
            payload = _fundamental_min_resistance_latest_payload()
            return jsonify(_json_sanitize(payload))
        except Exception as e:
            return jsonify({
                "ok": False,
                "ts": int(_now_ms()),
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "quality": "missing",
                "coverage": 0.0,
                "lr_state": "UNKNOWN",
                "dominant_driver_layer": "ERROR",
                "evidence_summary": "min_resistance_latest_failed",
                "execution_gate": "readonly_advisory",
                "layer_scores": [],
                "missing_metrics": [],
                "coverage_by_layer": [],
                "lr_total_history": [],
                "btc_price_history": [],
                "free_source_catalog": [],
                "research_markdown": "",
                "research_truncated": False,
                "error": str(e),
            }), 200


def _run_embedded_main() -> None:
    if "--agent-driver-once" in sys.argv:
        try:
            _load_config()
        except Exception:
            pass
        try:
            raw = sys.stdin.buffer.read() if hasattr(sys, "stdin") and hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
        except Exception:
            raw = b""
        payload = None
        try:
            payload = json.loads((raw or b"{}").decode("utf-8"))
        except Exception:
            try:
                payload = json.loads((raw or b"{}").decode("utf-8", errors="ignore"))
            except Exception:
                payload = None
        if isinstance(payload, dict):
            cmd = payload.get("cmd") if isinstance(payload.get("cmd"), dict) else {}
            llm = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
            try:
                _agent_chat_driver_process(cmd, llm)
            except Exception:
                pass
        raise SystemExit(0)

    _load_config()
    try:
        if bool(AUTOMATION.get("shadow_automation_autostart", False)):
            AUTOMATION["enable_shadow_automation_loop"] = True
    except Exception:
        pass
    try:
        if bool(AUTOMATION.get("gtw_autostart", False)):
            AUTOMATION["enable_gtw"] = True
    except Exception:
        pass
    try:
        if bool(CONFIG.get("orders_isolation_backfill_on_start", False)):
            _orders_archive_backfill_isolation(max_files=int(CONFIG.get("orders_isolation_backfill_max_files", 60) or 60))
    except Exception:
        pass
    try:
        CONFIG.setdefault("aster_maker_price_offset_bps", 1.0)
    except Exception:
        pass
    try:
        CONFIG.setdefault("aster_maker_fallback_to_market", False)
    except Exception:
        pass
    try:
        CONFIG.setdefault("aster_maker_complete_on_partial", True)
    except Exception:
        pass
    try:
        _load_models()
    except Exception:
        pass
    try:
        _ensure_scheduler_started()
    except Exception:
        pass
    try:
        _ensure_twitter_outbox_worker_started()
    except Exception:
        pass
    try:
        _ensure_telegram_outbox_worker_started()
    except Exception:
        pass
    try:
        _ensure_agent_chat_outbox_worker_started()
    except Exception:
        pass
    try:
        _ensure_sandbox_outbox_worker_started()
    except Exception:
        pass
    host = str(os.environ.get("LISTEN_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    env_port_raw = os.environ.get("PORT") or os.environ.get("ML_TRADE_SERVICE_PORT")
    env_port = _parse_listen_port(env_port_raw)
    cfg_port = _parse_listen_port(CONFIG.get("trade_service_port"))
    if cfg_port is None:
        cfg_port = _parse_listen_port(CONFIG.get("service_port"))
    if cfg_port is None:
        cfg_port = _parse_listen_port(CONFIG.get("server_port"))
    preferred_port = int(env_port or cfg_port or 8092)
    port = _pick_listen_port(host, preferred_port, strict=(env_port is not None or cfg_port is not None))
    CONFIG["_listen_host"] = host
    CONFIG["_listen_port"] = int(port)
    app.run(host=host, port=int(port), threaded=True)


if __name__ == "__main__":
    _run_embedded_main()
