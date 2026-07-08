"""
dream-data-analysis/renderer.py
可视化渲染器 - 支持 Chart.js / Plotly / 静态图片
Version: 1.0.0
"""

import json
from typing import Dict, List, Optional, Union
from pathlib import Path
from datetime import datetime

# ============== 配置 ==============

CHART_TEMPLATE_DIR = Path(__file__).parent / "templates" if __file__ else Path("./templates")
DEFAULT_CHART_SIZE = "1024x768"

# ============== 数据准备辅助函数 ==============

def calculate_ma(data: List[Optional[float]], window: int) -> List[Optional[float]]:
    """
    计算移动平均

    Args:
        data: 价格序列
        window: 窗口大小

    Returns:
        MA 序列，None 表示数据不足
    """
    result = []
    for i in range(len(data)):
        if i < window - 1 or data[i] is None:
            result.append(None)
        else:
            window_data = data[i-window+1:i+1]
            valid = [x for x in window_data if x is not None]
            result.append(sum(valid) / len(valid) if valid else None)
    return result


def calculate_ema(data: List[Optional[float]], window: int) -> List[Optional[float]]:
    """
    计算指数移动平均 (EMA)

    Args:
        data: 价格序列
        window: 窗口大小

    Returns:
        EMA 序列
    """
    if not data or window <= 0:
        return [None] * len(data)

    k = 2 / (window + 1)
    result = [None] * len(data)

    # 找到第一个有效值作为初始 EMA
    first_valid_idx = None
    for i, v in enumerate(data):
        if v is not None:
            first_valid_idx = i
            result[i] = v
            break

    if first_valid_idx is not None:
        for i in range(first_valid_idx + 1, len(data)):
            if data[i] is not None:
                prev_ema = result[i-1] if result[i-1] is not None else data[i]
                result[i] = data[i] * k + prev_ema * (1 - k)

    return result


def generate_evidence_list(analysis_result: Dict) -> str:
    """生成证据列表 HTML"""
    evidence_refs = analysis_result.get("evidence_refs", [])
    reason_codes = analysis_result.get("reason_codes", [])

    items = [f"<li>{e}</li>" for e in evidence_refs + reason_codes]
    return "\n".join(items) if items else "<li>No evidence available</li>"


def calculate_velocity(price_series: List[float], dt: float = 1.0) -> List[Optional[float]]:
    """计算价格变化速度 (Δprice/Δt)"""
    if len(price_series) < 2:
        return [None] * len(price_series)

    velocity = [None]
    for i in range(1, len(price_series)):
        if price_series[i] is not None and price_series[i-1] is not None:
            velocity.append((price_series[i] - price_series[i-1]) / dt)
        else:
            velocity.append(None)
    return velocity


def calculate_acceleration(velocity_series: List[float], dt: float = 1.0) -> List[Optional[float]]:
    """计算加速度 (Δvelocity/Δt)"""
    if len(velocity_series) < 2:
        return [None] * len(velocity_series)

    acceleration = [None]
    for i in range(1, len(velocity_series)):
        if velocity_series[i] is not None and velocity_series[i-1] is not None:
            acceleration.append((velocity_series[i] - velocity_series[i-1]) / dt)
        else:
            acceleration.append(None)
    return acceleration


# ============== Chart.js 渲染 ==============

