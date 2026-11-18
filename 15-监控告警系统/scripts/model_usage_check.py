#!/usr/bin/env python3
"""模型用量告警：小时级抓取供应商余额，推算消耗速率与可用天数，异常推飞书。

监控项（以 DeepSeek 余额接口为准，覆盖全部调用方的真实消耗，不依赖调用埋点）：
  1. 余额低于下限 → P1；低于预警线 → P2
  2. 按 7 日均消耗推算可用天数不足 → P2
  3. 近 24h 消耗相对基线突增（充值/异常重试/死循环） → P2
  4. 余额接口 401/不可用 → P1（凭证失效或额度中断，推理链会静默断供）

只读余额接口，不修改业务配置；快照落 logs/model-usage/，告警经 receiver 推飞书，
同一告警 6h 内去重。

用法：
  python3 scripts/model_usage_check.py --push
  python3 scripts/model_usage_check.py --dry-run --json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = BASE_DIR / "config/model_usage.json"
DEFAULT_REPO = BASE_DIR.parent
DEFAULT_STATE = Path.home() / ".cache/dreambuddy-model-usage.json"

CURRENCY_SYMBOL = {"CNY": "¥", "USD": "$"}


# ────────────────────────────── 基础工具 ──────────────────────────────


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_config(path: Path) -> dict:
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        raise SystemExit(f"配置读取失败: {path}")
    return cfg


def read_env_value(path: Path, key: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def parse_ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def fmt_money(currency: str, value) -> str:
    symbol = CURRENCY_SYMBOL.get(str(currency or "").upper(), "")
    try:
        return f"{symbol}{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


# ────────────────────────────── 余额采集 ──────────────────────────────


def fetch_deepseek_balance(base_url: str, api_key: str, timeout: float = 15) -> dict:
    url = base_url.rstrip("/") + "/user/balance"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    infos = payload.get("balance_infos") or []
    if not infos:
        raise ValueError("balance_infos 为空")
    primary = next((i for i in infos if i.get("currency") == "CNY"), infos[0])
    return {
        "is_available": bool(payload.get("is_available")),
        "currency": primary.get("currency"),
        "total": float(primary.get("total_balance") or 0.0),
        "granted": float(primary.get("granted_balance") or 0.0),
        "topped_up": float(primary.get("topped_up_balance") or 0.0),
    }


def key_candidates(provider: dict, repo: Path) -> list[tuple[str, str]]:
    """按优先级返回 (key, 来源) 候选：环境变量优先，其次 .env 文件。401 时自动回退下一个。"""
    key_env = provider.get("api_key_env") or ""
    candidates: list[tuple[str, str]] = []
    env_value = os.environ.get(key_env, "").strip() if key_env else ""
    if env_value:
        candidates.append((env_value, f"env:{key_env}"))
    seen = {env_value} if env_value else set()
    for rel in provider.get("env_files") or []:
        path = Path(rel)
        if not path.is_absolute():
            path = repo / rel
        value = read_env_value(path, key_env) if key_env else ""
        if value and value not in seen:
            candidates.append((value, rel))
            seen.add(value)
    return candidates


def collect_provider(
    provider: dict, repo: Path, timeout: float = 15
) -> tuple[dict | None, dict | None]:
    """抓取余额；凭证全失效或接口异常时返回 (None, finding)。"""
    name = provider.get("name", "unknown")
    providers_type = provider.get("type", "")
    if providers_type != "deepseek_balance":
        return None, {
            "key": f"{name}_unsupported",
            "level": "P2",
            "title": "模型用量监控未支持该供应商",
            "text": f"`{name}` 类型 `{providers_type}` 暂无余额接口，用量只能依赖调用埋点（待接入）",
        }

    candidates = key_candidates(provider, repo)
    if not candidates:
        return None, {
            "key": f"{name}_unavailable",
            "level": "P1",
            "title": "模型凭证缺失",
            "text": f"`{name}` 未找到 `{provider.get('api_key_env')}`，推理将无法调用",
        }

    base_url = provider.get("base_url", "https://api.deepseek.com")
    errors: list[str] = []
    for api_key, source in candidates:
        try:
            balance = fetch_deepseek_balance(base_url, api_key, timeout)
            balance["key_source"] = source
            if not balance.get("is_available"):
                return None, {
                    "key": f"{name}_unavailable",
                    "level": "P1",
                    "title": "模型账户不可用",
                    "text": f"`{name}` 余额接口返回 is_available=false（凭证来源 `{source}`）",
                }
            return balance, None
        except urllib.error.HTTPError as exc:
            errors.append(f"{source}: HTTP {exc.code}")
            if exc.code in (401, 403):
                continue
            break
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"{source}: {exc}")
            break

    return None, {
        "key": f"{name}_unavailable",
        "level": "P1",
        "title": "模型余额接口异常",
        "text": f"`{name}` 余额查询失败：{'；'.join(errors) or '未知错误'}",
    }


# ────────────────────────────── 快照与用量推算 ──────────────────────────────


def snapshot_path(history_dir: Path, provider: str, day: str) -> Path:
    return history_dir / f"balance-{provider}-{day.replace('-', '')}.jsonl"


def append_snapshot(history_dir: Path, provider: str, balance: dict, tz: ZoneInfo) -> dict:
    now = datetime.now(tz)
    record = {
        "ts": now.isoformat(),
        "provider": provider,
        "currency": balance.get("currency"),
        "total": balance.get("total"),
        "granted": balance.get("granted"),
        "topped_up": balance.get("topped_up"),
        "is_available": balance.get("is_available"),
        "key_source": balance.get("key_source"),
    }
    history_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(history_dir, provider, now.date().isoformat())
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_snapshots(history_dir: Path, provider: str, days: int) -> list[dict]:
    rows: list[dict] = []
    if not history_dir.exists():
        return rows
    for path in sorted(history_dir.glob(f"balance-{provider}-*.jsonl"))[-days:]:
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("total"), (int, float)):
                    rows.append(obj)
        except OSError:
            continue
    rows.sort(key=lambda r: parse_ts(r.get("ts")))
    return rows


def compute_usage(snapshots: list[dict], now: datetime, baseline_days: int = 7) -> dict:
    """基于余额快照推算消耗；充值导致余额上升的区间不计入消耗。"""
    if not snapshots:
        return {"current": None}

    current = snapshots[-1]
    now_ts = now.timestamp()
    usage = {
        "current": current.get("total"),
        "currency": current.get("currency"),
        "snapshot_at": current.get("ts"),
        "burn_24h": None,
        "avg_daily_burn": None,
        "days_remaining": None,
        "today_burn": None,
        "projected_daily_burn": None,
        "spike_ratio": None,
        "baseline_days": 0,
    }

    cutoff = now_ts - 86400
    ref = None
    for snap in snapshots:
        if parse_ts(snap.get("ts")) <= cutoff:
            ref = snap
    if ref is None:
        first = snapshots[0]
        if now_ts - parse_ts(first.get("ts")) >= 20 * 3600:
            ref = first
    if ref is not None and ref.get("total") >= current.get("total", 0):
        usage["burn_24h"] = round(ref["total"] - current["total"], 4)

    # 按自然日取每日末余额，逐日差分得到日消耗；充值日（余额上升）跳过
    tz = now.tzinfo
    by_day: dict[str, list[dict]] = {}
    for snap in snapshots:
        ts = parse_ts(snap.get("ts"))
        if not ts:
            continue
        day = datetime.fromtimestamp(ts, tz).date().isoformat()
        by_day.setdefault(day, []).append(snap)

    day_ends = [(day, by_day[day][-1]["total"]) for day in sorted(by_day)]
    completed = day_ends[:-1] if len(day_ends) > 1 else []
    burns: list[float] = []
    for prev_item, item in zip(completed, completed[1:], strict=False):
        delta = prev_item[1] - item[1]
        if delta >= 0:
            burns.append(delta)
    burns = burns[-baseline_days:]
    if burns:
        usage["baseline_days"] = len(burns)
        usage["avg_daily_burn"] = round(statistics.fmean(burns), 4)
        if usage["avg_daily_burn"] > 0:
            usage["days_remaining"] = round(current["total"] / usage["avg_daily_burn"], 2)

    today = now.date().isoformat()
    today_snaps = by_day.get(today) or []
    if today_snaps:
        start_balance = today_snaps[0]["total"]
        elapsed_h = max((now_ts - parse_ts(today_snaps[0]["ts"])) / 3600, 0.0)
        today_burn = start_balance - current["total"]
        if today_burn >= 0:
            usage["today_burn"] = round(today_burn, 4)
            if elapsed_h >= 1:
                projected = round(today_burn / elapsed_h * 24, 4)
                usage["projected_daily_burn"] = projected
                avg = usage["avg_daily_burn"]
                if avg:
                    usage["spike_ratio"] = round(projected / avg, 2)

    return usage


def evaluate(provider: dict, usage: dict, tz: ZoneInfo) -> list[dict]:
    """按阈值产出告警；余额已触发时不再重复报可用天数。"""
    name = provider.get("name", "unknown")
    thresholds = provider.get("thresholds") or {}
    current = usage.get("current")
    if current is None:
        return []

    currency = usage.get("currency")
    min_balance = float(thresholds.get("min_balance", 10))
    warn_balance = float(thresholds.get("warn_balance", 20))
    min_days = float(thresholds.get("min_days_remaining", 3))
    spike_ratio = float(thresholds.get("burn_spike_ratio", 3))
    min_baseline = int(thresholds.get("min_baseline_days", 3))

    balance_txt = fmt_money(currency, current)
    burn_txt = (
        fmt_money(currency, usage.get("burn_24h")) if usage.get("burn_24h") is not None else "未知"
    )
    avg_txt = (
        fmt_money(currency, usage.get("avg_daily_burn"))
        if usage.get("avg_daily_burn") is not None
        else "未知"
    )
    days_txt = usage.get("days_remaining")
    base = f"余额 {balance_txt} · 24h 消耗 {burn_txt} · 日均 {avg_txt}"
    if days_txt is not None:
        base += f" · 预计可用 {days_txt} 天"

    findings: list[dict] = []
    if current <= min_balance:
        findings.append(
            {
                "key": f"{name}_balance_low",
                "level": "P1",
                "title": "模型余额低于下限",
                "text": f"{base}\n**余额 {balance_txt} 已低于下限 {fmt_money(currency, min_balance)}，请及时充值，否则推理链将断供**",
            }
        )
    elif current <= warn_balance:
        findings.append(
            {
                "key": f"{name}_balance_warn",
                "level": "P2",
                "title": "模型余额接近预警线",
                "text": f"{base}\n余额低于预警线 {fmt_money(currency, warn_balance)}，建议提前充值",
            }
        )
    elif days_txt is not None and days_txt < min_days:
        findings.append(
            {
                "key": f"{name}_days_remaining",
                "level": "P2",
                "title": "模型余额可用天数不足",
                "text": f"{base}\n按近 7 日均消耗，可用天数低于 {min_days} 天",
            }
        )

    spike = usage.get("spike_ratio")
    if spike is not None and spike >= spike_ratio and usage.get("baseline_days", 0) >= min_baseline:
        findings.append(
            {
                "key": f"{name}_burn_spike",
                "level": "P2",
                "title": "模型消耗突增",
                "text": (
                    f"{base}\n24h 折算消耗是 7 日均值的 **{spike}x**（阈值 {spike_ratio}x），"
                    "检查是否有异常重试/循环调用/新任务放量"
                ),
            }
        )

    # 统一补充时间口径，便于值班判断
    for item in findings:
        item["text"] += f"\n_统计时点：{datetime.now(tz).strftime('%Y-%m-%d %H:%M')} {tz.key}_"
    return findings


# ────────────────────────────── 推送与去重 ──────────────────────────────


def load_state(path: Path) -> dict:
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def push_text(cfg: dict, text: str) -> tuple[bool, str]:
    push_cfg = cfg.get("push", {})
    url = push_cfg.get("receiver_url")
    level = push_cfg.get("level", "P1")
    receiver_error = ""
    if url:
        try:
            body = json.dumps({"level": level, "text": text}).encode()
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True, f"receiver:{url}"
            receiver_error = "receiver non-200"
        except (urllib.error.URLError, OSError) as exc:
            receiver_error = str(exc)
    else:
        receiver_error = "no receiver_url"

    if push_cfg.get("fallback_direct"):
        try:
            import sys

            sys.path.insert(0, str(BASE_DIR))
            import feishu_alert  # noqa: PLC0415

            feishu_alert.send_alert("model", "warning", text, None, "15-模型用量")
            return True, "direct-feishu"
        except Exception as exc:  # noqa: BLE001 - 推送失败不能影响主流程
            return False, f"receiver={receiver_error}; direct={exc}"
    return False, f"receiver={receiver_error}"


def prune_history(history_dir: Path, retain_days: int, today: date) -> None:
    if not history_dir.exists():
        return
    cutoff = today - timedelta(days=retain_days)
    for path in history_dir.glob("balance-*-*.jsonl"):
        try:
            day = datetime.strptime(path.stem.rsplit("-", 1)[-1], "%Y%m%d").date()
        except ValueError:
            continue
        if day < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


# ────────────────────────────── 主流程 ──────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="模型用量告警（余额/消耗/可用天数）")
    parser.add_argument(
        "--repo-root", default=os.environ.get("DREAMBUDDY_REPO_ROOT", str(DEFAULT_REPO))
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--push", action="store_true", help="推送飞书（默认开启，显式声明用）")
    parser.add_argument("--no-push", action="store_true", help="只检查不推送")
    parser.add_argument("--dry-run", action="store_true", help="不推送、不写去重状态")
    parser.add_argument("--json", action="store_true", help="stdout 输出 JSON 摘要")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).expanduser().resolve()
    cfg = load_config(Path(args.config))
    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    history_dir = Path(cfg.get("history", {}).get("dir", "logs/model-usage"))
    if not history_dir.is_absolute():
        history_dir = BASE_DIR / history_dir
    retain_days = int(cfg.get("history", {}).get("retain_days", 14))

    findings: list[dict] = []
    providers_summary: list[dict] = []
    for provider in cfg.get("providers", []):
        if not provider.get("enabled", True):
            continue
        name = provider.get("name", "unknown")
        balance, problem = collect_provider(provider, repo)
        if problem:
            findings.append(problem)
            providers_summary.append({"name": name, "ok": False, "error": problem["text"]})
            continue

        append_snapshot(history_dir, name, balance, tz)
        snapshots = load_snapshots(history_dir, name, retain_days)
        usage = compute_usage(snapshots, now)
        provider_findings = evaluate(provider, usage, tz)
        findings.extend(provider_findings)
        providers_summary.append(
            {
                "name": name,
                "ok": True,
                "currency": usage.get("currency"),
                "balance": usage.get("current"),
                "burn_24h": usage.get("burn_24h"),
                "avg_daily_burn": usage.get("avg_daily_burn"),
                "days_remaining": usage.get("days_remaining"),
                "spike_ratio": usage.get("spike_ratio"),
                "findings": len(provider_findings),
            }
        )

    prune_history(history_dir, retain_days, now.date())

    push_cfg = cfg.get("push", {})
    cooldown = float(push_cfg.get("cooldown_seconds", 21600))
    state_path = Path(args.state).expanduser()
    state = {} if args.dry_run else load_state(state_path)
    pushed: list[str] = []
    skipped: list[str] = []
    if findings and not (args.no_push or args.dry_run or not push_cfg.get("enabled", True)):
        pending = [
            f for f in findings if now.timestamp() - float(state.get(f["key"], 0)) >= cooldown
        ]
        pending_keys = {f["key"] for f in pending}
        skipped = [f["key"] for f in findings if f["key"] not in pending_keys]
        if pending:
            lines = [f"**模型用量告警 · {now.strftime('%Y-%m-%d %H:%M')}**", ""]
            for item in pending:
                lines.append(f"[{item['level']}] **{item['title']}**")
                lines.append(item["text"])
                lines.append("")
            ok, detail = push_text(cfg, "\n".join(lines).strip())
            if ok:
                for item in pending:
                    state[item["key"]] = now.timestamp()
                    pushed.append(item["key"])
            else:
                skipped.extend([f["key"] for f in pending])

    if not args.dry_run and pushed:
        state = {k: v for k, v in state.items() if now.timestamp() - float(v) < 7 * 86400}
        save_state(state_path, state)

    summary = {
        "checked_at": now.isoformat(),
        "providers": providers_summary,
        "findings": [{"key": f["key"], "level": f["level"], "title": f["title"]} for f in findings],
        "pushed": pushed,
        "skipped_by_cooldown": skipped,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        parts = []
        for item in providers_summary:
            if item["ok"]:
                parts.append(
                    f"{item['name']}={fmt_money(item.get('currency'), item.get('balance'))}"
                    f"(days={item.get('days_remaining')},24h={item.get('burn_24h')})"
                )
            else:
                parts.append(f"{item['name']}=ERROR")
        print(
            f"[model-usage] {' · '.join(parts) or '无启用供应商'} · "
            f"findings={len(findings)} pushed={len(pushed)} skipped={len(skipped)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
