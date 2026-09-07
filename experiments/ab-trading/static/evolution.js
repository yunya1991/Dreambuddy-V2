/**
 * 🧬 自进化架构可视化 — evolution.js
 *
 * 对应 spec: docs/superpowers/specs/2026-09-05-evolution-arch-visualization-design.md
 *
 * 4区块:
 *   1. 核心盈亏指标卡片（evolution vs main_pool）
 *   2. 累计盈亏曲线对比（ECharts折线，点击下钻）
 *   3. 每日盈亏柱状对比（ECharts柱状，点击下钻）
 *   4. 进化证据（降级显示"进化引擎数据接入中"）
 *
 * 数据源: /api/evolution-overview | /api/evolution-timeline | /api/evolution-evidence | /api/evolution-detail
 */

// ── 全局状态 ────────────────────────────────────────────────────────────
let _evoCurrentRange = 'all';
let _evoCharts = {};  // 缓存 ECharts 实例

// ── 主入口 ──────────────────────────────────────────────────────────────
async function loadEvolutionData() {
  console.log('[evolution] 加载数据, range:', _evoCurrentRange);
  window._evoDataLoaded = true;

  // 并行调用4个API（detail按需加载）
  const [overviewRes, timelineRes, evidenceRes, ftcRes] = await Promise.allSettled([
    fetchJsonWithRetry(`/api/evolution-overview?range=${_evoCurrentRange}`),
    fetchJsonWithRetry(`/api/evolution-timeline?range=${_evoCurrentRange}`),
    fetchJsonWithRetry(`/api/evolution-evidence?range=${_evoCurrentRange}`),
    fetchJsonWithRetry(`/api/evolution-ftc`),
  ]);

  // 更新最后更新时间
  document.getElementById('evo-last-update').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN');

  // 渲染5区块
  renderOverview(overviewRes.status === 'fulfilled' ? overviewRes.value : null);
  renderTimeline(timelineRes.status === 'fulfilled' ? timelineRes.value : null);
  renderEvidence(evidenceRes.status === 'fulfilled' ? evidenceRes.value : null);
  renderFTC(ftcRes.status === 'fulfilled' ? ftcRes.value : null);

  // 绑定时间窗口按钮
  bindRangeButtons();
}

// ── 辅助：fetch 重试 ────────────────────────────────────────────────────
async function fetchJsonWithRetry(url, retries = 2) {
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (i === retries) throw e;
      await new Promise(r => setTimeout(r, 500));
    }
  }
}

// ── 区块1: 核心盈亏指标卡片 ─────────────────────────────────────────────
function renderOverview(data) {
  const evoEl = document.getElementById('evo-overview-evolution');
  const mainEl = document.getElementById('evo-overview-main');

  if (!data || data.error) {
    const errMsg = data?.error || '数据加载失败';
    evoEl.innerHTML = `<div style="text-align:center;color:var(--red);padding:30px">${errMsg}</div>`;
    mainEl.innerHTML = `<div style="text-align:center;color:var(--red);padding:30px">${errMsg}</div>`;
    return;
  }

  evoEl.innerHTML = renderPoolCard('演化子池 (25U)', data.evolution, 'var(--blue)');
  mainEl.innerHTML = renderPoolCard('主池 (非evo)', data.main_pool, 'var(--purple)');
}

function renderPoolCard(title, pool, color) {
  if (!pool || pool.total_pnl === null) {
    return `
      <div style="padding:16px">
        <div style="font-weight:bold;color:${color};margin-bottom:12px">${title}</div>
        <div style="text-align:center;color:var(--muted);padding:20px">数据积累中<br><span style="font-size:11px">运行 ${pool?.running_days || 0} 天</span></div>
      </div>
    `;
  }
  const pnlColor = pool.total_pnl >= 0 ? 'var(--green)' : 'var(--red)';
  const winRatePct = (pool.win_rate * 100).toFixed(1) + '%';
  const ddPct = (pool.max_drawdown * 100).toFixed(2) + '%';
  return `
    <div style="padding:16px">
      <div style="font-weight:bold;color:${color};margin-bottom:12px">${title}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px">
        <div><div style="color:var(--muted)">总盈亏</div><div style="font-size:18px;font-weight:bold;color:${pnlColor}">${pool.total_pnl >= 0 ? '+' : ''}${pool.total_pnl.toFixed(2)} ${pool.currency}</div></div>
        <div><div style="color:var(--muted)">胜率</div><div style="font-size:18px;font-weight:bold">${winRatePct}</div></div>
        <div><div style="color:var(--muted)">最大回撤</div><div style="color:var(--red)">${ddPct}</div></div>
        <div><div style="color:var(--muted)">仓位数</div><div>${pool.position_count}</div></div>
        <div><div style="color:var(--muted)">已平仓</div><div>${pool.closed_count}</div></div>
        <div><div style="color:var(--muted)">运行天数</div><div>${pool.running_days}</div></div>
      </div>
    </div>
  `;
}

