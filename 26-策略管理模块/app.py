"""
26-策略管理模块 - Flask 服务（端口 8093）

双层接口：
- 中台层 /api/v1/lib/*  只读 + admin token 写入
- 用户层 /api/v1/user/*  CRUD（用户策略空间）
- 代理层 /api/v1/agent/*  策略发现 + 回测触发代理
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request

from strategy_lib.services import registry as reg

app = Flask(__name__)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token, X-User-Id"
    return resp


# Admin token（环境变量配置，默认开发用 token）
ADMIN_TOKEN = os.environ.get("STRATEGY_LIB_ADMIN_TOKEN", "dev-admin-token-2026")

# 用户策略存储目录
USER_STRATEGIES_DIR = Path(__file__).resolve().parent / "data" / "registry" / "user"
USER_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

# Freqtrade 配置
_FREQTRADE_BIN = os.environ.get("FREQTRADE_BIN", "/opt/anaconda3/bin/freqtrade")
_CLASSIC_ROOT = Path(__file__).resolve().parents[1] / "10-经典指标系统"
_USER_DATA_DIR = _CLASSIC_ROOT / "user_data"
_STRATEGIES_DIR = _USER_DATA_DIR / "strategies"

# M25 回测引擎（用于回测触发代理）
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "25-用户策略生成系统"))


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------

def _require_admin() -> bool:
    """检查 admin token"""
    token = request.headers.get("X-Admin-Token", "")
    return token == ADMIN_TOKEN


def _user_id() -> str:
    """获取用户 ID（从 header 或默认）"""
    return request.headers.get("X-User-Id", "default")


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    try:
        data = reg._strategy_registry_load()
        return jsonify({"ok": True, "entries": len(data.get("entries", {}))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 中台层接口（只读 + admin 写入）
# ---------------------------------------------------------------------------

@app.route("/api/v1/lib/strategies", methods=["GET"])
def lib_list_strategies():
    """列出所有中台策略"""
    try:
        data = reg._strategy_registry_load()
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        items = []
        for k, v in entries.items():
            if isinstance(v, dict):
                items.append({
                    "strategy_id": v.get("strategy_id"),
                    "source_zip": v.get("source_zip"),
                    "family": v.get("family"),
                    "stage": v.get("stage"),
                    "tier": v.get("tier"),
                    "tags": v.get("tags", []),
                    "updated_at": v.get("updated_at"),
                })
        return jsonify({"ok": True, "entries": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/lib/strategies/<strategy_id>", methods=["GET"])
def lib_get_strategy(strategy_id):
    """获取中台策略详情"""
    source_zip = request.args.get("source_zip", "")
    try:
        entry = reg._strategy_registry_get_entry(strategy_id, source_zip)
        if not entry:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "entry": entry})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/lib/strategies/<strategy_id>/events", methods=["GET"])
def lib_get_strategy_events(strategy_id):
    """获取中台策略事件历史"""
    source_zip = request.args.get("source_zip", "")
    try:
        events = reg._strategy_registry_events_tail(strategy_id=strategy_id, source_zip=source_zip)
        return jsonify({"ok": True, "events": events or []})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/lib/tiers", methods=["GET"])
def lib_get_tiers():
    """获取 tier 分级标准"""
    return jsonify({
        "ok": True,
        "tiers": [
            {"tier": "A", "label": "核心策略", "criteria": "多市场验证通过，robustness=pass"},
            {"tier": "B", "label": "稳定策略", "criteria": "回测达标，稳健性良好"},
            {"tier": "C", "label": "实验策略", "criteria": "初步验证，需更多数据"},
            {"tier": "D", "label": "淘汰策略", "criteria": "不达标或已退役"},
        ],
    })


@app.route("/api/v1/lib/strategies/upsert", methods=["POST"])
def lib_upsert_strategy():
    """中台写入策略（需 admin token）"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    try:
        body = request.get_json(force=True) or {}
        data = reg._strategy_registry_load()
        entries = data.setdefault("entries", {})
        sid = str(body.get("strategy_id") or "").strip()
        z = str(body.get("source_zip") or "").strip()
        if not sid or not z:
            return jsonify({"ok": False, "error": "strategy_id and source_zip required"}), 400
        key = reg._strategy_registry_key(sid, z)
        entry = entries.get(key, {})
        entry.update(body)
        entry["strategy_id"] = sid
        entry["source_zip"] = z
        entries[key] = entry
        reg._strategy_registry_save(data)
        return jsonify({"ok": True, "entry": entry})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/lib/strategies/event", methods=["POST"])
