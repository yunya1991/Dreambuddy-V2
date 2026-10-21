# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · L3 多因子矛盾综合（SPEC §9.7 第三级，零 token）

横向结合情绪标签、系统指标、矛盾观测镜像，纵向结合时间维度，
产出描述性复杂语义结论（如『情绪与资金费率持续背离，矛盾升温期』）。

复用不新建（§9.7 设计原则）：全部消费现有产出物——
  - 原子层：恐惧贪婪状态 / 资金费率（情绪×指标维度）
  - P-矛盾：contradiction_events.jsonl（矛盾观测镜像）
  - L2 事件线：event_lines.json 五维画像与量变信号（频维/量维）

综合窗口（预注册）：最近 48h 为观测窗，前 48h 为对照窗
产出: l3_synthesis.json（描述性复杂语义结论，覆盖式更新）
用法: /home/luke/venv-trading/bin/python3 gen_l3_synthesis.py
边界: L3 的『判断』仍是观察性结论（矛盾状态/背离程度/演化方向），
      交易决策归 23 门禁体系（§8.2/§9.7 强制）
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)

ATOMIC_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
CONTRA_PATH = os.path.join(_SYS_DIR, "contradiction_events.jsonl")
EVENT_LINES_PATH = os.path.join(_SYS_DIR, "event_lines.json")
OUT_PATH = os.path.join(_SYS_DIR, "l3_synthesis.json")

# ── 预注册参数（禁止事后调整）──
OBS_WINDOW_H = 48     # 观测窗：最近 48h
CTRL_WINDOW_H = 48    # 对照窗：观测窗前 48h
EXTREME_LOW, EXTREME_HIGH = 25.0, 75.0
CONTRA_HEAT_RATIO = 1.5   # 矛盾升温判定：观测窗计数 >= 对照窗 1.5 倍


def _parse_ts(ts):
    if not ts:
        return None
    t = str(ts).replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H"):
        try:
            return datetime.strptime(t[:19], fmt)
        except Exception:
            continue
    return None


def _load_jsonl(path):
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return events


def load_internal_timelines():
    """恐惧贪婪与资金费率状态时间线。"""
    fg, fr = [], []
    for e in _load_jsonl(ATOMIC_PATH):
        ts = _parse_ts(e.get("timestamp", ""))
        if ts is None:
            continue
        v = e.get("value")
        cat = e.get("category", "")
        if cat in ("crypto_fear_greed", "fear_greed_enhanced") and isinstance(v, (int, float)):
            fg.append((ts, float(v)))
        elif cat == "funding_rate" and isinstance(v, (int, float)):
            fr.append((ts, float(v)))
    fg.sort()
    fr.sort()
    return fg, fr


def _state_at(timeline, ts):
    val = None
    for t, v in timeline:
        if t <= ts:
            val = v
        else:
            break
    return val


def _fg_zone(v):
    if v is None:
        return None
    if v < EXTREME_LOW:
        return "极度恐慌"
    if v > EXTREME_HIGH:
        return "极度贪婪"
    if v < 50:
        return "恐慌区"
    if v >= 50:
        return "贪婪区"
    return None


