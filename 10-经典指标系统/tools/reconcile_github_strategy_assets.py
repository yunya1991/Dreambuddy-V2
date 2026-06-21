import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
 
 
def _safe_seg(s: str, *, fallback: str = "x", max_len: int = 80) -> str:
    raw = "" if s is None else str(s)
    raw = raw.strip()
    if not raw:
        return fallback
    raw = raw.replace(":", "__")
    out: List[str] = []
    last_us = False
    for ch in raw:
        ok = ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in {"-", "_", ".", "@"}
        if ok:
            out.append(ch)
            last_us = False
        else:
            if not last_us:
                out.append("_")
                last_us = True
    s2 = "".join(out).strip("._-")
    if not s2:
        s2 = fallback
    if len(s2) > int(max_len):
        s2 = s2[: int(max_len)]
    return s2
 
 
def _read_text(p: Path, *, max_bytes: int = 800_000) -> str:
    try:
        b = p.read_bytes()
    except Exception:
        return ""
    if len(b) > int(max_bytes):
        b = b[: int(max_bytes)]
    try:
        return b.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return b.decode(errors="ignore")
        except Exception:
            return ""
 
 
def _contains_class(text: str, cls: str) -> bool:
    if not cls:
        return False
    low = text.lower()
    c = cls.lower()
    return (f"class {c}" in low) or (f"class\t{c}" in low)
 
 
def _infer_market(text: str) -> str:
    low = text.lower()
    if "can_short" in low and "true" in low:
        return "futures"
    if "def leverage" in low or "leverage_mode" in low:
        return "futures"
    return "spot"
 
 
def _infer_timeframe(text: str) -> str:
    m = re.search(r"timeframe\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not m:
        return "unknown"
    tf = str(m.group(1) or "").strip()
    if not tf:
        return "unknown"
    tf = tf.replace(" ", "")
    return tf[:20]
 
 
def _infer_family(text: str, name: str) -> str:
    low = (text or "").lower()
    nm = (name or "").lower()
    if "carry" in nm or "funding" in low or "funding_rate" in low:
        return "carry"
    if "breakout" in nm or "donchian" in low or "breakout" in low:
        return "breakout"
    mr_hits = 0
    for kw in ("mean_reversion", "mean reversion", "reversion", "bollinger", "bbands", "zscore", "z-score"):
        if kw in low:
            mr_hits += 1
    if mr_hits >= 2:
        return "mean_reversion"
    return "trend"
 
 
def _infer_stage(path: Path) -> str:
    s = "/".join([str(x).lower() for x in path.parts])
    if "/deployment/" in s or s.endswith("/deployment"):
        return "deployment"
    if "/model/" in s or s.endswith("/model"):
        return "model"
    return "research"
 
 
def _infer_indicator_tags(text: str) -> List[str]:
    low = text.lower()
    tags: List[str] = []
    table = [
        ("supertrend", "supertrend"),
        ("adx", "adx"),
        ("rsi", "rsi"),
        ("macd", "macd"),
        ("bollinger", "bbands"),
        ("bbands", "bbands"),
        ("ema", "ema"),
        ("sma", "sma"),
        ("atr", "atr"),
        ("ott", "ott"),
        ("ichimoku", "ichimoku"),
    ]
    for kw, tag in table:
        if kw in low and tag not in tags:
            tags.append(tag)
    if "intparameter" in low or "decimalparameter" in low or "categoricalparameter" in low:
        tags.append("hyperopt")
    if "informative" in low or "merge_informative_pair" in low:
        tags.append("mtf")
    if "protections" in low:
        tags.append("protections")
    if "trailing_stop" in low:
        tags.append("trailing")
    if "stoploss" in low:
        tags.append("stoploss")
    return tags[:12]
 
 
def _symlink_or_copy(src: Path, dst: Path) -> Tuple[bool, str]:
    sp = Path(src)
    dp = Path(dst)
    try:
        dp.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        if dp.exists() or dp.is_symlink():
            try:
                if dp.is_symlink():
                    cur = os.readlink(str(dp))
                    if str(cur) == str(sp):
                        return True, "kept"
                dp.unlink()
            except Exception:
                try:
                    if dp.exists() and dp.is_file():
                        dp.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        os.symlink(str(sp), str(dp))
        return True, "symlink"
    except Exception:
        try:
            shutil.copy2(sp, dp)
            return True, "copy"
        except Exception as e:
            return False, str(e)
 
 
@dataclass(frozen=True)
class StrategyAsset:
    src_path: Path
    repo_slug: str
    rel_dir: str
    strategy_name: str
    family: str
    stage: str
    tier: str
    market: str
    timeframe: str
    tags: List[str]
    text_has_class: bool
 
 
def _collect_assets(root: Path) -> Tuple[List[StrategyAsset], List[Dict[str, str]]]:
    items: List[StrategyAsset] = []
    errs: List[Dict[str, str]] = []
    for p in root.rglob("*.py"):
        parts = p.parts
        if "__pycache__" in parts:
            continue
        if any(seg.startswith("_by_") for seg in parts):
            continue
        if any(seg in {"_reports"} for seg in parts):
            continue
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root)
        except Exception:
            rel = Path(p.name)
        repo_slug = _safe_seg((rel.parts[0] if len(rel.parts) >= 2 else "unknown_repo"), fallback="unknown_repo", max_len=120)
        rel_dir = str(rel.parent) if str(rel.parent) != "." else ""
        st_name = p.stem
        text = _read_text(p)
        has_cls = _contains_class(text, st_name)
        family = _infer_family(text, st_name)
        stage = _infer_stage(p)
        tier = "UNRATED"
        market = _infer_market(text)
        timeframe = _infer_timeframe(text)
        tags = _infer_indicator_tags(text)
        tags = [market] + tags
        dedup: List[str] = []
        for t in tags:
            s = str(t or "").strip()
            if not s:
                continue
            if s not in dedup:
                dedup.append(s)
        items.append(
            StrategyAsset(
                src_path=p,
                repo_slug=repo_slug,
                rel_dir=rel_dir,
                strategy_name=st_name,
                family=family,
                stage=stage,
                tier=tier,
                market=market,
                timeframe=timeframe,
                tags=dedup[:16],
                text_has_class=bool(has_cls),
            )
        )
    items.sort(key=lambda x: (x.repo_slug, x.strategy_name, str(x.src_path)))
    return items, errs
 
 
