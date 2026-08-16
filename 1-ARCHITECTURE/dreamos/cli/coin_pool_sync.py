#!/usr/bin/env python3
"""coin_pool_sync.py — 多空币池统一同步入口（独立池 · 多写入方）

多空币池是独立共享池，任何写入方（Hermes 每周选币任务、外部模型调研等）
都通过本 CLI 同步推荐，禁止直接整文件覆盖。

Schema v2 契约（scheduler_data/coin_pool.json）:
    {
      "version": 2,
      "long_pool":  [{"symbol","score","reasons","source","updated_at"}, ...],
      "short_pool": [{"symbol","score","reasons","source","updated_at"}, ...],
      "timestamp": "<最后一次同步的 UTC ISO 时间>",
      "source": "<最后写入方>",
      "producers": ["hermes-weekly", ...],
      "week": "2026-W33",
      "regime": "...",
      "notes": "...",
      "conflict_symbols": ["X"]
    }

合并规则（按 symbol upsert，不整文件覆盖）:
    - 同池同 symbol → 覆盖该条（新写入方的 score/reasons 生效），记录 source/updated_at
    - 本次未涉及的 symbol → 原样保留（其他写入方的推荐不被抹掉）
    - --replace-source: 合并前先移除 source==本次写入方 的旧条目（整周刷新语义：
      该写入方上周未再入选的币自动出池，其他写入方的币不受影响）
    - 同一 symbol 同时出现在多/空两池 → 两条都保留，记入 conflict_symbols（只标记不销毁，
      仲裁规则待第二个真实写入方接入后再定，见 P1）

用法:
    python3 coin_pool_sync.py --source <写入方> --file recs.json [--replace-source] [--week 2026-W33] [--regime ...] [--notes ...]
    cat recs.json | python3 coin_pool_sync.py --source <写入方> --stdin [...]
    python3 coin_pool_sync.py --show

recs.json 输入格式（与池同构，币级 source/updated_at 可省略，由 --source 补全）:
    {"long_pool": [{"symbol":"BTC","score":0.8,"reasons":["..."]}],
     "short_pool": [{"symbol":"DOGE","score":0.6,"reasons":["..."]}]}

退出码: 0=成功, 1=输入校验失败/写入失败
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

POOL_FILE = Path(__file__).parent / "scheduler_data" / "coin_pool.json"
POOL_BACKUP = POOL_FILE.with_suffix(".json.bak")
SCHEMA_VERSION = 2
MAX_POOL_SIZE = 20  # 单池上限，防止异常输入撑爆池


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_week() -> str:
    now = datetime.now(timezone.utc)
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def load_pool() -> dict:
    """读取现有池；不存在返回空 v2 结构；v1 自动迁移为 v2（币级 source 用池级 source 补全）"""
    empty = {
        "version": SCHEMA_VERSION,
        "long_pool": [],
        "short_pool": [],
        "timestamp": "",
        "source": "",
        "producers": [],
        "week": "",
        "regime": "",
        "notes": "",
        "conflict_symbols": [],
    }
    if not POOL_FILE.exists():
        return empty
    try:
        data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[coin_pool_sync] 现有池文件损坏({e})，将以空池重建（备份保留在 {POOL_BACKUP}）", file=sys.stderr)
        shutil.copy2(POOL_FILE, POOL_BACKUP)
        return empty

    if data.get("version", 1) < 2:
        # v1 → v2 迁移：币级补 source/updated_at
        top_source = data.get("source", "unknown")
        ts = data.get("timestamp", "")
        for key in ("long_pool", "short_pool"):
            for item in data.get(key, []):
                item.setdefault("source", top_source)
                item.setdefault("updated_at", ts)
        data["version"] = SCHEMA_VERSION
        data.setdefault("producers", [top_source] if top_source else [])
        print(f"[coin_pool_sync] 检测到 v1 池，已按 v2 契约处理（source={top_source}）", file=sys.stderr)
    return data


def _validate_entry(item: dict, pool_name: str, idx: int, source: str) -> dict:
    """校验并规范化单条推荐，失败抛 ValueError"""
    sym = str(item.get("symbol", "")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", sym):
        raise ValueError(f"{pool_name}[{idx}] symbol 非法: {item.get('symbol')!r}")
    score = item.get("score", 0.5)
    try:
        score = float(score)
    except (TypeError, ValueError):
        raise ValueError(f"{pool_name}[{idx}] score 非数值: {item.get('score')!r}")
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{pool_name}[{idx}] score 超出 [0,1]: {score}")
    reasons = item.get("reasons", [])
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise ValueError(f"{pool_name}[{idx}] reasons 必须为字符串列表")
    return {
        "symbol": sym,
        "score": round(score, 4),
        "reasons": reasons[:10],
        "source": str(item.get("source", source)),
        "updated_at": str(item.get("updated_at", _now_iso())),
    }


def merge(pool: dict, recs: dict, source: str, replace_source: bool = False) -> dict:
    """按 symbol upsert 合并，返回统计。replace_source=True 时先移除本写入方的旧条目"""
    stats = {"added": 0, "updated": 0, "kept": 0, "removed_stale": 0}
    for key in ("long_pool", "short_pool"):
        incoming = recs.get(key, []) or []
        if not isinstance(incoming, list):
            raise ValueError(f"{key} 必须为列表")
        if len(incoming) > MAX_POOL_SIZE:
            raise ValueError(f"{key} 超过单池上限 {MAX_POOL_SIZE}")
        validated = [_validate_entry(it, key, i, source) for i, it in enumerate(incoming)]
        incoming_syms = {v["symbol"] for v in validated}

        existing = pool.get(key, []) or []
        if replace_source:
            kept_existing = [it for it in existing if str(it.get("source", "")) != source]
            stats["removed_stale"] += len(existing) - len(kept_existing)
            existing = kept_existing

        merged = list(validated)
        existing_syms = {str(it.get("symbol", "")).upper() for it in existing}
        for item in existing:
            sym = str(item.get("symbol", "")).upper()
            if sym and sym not in incoming_syms:
                # 其他写入方/上次残留的推荐，原样保留（v1 条目补默认字段）
                item.setdefault("source", pool.get("source", "unknown"))
                item.setdefault("updated_at", pool.get("timestamp", ""))
                merged.append(item)
                stats["kept"] += 1
        # 统计新增 vs 更新
        for v in validated:
            if v["symbol"] in existing_syms:
                stats["updated"] += 1
            else:
                stats["added"] += 1
        pool[key] = merged

    # 冲突标记：同时出现在多空两池的 symbol（只标记不销毁）
    long_syms = {it["symbol"] for it in pool.get("long_pool", [])}
    short_syms = {it["symbol"] for it in pool.get("short_pool", [])}
    pool["conflict_symbols"] = sorted(long_syms & short_syms)

    # 顶层元数据
    pool["version"] = SCHEMA_VERSION
    pool["timestamp"] = _now_iso()
    pool["source"] = source
    producers = pool.get("producers", []) or []
    if source not in producers:
        producers.append(source)
    pool["producers"] = producers
    return stats


def atomic_write(pool: dict) -> None:
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if POOL_FILE.exists():
        shutil.copy2(POOL_FILE, POOL_BACKUP)
    tmp = POOL_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, POOL_FILE)


def show() -> int:
    pool = load_pool()
    print(f"池文件: {POOL_FILE}")
    print(f"version={pool.get('version')} week={pool.get('week')!r} source(最后写入)={pool.get('source')!r}")
    print(f"producers: {pool.get('producers', [])}")
    print(f"timestamp: {pool.get('timestamp')}")
    for key, label in (("long_pool", "做多"), ("short_pool", "做空")):
        items = pool.get(key, [])
        print(f"\n【{label}池】{len(items)} 币:")
        for it in items:
            print(f"  {it.get('symbol'):<8} score={it.get('score'):<6} by {it.get('source', '?')} @ {it.get('updated_at', '?')}")
    if pool.get("conflict_symbols"):
        print(f"\n⚠️ 多空冲突 symbol: {pool['conflict_symbols']}")
    if pool.get("regime"):
        print(f"\nregime: {pool['regime']}")
    if pool.get("notes"):
        print(f"notes: {pool['notes']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="多空币池统一同步入口（独立池·多写入方）")
    ap.add_argument("--source", help="写入方名称，如 hermes-weekly / model-X")
    ap.add_argument("--file", help="推荐 JSON 文件路径")
    ap.add_argument("--stdin", action="store_true", help="从 stdin 读取推荐 JSON")
    ap.add_argument("--replace-source", action="store_true",
                    help="整周刷新语义：先移除本写入方的旧条目（其他写入方不受影响）")
    ap.add_argument("--week", help="覆盖周标签（默认当前 ISO 周）")
    ap.add_argument("--regime", help="本周 regime 描述（覆盖）")
    ap.add_argument("--notes", help="备注（覆盖）")
    ap.add_argument("--show", action="store_true", help="只读展示当前池")
    args = ap.parse_args()

    if args.show:
        return show()

    if not args.source:
        print("错误: 必须提供 --source <写入方>", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[A-Za-z0-9_\-]{2,40}", args.source):
        print(f"错误: source 非法: {args.source!r}（仅允许字母数字_-，2-40字符）", file=sys.stderr)
        return 1

    if args.stdin:
        raw = sys.stdin.read()
    elif args.file:
        try:
            raw = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"错误: 读取 {args.file} 失败: {e}", file=sys.stderr)
            return 1
    else:
        print("错误: 必须提供 --file 或 --stdin", file=sys.stderr)
        return 1

    try:
        recs = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"错误: 推荐 JSON 解析失败: {e}", file=sys.stderr)
        return 1
    if not isinstance(recs, dict) or not (recs.get("long_pool") or recs.get("short_pool")):
        print("错误: 推荐至少需包含非空 long_pool 或 short_pool", file=sys.stderr)
        return 1

    pool = load_pool()
    try:
        stats = merge(pool, recs, args.source, replace_source=args.replace_source)
    except ValueError as e:
        print(f"错误: 输入校验失败: {e}", file=sys.stderr)
        return 1

    if args.week:
        pool["week"] = args.week
    else:
        pool.setdefault("week", "") or pool.__setitem__("week", _iso_week())
        if not pool.get("week"):
            pool["week"] = _iso_week()
    if args.regime:
        pool["regime"] = args.regime
    if args.notes:
        pool["notes"] = args.notes

    try:
        atomic_write(pool)
    except OSError as e:
        print(f"错误: 写入池文件失败: {e}", file=sys.stderr)
        return 1

    print(
        f"[coin_pool_sync] 同步完成 source={args.source} | "
        f"新增={stats['added']} 更新={stats['updated']} 保留={stats['kept']}"
        + (f" 移除过期={stats['removed_stale']}" if stats.get("removed_stale") else "")
        + f" | 多={len(pool['long_pool'])} 空={len(pool['short_pool'])}"
        + (f" | 冲突={pool['conflict_symbols']}" if pool["conflict_symbols"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
