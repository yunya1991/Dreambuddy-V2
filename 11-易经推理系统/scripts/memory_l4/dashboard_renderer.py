import json
from pathlib import Path
import sys
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from scripts.memory_l4.paths import artifacts_memory_l4_dir, memory_l4_stats_dir


def _load_latest_bandit_rollup() -> Dict[str, Any]:
    bandit_root = _ROOT / "artifacts" / "memory_engine" / "bandit"
    if not bandit_root.exists():
        return {}
    day_dirs = sorted([p for p in bandit_root.iterdir() if p.is_dir()])
    daily_reason_series: List[Dict[str, Any]] = []
    latest: Dict[str, Any] = {}
    for day_dir in day_dirs[-7:]:
        summary_path = day_dir / "summary.json"
        if not summary_path.exists():
            continue
        try:
            raw = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        latest = raw
        daily_reason_series.append(
            {
                "date": day_dir.name,
                "reason_counts": raw.get("reason_counts") or {},
                "total_updates": int(raw.get("total_updates") or 0),
            }
        )
    if not latest:
        return {}
    out = dict(latest)
    out["daily_reason_series"] = daily_reason_series
    rc = out.get("reason_counts") or {}
    realized = float(rc.get("episode_close_realized") or 0.0)
    estimated = float(rc.get("episode_ingest_estimated") or 0.0)
    denom = realized + estimated
    out["latest_realized_ratio_pct"] = round((realized / denom) * 100.0, 4) if denom > 0 else None
    return out