def _pick_best_by_key(assets: List[StrategyAsset]) -> Dict[Tuple[str, str], StrategyAsset]:
    best: Dict[Tuple[str, str], StrategyAsset] = {}
    for a in assets:
        k = (a.repo_slug, a.strategy_name)
        prev = best.get(k)
        if prev is None:
            best[k] = a
            continue
        if a.text_has_class and not prev.text_has_class:
            best[k] = a
            continue
        if (not a.text_has_class) and prev.text_has_class:
            continue
        try:
            sa = a.src_path.stat().st_size
        except Exception:
            sa = -1
        try:
            sb = prev.src_path.stat().st_size
        except Exception:
            sb = -1
        if sa > sb:
            best[k] = a
    return best
 
 
def _ensure_dirs(root: Path) -> Dict[str, Path]:
    cats = {
        "_by_family": root / "_by_family",
        "_by_stage": root / "_by_stage",
        "_by_tier": root / "_by_tier",
        "_by_market": root / "_by_market",
        "_by_timeframe": root / "_by_timeframe",
        "_by_tag": root / "_by_tag",
        "_by_repo": root / "_by_repo",
        "_reports": root / "_reports",
    }
    for p in cats.values():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return cats
 
 
def _canonical_mirror(root: Path, repo_slug: str, rel_dir: str, strategy_name: str) -> Path:
    p = root / _safe_seg(repo_slug, fallback="unknown_repo", max_len=120)
    if rel_dir:
        segs = [x for x in rel_dir.replace("\\", "/").split("/") if x and x not in {".", ".."}]
        if segs and segs[0] == repo_slug:
            segs = segs[1:]
        for seg in segs[:10]:
            p = p / _safe_seg(seg, fallback="p", max_len=80)
    name = _safe_seg(strategy_name, fallback="strategy", max_len=140)
    if not name.lower().endswith(".py"):
        name += ".py"
    return p / name
 
 