def lib_record_event():
    """中台记录策略事件（需 admin token）"""
    if not _require_admin():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    try:
        body = request.get_json(force=True) or {}
        # 事件写入 events 文件
        events_path = reg._strategy_registry_events_path()
        events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": body.get("ts"),
            "strategy_id": body.get("strategy_id"),
            "source_zip": body.get("source_zip"),
            "action": body.get("action"),
            "actor": body.get("actor"),
            "note": body.get("note", ""),
        }
        with events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# 用户层接口（CRUD）
# ---------------------------------------------------------------------------

def _user_strategies_path(uid: str) -> Path:
    return USER_STRATEGIES_DIR / uid / "strategies.json"


def _load_user_strategies(uid: str) -> Dict[str, Any]:
    p = _user_strategies_path(uid)
    if not p.exists():
        return {"entries": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": {}}


def _save_user_strategies(uid: str, data: Dict[str, Any]) -> bool:
    p = _user_strategies_path(uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


@app.route("/api/v1/user/strategies", methods=["GET"])
def user_list_strategies():
    """列出用户策略"""
    uid = _user_id()
    data = _load_user_strategies(uid)
    entries = data.get("entries", {})
    items = [v for v in entries.values() if isinstance(v, dict)]
    return jsonify({"ok": True, "strategies": items})


@app.route("/api/v1/user/strategies", methods=["POST"])
def user_create_strategy():
    """创建用户策略"""
    uid = _user_id()
    body = request.get_json(force=True) or {}
    sid = str(body.get("strategy_id") or f"user_{uuid.uuid4().hex[:8]}").strip()
    data = _load_user_strategies(uid)
    entries = data.setdefault("entries", {})
    body["strategy_id"] = sid
    body["owner"] = uid
    entries[sid] = body
    _save_user_strategies(uid, data)
    return jsonify({"ok": True, "id": sid, "strategy": body})


@app.route("/api/v1/user/strategies/<sid>", methods=["PUT"])
def user_update_strategy(sid):
    """更新用户策略"""
    uid = _user_id()
    body = request.get_json(force=True) or {}
    data = _load_user_strategies(uid)
    entries = data.get("entries", {})
    if sid not in entries:
        return jsonify({"ok": False, "error": "not_found"}), 404
    entries[sid].update(body)
    entries[sid]["strategy_id"] = sid
    _save_user_strategies(uid, data)
    return jsonify({"ok": True, "strategy": entries[sid]})


@app.route("/api/v1/user/strategies/<sid>", methods=["DELETE"])
def user_delete_strategy(sid):
    """删除用户策略"""
    uid = _user_id()
    data = _load_user_strategies(uid)
    entries = data.get("entries", {})
    if sid not in entries:
        return jsonify({"ok": False, "error": "not_found"}), 404
    del entries[sid]
    _save_user_strategies(uid, data)
    return jsonify({"ok": True})


@app.route("/api/v1/user/strategies/<sid>/clone", methods=["POST"])
def user_clone_strategy(sid):
    """从中台克隆策略到用户空间"""
    uid = _user_id()
    # 从中台获取策略
    source_zip = request.args.get("source_zip", "")
    entry = reg._strategy_registry_get_entry(sid, source_zip)
    if not entry:
        return jsonify({"ok": False, "error": "central_strategy_not_found"}), 404
    # 克隆到用户空间
    user_sid = f"{sid}_user_{uuid.uuid4().hex[:6]}"
    cloned = dict(entry)
    cloned["strategy_id"] = user_sid
    cloned["source_zip"] = entry.get("source_zip", "")
    cloned["owner"] = uid
    cloned["cloned_from"] = sid
    data = _load_user_strategies(uid)
    data.setdefault("entries", {})[user_sid] = cloned
    _save_user_strategies(uid, data)
    return jsonify({"ok": True, "user_strategy_id": user_sid, "strategy": cloned})


# ---------------------------------------------------------------------------
# 代理层：策略发现 + 回测触发代理
# ---------------------------------------------------------------------------

def _parse_strategy_table(stdout: str) -> List[Dict[str, Any]]:
    """解析 freqtrade list-strategies 的表格输出。"""
    strategies = []
    lines = stdout.split("\n")
    in_table = False
    for line in lines:
        # 表格行以 │ 开头
        if line.startswith("│") or line.startswith("┃"):
            # 跳过分隔行
            if "━" in line or "─" in line:
                continue
            in_table = True
            # 按 │ 分割
            cells = [c.strip() for c in re.split(r"[│┃]", line) if c.strip()]
            if len(cells) >= 7 and cells[0] != "Strategy name":
                strategies.append({
                    "name": cells[0],
                    "file": cells[1],
                    "status": cells[2],
                    "hyperoptable": cells[3] == "Yes",
                    "buy_params": int(cells[4]) if cells[4].isdigit() else 0,
                    "sell_params": int(cells[5]) if cells[5].isdigit() else 0,
                    "protection_params": int(cells[6]) if cells[6].isdigit() else 0,
                })
    return strategies


@app.route("/api/v1/agent/discover", methods=["GET"])
def agent_discover_strategies():
    """策略自动发现：调用 freqtrade list-strategies。"""
    try:
        cmd = [
            _FREQTRADE_BIN, "list-strategies",
            "--userdir", str(_USER_DATA_DIR),
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_CLASSIC_ROOT)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            env=env, cwd=str(_CLASSIC_ROOT),
        )
        if result.returncode != 0:
            return jsonify({"ok": False, "error": result.stderr[-500:]}), 500

        strategies = _parse_strategy_table(result.stdout)
        # 过滤重复名策略
        seen = set()
        unique = []
        for s in strategies:
            if s["name"] not in seen and s["status"] == "OK":
                seen.add(s["name"])
                unique.append(s)
        return jsonify({"ok": True, "strategies": unique, "total": len(unique)})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "timeout"}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/agent/backtest", methods=["POST"])