// ── 区块2+3: 累计盈亏曲线 + 每日柱状 ──────────────────────────────────────
function renderTimeline(data) {
  if (!data || data.error || !data.dates || data.dates.length === 0) {
    const errMsg = data?.error || '暂无平仓数据';
    document.getElementById('evo-chart-cumulative').innerHTML = `<div style="text-align:center;color:var(--muted);padding:60px">${errMsg}</div>`;
    document.getElementById('evo-chart-daily').innerHTML = `<div style="text-align:center;color:var(--muted);padding:40px">${errMsg}</div>`;
    return;
  }

  // 累计盈亏折线
  renderCumulativeChart(data);
  // 每日盈亏柱状
  renderDailyChart(data);
}

function renderCumulativeChart(data) {
  const container = document.getElementById('evo-chart-cumulative');
  let chart = _evoCharts.cumulative;
  if (chart) chart.dispose();
  chart = echarts.init(container);
  _evoCharts.cumulative = chart;

  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['演化子池', '主池'], top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: data.dates, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: '累计盈亏 (USDT)' },
    series: [
      {
        name: '演化子池',
        type: 'line',
        data: data.cumulative.evolution,
        smooth: true,
        itemStyle: { color: '#3b82f6' },
        emphasis: { focus: 'series' },
      },
      {
        name: '主池',
        type: 'line',
        data: data.cumulative.main_pool,
        smooth: true,
        itemStyle: { color: '#a855f7' },
        emphasis: { focus: 'series' },
      },
    ],
  };
  chart.setOption(option);

  // 点击下钻
  chart.on('click', (params) => {
    const date = data.dates[params.dataIndex];
    if (date) showTradesForDate(date, data.trade_points);
  });
}

function renderDailyChart(data) {
  const container = document.getElementById('evo-chart-daily');
  let chart = _evoCharts.daily;
  if (chart) chart.dispose();
  chart = echarts.init(container);
  _evoCharts.daily = chart;

  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['演化子池', '主池'], top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: data.dates, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: '每日盈亏 (USDT)' },
    series: [
      {
        name: '演化子池',
        type: 'bar',
        data: data.daily.evolution,
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: '主池',
        type: 'bar',
        data: data.daily.main_pool,
        itemStyle: { color: '#a855f7' },
      },
    ],
  };
  chart.setOption(option);

  // 点击下钻
  chart.on('click', (params) => {
    const date = data.dates[params.dataIndex];
    if (date) showTradesForDate(date, data.trade_points);
  });
}