def render_trend_chart(episode_series: List[Dict],
                       ma_windows: Dict[str, int] = None,
                       output_path: str = None) -> str:
    """
    生成趋势分析图表 (Chart.js)

    包含:
    - 价格 + MA/EMA 曲线
    - 趋势强度指标
    - 交易决策标注

    Args:
        episode_series: episode 数据列表
        ma_windows: MA/EMA 窗口配置
        output_path: 输出文件路径

    Returns:
        HTML 字符串
    """
    if ma_windows is None:
        ma_windows = {"ma_short": 5, "ma_medium": 20, "ma_long": 60,
                      "ema_fast": 8, "ema_slow": 21}

    # 提取数据
    timestamps = [e.get("ts", "") for e in episode_series]
    prices = []
    for e in episode_series:
        if e.get("price_ref"):
            prices.append(e["price_ref"].get("close"))
        else:
            prices.append(None)

    # 提取评分
    scores = []
    for e in episode_series:
        if e.get("scores"):
            scores.append(e["scores"].get("total"))
        else:
            scores.append(None)

    # 提取门禁决策
    gate_decisions = []
    for e in episode_series:
        if e.get("gatekeeper"):
            gate_decisions.append(e["gatekeeper"].get("decision", "PASS"))
        else:
            gate_decisions.append("N/A")

    # 计算 MA/EMA
    ma_short = calculate_ma(prices, ma_windows["ma_short"])
    ma_medium = calculate_ma(prices, ma_windows["ma_medium"])
    ma_long = calculate_ma(prices, ma_windows["ma_long"])
    ema_fast = calculate_ema(prices, ma_windows["ema_fast"])
    ema_slow = calculate_ema(prices, ma_windows["ema_slow"])

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 20px;
            background: #fafafa;
        }}
        .chart-container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h2 {{
            text-align: center;
            color: #333;
            margin-bottom: 20px;
        }}
        .legend-info {{
            text-align: center;
            font-size: 12px;
            color: #666;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="chart-container">
        <h2>📈 Trend Analysis (MA{ma_windows['ma_short']}/{ma_windows['ma_medium']}/{ma_windows['ma_long']})</h2>
        <canvas id="trendChart"></canvas>
        <div class="legend-info">
            MA: 移动平均线 | EMA: 指数移动平均 | Score: 综合评分 | Gate: 门禁决策
        </div>
    </div>
    <div class="chart-container" style="margin-top: 20px;">
        <canvas id="scoreChart"></canvas>
    </div>
    <script>
    // 注册 Chart.js
    const Chart = window.Chart;

    // 趋势图
    new Chart(document.getElementById('trendChart'), {{
        type: 'line',
        data: {{
            labels: {json.dumps(timestamps, ensure_ascii=False)},
            datasets: [
                {{
                    label: 'Price',
                    data: {json.dumps(prices)},
                    borderColor: 'rgb(75, 192, 192)',
                    backgroundColor: 'rgba(75, 192, 192, 0.1)',
                    tension: 0.1,
                    order: 0
                }},
                {{
                    label: 'MA{ma_windows["ma_short"]}',
                    data: {json.dumps(ma_short)},
                    borderColor: 'rgb(255, 99, 132)',
                    borderDash: [5, 5],
                    tension: 0.1,
                    order: 4
                }},
                {{
                    label: 'MA{ma_windows["ma_medium"]}',
                    data: {json.dumps(ma_medium)},
                    borderColor: 'rgb(54, 162, 235)',
                    borderDash: [5, 5],
                    tension: 0.1,
                    order: 3
                }},
                {{
                    label: 'MA{ma_windows["ma_long"]}',
                    data: {json.dumps(ma_long)},
                    borderColor: 'rgb(255, 206, 86)',
                    borderDash: [5, 5],
                    tension: 0.1,
                    order: 2
                }},
                {{
                    label: 'EMA{ma_windows["ema_fast"]}',
                    data: {json.dumps(ema_fast)},
                    borderColor: 'rgb(153, 102, 255)',
                    tension: 0.1,
                    order: 1
                }},
                {{
                    label: 'EMA{ma_windows["ema_slow"]}',
                    data: {json.dumps(ema_slow)},
                    borderColor: 'rgb(255, 159, 64)',
                    tension: 0.1,
                    order: 1
                }}
            ]
        }},
        options: {{
            responsive: true,
            interaction: {{
                mode: 'index',
                intersect: false
            }},
            plugins: {{
                legend: {{
                    position: 'top',
                }},
                tooltip: {{
                    callbacks: {{
                        label: function(context) {{
                            let label = context.dataset.label || '';
                            if (label) {{ label += ': '; }}
                            if (context.parsed.y !== null) {{
                                label += context.parsed.y.toFixed(4);
                            }}
                            return label;
                        }}
                    }}
                }}
            }},
            scales: {{
                x: {{
                    title: {{ display: true, text: 'Time' }},
                    ticks: {{ maxRotation: 45 }}
                }},
                y: {{
                    title: {{ display: true, text: 'Price / MA' }},
                    position: 'left'
                }}
            }}
        }}
    }});

    // 评分图
    const scoreData = {json.dumps(scores)};
    const gateData = {json.dumps(gate_decisions)};
    const gateColors = gateData.map(g => {{
        if (g === 'PASS') return 'rgba(76, 175, 80, 0.8)';
        if (g === 'SKIP') return 'rgba(255, 193, 7, 0.8)';
        if (g === 'REJECT') return 'rgba(244, 67, 54, 0.8)';
        return 'rgba(158, 158, 158, 0.8)';
    }});

    new Chart(document.getElementById('scoreChart'), {{
        type: 'bar',
        data: {{
            labels: {json.dumps(timestamps, ensure_ascii=False)},
            datasets: [{{
                label: 'Total Score',
                data: scoreData,
                backgroundColor: gateColors,
                borderColor: gateColors.map(c => c.replace('0.8', '1')),
                borderWidth: 1
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }},
                title: {{ display: true, text: 'Scores & Gate Decisions' }}
            }},
            scales: {{
                x: {{
                    title: {{ display: true, text: 'Time' }},
                    ticks: {{ maxRotation: 45 }}
                }},
                y: {{
                    min: 0,
                    max: 100,
                    title: {{ display: true, text: 'Score' }}
                }}
            }}
        }}
    }});
    </script>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')

    return html


def render_radar_snapshot(scores: Dict, resistance: Dict,
                          output_path: str = None) -> str:
    """
    生成雷达图快照

    包含:
    - 三维评分雷达图 (技术/宏观/记忆)
    - 阻力分解雷达图

    Args:
        scores: 评分数据
        resistance: 阻力数据
        output_path: 输出文件路径

    Returns:
        HTML 字符串
    """
    # 提取评分数据
    tech_score = scores.get("technical", {}).get("total", 50) if isinstance(scores, dict) else 50
    macro_score = scores.get("macro", {}).get("total", 50) if isinstance(scores, dict) else 50
    memory_score = scores.get("memory_safety", 50) if isinstance(scores, dict) else 50

    # 提取阻力数据
    friction_data = resistance.get("components", {}) if isinstance(resistance, dict) else {}
    cost = friction_data.get("cost_friction", 0)
    liquidity = friction_data.get("liquidity_friction", 0)
    crowding = friction_data.get("crowding_friction", 0)
    vol = friction_data.get("vol_friction", 0)

    # 计算综合评分
    total_score = (tech_score + macro_score + memory_score) / 3
    total_resistance = (cost + liquidity + crowding + vol) / 4

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 20px;
            background: #fafafa;
        }}
        .radar-container {{
            display: flex;
            justify-content: center;
            gap: 40px;
            flex-wrap: wrap;
            max-width: 1000px;
            margin: 0 auto;
        }}
        .radar-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }}
        h2 {{
            text-align: center;
            color: #333;
            margin-bottom: 20px;
        }}
        .summary {{
            display: flex;
            justify-content: center;
            gap: 40px;
            margin-top: 20px;
        }}
        .summary-item {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .summary-value {{
            font-size: 32px;
            font-weight: bold;
        }}
        .summary-label {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }}
        .score-good {{ color: #4CAF50; }}
        .score-medium {{ color: #FFC107; }}
        .score-bad {{ color: #F44336; }}
    </style>
</head>
<body>
    <h2>🎯 Signal & Resistance Radar Snapshot</h2>

    <div class="summary">
        <div class="summary-item">
            <div class="summary-value {'score-good' if total_score >= 70 else 'score-medium' if total_score >= 50 else 'score-bad'}">
                {total_score:.1f}
            </div>
            <div class="summary-label">Overall Score</div>
        </div>
        <div class="summary-item">
            <div class="summary-value {'score-bad' if total_resistance >= 70 else 'score-medium' if total_resistance >= 50 else 'score-good'}">
                {total_resistance:.1f}
            </div>
            <div class="summary-label">Overall Resistance</div>
        </div>
    </div>

    <div class="radar-container">
        <div class="radar-card">
            <h3>Signal Scores</h3>
            <canvas id="scoreRadar" width="350" height="350"></canvas>
        </div>
        <div class="radar-card">
            <h3>Resistance Breakdown</h3>
            <canvas id="resistanceRadar" width="350" height="350"></canvas>
        </div>
    </div>

    <script>
    const Chart = window.Chart;

    // 评分雷达图
    new Chart(document.getElementById('scoreRadar'), {{
        type: 'radar',
        data: {{
            labels: ['Technical', 'Macro', 'Memory Safety'],
            datasets: [{{
                label: 'Scores',
                data: [{tech_score:.1f}, {macro_score:.1f}, {memory_score:.1f}],
                backgroundColor: 'rgba(54, 162, 235, 0.2)',
                borderColor: 'rgb(54, 162, 235)',
                pointBackgroundColor: 'rgb(54, 162, 235)',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: 'rgb(54, 162, 235)'
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }}
            }},
            scales: {{
                r: {{
                    min: 0,
                    max: 100,
                    beginAtZero: true
                }}
            }}
        }}
    }});

    // 阻力雷达图
    new Chart(document.getElementById('resistanceRadar'), {{
        type: 'radar',
        data: {{
            labels: ['Cost', 'Liquidity', 'Crowding', 'Volatility'],
            datasets: [{{
                label: 'Resistance',
                data: [{cost:.1f}, {liquidity:.1f}, {crowding:.1f}, {vol:.1f}],
                backgroundColor: 'rgba(255, 99, 132, 0.2)',
                borderColor: 'rgb(255, 99, 132)',
                pointBackgroundColor: 'rgb(255, 99, 132)',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: 'rgb(255, 99, 132)'
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: false }}
            }},
            scales: {{
                r: {{
                    min: 0,
                    max: 100,
                    beginAtZero: true
                }}
            }}
        }}
    }});
    </script>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')

    return html


def render_calibration_dashboard(analysis_result: Dict,
                                  output_path: str = None) -> str:
    """
    生成校准仪表盘

    包含:
    - E[R] 映射状态
    - λ 风险建议
    - 阈值建议
    - 综合状态

    Args:
        analysis_result: 分析结果
        output_path: 输出文件路径

    Returns:
        HTML 字符串
    """
    calibration = analysis_result.get("calibration_suggestions", {}) if isinstance(analysis_result, dict) else {}

    er_mapping = calibration.get("expected_return_mapping", {})
    er_status = er_mapping.get("status", "unknown") if isinstance(er_mapping, dict) else "unknown"

    lambda_risk = calibration.get("lambda_risk", {})
    lambda_status = lambda_risk.get("status", "unknown") if isinstance(lambda_risk, dict) else "unknown"

    thresholds = calibration.get("thresholds", {}) if isinstance(calibration, dict) else {}

    # 状态颜色映射
    status_colors = {
        "keep": "#4CAF50",
        "tighten": "#FFC107",
        "loosen": "#2196F3",
        "rebuild": "#F44336",
        "up": "#FF9800",
        "down": "#9C27B0",
        "unknown": "#9E9E9E"
    }

    status_labels = {
        "keep": "保持不变",
        "tighten": "收紧",
        "loosen": "放松",
        "rebuild": "重建",
        "up": "提高",
        "down": "降低",
        "unknown": "待定"
    }

    overall_needs_calibration = er_status != "keep" or lambda_status != "keep"
    overall_color = "#F44336" if overall_needs_calibration else "#4CAF50"
    overall_text = "⚠️ 需要校准" if overall_needs_calibration else "✅ 稳定运行"

    # 获取证据
    evidence_refs = analysis_result.get("evidence_refs", []) if isinstance(analysis_result, dict) else []
    reason_codes = analysis_result.get("reason_codes", []) if isinstance(analysis_result, dict) else []
    all_evidence = evidence_refs + reason_codes

    evidence_html = ""
    if all_evidence:
        for i, e in enumerate(all_evidence[:10], 1):  # 最多显示10条
            evidence_html += f"<li>{i}. {e}</li>"
    else:
        evidence_html = "<li>暂无证据</li>"

    # 阈值建议
    threshold_html = ""
    if thresholds:
        for k, v in thresholds.items():
            threshold_html += f"<tr><td>{k}</td><td><code>{v}</code></td></tr>"
    else:
        threshold_html = "<tr><td colspan='2'>暂无阈值建议</td></tr>"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Roboto', sans-serif;
            padding: 20px;
            background: #fafafa;
        }}
        h2 {{
            text-align: center;
            color: #333;
        }}
        .dashboard {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            max-width: 1200px;
            margin: 20px auto;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .card-title {{
            font-size: 14px;
            color: #666;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .card-value {{
            font-size: 42px;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        .card-subtitle {{
            font-size: 14px;
            color: #999;
        }}
        .evidence-section {{
            max-width: 800px;
            margin: 20px auto;
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .evidence-title {{
            font-size: 16px;
            font-weight: 500;
            color: #333;
            margin-bottom: 15px;
        }}
        .evidence-list {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .evidence-list li {{
            padding: 8px 0;
            border-bottom: 1px solid #eee;
            font-size: 13px;
            color: #555;
        }}
        .evidence-list li:last-child {{
            border-bottom: none;
        }}
        .threshold-table {{
            max-width: 600px;
            margin: 20px auto;
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            font-weight: 500;
            color: #666;
        }}
        code {{
            background: #f5f5f5;
            padding: 2px 8px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
        }}
    </style>
</head>
<body>
    <h2>🎛️ Calibration Dashboard</h2>

    <div class="dashboard">
        <div class="card">
            <div class="card-title">E[R] Mapping</div>
            <div class="card-value" style="color: {status_colors.get(er_status, '#9E9E9E')}">
                {status_labels.get(er_status, 'Unknown').upper()}
            </div>
            <div class="card-subtitle">预期收益映射</div>
        </div>
        <div class="card">
            <div class="card-title">λ Risk</div>
            <div class="card-value" style="color: {status_colors.get(lambda_status, '#9E9E9E')}">
                {status_labels.get(lambda_status, 'Unknown').upper()}
            </div>
            <div class="card-subtitle">风险敏感度</div>
        </div>
        <div class="card">
            <div class="card-title">Overall Status</div>
            <div class="card-value" style="color: {overall_color}; font-size: 24px;">
                {overall_text}
            </div>
            <div class="card-subtitle">系统状态</div>
        </div>
    </div>

    <div class="evidence-section">
        <div class="evidence-title">📋 Evidence & Reason Codes</div>
        <ul class="evidence-list">
            {evidence_html}
        </ul>
    </div>

    <div class="threshold-table">
        <div class="evidence-title">⚙️ Threshold Suggestions</div>
        <table>
            <tr>
                <th>Parameter</th>
                <th>Suggested Value</th>
            </tr>
            {threshold_html}
        </table>
    </div>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')

    return html


def render_trend_vs_resistance(trend_data: Dict, resistance_data: Dict,
                               output_path: str = None) -> str:
    """
    生成趋势 vs 阻力对比图

    Args:
        trend_data: 趋势分析数据
        resistance_data: 阻力分析数据
        output_path: 输出文件路径

    Returns:
        HTML 字符串
    """
    velocity = trend_data.get("velocity", 0)
    acceleration = trend_data.get("acceleration", 0)
    resistance_score = resistance_data.get("resistance_score", 0)

    # 计算趋势强度
    trend_strength = abs(velocity) * 10 if velocity else 50
    trend_direction = "↑" if velocity > 0 else "↓" if velocity < 0 else "→"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 20px;
            background: #fafafa;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h2 {{
            text-align: center;
            color: #333;
        }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin: 30px 0;
        }}
        .metric {{
            text-align: center;
            padding: 20px;
            background: #f9f9f9;
            border-radius: 8px;
        }}
        .metric-value {{
            font-size: 28px;
            font-weight: bold;
        }}
        .metric-label {{
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }}
        .gauge-container {{
            display: flex;
            justify-content: space-around;
            margin: 30px 0;
        }}
        canvas {{
            max-width: 300px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h2>⚖️ Trend vs Resistance Analysis</h2>

        <div class="metrics">
            <div class="metric">
                <div class="metric-value" style="color: #2196F3;">{velocity:.4f}</div>
                <div class="metric-label">Velocity (速度)</div>
            </div>
            <div class="metric">
                <div class="metric-value" style="color: #FF9800;">{acceleration:.4f}</div>
                <div class="metric-label">Acceleration (加速度)</div>
            </div>
            <div class="metric">
                <div class="metric-value" style="color: #F44336;">{resistance_score:.1f}</div>
                <div class="metric-label">Resistance (阻力)</div>
            </div>
            <div class="metric">
                <div class="metric-value">{'🟢' if velocity > 0 and resistance_score < 50 else '🔴' if velocity < 0 or resistance_score > 70 else '🟡'} {trend_direction}</div>
                <div class="metric-label">Direction</div>
            </div>
        </div>

        <div class="gauge-container">
            <div>
                <canvas id="trendGauge"></canvas>
            </div>
            <div>
                <canvas id="resistanceGauge"></canvas>
            </div>
        </div>
    </div>

    <script>
    const Chart = window.Chart;

    // 趋势仪表
    new Chart(document.getElementById('trendGauge'), {{
        type: 'doughnut',
        data: {{
            datasets: [{{
                data: [{min(100, max(0, trend_strength))}, {max(0, 100 - trend_strength)}],
                backgroundColor: ['#4CAF50', '#f5f5f5'],
                borderWidth: 0
            }}]
        }},
        options: {{
            responsive: true,
            cutout: '70%',
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{ enabled: false }},
                title: {{
                    display: true,
                    text: 'Trend Strength',
                    position: 'bottom'
                }}
            }}
        }}
    }});

    // 阻力仪表
    new Chart(document.getElementById('resistanceGauge'), {{
        type: 'doughnut',
        data: {{
            datasets: [{{
                data: [{resistance_score}, {100 - resistance_score}],
                backgroundColor: ['#F44336', '#f5f5f5'],
                borderWidth: 0
            }}]
        }},
        options: {{
            responsive: true,
            cutout: '70%',
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{ enabled: false }},
                title: {{
                    display: true,
                    text: 'Resistance Level',
                    position: 'bottom'
                }}
            }}
        }}
    }});
    </script>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')

    return html


# ============== Plotly 交互图表 ==============

def render_interactive_trend(episode_series: List[Dict],
                             output_path: str = None) -> str:
    """
    生成 Plotly 交互式图表

    支持:
    - 缩放
    - 悬停查看详细数据
    - 双 Y 轴 (价格 + 评分)

    Args:
        episode_series: episode 数据列表
        output_path: 输出文件路径

    Returns:
        HTML 字符串
    """
    # 数据准备
    timestamps = [e.get("ts", "") for e in episode_series]
    prices = []
    for e in episode_series:
        if e.get("price_ref"):
            prices.append(e["price_ref"].get("close"))
        else:
            prices.append(None)

    scores = []
    for e in episode_series:
        if e.get("scores"):
            scores.append(e["scores"].get("total"))
        else:
            scores.append(None)

    # 计算 MA
    ma20 = calculate_ma(prices, 20)
    ma60 = calculate_ma(prices, 60)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        #chart {{
            width: 100%;
            height: 600px;
        }}
    </style>