def _reset_derived_dirs(root: Path) -> None:
    try:
        for p in root.iterdir():
            if p.is_dir() and p.name.startswith("_by_"):
                shutil.rmtree(p)
    except Exception:
        pass


def reconcile(*, root: Path, dry_run: bool, reset_derived: bool) -> Dict[str, object]:
    if reset_derived and (not dry_run):
        _reset_derived_dirs(root)
    cats = _ensure_dirs(root)
    assets, errs = _collect_assets(root)
    best = _pick_best_by_key(assets)
 
    actions: List[Dict[str, object]] = []
    mirrored: List[Dict[str, object]] = []
    linked: List[Dict[str, object]] = []
 
    for (repo_slug, st_name), a in best.items():
        mirror = _canonical_mirror(root, repo_slug, a.rel_dir, st_name)
        if mirror.resolve() != a.src_path.resolve():
            if not mirror.exists():
                act = {"type": "mirror_copy", "src": str(a.src_path), "dst": str(mirror)}
                actions.append(act)
                if not dry_run:
                    try:
                        mirror.parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                    shutil.copy2(a.src_path, mirror)
            mirrored.append({"strategy": st_name, "repo": repo_slug, "mirror": str(mirror)})
        else:
            mirrored.append({"strategy": st_name, "repo": repo_slug, "mirror": str(mirror)})
 
        base = f"{_safe_seg(repo_slug, fallback='repo', max_len=80)}__{_safe_seg(st_name, fallback='strategy', max_len=140)}.py"
        targets: List[Tuple[str, Path]] = []
        targets.append(("family", cats["_by_family"] / _safe_seg(a.family, fallback="trend", max_len=40) / base))
        targets.append(("stage", cats["_by_stage"] / _safe_seg(a.stage, fallback="research", max_len=40) / base))
        targets.append(("tier", cats["_by_tier"] / _safe_seg(a.tier, fallback="UNRATED", max_len=40) / base))
        targets.append(("market", cats["_by_market"] / _safe_seg(a.market, fallback="unknown", max_len=40) / base))
        targets.append(("timeframe", cats["_by_timeframe"] / _safe_seg(a.timeframe, fallback="unknown", max_len=40) / base))
        targets.append(("repo", cats["_by_repo"] / _safe_seg(repo_slug, fallback="repo", max_len=80) / base))
        for t in a.tags[:10]:
            targets.append(("tag", cats["_by_tag"] / _safe_seg(t, fallback="tag", max_len=60) / base))
 
        for kind, dst in targets:
            if dry_run:
                linked.append({"ok": True, "dry_run": True, "kind": kind, "dst": str(dst), "src": str(mirror)})
                continue
            ok, mode = _symlink_or_copy(mirror, dst)
            linked.append({"ok": bool(ok), "mode": mode, "kind": kind, "dst": str(dst), "src": str(mirror)})
 
    return {
        "ok": True,
        "ts": int(time.time() * 1000),
        "root": str(root),
        "dry_run": bool(dry_run),
        "n_seen_py": int(len(assets)),
        "n_unique": int(len(best)),
        "mirrored": mirrored,
        "actions": actions,
        "links": linked,
        "errors": errs,
    }
 
 
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="user_data/strategies/github")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-report", action="store_true")
    ap.add_argument("--reset-derived", action="store_true")
    ns = ap.parse_args(argv)
 
    cwd = Path(os.getcwd())
    root = Path(ns.root)
    if not root.is_absolute():
        root = cwd / root
    root = root.resolve()
 
    out = reconcile(root=root, dry_run=bool(ns.dry_run), reset_derived=bool(ns.reset_derived))
    print(json.dumps(out, ensure_ascii=False, indent=2))
 
    if bool(ns.write_report):
        rep_dir = root / "_reports"
        try:
            rep_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        name = f"asset_reconcile_{int(time.time())}.json"
        p = rep_dir / name
        try:
            p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            try:
                p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
            except Exception:
                pass
 
    return 0 if bool(out.get("ok")) else 1
 
 
if __name__ == "__main__":
    raise SystemExit(main())