def agent_trigger_backtest():
    """回测触发代理：调用 M25 run_backtest。"""
    try:
        from strategy_gen.backtest_engine import run_backtest
        body = request.get_json(force=True) or {}
        strategy_id = body.get("strategy_id")
        if not strategy_id:
            return jsonify({"ok": False, "error": "strategy_id required"}), 400

        result = run_backtest(
            strategy_id,
            timeframe=body.get("timeframe"),
            timerange=body.get("timerange"),
            pairs=body.get("pairs"),
            stake_amount=body.get("stake_amount"),
            max_open_trades=body.get("max_open_trades"),
            fee=body.get("fee"),
        )
        return jsonify(result)
    except ImportError as e:
        return jsonify({"ok": False, "error": f"backtest_engine_import_error: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v1/agent/paramopt", methods=["POST"])
def agent_trigger_paramopt():
    """参数优化代理：调用 M25 paramopt。"""
    try:
        from strategy_gen.paramopt import paramopt
        body = request.get_json(force=True) or {}
        strategy_id = body.get("strategy_id")
        if not strategy_id:
            return jsonify({"ok": False, "error": "strategy_id required"}), 400

        result = paramopt(
            strategy_id,
            epochs=body.get("epochs", 50),
            spaces=body.get("spaces", ["buy", "sell"]),
            timerange=body.get("timerange"),
            pairs=body.get("pairs"),
        )
        return jsonify(result)
    except ImportError as e:
        return jsonify({"ok": False, "error": f"paramopt_import_error: {e}"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("STRATEGY_LIB_PORT", "8093"))
    app.run(host="127.0.0.1", port=port, debug=False)
