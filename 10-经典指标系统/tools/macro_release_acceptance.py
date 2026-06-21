#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _get(url: str, timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _dig(d: Dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _check_api(base_url: str, timeout: float, signal_window_h: int, shape_n: int) -> Tuple[List[str], List[str], Dict[str, Any]]:
    errors: List[str] = []
    warns: List[str] = []
    qs = urllib.parse.urlencode({"shape_n": int(shape_n), "signal_window_h": int(signal_window_h)})
    url = f"{base_url.rstrip('/')}/macro/viz?{qs}"
    data = _get(url, timeout=timeout)
    target_source = _dig(data, "position_budget", "target", "target_source")
    tri_target = _dig(data, "position_budget", "tri_layer_target")
    tri_trace = _dig(data, "tri_layer", "trace")
    if not isinstance(target_source, str) or not target_source:
        errors.append("API缺少 position_budget.target.target_source（疑似旧版本未生效）")
    if not isinstance(tri_target, dict):
        errors.append("API缺少 position_budget.tri_layer_target（疑似旧版本未生效）")
    if not isinstance(tri_trace, dict):
        errors.append("API缺少 tri_layer.trace（疑似旧版本未生效）")
    tri_allow_open = _dig(data, "position_budget", "tri_layer_target", "allow_open")
    tri_allow_addon = _dig(data, "position_budget", "tri_layer_target", "allow_addon")
    tri_reason_match = _dig(data, "tri_layer", "trace", "reason_match")
    tri_observed_macro_blocks = _dig(data, "tri_layer", "trace", "observed_macro_blocks")
    tri_warning = _dig(data, "tri_layer", "trace", "warning")
    tri_net_bias = _dig(data, "position_budget", "tri_layer_target", "target_net_bias")
    if tri_net_bias is not None and target_source != "tri_layer":
        errors.append("tri_layer_target.target_net_bias 非空但 target_source 不是 tri_layer")
    if tri_allow_open is False and tri_reason_match is False and isinstance(tri_observed_macro_blocks, int) and tri_observed_macro_blocks > 0:
        errors.append("tri-layer 禁开且窗口内存在宏观拦截样本，但 tri_layer.trace.reason_match=false")
    if tri_allow_open is False and tri_reason_match is False and (not isinstance(tri_observed_macro_blocks, int) or tri_observed_macro_blocks <= 0):
        warns.append("tri-layer 禁开但窗口内无宏观拦截样本，建议扩大 signal_window_h 再复核")
    if tri_allow_open is False and not tri_warning:
        warns.append("tri-layer 禁开但 tri_layer.trace.warning 为空，建议补充提示")
    snapshot = {
        "signal_window_h": int(signal_window_h),
        "shape_n": int(shape_n),
        "target_source": target_source,
        "tri_allow_open": tri_allow_open,
        "tri_allow_addon": tri_allow_addon,
        "tri_target_net_bias": tri_net_bias,
        "tri_reason_match": tri_reason_match,
        "tri_observed_macro_blocks": tri_observed_macro_blocks,
        "tri_warning": tri_warning,
    }
    return errors, warns, snapshot


def _parse_windows(raw: List[str]) -> List[int]:
    out: List[int] = []
    for it in raw:
        s = str(it or "").strip()
        if not s:
            continue
        for part in s.split(","):
            p = str(part or "").strip()
            if not p:
                continue
            try:
                v = int(float(p))
            except Exception:
                continue
            v = max(1, min(168, int(v)))
            out.append(v)
    if not out:
        out = [6, 24, 72]
    return list(dict.fromkeys(out))


def _check_frontend(repo_root: Path) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warns: List[str] = []
    p = repo_root / "frontend" / "src" / "components" / "MacroPage.tsx"
    if not p.exists():
        return [f"缺少文件: {str(p)}"], warns
    text = p.read_text(encoding="utf-8", errors="replace")
    if "强提醒：当前图2主target来源来自 Shape12H 基线，不是三维目标。" not in text:
        errors.append("图2缺少 Shape12H 回退强提醒文案")
    if "口径提示：Shape12H 的 dir 与 tri-layer 的 DirW/DirD 不一致，请以三维主口径解释交易动作。" not in text:
        errors.append("图1缺少 Shape12H vs tri-layer 口径冲突提示文案")
    if "tri-trace" not in text:
        warns.append("图3未检测到 tri-trace 标识文案")
    return errors, warns


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8092")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--shape-n", type=int, default=10)
    parser.add_argument("--signal-window-h", nargs="*", default=["6", "24", "72"])
    args = parser.parse_args()

    all_errors: List[str] = []
    all_warns: List[str] = []
    snapshots: List[Dict[str, Any]] = []
    per_window: List[Dict[str, Any]] = []
    windows = _parse_windows(list(args.signal_window_h or []))
    shape_n = max(1, min(240, int(args.shape_n)))

    for wh in windows:
        errs: List[str] = []
        warns: List[str] = []
        snap: Dict[str, Any] = {"signal_window_h": int(wh), "shape_n": int(shape_n)}
        try:
            e, w, s = _check_api(args.base_url, args.timeout, signal_window_h=int(wh), shape_n=int(shape_n))
            errs.extend(e)
            warns.extend(w)
            snap = s
        except urllib.error.URLError as ex:
            errs.append(f"API请求失败: {str(ex)}")
        except Exception as ex:
            errs.append(f"API检查异常: {str(ex)}")
        all_errors.extend([f"[window={int(wh)}h] {x}" for x in errs])
        all_warns.extend([f"[window={int(wh)}h] {x}" for x in warns])
        snapshots.append(snap)
        per_window.append(
            {
                "signal_window_h": int(wh),
                "ok": len(errs) == 0,
                "errors": errs,
                "warnings": warns,
                "snapshot": snap,
            }
        )

    fe_errors, fe_warns = _check_frontend(Path(args.repo_root))
    all_errors.extend(fe_errors)
    all_warns.extend(fe_warns)

    ok = len(all_errors) == 0
    print("PASS" if ok else "FAIL")
    print(
        json.dumps(
            {
                "ok": ok,
                "errors": all_errors,
                "warnings": all_warns,
                "windows": windows,
                "per_window": per_window,
                "summary": {
                    "windows_total": len(windows),
                    "windows_ok": sum(1 for x in per_window if bool(x.get("ok"))),
                    "windows_failed": sum(1 for x in per_window if not bool(x.get("ok"))),
                    "frontend_errors": len(fe_errors),
                    "frontend_warnings": len(fe_warns),
                },
                "snapshots": snapshots,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