def render_dashboard_html(stats: Dict[str, Any], out_path: Path) -> None:
    points: List[Dict[str, Any]] = stats.get("points") or []
    case_points = [p for p in points if str(p.get("kind") or "") == "case"]
    distill_points = [p for p in points if str(p.get("kind") or "") == "distill"]

    bandit_rollup = stats.get("bandit_daily_rollup") or {}
    alert_threshold_pct = float(
        stats.get("bandit_alert_threshold_pct")
        or bandit_rollup.get("recommended_alert_threshold_pct")
        or 40.0
    )
    fig = make_subplots(
        rows=2,
        cols=2,
        specs=[[{}, {}], [{}, {"secondary_y": True}]],
        subplot_titles=("Quadrant Scatter", "Migration Trends", "Performance Facets", "Bandit Reason Trends"),
        vertical_spacing=0.18,
        horizontal_spacing=0.12,
    )

    fig.add_trace(
        go.Scatter(
            x=[p.get("x", 0.0) for p in case_points],
            y=[p.get("y", 0.0) for p in case_points],
            mode="markers",
            name="case",
            marker=dict(color="#1f77b4", size=9),
            text=[f"case:{p.get('id')}" for p in case_points],
            hovertemplate="%{text}<br>x=%{x:.2f}<br>y=%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[p.get("x", 0.0) for p in distill_points],
            y=[p.get("y", 0.0) for p in distill_points],
            mode="markers",
            name="distill",
            marker=dict(color="#d62728", size=9),
            text=[f"distill:{p.get('id')}" for p in distill_points],
            hovertemplate="%{text}<br>x=%{x:.2f}<br>y=%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    migration_trends = stats.get("migration_trends") or []
    for mt in migration_trends:
        series = mt.get("series") or []
        fig.add_trace(
            go.Scatter(
                x=[s.get("ts") for s in series],
                y=[s.get("y") for s in series],
                mode="lines+markers",
                name=f"trend:{mt.get('id')}",
            ),
            row=1,
            col=2,
        )

    perf = stats.get("performance") or {}
    perf_keys = ["win_rate", "profit_factor", "max_drawdown", "avg_pnl_usdt"]
    fig.add_trace(
        go.Bar(
            x=perf_keys,
            y=[perf.get(k) or 0.0 for k in perf_keys],
            name="performance",
            marker=dict(color="#2ca02c"),
        ),
        row=2,
        col=1,
    )

    daily_reason_series = bandit_rollup.get("daily_reason_series") or []
    if daily_reason_series:
        fig.add_trace(
            go.Bar(
                x=[row.get("date") for row in daily_reason_series],
                y=[float(row.get("total_updates") or 0.0) for row in daily_reason_series],
                name="bandit_total_updates_7d",
                marker=dict(color="#c7c7c7"),
                opacity=0.45,
            ),
            row=2,
            col=2,
            secondary_y=False,
        )
        reason_keys = sorted(
            {
                str(k)
                for row in daily_reason_series
                for k in ((row or {}).get("reason_counts") or {}).keys()
            }
        )
        for reason in reason_keys:
            fig.add_trace(
                go.Scatter(
                    x=[row.get("date") for row in daily_reason_series],
                    y=[((row.get("reason_counts") or {}).get(reason) or 0) for row in daily_reason_series],
                    mode="lines+markers",
                    name=f"bandit:{reason}",
                ),
                row=2,
                col=2,
            )
        realized_key = "episode_close_realized"
        estimated_key = "episode_ingest_estimated"
        fig.add_trace(
            go.Scatter(
                x=[row.get("date") for row in daily_reason_series],
                y=[
                    (
                        ((row.get("reason_counts") or {}).get(realized_key) or 0)
                        / max(
                            1,
                            (((row.get("reason_counts") or {}).get(realized_key) or 0)
                             + ((row.get("reason_counts") or {}).get(estimated_key) or 0)),
                        )
                    )
                    * 100.0
                    for row in daily_reason_series
                ],
                mode="lines+markers",
                name="bandit:realized_ratio_7d",
                line=dict(color="#111111", dash="dash"),
            ),
            row=2,
            col=2,
            secondary_y=True,
        )
        alert_points = []
        alert_dates: List[str] = []
        for row in daily_reason_series:
            rc = row.get("reason_counts") or {}
            realized = float(rc.get(realized_key) or 0.0)
            estimated = float(rc.get(estimated_key) or 0.0)
            ratio_pct = (realized / max(1.0, realized + estimated)) * 100.0
            if ratio_pct < alert_threshold_pct:
                alert_dates.append(str(row.get("date")))
                alert_points.append(ratio_pct)
        fig.add_trace(
            go.Scatter(
                x=alert_dates,
                y=alert_points,
                mode="markers",
                name="bandit:realized_ratio_alert",
                marker=dict(color="#d62728", size=9, symbol="circle"),
            ),
            row=2,
            col=2,
            secondary_y=True,
        )
    else:
        reason_counts = (bandit_rollup.get("reason_counts") or {})
        if reason_counts:
            total_updates = float(bandit_rollup.get("total_updates") or sum(float(v or 0.0) for v in reason_counts.values()))
            fig.add_trace(
                go.Bar(
                    x=["latest"],
                    y=[total_updates],
                    name="bandit_total_updates_7d",
                    marker=dict(color="#c7c7c7"),
                    opacity=0.45,
                ),
                row=2,
                col=2,
                secondary_y=False,
            )
            fig.add_trace(
                go.Bar(
                    x=list(reason_counts.keys()),
                    y=[reason_counts[k] for k in reason_counts.keys()],
                    name="bandit_reason_counts",
                    marker=dict(color="#9467bd"),
                ),
                row=2,
                col=2,
            )
            realized = float(reason_counts.get("episode_close_realized") or 0.0)
            estimated = float(reason_counts.get("episode_ingest_estimated") or 0.0)
            ratio = realized / max(1.0, realized + estimated)
            fig.add_trace(
                go.Scatter(
                    x=["latest"],
                    y=[ratio * 100.0],
                    mode="lines+markers",
                    name="bandit:realized_ratio_7d",
                    line=dict(color="#111111", dash="dash"),
                ),
                row=2,
                col=2,
                secondary_y=True,
            )
            alert_x = ["latest"] if ratio * 100.0 < alert_threshold_pct else []
            alert_y = [ratio * 100.0] if ratio * 100.0 < alert_threshold_pct else []
            fig.add_trace(
                go.Scatter(
                    x=alert_x,
                    y=alert_y,
                    mode="markers",
                    name="bandit:realized_ratio_alert",
                    marker=dict(color="#d62728", size=9, symbol="circle"),
                ),
                row=2,
                col=2,
                secondary_y=True,
            )

    fig.update_layout(
        title="Memory L4 Dashboard",
        showlegend=True,
        updatemenus=[
            {
                "type": "dropdown",
                "x": 0.0,
                "y": 1.2,
                "xanchor": "left",
                "yanchor": "top",
                "buttons": [
                    {"label": "All", "method": "update", "args": [{"visible": [True, True] + [True] * max(0, len(fig.data) - 2)}]},
                    {"label": "Case Only", "method": "update", "args": [{"visible": [True, False] + [True] * max(0, len(fig.data) - 2)}]},
                    {"label": "Distill Only", "method": "update", "args": [{"visible": [False, True] + [True] * max(0, len(fig.data) - 2)}]},
                ],
            }
        ],
        annotations=[
            {"text": "Filter Kind", "xref": "paper", "yref": "paper", "x": 0.0, "y": 1.27, "showarrow": False},
            {"text": "Migration Trends", "xref": "paper", "yref": "paper", "x": 0.73, "y": 1.06, "showarrow": False},
            {"text": "Performance Facets", "xref": "paper", "yref": "paper", "x": 0.23, "y": 0.42, "showarrow": False},
            {"text": "Bandit Reason Trends", "xref": "paper", "yref": "paper", "x": 0.73, "y": 0.42, "showarrow": False},
            {
                "text": f"Alert <{int(alert_threshold_pct)}%",
                "xref": "paper",
                "yref": "paper",
                "x": 0.73,
                "y": 0.36,
                "showarrow": False,
            },
        ],
    )
    fig.update_xaxes(title_text="Harm (−1) ↔ Benefit (+1)", range=[-1, 1], zeroline=True, row=1, col=1)
    fig.update_yaxes(title_text="Certainty Strength (0) → (1)", range=[0, 1], zeroline=True, row=1, col=1)
    fig.update_yaxes(title_text="Count", row=2, col=2, secondary_y=False)
    fig.update_yaxes(title_text="Realized Ratio (%)", range=[0, 100], row=2, col=2, secondary_y=True)
    fig.add_annotation(text="Filter Kind", xref="paper", yref="paper", x=0.0, y=1.27, showarrow=False)
    threshold_meta = bandit_rollup.get("threshold_meta") or {}
    if threshold_meta:
        p = int(threshold_meta.get("percentile") or 25)
        w = int(threshold_meta.get("window_days") or 7)
        n = int(threshold_meta.get("sample_size") or 0)
        min_cap = int(threshold_meta.get("min_cap") or 30)
        max_cap = int(threshold_meta.get("max_cap") or 70)
        fig.add_annotation(
            text=f"Threshold Meta: P{p}/{w}d sample={n} cap=[{min_cap},{max_cap}]",
            xref="paper",
            yref="paper",
            x=0.73,
            y=0.30,
            showarrow=False,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_path), include_plotlyjs="cdn", full_html=True)


def main() -> None:
    stats_path = memory_l4_stats_dir() / "latest.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["bandit_daily_rollup"] = _load_latest_bandit_rollup()
    out_path = artifacts_memory_l4_dir() / "dashboard.html"
    render_dashboard_html(stats, out_path)
    print(str(out_path))


if __name__ == "__main__":
    main()