</head>
<body>
    <div id="chart"></div>
    <script>
    const trace1 = {{
        x: {json.dumps(timestamps, ensure_ascii=False)},
        y: {json.dumps(prices)},
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Price',
        line: {{color: '#3366cc', width: 2}},
        marker: {{size: 6}}
    }};

    const trace2 = {{
        x: {json.dumps(timestamps, ensure_ascii=False)},
        y: {json.dumps(ma20)},
        type: 'scatter',
        mode: 'lines',
        name: 'MA20',
        line: {{color: '#ff9900', width: 1.5, dash: 'dot'}}
    }};

    const trace3 = {{
        x: {json.dumps(timestamps, ensure_ascii=False)},
        y: {json.dumps(ma60)},
        type: 'scatter',
        mode: 'lines',
        name: 'MA60',
        line: {{color: '#109618', width: 1.5, dash: 'dash'}}
    }};

    const trace4 = {{
        x: {json.dumps(timestamps, ensure_ascii=False)},
        y: {json.dumps(scores)},
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Score',
        yaxis: 'y2',
        line: {{color: '#ff6666', width: 2}},
        marker: {{size: 8}}
    }};

    const layout = {{
        title: 'Interactive Trend Analysis',
        xaxis: {{
            title: 'Time',
            rangeslider: {{ visible: true }},
            type: 'date'
        }},
        yaxis: {{
            title: 'Price (USD)',
            showgrid: true,
            domain: [0.3, 1]
        }},
        yaxis2: {{
            title: 'Score',
            overlaying: 'y',
            side: 'right',
            showgrid: false,
            domain: [0, 0.25]
        }},
        legend: {{
            x: 0.5,
            y: 1.1,
            xanchor: 'center',
            orientation: 'h'
        }},
        hovermode: 'x unified',
        margin: {{ t: 50, r: 50, b: 100, l: 60 }}
    }};

    Plotly.newPlot('chart', [trace1, trace2, trace3, trace4], layout, {{
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    }});
    </script>
