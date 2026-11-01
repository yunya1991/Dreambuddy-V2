#!/usr/bin/env python3
"""C6 能力声明校验（SPEC-L0 §6 / SPEC-C L0-I；接入 G0-4 阻断 job）。

文件即能力地图：0-系统文档管理/capabilities.yaml 为唯一事实源。
校验：五能力齐全且唯一、Schema 字段、status 枚举、port 可解析、
provides.impl 文件+符号存在（防声明漂移）、requirements 引用有效。
失败即 exit 1（CI 变红）。
"""

import argparse
import json
import os
import sys

REQUIRED_IDS = {"l0.cognition", "l0.data", "l0.search", "l0.store", "l0.rea"}
REQUIRED_FIELDS = {
    "capability_id",
    "category",
    "name",
    "provides",
    "consumes",
    "health_cmd",
    "port",
    "requirements",
    "status",
}
STATUS_ENUM = {"available", "degraded", "unavailable"}
PORT_ENUM = {"memory", "collector", "search", "store", "analysis", "event"}
DEFAULT_FILE = os.path.join("0-系统文档管理", "capabilities.yaml")


def _load_yaml(path):
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - CI 已安装 pyyaml
        raise SystemExit(f"需要 PyYAML：{e}") from e
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _repo_root(cli_root):
    if cli_root:
        return os.path.abspath(cli_root)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def validate(doc, root):
    """返回 (errors, summary)。errors 非空即失败。"""
    errors = []
    caps = (doc or {}).get("capabilities")
    if not isinstance(caps, list) or not caps:
        return ["capabilities 缺失或不是列表"], {}

    ids = []
    for cap in caps:
        cid = cap.get("capability_id", "<missing>")
        missing = REQUIRED_FIELDS - set(cap)
        if missing:
            errors.append(f"{cid}: 缺字段 {sorted(missing)}")
        if cap.get("status") not in STATUS_ENUM:
            errors.append(f"{cid}: status={cap.get('status')!r} 不在 {sorted(STATUS_ENUM)}")
        port = cap.get("port")
        if port not in PORT_ENUM:
            errors.append(f"{cid}: port={port!r} 不在六 port 内")
        else:
            pmod = os.path.join(root, "dreambuddy_l0", "ports", f"{port}.py")
            if not os.path.exists(pmod):
                errors.append(f"{cid}: port 模块缺失 {pmod}")
        provides = cap.get("provides") or []
        if not isinstance(provides, list) or not provides:
            errors.append(f"{cid}: provides 不能为空")
        names = set()
        for item in provides:
            if not isinstance(item, dict) or "name" not in item or "impl" not in item:
                errors.append(f"{cid}: provides 条目需含 name/impl")
                continue
            if item["name"] in names:
                errors.append(f"{cid}: provides 名称重复 {item['name']}")
            names.add(item["name"])
            path, sep, symbol = str(item["impl"]).partition("::")
            if not sep or not path or not symbol:
                errors.append(f"{cid}: impl 格式应为 path::symbol（{item['impl']}）")
                continue
            full = os.path.join(root, path)
            if not os.path.exists(full):
                errors.append(f"{cid}: impl 文件缺失 {path}")
                continue
            with open(full, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            if symbol not in text:
                errors.append(f"{cid}: {path} 未找到符号 {symbol}（声明漂移）")
        if not isinstance(cap.get("health_cmd"), str) or not cap["health_cmd"].strip():
            errors.append(f"{cid}: health_cmd 不能为空")
        ids.append(cid)
        if cap.get("requirements"):
            pass  # 引用校验在收集完全部 id 后执行

    if len(ids) != len(set(ids)):
        errors.append("capability_id 存在重复")
    if set(ids) != REQUIRED_IDS:
        errors.append(
            f"五能力集合不匹配：缺少 {sorted(REQUIRED_IDS - set(ids))}，"
            f"多出 {sorted(set(ids) - REQUIRED_IDS)}"
        )
    for cap in caps:
        for req in cap.get("requirements") or []:
            if req not in set(ids):
                errors.append(f"{cap.get('capability_id')}: 依赖不存在的能力 {req}")

    summary = {
        "capabilities": len(caps),
        "ids": sorted(ids),
        "provides_total": sum(len(c.get("provides") or []) for c in caps),
        "ports": sorted({c.get("port") for c in caps if c.get("port")}),
    }
    return errors, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="校验 L0 能力声明 capabilities.yaml")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--file", default=None)
    args = ap.parse_args(argv)
    root = _repo_root(args.repo_root)
    path = args.file or os.path.join(root, DEFAULT_FILE)
    if not os.path.exists(path):
        print(f"FAIL: 能力声明文件不存在 {path}")
        return 1
    errors, summary = validate(_load_yaml(path), root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        print(f"FAIL: {len(errors)} 项校验失败")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 能力声明与实现一致（五能力 / port / provides.impl 无漂移）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
