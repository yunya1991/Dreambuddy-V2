"""universe.py — U 层龙头宇宙投影（SPEC §2.3 / P0-B）。

原则：**不另立宇宙、不复制成员表**。
  - 成员 / instId / G 层归属的唯一真源 = `40-周期神经网络系统/asset_classes.py`
  - 本模块只持有本 SPEC 新增的信息（信号覆盖映射 `configs/leader_universe.json`）
  - 运行时把两者 join 成可消费的宇宙，并按月落 point-in-time 快照

为什么快照是硬要求：回测若用"今日宇宙"回看历史，会引入幸存者偏差（SPEC §2.3 纪律 2）。

用法：
    python universe.py --check      # 校验 10 大类 / 六锚 / 必备品种 / 价格主源
    python universe.py --snapshot   # 生成 runtime/universe_snapshots/leader_universe_<YYYYMM>.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]  # 48-涌现架构
CONFIG_PATH = _BASE / "configs" / "leader_universe.json"
SNAPSHOT_DIR = _BASE / "runtime" / "universe_snapshots"
CHANGE_LOG_PATH = _BASE / "runtime" / "universe_change_log.jsonl"
ASSET_CLASSES_MODULE = _BASE.parent / "40-周期神经网络系统" / "asset_classes.py"

REQUIRED_CLASSES = 10
SIGNAL_LAYERS = ("E", "S", "M", "P")


class UniverseError(RuntimeError):
    """宇宙投影不合规（缺类 / 缺锚 / 缺品种 / 成员被复制）。"""


def load_config(path: Path | None = None) -> dict:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def load_asset_classes(path: Path | None = None):
    """按文件路径加载 40 的常量模块（目录名含中文与短横线，不能常规 import）。"""
    target = Path(path or ASSET_CLASSES_MODULE)
    if not target.is_file():
        raise UniverseError(f"40 资产注册表不存在：{target}")
    spec = importlib.util.spec_from_file_location("dreambuddy_asset_classes", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deep_has_key(node, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(_deep_has_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_deep_has_key(v, key) for v in node)
    return False


def validate(config: dict, ac) -> list[str]:
    """返回违规列表（空 = 合规）。"""
    problems: list[str] = []
    classes = ac.ASSET_CLASSES

    if len(classes) != REQUIRED_CLASSES:
        problems.append(f"40 资产大类数={len(classes)}，期望 {REQUIRED_CLASSES}")

    coverage = config.get("signal_coverage", {})
    if set(coverage) != set(classes):
        problems.append(
            f"信号覆盖类别与 40 不一致：多 {set(coverage) - set(classes)}，缺 {set(classes) - set(coverage)}"
        )

    for cls, layers in coverage.items():
        unknown = set(layers) - set(SIGNAL_LAYERS)
        if unknown:
            problems.append(f"{cls} 含未知信号层 {sorted(unknown)}")
        if cls == "fx" and "P" in layers:
            problems.append("fx 为 G0 宏观，不应有 P 形态层")

    anchors = list(config.get("g1_anchors", []))
    if anchors != list(ac.G1_ANCHOR_SYMBOLS):
        problems.append(f"六锚不一致：config={anchors}，40={list(ac.G1_ANCHOR_SYMBOLS)}")
    for sym in anchors:
        if ac.class_of(sym) is None:
            problems.append(f"G1 锚 {sym} 未在 40 注册")

    for cls, symbols in config.get("required_symbols", {}).items():
        members = classes.get(cls, {}).get("members", [])
        for sym in symbols:
            if sym not in members:
                problems.append(f"{cls} 缺少必备品种 {sym}")

    for cls, cfg in classes.items():
        inst = cfg.get("inst_id")
        if cfg.get("session") == "macro_series_only":
            if inst is not None:
                problems.append(f"{cls} 为宏观序列，inst_id 应为 None")
        elif not str(inst or "").endswith("-USDT-SWAP"):
            problems.append(f"{cls} 价格主源不是 OKX 永续：{inst}")

    gold = config.get("price_source", {}).get("gold_dual_track", {})
    if gold.get("tradable") != ac.GOLD_DUAL_TRACK["tradable"]:
        problems.append("黄金双轨交易腿与 40 不一致")
    if gold.get("macro_reference") != ac.GOLD_DUAL_TRACK["macro_reference"]:
        problems.append("黄金双轨参考腿与 40 不一致")

    if _deep_has_key(config, "members"):
        problems.append("配置复制了成员表（应运行时从 40 投影，见 SPEC §2.3 纪律 3）")

    return problems


def load_universe(config: dict | None = None, ac=None) -> dict:
    """把 40 的成员表与信号覆盖 join 成可消费宇宙；不合规直接抛错。"""
    config = config or load_config()
    ac = ac or load_asset_classes()
    problems = validate(config, ac)
    if problems:
        raise UniverseError("宇宙校验失败：\n" + "\n".join(f"- {p}" for p in problems))

    classes = {}
    for cls, cfg in ac.ASSET_CLASSES.items():
        classes[cls] = {
            "leader": cfg["leader"],
            "inst_id": cfg.get("inst_id"),
            "g1_anchor": bool(cfg.get("g1_anchor")),
            "session": cfg.get("session"),
            "members": list(cfg.get("members", [])),
            "signals": dict(config["signal_coverage"][cls]),
        }
    return {
        "version": config.get("version", "v1"),
        "source_of_truth": config["source_of_truth"],
        "universe_reviewed_at": config["universe_reviewed_at"],
        "price_source": config["price_source"],
        "g1_anchors": list(config["g1_anchors"]),
        "classes": classes,
    }


def _digest(classes: dict) -> str:
    return hashlib.sha256(
        json.dumps(classes, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def snapshot(universe: dict | None = None, now: datetime | None = None) -> dict:
    """写当月 point-in-time 快照；成员变更才追加 change log（幂等）。"""
    universe = universe or load_universe()
    now = now or datetime.now(timezone.utc)
    digest = _digest(universe["classes"])

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"leader_universe_{now.strftime('%Y%m')}.json"
    payload = {
        "snapshot_at": now.isoformat(),
        "universe_reviewed_at": universe["universe_reviewed_at"],
        "source_of_truth": universe["source_of_truth"],
        "digest": digest,
        "g1_anchors": universe["g1_anchors"],
        "price_source": universe["price_source"],
        "classes": universe["classes"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    changed = True
    if CHANGE_LOG_PATH.is_file():
        last = [
            line
            for line in CHANGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if last:
            changed = json.loads(last[-1]).get("digest") != digest
    if changed:
        CHANGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CHANGE_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "changed_at": now.isoformat(),
                        "digest": digest,
                        "edge_count": sum(len(c["members"]) for c in universe["classes"].values()),
                        "class_count": len(universe["classes"]),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {"path": str(path), "digest": digest, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description="U 层龙头宇宙投影")
    parser.add_argument("--check", action="store_true", help="只校验不落盘")
    parser.add_argument("--snapshot", action="store_true", help="生成当月快照 + 变更日志")
    args = parser.parse_args()

    try:
        universe = load_universe()
    except UniverseError as exc:
        print(f"[FAIL] {exc}")
        return 1

    n_members = sum(len(c["members"]) for c in universe["classes"].values())
    print(
        f"[OK] {len(universe['classes'])} 大类 / {n_members} 标的 / 六锚 {universe['g1_anchors']}"
    )
    if args.snapshot:
        print(json.dumps(snapshot(universe), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