// ── 区块4: 进化证据（降级显示） ─────────────────────────────────────────
function renderEvidence(data) {
  const container = document.getElementById('evo-evidence-container');
  const grid = document.getElementById('evo-evidence-grid');

  if (!data || data.error) {
    container.style.display = 'block';
    container.innerHTML = '<div style="padding:30px;color:var(--red)">数据加载失败</div>';
    grid.style.display = 'none';
    return;
  }

  // 即使 degraded 也尝试渲染已有数据（Phase 4 后 ess/gmax 来自 FTCOrchestrator）
  container.style.display = 'none';
  grid.style.display = 'grid';

  const ess = data.ess_curve || { dates: [], evolution_avg: [], main_pool_avg: [] };
  const refl = data.reflection_count || { evolution: 0, main_pool: 0, by_date: {} };
  const gmax = data.gmax_trajectory || { dates: [], gmax_mult: [] };
  const cs = data.cs_distribution || { evolution: {}, main_pool: {} };

  // ── 1. ESS 评分曲线 ──
  try {
    const dom = document.getElementById('evo-chart-ess');
    if (dom && window.echarts) {
      if (_evoCharts.ess) _evoCharts.ess.dispose();
      _evoCharts.ess = echarts.init(dom);
      _evoCharts.ess.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['演化子池 ESS', '主池参考 ESS'], textStyle: { color: 'var(--muted)', fontSize: 11 }, top: 0 },
        grid: { left: 50, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: ess.dates, axisLabel: { color: 'var(--muted)', fontSize: 10 } },
        yAxis: { type: 'value', min: 0, max: 1, axisLabel: { color: 'var(--muted)' } },
        series: [
          { name: '演化子池 ESS', type: 'line', data: ess.evolution_avg, smooth: true, itemStyle: { color: '#22c55e' }, areaStyle: { opacity: 0.15 } },
          { name: '主池参考 ESS', type: 'line', data: ess.main_pool_avg, smooth: true, itemStyle: { color: '#3b82f6' }, areaStyle: { opacity: 0.1 } },
        ],
      });
    }
  } catch (e) { console.warn('[evolution] ess chart failed:', e); }

  // ── 2. 反思触发次数（按日期柱状图）──
  try {
    const dom = document.getElementById('evo-chart-reflection');
    if (dom && window.echarts) {
      if (_evoCharts.refl) _evoCharts.refl.dispose();
      _evoCharts.refl = echarts.init(dom);
      const dates = Object.keys(refl.by_date || {}).sort();
      const counts = dates.map(d => refl.by_date[d]);
      _evoCharts.refl.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 50, right: 20, top: 20, bottom: 30 },
        xAxis: { type: 'category', data: dates, axisLabel: { color: 'var(--muted)', fontSize: 10, rotate: 30 } },
        yAxis: { type: 'value', axisLabel: { color: 'var(--muted)' } },
        series: [{
          type: 'bar', data: counts, barWidth: '50%',
          itemStyle: { color: '#a855f7' },
          label: { show: true, position: 'top', color: '#fff', fontSize: 10 },
        }],
      });
    }
  } catch (e) { console.warn('[evolution] reflection chart failed:', e); }

  // ── 3. gmax 校准轨迹 ──
  try {
    const dom = document.getElementById('evo-chart-gmax');
    if (dom && window.echarts) {
      if (_evoCharts.gmax) _evoCharts.gmax.dispose();
      _evoCharts.gmax = echarts.init(dom);
      _evoCharts.gmax.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 50, right: 20, top: 20, bottom: 30 },
        xAxis: { type: 'category', data: gmax.dates, axisLabel: { color: 'var(--muted)', fontSize: 10 } },
        yAxis: { type: 'value', min: 0, max: 0.5, axisLabel: { color: 'var(--muted)' } },
        series: [{
          type: 'line', data: gmax.gmax_mult, smooth: true,
          itemStyle: { color: '#f97316' },
          areaStyle: { opacity: 0.2 },
          markLine: {
            silent: true,
            data: [{ yAxis: 0.3, lineStyle: { color: '#f97316', type: 'dashed' }, label: { formatter: '初始 0.3', color: '#f97316', fontSize: 10 } }],
          },
        }],
      });
    }
  } catch (e) { console.warn('[evolution] gmax chart failed:', e); }

  // ── 4. CS 一致性分布（箱线图模拟）──
  try {
    const dom = document.getElementById('evo-chart-cs');
    if (dom && window.echarts) {
      if (_evoCharts.cs) _evoCharts.cs.dispose();
      _evoCharts.cs = echarts.init(dom);
      const evoCs = cs.evolution || {};
      const mainCs = cs.main_pool || {};
      _evoCharts.cs.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 60, right: 20, top: 20, bottom: 30 },
        xAxis: { type: 'category', data: ['演化子池', '主池'], axisLabel: { color: 'var(--muted)', fontSize: 11 } },
        yAxis: { type: 'value', min: 0, max: 1, name: 'CS 置信度', nameTextStyle: { color: 'var(--muted)', fontSize: 10 }, axisLabel: { color: 'var(--muted)' } },
        series: [{
          type: 'boxplot',
          data: [
            [evoCs.min || 0, evoCs.p25 || 0, evoCs.median || 0, evoCs.p75 || 0, evoCs.max || 0],
            [mainCs.min || 0, mainCs.p25 || 0, mainCs.median || 0, mainCs.p75 || 0, mainCs.max || 0],
          ],
          itemStyle: { color: 'rgba(168,85,247,0.3)', borderColor: '#a855f7' },
        }],
      });
    }
  } catch (e) { console.warn('[evolution] cs chart failed:', e); }
}

