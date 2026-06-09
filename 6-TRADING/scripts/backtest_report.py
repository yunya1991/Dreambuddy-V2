#!/usr/bin/env python3
"""
回测报告生成模块
================
将回测结果渲染为交互式HTML报告，包含:
  - 权益曲线图
  - 回撤曲线图
  - 月度收益率热力图
  - 交易记录表
  - 信号强度分析
"""

import json
import html
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# ==================== HTML模板 ====================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dream Systematic Trading - 回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d29922;
    --purple: #bc8cff;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
  h1 {{
    text-align: center;
    font-size: 28px;
    margin: 30px 0 10px;
    background: linear-gradient(135deg, var(--accent), var(--purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .subtitle {{ text-align: center; color: var(--text-muted); margin-bottom: 30px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }}
  .card-title {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
  .card-value {{ font-size: 28px; font-weight: 700; }}
  .card-value.positive {{ color: var(--green); }}
  .card-value.negative {{ color: var(--red); }}
  .card-sub {{ font-size: 13px; color: var(--text-muted); margin-top: 4px; }}
  .chart-container {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .chart-title {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; }}
  canvas {{ width: 100% !important; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th, td {{
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }}
  th {{ color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
  tr:hover {{ background: rgba(255,255,255,0.03); }}
  .tag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }}
  .tag-long {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .tag-short {{ background: rgba(248,81,73,0.15); color: var(--red); }}
  .tag-wait {{ background: rgba(139,148,158,0.15); color: var(--text-muted); }}
  .tag-win {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .tag-loss {{ background: rgba(248,81,73,0.15); color: var(--red); }}
  .heatmap {{ display: grid; gap: 3px; }}
  .heatmap-cell {{
    text-align: center;
    padding: 8px 4px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
  }}
  .section-title {{
    font-size: 18px;
    font-weight: 600;
    margin: 30px 0 16px;
    padding-left: 12px;
    border-left: 3px solid var(--accent);
  }}
  .signal-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
  .signal-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}
  .signal-name {{ font-size: 14px; font-weight: 600; margin-bottom: 8px; }}
  .signal-bar {{ height: 8px; border-radius: 4px; background: var(--border); margin: 8px 0; overflow: hidden; }}
  .signal-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
  .footer {{ text-align: center; color: var(--text-muted); margin-top: 40px; padding: 20px; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">

<h1>Dream Systematic Trading</h1>
<p class="subtitle">三屏交易体系 + 马丁策略 回测报告 | {generated_at}</p>

<!-- 核心指标 -->
<div class="grid">
  <div class="card">
    <div class="card-title">总收益率</div>
    <div class="card-value {total_return_class}">{total_return:+.2f}%</div>
    <div class="card-sub">期末 ${final_equity:,.2f}</div>
  </div>
  <div class="card">
    <div class="card-title">年化收益率</div>
    <div class="card-value {annual_return_class}">{annual_return:+.2f}%</div>
    <div class="card-sub">回测 {backtest_days} 天</div>
  </div>
  <div class="card">
    <div class="card-title">最大回撤</div>
    <div class="card-value {dd_class}">{max_drawdown:.2f}%</div>
    <div class="card-sub">{'<= 20% 达标' if max_drawdown <= 20 else '超出限制!'}</div>
  </div>
  <div class="card">
    <div class="card-title">夏普比率</div>
    <div class="card-value">{sharpe_ratio:.2f}</div>
    <div class="card-sub">风险调整收益</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <div class="card-title">胜率</div>
    <div class="card-value">{win_rate:.1f}%</div>
    <div class="card-sub">{win_trades}胜 / {total_trades}次交易</div>
  </div>
  <div class="card">
    <div class="card-title">盈亏比</div>
    <div class="card-value">{profit_factor:.2f}</div>
    <div class="card-sub">平均盈利/平均亏损</div>
  </div>
  <div class="card">
    <div class="card-title">加仓次数</div>
    <div class="card-value">{add_on_count}</div>
    <div class="card-sub">马丁策略执行</div>
  </div>
  <div class="card">
    <div class="card-title">第一屏正确率</div>
    <div class="card-value">{screen1_accuracy:.1f}%</div>
    <div class="card-sub">周线方向判断</div>
  </div>
</div>

<!-- 权益曲线 -->
<h2 class="section-title">权益曲线</h2>
<div class="chart-container">
  <canvas id="equityChart" height="100"></canvas>
</div>

<!-- 回撤曲线 -->
<h2 class="section-title">回撤曲线</h2>
<div class="chart-container">
  <canvas id="drawdownChart" height="80"></canvas>
</div>

<!-- 月度收益率热力图 -->
<h2 class="section-title">月度收益率</h2>
<div class="chart-container">
  <div id="heatmap" class="heatmap"></div>
</div>

<!-- 信号强度分析 -->
<h2 class="section-title">信号强度分析</h2>
<div class="signal-grid">
{signal_cards}
</div>

<!-- 交易记录 -->
<h2 class="section-title">交易记录</h2>
<div class="chart-container" style="overflow-x: auto;">
  <table id="tradeTable">
    <thead>
      <tr>
        <th>#</th><th>日期</th><th>操作</th><th>方向</th><th>信号</th>
        <th>价格</th><th>仓位(USDT)</th><th>手续费</th><th>盈亏</th><th>离场原因</th>
      </tr>
    </thead>
    <tbody>
{trade_rows}
    </tbody>
  </table>
</div>

<div class="footer">
  Dream Systematic Trading v1.0 | 三屏交易体系 + 马丁策略<br>
  回测仅供参考，不构成投资建议
</div>

</div>

<script>
// 权益曲线
const equityCtx = document.getElementById('equityChart').getContext('2d');
new Chart(equityCtx, {{
  type: 'line',
  data: {{
    labels: {equity_labels},
    datasets: [{{
      label: '权益 (USDT)',
      data: {equity_data},
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88,166,255,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: ctx => '$' + ctx.parsed.y.toLocaleString()
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#8b949e', maxTicksLimit: 12 }},
        grid: {{ color: 'rgba(48,54,61,0.5)' }}
      }},
      y: {{
        ticks: {{ color: '#8b949e', callback: v => '$' + v.toLocaleString() }},
        grid: {{ color: 'rgba(48,54,61,0.5)' }}
      }}
    }}
  }}
}});

// 回撤曲线
const ddCtx = document.getElementById('drawdownChart').getContext('2d');
new Chart(ddCtx, {{
  type: 'line',
  data: {{
    labels: {dd_labels},
    datasets: [{{
      label: '回撤 (%)',
      data: {dd_data},
      borderColor: '#f85149',
      backgroundColor: 'rgba(248,81,73,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{ label: ctx => ctx.parsed.y.toFixed(2) + '%' }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#8b949e', maxTicksLimit: 12 }},
        grid: {{ color: 'rgba(48,54,61,0.5)' }}
      }},
      y: {{
        ticks: {{ color: '#8b949e', callback: v => v.toFixed(0) + '%' }},
        grid: {{ color: 'rgba(48,54,61,0.5)' }}
      }}
    }}
  }}
}});

// 月度热力图
{heatmap_data}
</script>

</body>
</html>
"""


# ==================== 报告生成器 ====================

class ReportGenerator:
    def __init__(self):
        pass

    def generate(self, result: dict, output_path: str = None) -> str:
        """生成HTML报告"""
        if output_path is None:
            output_path = str(
                Path(__file__).parent.parent / "reports" /
                f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )

        # CSS类
        total_return = result.get("total_return", 0)
        annual_return = result.get("annual_return", 0)
        max_dd = result.get("max_drawdown", 0)

        total_return_class = "positive" if total_return >= 0 else "negative"
        annual_return_class = "positive" if annual_return >= 0 else "negative"
        dd_class = "negative" if max_dd > 15 else ""

        # 权益曲线数据
        eq_curve = result.get("equity_curve", [])
        equity_labels = json.dumps([p["date"] for p in eq_curve])
        equity_data = json.dumps([p["equity"] for p in eq_curve])

        # 回撤数据
        dd_curve = result.get("drawdown_curve", [])
        dd_labels = json.dumps([p["date"] for p in dd_curve])
        dd_data = json.dumps([-p["drawdown"] for p in dd_curve])  # 负值显示

        # 信号卡片
        signal_analysis = result.get("signal_analysis", {})
        signal_cards = self._build_signal_cards(signal_analysis)

        # 交易记录
        trades = result.get("trades", [])
        trade_rows = self._build_trade_rows(trades)

        # 月度热力图
        monthly = result.get("monthly_returns", {})
        heatmap_data = self._build_heatmap_js(monthly)

        # 渲染
        html_content = HTML_TEMPLATE.format(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_return=total_return,
            total_return_class=total_return_class,
            annual_return=annual_return,
            annual_return_class=annual_return_class,
            max_drawdown=max_dd,
            dd_class=dd_class,
            sharpe_ratio=result.get("sharpe_ratio", 0),
            win_rate=result.get("win_rate", 0),
            win_trades=result.get("win_trades", 0),
            total_trades=result.get("total_trades", 0),
            profit_factor=result.get("profit_factor", 0),
            add_on_count=result.get("add_on_count", 0),
            screen1_accuracy=result.get("screen1_accuracy", 0),
            final_equity=result.get("final_equity", 0),
            backtest_days=result.get("backtest_days", 0),
            equity_labels=equity_labels,
            equity_data=equity_data,
            dd_labels=dd_labels,
            dd_data=dd_data,
            signal_cards=signal_cards,
            trade_rows=trade_rows,
            heatmap_data=heatmap_data,
        )

        # 保存
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(html_content)

        return str(out)

    def _build_signal_cards(self, signal_analysis: dict) -> str:
        signal_names = {
            "strong": ("强信号", "#3fb950", ">= 70分"),
            "medium": ("中信号", "#58a6ff", "50-69分"),
            "weak": ("弱信号", "#d29922", "< 50分"),
            "none": ("无信号", "#8b949e", "< 30分"),
        }
        cards = []
        for key, (name, color, desc) in signal_names.items():
            data = signal_analysis.get(key, {})
            count = data.get("count", 0)
            wr = data.get("win_rate", 0)
            cards.append(f"""
            <div class="signal-card">
              <div class="signal-name" style="color: {color}">{html.escape(name)}</div>
              <div class="card-sub">{html.escape(desc)}</div>
              <div style="font-size: 24px; font-weight: 700; margin: 8px 0;">{count}次</div>
              <div class="signal-bar">
                <div class="signal-bar-fill" style="width: {wr}%; background: {color};"></div>
              </div>
              <div class="card-sub">胜率 {wr:.1f}%</div>
            </div>""")
        return "\n".join(cards)

    def _build_trade_rows(self, trades: list) -> str:
        rows = []
        action_names = {"open": "开仓", "add_on": "加仓", "close": "平仓"}
        direction_tags = {
            "long": '<span class="tag tag-long">多</span>',
            "short": '<span class="tag tag-short">空</span>',
            "wait": '<span class="tag tag-wait">观望</span>',
        }
        signal_names = {
            "strong": '<span style="color:#3fb950">强</span>',
            "medium": '<span style="color:#58a6ff">中</span>',
            "weak": '<span style="color:#d29922">弱</span>',
            "none": '<span style="color:#8b949e">无</span>',
        }
        exit_names = {
            "take_profit": "止盈",
            "stop_loss": "止损",
            "signal_reversal": "信号反转",
            "drawdown_limit": "回撤限制",
            "risk_event": "风险事件",
            "end_of_backtest": "回测结束",
            "none": "",
        }

        for t in trades:
            action = action_names.get(t.action, t.action)
            direction = direction_tags.get(t.direction.value, t.direction.value)
            signal = signal_names.get(t.signal_strength.value, t.signal_strength.value)
            pnl_str = ""
            pnl_class = ""
            if t.pnl != 0:
                pnl_str = f"{t.pnl:+,.2f}"
                pnl_class = "tag-win" if t.pnl > 0 else "tag-loss"
                pnl_str = f'<span class="tag {pnl_class}">{pnl_str}</span>'
            exit_r = exit_names.get(t.exit_reason.value, t.exit_reason.value)
            rows.append(
                f'<tr>'
                f'<td>{t.trade_id}</td>'
                f'<td>{t.date}</td>'
                f'<td>{action}</td>'
                f'<td>{direction}</td>'
                f'<td>{signal}</td>'
                f'<td>${t.price:,.2f}</td>'
                f'<td>{t.size_usd:,.2f}</td>'
                f'<td>{t.fee:.2f}</td>'
                f'<td>{pnl_str}</td>'
                f'<td>{exit_r}</td>'
                f'</tr>'
            )
        return "\n".join(rows)

    def _build_heatmap_js(self, monthly: dict) -> str:
        """生成月度热力图的HTML和JS"""
        if not monthly:
            return '<div style="color: var(--text-muted);">无月度数据</div>'

        # 按年分组
        years: Dict[str, Dict[str, float]] = {}
        for key, val in monthly.items():
            y, m = key.split("-")
            if y not in years:
                years[y] = {}
            years[y][m] = val

        # HTML
        cells_html = ""
        months = ["01","02","03","04","05","06","07","08","09","10","11","12"]
        month_names = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]

        # 表头
        header = '<div style="display:flex;gap:3px;margin-bottom:8px;">'
        header += '<div style="width:60px;"></div>'  # 年份列
        for mn in month_names:
            header += f'<div style="flex:1;text-align:center;font-size:11px;color:var(--text-muted);padding:4px 0;">{mn}</div>'
        header += '</div>'

        # 数据行
        for year in sorted(years.keys()):
            row = f'<div style="display:flex;gap:3px;margin-bottom:3px;">'
            row += f'<div style="width:60px;display:flex;align-items:center;font-size:13px;font-weight:600;">{year}</div>'
            for m in months:
                val = years[year].get(m, None)
                if val is not None:
                    if val >= 5:
                        bg = f"rgba(63,185,80,{min(abs(val)/20, 0.7):.2f})"
                        color = "#3fb950"
                    elif val <= -5:
                        bg = f"rgba(248,81,73,{min(abs(val)/20, 0.7):.2f})"
                        color = "#f85149"
                    else:
                        bg = "rgba(139,148,158,0.08)"
                        color = "#8b949e"
                    row += f'<div class="heatmap-cell" style="flex:1;background:{bg};color:{color};">{val:+.1f}%</div>'
                else:
                    row += f'<div class="heatmap-cell" style="flex:1;background:transparent;color:transparent;">-</div>'
            row += '</div>'
            cells_html += row

        return f"""
const heatmapContainer = document.getElementById('heatmap');
heatmapContainer.innerHTML = `
{header}
{cells_html}
`;"""
