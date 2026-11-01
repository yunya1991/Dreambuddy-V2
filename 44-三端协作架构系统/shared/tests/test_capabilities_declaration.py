"""C6 能力声明（capabilities.yaml）契约测试（进 G0-4 阻断 job）。

覆盖：五能力齐全且唯一、Schema 字段、port 可解析、provides.impl 文件+符号存在、
requirements 引用有效、status 枚举、校验脚本可拦截漂移。
"""

import json
import os
import subprocess
import sys
import tempfile

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DECL_PATH = os.path.join(REPO_ROOT, "0-系统文档管理", "capabilities.yaml")
VALIDATOR = os.path.join(REPO_ROOT, "scripts", "validate_capabilities.py")

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


def _load():
    with open(DECL_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_declaration_file_exists_and_parses():
    assert os.path.exists(DECL_PATH), "capabilities.yaml 未落盘"
    doc = _load()
    assert isinstance(doc, dict) and isinstance(doc.get("capabilities"), list)


def test_five_capabilities_declared_and_unique():
    caps = _load()["capabilities"]
    ids = [c["capability_id"] for c in caps]
    assert len(ids) == len(set(ids)) == 5
    assert set(ids) == REQUIRED_IDS


def test_schema_fields_and_status_enum():
    for c in _load()["capabilities"]:
        missing = REQUIRED_FIELDS - set(c)
        assert not missing, f"{c.get('capability_id')} 缺字段 {missing}"
        assert c["status"] in STATUS_ENUM, f"{c['capability_id']} status 非法"
        assert (
            isinstance(c["provides"], list) and c["provides"]
        ), f"{c['capability_id']} provides 不能为空"


def test_ports_resolve_to_protocol_modules():
    for c in _load()["capabilities"]:
        assert c["port"] in PORT_ENUM, f"{c['capability_id']} port={c['port']} 不在六 port 内"
        p = os.path.join(REPO_ROOT, "dreambuddy_l0", "ports", c["port"] + ".py")
        assert os.path.exists(p), f"port 模块缺失: {p}"


def test_provides_impl_files_and_symbols_exist():
    for c in _load()["capabilities"]:
        for item in c["provides"]:
            assert isinstance(item, dict) and "name" in item and "impl" in item
            path, _, symbol = item["impl"].partition("::")
            assert path and symbol, f"{c['capability_id']} impl 格式应为 path::symbol"
            full = os.path.join(REPO_ROOT, path)
            assert os.path.exists(full), f"impl 文件缺失: {path}"
            with open(full, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            assert symbol in text, f"{path} 未找到符号 {symbol}（声明漂移）"


def test_requirements_reference_existing_capabilities():
    doc = _load()
    ids = {c["capability_id"] for c in doc["capabilities"]}
    for c in doc["capabilities"]:
        for r in c.get("requirements") or []:
            assert r in ids, f"{c['capability_id']} 依赖不存在的能力 {r}"


def test_validator_cli_passes():
    r = subprocess.run(
        [sys.executable, VALIDATOR, "--repo-root", REPO_ROOT], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def test_validator_detects_port_drift():
    doc = json.loads(json.dumps(_load()))  # 深拷贝
    doc["capabilities"][0]["port"] = "nope"
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "capabilities.yaml")
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True)
        r = subprocess.run(
            [sys.executable, VALIDATOR, "--repo-root", REPO_ROOT, "--file", p],
            capture_output=True,
            text=True,
        )
    assert r.returncode != 0
    assert "nope" in r.stdout + r.stderr


def test_validator_detects_impl_drift():
    doc = json.loads(json.dumps(_load()))
    doc["capabilities"][1]["provides"][0][
        "impl"
    ] = "18-数据获取中心/data_center/collectors/_base.py::NoSuchSymbol"
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "capabilities.yaml")
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True)
        r = subprocess.run(
            [sys.executable, VALIDATOR, "--repo-root", REPO_ROOT, "--file", p],
            capture_output=True,
            text=True,
        )
    assert r.returncode != 0
    assert "NoSuchSymbol" in r.stdout + r.stderr