// ── 下钻 modal ──────────────────────────────────────────────────────────
async function showTradesForDate(date, tradePoints) {
  const evoTrades = (tradePoints.evolution || []).filter(t => t.date === date);
  const mainTrades = (tradePoints.main_pool || []).filter(t => t.date === date);
  const allTrades = [...evoTrades, ...mainTrades];

  if (allTrades.length === 0) {
    showDetailModal(`<h3>${date} 交易</h3><p>当日无交易记录</p>`);
    return;
  }

  let html = `<h3>${date} 交易（共 ${allTrades.length} 笔）</h3>`;
  html += '<table style="width:100%;border-collapse:collapse;font-size:13px"><thead><tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:8px">币种</th><th>方向</th><th>来源</th><th>盈亏</th><th>操作</th></tr></thead><tbody>';
  for (const t of allTrades) {
    const pool = tradePoints.evolution.includes(t) ? '演化子池' : '主池';
    const pnlColor = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
    html += `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:8px">${t.symbol}</td>
      <td style="text-align:center">${t.direction}</td>
      <td style="text-align:center">${pool}</td>
      <td style="text-align:center;color:${pnlColor}">${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(4)}</td>
      <td style="text-align:center"><button onclick="showTradeDetail('${t.trade_id}')" style="background:var(--border);border:none;color:var(--text);padding:4px 8px;border-radius:4px;cursor:pointer">详情</button></td>
    </tr>`;
  }
  html += '</tbody></table>';
  showDetailModal(html);
}

async function showTradeDetail(tradeId) {
  showDetailModal('<div style="text-align:center;padding:30px">加载交易详情...</div>');
  try {
    const data = await fetchJsonWithRetry(`/api/evolution-detail?type=trade&id=${tradeId}`);
    if (data.error) {
      showDetailModal(`<h3>交易详情</h3><p style="color:var(--red)">${data.error}</p>`);
      return;
    }
    let html = `<h3>交易详情 — ${data.symbol} ${data.direction}</h3>`;
    html += '<table style="width:100%;border-collapse:collapse;font-size:13px"><tbody>';
    const rows = [
      ['Trade ID', data.trade_id],
      ['币种', data.symbol],
      ['方向', data.direction],
      ['来源', data.source_tag],
      ['入场时间', data.entry_time],
      ['入场价', data.entry_price],
      ['出场时间', data.exit_time],
      ['出场价', data.exit_price],
      ['盈亏', `<span style="color:${data.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${data.pnl >= 0 ? '+' : ''}${data.pnl}</span>`],
      ['盈亏%', (data.pnl_pct * 100).toFixed(4) + '%'],
      ['出场原因', data.exit_reason],
      ['置信度', data.confidence],
      ['卦象', data.hexagram],
    ];
    for (const [k, v] of rows) {
      html += `<tr style="border-bottom:1px solid var(--border)"><td style="padding:8px;color:var(--muted)">${k}</td><td style="padding:8px">${v}</td></tr>`;
    }
    html += '</tbody></table>';
    showDetailModal(html);
  } catch (e) {
    showDetailModal(`<h3>交易详情</h3><p style="color:var(--red)">加载失败: ${e.message}</p>`);
  }
}

function showDetailModal(html) {
  document.getElementById('evo-detail-content').innerHTML = html;
  document.getElementById('evo-detail-modal').style.display = 'block';
}