def main():
    now = datetime.now()
    obs_start = now - timedelta(hours=OBS_WINDOW_H)
    ctrl_start = obs_start - timedelta(hours=CTRL_WINDOW_H)

    fg, fr = load_internal_timelines()
    contra = _load_jsonl(CONTRA_PATH)
    try:
        with open(EVENT_LINES_PATH, "r", encoding="utf-8") as f:
            lines_data = json.load(f)
    except Exception:
        lines_data = {"lines": []}

    # ── 维度一：情绪标签（观测窗末端状态 + 窗口内极值轨迹）──
    fg_now = _state_at(fg, now)
    fg_zone = _fg_zone(fg_now)
    fg_in_window = [v for t, v in fg if obs_start <= t <= now]
    fg_note = None
    if fg_in_window:
        if max(fg_in_window) > EXTREME_HIGH and min(fg_in_window) < EXTREME_LOW:
            fg_note = "窗口内情绪跨越极值分区（恐慌↔贪婪切换）"
        elif fg_in_window and abs(fg_in_window[-1] - fg_in_window[0]) > 20:
            fg_note = f"窗口内情绪显著漂移（{fg_in_window[0]:.0f}→{fg_in_window[-1]:.0f}）"

    # ── 维度二：系统指标（资金费率状态）──
    fr_now = _state_at(fr, now)
    fr_state = None
    if fr_now is not None:
        fr_state = "多头主导（正费率）" if fr_now > 0 else ("空头主导（负费率）" if fr_now < 0 else "平衡")

    # ── 维度三：矛盾观测镜像（观测窗 vs 对照窗）──
    contra_obs = [c for c in contra if obs_start <= _parse_ts(c.get("window_end", "")) <= now]
    contra_ctrl = [c for c in contra if ctrl_start <= _parse_ts(c.get("window_end", "")) < obs_start]
    n_obs, n_ctrl = len(contra_obs), len(contra_ctrl)
    by_type_obs = defaultdict(int)
    for c in contra_obs:
        by_type_obs[c.get("contradiction_type", "?")] += 1
    if n_ctrl == 0:
        heat = "升温期（对照窗无矛盾记录，观测窗出现矛盾）" if n_obs > 0 else "平稳期（两窗均无矛盾检出）"
    elif n_obs >= n_ctrl * CONTRA_HEAT_RATIO:
        heat = f"升温期（观测窗 {n_obs} 条 vs 对照窗 {n_ctrl} 条，≥{CONTRA_HEAT_RATIO}倍）"
    elif n_obs <= n_ctrl / CONTRA_HEAT_RATIO:
        heat = f"降温期（观测窗 {n_obs} 条 vs 对照窗 {n_ctrl} 条）"
    else:
        heat = f"持续期（观测窗 {n_obs} 条 vs 对照窗 {n_ctrl} 条，量级相当）"

    # ── 维度四：L2 量变信号（事件线频维/量维共振）──
    active_signals = []
    for l in lines_data.get("lines", []):
        qs = l.get("quantity_signal", "")
        if "加速" in qs:
            active_signals.append(f"{l.get('topic')}（量变加速积累）")
        vol = l.get("volume_dimension") or {}
        if vol.get("surge_events", 0) > vol.get("shrink_events", 0) * 2 and vol.get("surge_events", 0) > 0:
            active_signals.append(f"{l.get('topic')}（放量主导）")

    # ── 综合结论（描述性，观察性判断）──
    conclusions = []
    # 背离检测：情绪 vs 资金费率
    if fg_zone in ("极度贪婪", "贪婪区") and fr_state == "空头主导（负费率）":
        conclusions.append("情绪与资金费率背离：市场情绪偏贪婪，持仓结构空头主导——观察性结论，背离程度待后续窗口验证")
    elif fg_zone in ("极度恐慌", "恐慌区") and fr_state == "多头主导（正费率）":
        conclusions.append("情绪与资金费率背离：市场情绪偏恐慌，持仓结构多头主导——观察性结论，背离程度待后续窗口验证")
    elif fg_zone and fr_state:
        conclusions.append(f"情绪与持仓结构同向：情绪 {fg_zone}，{fr_state}——未检出背离")
    # 矛盾演化
    conclusions.append(f"矛盾演化状态：{heat}")
    if by_type_obs:
        top_type = sorted(by_type_obs.items(), key=lambda kv: -kv[1])[0]
        conclusions.append(f"观测窗主导矛盾类型：{top_type[0]}（{top_type[1]} 条）")
    # 五维共振
    if active_signals:
        conclusions.append("L2 量变共振信号：" + "；".join(active_signals[:3]))
    if fg_note:
        conclusions.append(f"情绪轨迹：{fg_note}")

    out = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "window": {
            "observation": f"{obs_start.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')}",
            "control": f"{ctrl_start.strftime('%Y-%m-%d %H:%M')} ~ {obs_start.strftime('%Y-%m-%d %H:%M')}",
        },
        "dimensions": {
            "sentiment": {"fear_greed": fg_now, "zone": fg_zone, "trajectory_note": fg_note},
            "indicator": {"funding_rate": fr_now, "state": fr_state},
            "contradiction_mirror": {
                "obs_window_count": n_obs, "ctrl_window_count": n_ctrl,
                "by_type": dict(by_type_obs), "heat": heat,
            },
            "l2_quantity_signals": active_signals,
        },
        "conclusions": conclusions,
        "evidence_note": f"观测窗 {OBS_WINDOW_H}h / 对照窗 {CTRL_WINDOW_H}h（预注册）；矛盾升温阈值 {CONTRA_HEAT_RATIO} 倍",
        "boundary": "L3 观察性结论（矛盾状态/背离程度/演化方向），不做方向判断；交易决策归 23 门禁体系（§9.7 强制）",
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] L3 多因子矛盾综合完成 -> {OUT_PATH}")
    print(f"     情绪: {fg_zone}（{fg_now:.0f}） | 指标: {fr_state}")
    print(f"     矛盾镜像: 观测窗 {n_obs} 条 vs 对照窗 {n_ctrl} 条 → {heat}")
    for c in conclusions:
        print(f"     [结论] {c}")


if __name__ == "__main__":
    main()