</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')

    return html


# ============== 导出接口 ==============

def render_all_charts(episode_series: List[Dict],
                      analysis_result: Dict,
                      output_dir: str = "./charts") -> Dict[str, str]:
    """
    生成所有图表

    Args:
        episode_series: episode 数据列表
        analysis_result: 分析结果
        output_dir: 输出目录

    Returns:
        文件路径字典
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    # 1. 趋势图
    paths["trend_chart"] = str(output_dir / "trend_chart.html")
    render_trend_chart(episode_series, output_path=paths["trend_chart"])

    # 2. 雷达快照
    latest = episode_series[-1] if episode_series else {}
    scores = latest.get("scores", {}) if isinstance(latest, dict) else {}
    resistance = analysis_result.get("resistance", {}) if isinstance(analysis_result, dict) else {}

    paths["radar_snapshot"] = str(output_dir / "radar_snapshot.html")
    render_radar_snapshot(scores, resistance, output_path=paths["radar_snapshot"])

    # 3. 校准仪表盘
    paths["calibration_dashboard"] = str(output_dir / "calibration_dashboard.html")
    render_calibration_dashboard(analysis_result, output_path=paths["calibration_dashboard"])

    # 4. 趋势 vs 阻力图
    paths["trend_vs_resistance"] = str(output_dir / "trend_vs_resistance.html")
    trend_data = analysis_result.get("trend", {}) if isinstance(analysis_result, dict) else {}
    render_trend_vs_resistance(trend_data, resistance, output_path=paths["trend_vs_resistance"])

    # 5. 交互式图表
    paths["interactive_trend"] = str(output_dir / "interactive_trend.html")
    render_interactive_trend(episode_series, output_path=paths["interactive_trend"])

    return paths


# ============== CLI 接口 ==============

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Dream-Data-Analysis Renderer")
    parser.add_argument("--input", "-i", help="Input JSON file path")
    parser.add_argument("--output", "-o", default="./charts", help="Output directory")
    parser.add_argument("--type", "-t", choices=["all", "trend", "radar", "dashboard", "interactive"],
                        default="all", help="Chart type to generate")

    args = parser.parse_args()

    # 加载输入数据
    if args.input:
        input_data = json.loads(Path(args.input).read_text(encoding='utf-8'))
        episode_series = input_data.get("episode_series", [])
        analysis_result = input_data.get("analysis_result", {})
    else:
        # 使用示例数据
        episode_series = []
        analysis_result = {}

    # 生成图表
    paths = render_all_charts(episode_series, analysis_result, args.output)

    print("Generated charts:")
    for name, path in paths.items():
        print(f"  {name}: {path}")