// ── 时间窗口切换 ────────────────────────────────────────────────────────
function bindRangeButtons() {
  const btns = document.querySelectorAll('.evo-range-btn');
  btns.forEach(btn => {
    if (btn._bound) return;
    btn._bound = true;
    btn.addEventListener('click', () => {
      btns.forEach(b => {
        b.classList.remove('active');
        b.style.background = 'var(--border)';
        b.style.color = 'var(--text)';
      });
      btn.classList.add('active');
      btn.style.background = 'var(--blue)';
      btn.style.color = '#fff';
      _evoCurrentRange = btn.dataset.range;
      loadEvolutionData();
    });
  });
}

// ── 窗口 resize 重绘图表 ─────────────────────────────────────────────────
window.addEventListener('resize', () => {
  Object.values(_evoCharts).forEach(c => c && c.resize());
});

// ── 区块5: FTC 金融思维链核心指标 ───────────────────────────────────────
function renderFTC(data) {
  const container = document.getElementById('evo-ftc-container');
  if (!container) return;

  if (!data || data.degraded) {
    container.innerHTML = `<div style="text-align:center;color:var(--muted);padding:30px">FTC 数据加载中${data && data.error ? `: ${data.error}` : ''}...</div>`;
    return;
  }

  const ts = data.track_summary || {};
  const ess = data.ess_stats || {};
  const trackColor = { exploit: '#22c55e', mixed: '#eab308', explore: '#f97316', discard: '#ef4444' };
  const trackLabel = { exploit: '利用(满仓)', mixed: '混合(半仓)', explore: '探索(小仓)', discard: '丢弃' };

  let html = '';

  // ── 顶部指标卡片：总数 + ε + ESS 统计 ──
  html += `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px">`;
  html += `<div style="background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.2);border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:11px;color:var(--muted)">FTC 总数</div>
    <div style="font-size:24px;font-weight:700;color:#a855f7">${data.total || 0}</div>
  </div>`;
  const eps = data.epsilon || 0;
  const epsRange = data.epsilon_range || { min: 0.2, max: 0.6 };
  const epsPct = ((eps - epsRange.min) / (epsRange.max - epsRange.min)) * 100;
  html += `<div style="background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.2);border-radius:8px;padding:12px">
    <div style="font-size:11px;color:var(--muted)">ε 探索因子</div>
    <div style="font-size:24px;font-weight:700;color:#a855f7">${eps.toFixed(3)}</div>
    <div style="font-size:10px;color:var(--muted)">地板 ${epsRange.min} ~ 天花板 ${epsRange.max}</div>
    <div style="height:4px;background:var(--border);border-radius:2px;margin-top:6px;overflow:hidden">
      <div style="height:100%;width:${Math.max(0, Math.min(100, epsPct))}%;background:#a855f7;border-radius:2px"></div>
    </div>
  </div>`;
  html += `<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:11px;color:var(--muted)">ESS 均值 / 最高</div>
    <div style="font-size:20px;font-weight:700;color:#22c55e">${(ess.mean || 0).toFixed(3)} / ${(ess.max || 0).toFixed(3)}</div>
    <div style="font-size:10px;color:var(--muted)">最低 ${(ess.min || 0).toFixed(3)} · 样本 ${ess.count || 0}</div>
  </div>`;
  // 轨道分布概览
  html += `<div style="background:rgba(234,179,8,0.08);border:1px solid rgba(234,179,8,0.2);border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:11px;color:var(--muted)">轨道分布</div>
    <div style="display:flex;justify-content:center;gap:8px;margin-top:4px">
      <span style="color:#22c55e;font-weight:600">${ts.exploit || 0}</span>
      <span style="color:var(--muted);font-size:10px">/</span>
      <span style="color:#eab308;font-weight:600">${ts.mixed || 0}</span>
      <span style="color:var(--muted);font-size:10px">/</span>
      <span style="color:#f97316;font-weight:600">${ts.explore || 0}</span>
      <span style="color:var(--muted);font-size:10px">/</span>
      <span style="color:#ef4444;font-weight:600">${ts.discard || 0}</span>
    </div>
    <div style="font-size:10px;color:var(--muted)">利用/混合/探索/丢弃</div>
  </div>`;
  html += `</div>`;

  // ── 轨道分布柱状图 ──
  html += `<div id="evo-chart-ftc-track" style="height:200px;margin-bottom:16px"></div>`;

  // ── Top FTC 表格 ──
  const topFtcs = data.top_ftcs || [];
  html += `<div style="font-weight:bold;margin-bottom:8px">Top FTC（按 ESS 排序）</div>`;
  html += `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">`;
  html += `<thead><tr style="border-bottom:1px solid var(--border);color:var(--muted)">
    <th style="text-align:left;padding:6px 8px">#</th>
    <th style="text-align:left;padding:6px 8px">FTC ID</th>
    <th style="text-align:right;padding:6px 8px">ESS</th>
    <th style="text-align:center;padding:6px 8px">轨道</th>
    <th style="text-align:right;padding:6px 8px">回测样本 N</th>
  </tr></thead><tbody>`;
  topFtcs.forEach((f, i) => {
    const tc = trackColor[f.track] || 'var(--muted)';
    html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
      <td style="padding:6px 8px;color:var(--muted)">${i + 1}</td>
      <td style="padding:6px 8px;font-family:monospace;font-size:11px">${f.ftc_id}</td>
      <td style="padding:6px 8px;text-align:right;font-weight:600">${f.ess != null ? f.ess.toFixed(3) : '-'}</td>
      <td style="padding:6px 8px;text-align:center"><span style="color:${tc};font-weight:600">${trackLabel[f.track] || f.track}</span></td>
      <td style="padding:6px 8px;text-align:right">${f.n_samples || 0}</td>
    </tr>`;
  });
  if (topFtcs.length === 0) {
    html += `<tr><td colspan="5" style="text-align:center;padding:16px;color:var(--muted)">暂无 FTC 数据</td></tr>`;
  }
  html += `</tbody></table></div>`;

  // ── 最近实盘 FTC 触发活动 ──
  const recent = data.recent_ftc_activity || [];
  if (recent.length > 0) {
    html += `<div style="font-weight:bold;margin:16px 0 8px">最近实盘 FTC 触发活动</div>`;
    html += `<div style="display:flex;gap:8px;flex-wrap:wrap">`;
    recent.forEach(r => {
      const pnlColor = r.total_pnl >= 0 ? '#22c55e' : '#ef4444';
      html += `<div style="background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.15);border-radius:6px;padding:8px 12px">
        <div style="font-family:monospace;font-size:11px;color:var(--text)">${r.ftc_id}</div>
        <div style="font-size:11px;color:var(--muted)">触发 ${r.trade_count} 次 · <span style="color:${pnlColor};font-weight:600">${r.total_pnl >= 0 ? '+' : ''}${r.total_pnl.toFixed(2)}U</span></div>
      </div>`;
    });
    html += `</div>`;
  }

  container.innerHTML = html;

  // 渲染轨道分布柱状图
  try {
    const chartDom = document.getElementById('evo-chart-ftc-track');
    if (chartDom && window.echarts) {
      if (_evoCharts.ftcTrack) _evoCharts.ftcTrack.dispose();
      _evoCharts.ftcTrack = echarts.init(chartDom);
      _evoCharts.ftcTrack.setOption({
        title: { text: 'FTC 轨道分布', textStyle: { fontSize: 12, color: '#a855f7' }, left: 0 },
        tooltip: { trigger: 'axis' },
        grid: { left: 50, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: ['利用 exploit', '混合 mixed', '探索 explore', '丢弃 discard'], axisLabel: { color: 'var(--muted)', fontSize: 11 } },
        yAxis: { type: 'value', axisLabel: { color: 'var(--muted)' } },
        series: [{
          type: 'bar',
          data: [
            { value: ts.exploit || 0, itemStyle: { color: '#22c55e' } },
            { value: ts.mixed || 0, itemStyle: { color: '#eab308' } },
            { value: ts.explore || 0, itemStyle: { color: '#f97316' } },
            { value: ts.discard || 0, itemStyle: { color: '#ef4444' } },
          ],
          barWidth: '40%',
          label: { show: true, position: 'top', color: '#fff', fontSize: 12 },
        }],
      });
    }
  } catch (e) {
    console.warn('[evolution] FTC track chart render failed:', e);
  }
}
