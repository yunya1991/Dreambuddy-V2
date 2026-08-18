"""
6-TRADING Screen 2 全流程执行器 v1.1
职责划分（遵循 TRIGGER_PROMPTS v1.6）：
  Phase-0: Tavily 搜索采集 BTC 当前数据
  Phase-M: memory_db prefetch → 历史背景注入 A1/A2
  Phase-1: 调用 screen2_qwen.py（qwen-analyst 驱动 A1/A2/A3）
  Phase-3: 写入产物到 GitHub + memory_db 索引 preset

用法:
    python screen2_runner.py [--date YYYYMMDD] [--dry-run]
    python screen2_runner.py  # 自动取今日日期
"""
import sys, io, os, json, urllib.request, ssl, subprocess, argparse, base64
from datetime import datetime, timezone

# 延迟导入 memory_db（不影响无 DB 的运行）
def _try_import_memory_db():
    try:
        import memory_db as _mdb
        _mdb.init_db()
        return _mdb
    except Exception as e:
        print(f'[runner] memory_db unavailable: {e}', file=sys.stderr)
        return None

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── 配置 ─────────────────────────────────────────────────────────────────────

TAVILY_KEY = os.environ.get('TAVILY_API_KEY', '')
GITHUB_TOKEN = os.environ.get('GH_TOKEN', '') or os.environ.get('GITHUB_TOKEN', '')
REPO = 'yunya1991/Dreambuddy-V2'
SCREEN2_SCRIPT    = 'C:/tmp/screen2_qwen.py'
V15_SIGNAL_SCRIPT = 'C:/tmp/v15_signal.py'

# A 系列覆盖 V15 的置信度门槛（A2.trend_confidence）
AI_CONFIDENCE_THRESHOLD = 0.70

# screen1 记忆中的基准价（用于漂移检查，可被 --basis 参数覆盖）
DEFAULT_SCREEN1_BASIS = 76981

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


# ─── Phase-0: Tavily 搜索 ─────────────────────────────────────────────────────

def tavily_search(query, search_depth='basic', max_results=5):
    data = json.dumps({
        'api_key': TAVILY_KEY,
        'query': query,
        'search_depth': search_depth,
        'max_results': max_results,
    }).encode()
    req = urllib.request.Request(
        'https://api.tavily.com/search',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as r:
        return json.loads(r.read())


def phase0_collect(date_str):
    """P0.1-P0.3: 采集 BTC 价格、资金费率、ETF流向"""
    print('[Phase-0] P0.1 采集 BTC 当前价格...', file=sys.stderr)
    r1 = tavily_search(f'Bitcoin BTC price USD {date_str} current', search_depth='basic', max_results=3)
    price_snippet = r1.get('results', [{}])[0].get('content', '') if r1.get('results') else ''

    print('[Phase-0] P0.2 采集资金费率...', file=sys.stderr)
    r2 = tavily_search(f'Bitcoin perpetual futures funding rate {date_str} OKX Binance', search_depth='basic', max_results=3)
    funding_snippet = r2.get('results', [{}])[0].get('content', '') if r2.get('results') else ''

    print('[Phase-0] P0.3 采集 ETF 流向...', file=sys.stderr)
    r3 = tavily_search(f'Bitcoin spot ETF net inflow outflow {date_str}', search_depth='basic', max_results=3)
    etf_snippet = r3.get('results', [{}])[0].get('content', '') if r3.get('results') else ''

    return {
        'date': date_str,
        'raw_price_snippet': price_snippet[:500],
        'raw_funding_snippet': funding_snippet[:500],
        'raw_etf_snippet': etf_snippet[:500],
        'tavily_results': {
            'price_results': r1.get('results', [])[:2],
            'funding_results': r2.get('results', [])[:2],
            'etf_results': r3.get('results', [])[:2],
        }
    }


def extract_price_from_snippets(snippets_text):
    """简单启发式提取价格数字（BTC 通常在 70k-120k 范围）"""
    import re
    matches = re.findall(r'\$?\b(7[0-9],\d{3}|8[0-9],\d{3}|9[0-9],\d{3}|1[01][0-9],\d{3})\b', snippets_text.replace(',', ','))
    if not matches:
        # 尝试不带逗号格式
        matches = re.findall(r'\b(7\d{4}|8\d{4}|9\d{4}|1[01]\d{4})\b', snippets_text)
    if matches:
        price_str = matches[0].replace(',', '')
        return int(price_str)
    return None


def check_price_drift(current_price, basis_price):
    """P0.2: 漂移检查，返回 (drift_pct, drift_level)"""
    drift = abs(current_price - basis_price) / basis_price * 100
    if drift > 10:
        level = 'CRITICAL'
    elif drift > 5:
        level = 'WARNING'
    else:
        level = 'OK'
    return drift, level


# ─── Phase-1: qwen-analyst 驱动 A1/A2/A3 ─────────────────────────────────────

def phase1_qwen(phase0_data, screen1_context):
    """调用 screen2_qwen.py 执行 A1→A2→A3"""
    ctx = {**screen1_context, **phase0_data, 'session_id': phase0_data['session_id']}
    r = subprocess.run(
        ['python', SCREEN2_SCRIPT, json.dumps(ctx, ensure_ascii=True)],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=300
    )
    if r.returncode != 0:
        raise RuntimeError(f'screen2_qwen.py failed (rc={r.returncode}): {r.stderr[:400]}')
    return json.loads(r.stdout)


# ─── Phase-3: 写入 GitHub ────────────────────────────────────────────────────

def gh_put_file(path, content_str, commit_msg):
    """PUT 文件到 GitHub，自动处理 create/update"""
    content_b64 = base64.b64encode(content_str.encode('utf-8')).decode()
    url = f'https://api.github.com/repos/{REPO}/contents/{path}'
    req_get = urllib.request.Request(url, headers={
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
    })
    sha = None
    try:
        with urllib.request.urlopen(req_get, context=ssl_ctx, timeout=15) as rg:
            sha = json.loads(rg.read()).get('sha')
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    body = {'message': commit_msg, 'content': content_b64}
    if sha:
        body['sha'] = sha

    req_put = urllib.request.Request(url,
        data=json.dumps(body).encode(),
        headers={
            'Authorization': f'token {GITHUB_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/vnd.github+json',
        },
        method='PUT'
    )
    with urllib.request.urlopen(req_put, context=ssl_ctx, timeout=30) as rp:
        result = json.loads(rp.read())
    return result.get('content', {}).get('sha', '')[:8]


def phase3_write_github(session_id, phase0_data, qwen_result, dry_run=False):
    """写入 9 个产物文件到 GitHub sessions/ 目录（含 A4 挂单计划 + V15 影子 + 裁决）"""
    base = f'6-TRADING/sessions/{session_id}/team-a/screen2'
    presets = qwen_result['daily_presets']
    a1, a2, a3 = qwen_result['a1'], qwen_result['a2'], qwen_result['a3']
    a4 = qwen_result.get('a4', {})

    files = {
        'a1-daily-contradiction.md': f"""---
chain_phase: A1
type: daily_contradiction
session_id: {session_id}
driven_by: qwen-plus
---

# A1 日线矛盾分析

**主要矛盾**: {a1.get('primary_contradiction', '')}

**矛盾比例**: {a1.get('contradiction_score', '')}

**多方论据**:
{chr(10).join('- ' + e for e in a1.get('bull_evidence', []))}

**空方论据**:
{chr(10).join('- ' + e for e in a1.get('bear_evidence', []))}

**日线约束**:
- 阻力: {a1.get('daily_constraints', {}).get('resistance', 'N/A')}
- 支撑: {a1.get('daily_constraints', {}).get('support', 'N/A')}
- 失效: {a1.get('daily_constraints', {}).get('invalidation', 'N/A')}

**结论**: {a1.get('summary', '')}
""",
        'a2-daily-first-principles.md': f"""---
chain_phase: A2
type: daily_first_principles
session_id: {session_id}
driven_by: qwen-plus
---

# A2 第一性原理

**基础成立**: {a2.get('foundation_intact', True)}

**推导链**:
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(a2.get('reasoning_chain', [])))}

**最小阻力路径**: {a2.get('minimum_resistance_path', '')}

**失效条件**: {a2.get('invalidation_threshold', '')}

**趋势置信度**: {a2.get('trend_confidence', 0)} | **Screen1对齐度**: {a2.get('screen1_alignment_pct', 0)}%

**结论**: {a2.get('summary', '')}
""",
        'a3-daily-simulation.md': f"""---
chain_phase: A3
type: daily_simulation
session_id: {session_id}
driven_by: qwen-max
red_team_flag: {str(a3.get('red_team_analysis', {}).get('red_team_flag', False)).lower()}
---

# A3 三情景沙盘

## S1 基准情景 (P={a3.get('S1', {}).get('probability', 0)})
{json.dumps(a3.get('S1', {}), ensure_ascii=False, indent=2)}

## S2 对立情景 (P={a3.get('S2', {}).get('probability', 0)})
{json.dumps(a3.get('S2', {}), ensure_ascii=False, indent=2)}

## S3 极端情景 (P={a3.get('S3', {}).get('probability', 0)})
{json.dumps(a3.get('S3', {}), ensure_ascii=False, indent=2)}

## [RED_TEAM_ANALYSIS]
{json.dumps(a3.get('red_team_analysis', {}), ensure_ascii=False, indent=2)}

## Phase7 应急预案
{json.dumps(a3.get('phase7_contingency', {}), ensure_ascii=False, indent=2)}
""",
        'daily-presets.json': json.dumps(presets, ensure_ascii=False, indent=2),
        'martingale-grid.json': json.dumps({
            'session_id': session_id,
            'generated_at': phase0_data['date'],
            'driven_by': 'qwen3.7-max+deepseek',
            'primary_direction': presets.get('screen1_direction'),
            'S1': presets.get('martingale_presets', {}).get('S1'),
            'S2': presets.get('martingale_presets', {}).get('S2'),
            'S3': presets.get('martingale_presets', {}).get('S3'),
        }, ensure_ascii=False, indent=2),
        'a4-order-plan.json': json.dumps(a4, ensure_ascii=False, indent=2),
        'v15-shadow.json': json.dumps(qwen_result.get('v15', {}), ensure_ascii=False, indent=2),
        'execution-decision.json': json.dumps(qwen_result.get('decision', {}), ensure_ascii=False, indent=2),
        'order-plan.md': f"""---
chain_phase: A4
type: order_plan
session_id: {session_id}
strategy: {a4.get('strategy', 'V15_martingale')}
direction: {a4.get('direction')}
status: {a4.get('status', 'PENDING_EXECUTION')}
---

# A4 挂单计划

**策略**: {a4.get('strategy')} | **方向**: {a4.get('direction')} | **总敞口**: {a4.get('total_exposure_usdt')} USDT

**入场区**: {a4.get('entry_zone')} | **TP**: {a4.get('tp_target')} | **SL**: {a4.get('sl_trigger')}

**触发条件**: {a4.get('execute_condition')}

## 挂单明细

| 层级 | 类型 | 方向 | 价格 | 仓位(USDT) | TP | SL |
|------|------|------|------|-----------|----|----|
{chr(10).join(f"| {o['layer']} | {o['type']} | {o['direction']} | {o['price']:,} | {o['size_usdt']} | {o['tp']} | {o['sl']} |" for o in a4.get('orders', []))}

**S2 取消条件**: {a4.get('s2_cancel_condition')}

> {a4.get('note')}
""",
    }

    print(f'[Phase-3] 写入 {len(files)} 个产物到 GitHub {base}/...', file=sys.stderr)
    results = {}
    for fname, content in files.items():
        fpath = f'{base}/{fname}'
        if dry_run:
            print(f'  [DRY-RUN] 跳过写入: {fpath}', file=sys.stderr)
            results[fname] = 'dry-run'
        else:
            sha = gh_put_file(fpath, content, f'feat: Screen2 {session_id} {fname}')
            print(f'  OK {fname} (sha={sha})', file=sys.stderr)
            results[fname] = sha
    return results


# ─── Phase-V: V15 机械信号（影子计算）────────────────────────────────────────

def phase_v_signal(direction: str, current_price: float, position_cap: float) -> dict:
    """
    运行 v15_signal.py 获取 V15 机械入场信号。
    非阻塞：失败时返回 {'v15_signal': {'signal': 'UNAVAILABLE'}} 不影响主流程。
    """
    try:
        r = subprocess.run(
            ['python', V15_SIGNAL_SCRIPT,
             '--direction', direction,
             '--price', str(int(current_price))],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=45,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        print(f'[Phase-V] v15_signal.py rc={r.returncode}: {r.stderr[:200]}', file=sys.stderr)
    except Exception as e:
        print(f'[Phase-V] 失败（降级跳过）: {e}', file=sys.stderr)
    return {'v15_signal': {'signal': 'UNAVAILABLE'}, 'error': 'v15_signal unavailable'}


# ─── Phase-D: 裁决层（AI vs V15）────────────────────────────────────────────

def phase_decision(a2_result: dict, a3_result: dict, v15_result: dict,
                   direction: str, date_str: str) -> dict:
    """
    裁决规则:
      A2.trend_confidence >= AI_CONFIDENCE_THRESHOLD
      AND A3.red_team_flag == False
        → 执行 AI 挂单（A 系列覆盖 V15）
      否则 → 执行 V15 机械挂单（回退基线）
    """
    confidence   = float(a2_result.get('trend_confidence') or 0)
    red_team     = bool(a3_result.get('red_team_analysis', {}).get('red_team_flag', True))
    v15_sig      = v15_result.get('v15_signal', {})
    v15_available = v15_sig.get('signal') not in ('UNAVAILABLE', None)

    ai_override = confidence >= AI_CONFIDENCE_THRESHOLD and not red_team

    if ai_override:
        execution = 'AI'
        reason    = (f'trend_confidence={confidence:.2f} >= {AI_CONFIDENCE_THRESHOLD}'
                     f', red_team_flag=False')
    elif not v15_available:
        execution = 'AI'
        reason    = 'V15 信号不可用，回退 AI'
    else:
        execution = 'V15'
        if confidence < AI_CONFIDENCE_THRESHOLD:
            reason = (f'trend_confidence={confidence:.2f} < {AI_CONFIDENCE_THRESHOLD}'
                      f'，AI 置信度不足，使用 V15 基线')
        else:
            reason = 'red_team_flag=True，AI 红队警告，使用 V15 基线'

    v15_direction = v15_sig.get('signal', 'WAIT')
    signal_agree  = (v15_direction == direction) if v15_direction not in ('WAIT', 'UNAVAILABLE') else None

    return {
        'date':               date_str,
        'execution':          execution,       # 'AI' | 'V15'
        'ai_override':        ai_override,
        'ai_confidence':      confidence,
        'threshold':          AI_CONFIDENCE_THRESHOLD,
        'red_team_flag':      red_team,
        'reason':             reason,
        'v15_signal':         v15_direction,
        'v15_position':       v15_result.get('price_position'),
        'v15_fib_zone':       v15_sig.get('fib_zone'),
        'ai_signal':          direction,
        'signals_agree':      signal_agree,    # None=V15 WAIT，True=一致，False=分歧
        'process_d_ref': {
            'v15_entry': v15_sig.get('entry'),
            'v15_tp':    v15_sig.get('TP'),
            'v15_sl':    v15_sig.get('SL'),
            'ai_entry':  None,                 # 由 A4 填充
        },
    }


# ─── Phase-4: A4 挂单计划（V15 马丁格基线）─────────────────────────────────

POSITION_CAP_USDT = 150  # 默认仓位上限，可被 session_state 覆盖


def phase4_order_plan(a3_result, direction, current_price, date_str,
                      position_cap_usdt=POSITION_CAP_USDT,
                      decision=None, v15_result=None):
    """
    A4: 根据 Phase-D 裁决结果，用 AI 或 V15 参数生成挂单。
    decision['execution'] == 'V15' 时使用 v15_result 中的 orders 和参数。
    decision['execution'] == 'AI'  时使用 A3.S1 参数（原逻辑）。
    """
    execution = (decision or {}).get('execution', 'AI')

    # ── V15 路径 ──────────────────────────────────────────────────────────────
    if execution == 'V15' and v15_result:
        v15_sig = v15_result.get('v15_signal', {})
        if v15_sig.get('signal') == 'WAIT':
            return {
                'date': date_str, 'source': 'V15_mechanical',
                'strategy': 'V15_mechanical', 'direction': direction,
                'status': 'NO_SIGNAL', 'orders': [], 'total_exposure_usdt': 0,
                'reason': f"V15 WAIT: {v15_sig.get('reason', 'not in Fib zone')}",
            }
        orders   = v15_sig.get('orders', [])
        tp       = v15_sig.get('TP')
        sl       = v15_sig.get('SL')
        entry    = v15_sig.get('entry', current_price)
        fib_zone = v15_sig.get('fib_zone', 'unknown')
        return {
            'date':                date_str,
            'source':              'V15_mechanical',
            'strategy':            'V15_mechanical',
            'direction':           direction,
            'entry_zone':          [entry, entry],
            'total_exposure_usdt': round(sum(o['size_usdt'] for o in orders), 1),
            'tp_target':           tp,
            'sl_trigger':          sl,
            'grid_spacing_pct':    1.5,
            'fib_zone':            fib_zone,
            'size_mult':           v15_sig.get('size_mult', 1.0),
            'orders':              orders,
            'status':              'PENDING_EXECUTION',
            'execute_condition':   f'V15 BELOW_ALL Fib {fib_zone} zone',
            'note':                'V15 机械信号，AI 置信度不足时启用',
        }

    # ── AI 路径（A3 S1 参数）─────────────────────────────────────────────────
    s1 = a3_result.get('S1', {})
    s2 = a3_result.get('S2', {})

    entry_zone = s1.get('entry_zone') or [
        round(current_price * 0.99), round(current_price * 1.01)
    ]
    tp       = s1.get('TP')
    sl       = s1.get('SL')
    l0_pct   = (s1.get('L0_position_pct')  or 30)  / 100
    grid_pct = (s1.get('grid_spacing_pct') or 1.5) / 100

    l0_price   = entry_zone[1] if direction == 'SHORT' else entry_zone[0]
    layer_sign = 1 if direction == 'SHORT' else -1

    remaining = round(1.0 - l0_pct, 4)
    pcts = [l0_pct] + [round(remaining / 3, 4)] * 3

    orders = []
    for i in range(4):
        price = round(l0_price * (1 + layer_sign * grid_pct * i))
        size  = round(position_cap_usdt * pcts[i], 1)
        orders.append({
            'layer': f'L{i}', 'type': 'limit', 'direction': direction,
            'price': price, 'size_usdt': size,
            'tp': tp, 'sl': sl, 'status': 'pending',
        })

    plan = {
        'date':                date_str,
        'source':              'AI_driven',
        'strategy':            'AI_martingale',
        'direction':           direction,
        'entry_zone':          entry_zone,
        'total_exposure_usdt': round(sum(o['size_usdt'] for o in orders), 1),
        'tp_target':           tp,
        'sl_trigger':          sl,
        'grid_spacing_pct':    round(grid_pct * 100, 2),
        'orders':              orders,
        'status':              'PENDING_EXECUTION',
        'execute_condition':   s1.get('trigger', 'entry_zone_reached'),
        's1_probability':      s1.get('probability'),
        's2_cancel_condition': s2.get('trigger'),
        'note':                'AI 高置信度信号，L0 先挂；L1-L3 随马丁触发逐层挂入',
    }
    # 回填 process_d_ref 中的 ai_entry
    if decision and 'process_d_ref' in decision:
        decision['process_d_ref']['ai_entry'] = l0_price
    return plan


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=None, help='YYYYMMDD, default: today')
    parser.add_argument('--basis', type=int, default=DEFAULT_SCREEN1_BASIS,
                        help='screen1_btc_price_basis for drift check')
    parser.add_argument('--direction', default='SHORT', help='screen1_direction')
    parser.add_argument('--score', type=int, default=68, help='screen1_score')
    parser.add_argument('--dry-run', action='store_true', help='Skip GitHub writes')
    args = parser.parse_args()

    today = args.date or datetime.now(timezone.utc).strftime('%Y%m%d')
    date_str = f'{today[:4]}-{today[4:6]}-{today[6:]}'
    session_id = f'{today}-BTC-SCREEN2'

    print(f'=== 6-TRADING Screen 2 Runner | session={session_id} ===', file=sys.stderr)

    # Phase-0
    if not TAVILY_KEY:
        print('[WARN] TAVILY_API_KEY not set — Phase-0 skipped, using mock data', file=sys.stderr)
        phase0_data = {
            'date': date_str, 'session_id': session_id,
            'btc_price_current': args.basis,
            'funding_rate': 'unknown', 'etf_flows': 'unknown',
            'raw_price_snippet': '', 'raw_funding_snippet': '', 'raw_etf_snippet': '',
        }
        current_price = args.basis
    else:
        phase0_raw = phase0_collect(date_str)
        price_text = phase0_raw['raw_price_snippet'] + ' '.join(
            r.get('content', '') for r in phase0_raw['tavily_results']['price_results']
        )
        current_price = extract_price_from_snippets(price_text) or args.basis
        print(f'[Phase-0] BTC 当前价格: ${current_price:,}', file=sys.stderr)

        drift_pct, drift_level = check_price_drift(current_price, args.basis)
        print(f'[Phase-0] 价格漂移: {drift_pct:.1f}% [{drift_level}] (basis=${args.basis:,})', file=sys.stderr)
        if drift_level == 'CRITICAL':
            print('[Phase-0] PRICE_DRIFT_CRITICAL — 应先触发 Screen1 重跑，本次降级继续', file=sys.stderr)

        phase0_data = {
            'date': date_str, 'session_id': session_id,
            'btc_price_current': current_price,
            'price_drift_pct': round(drift_pct, 2),
            'price_drift_level': drift_level,
            'funding_rate': phase0_raw['raw_funding_snippet'][:200],
            'etf_flows': phase0_raw['raw_etf_snippet'][:200],
            **{k: v for k, v in phase0_raw.items() if k != 'tavily_results'},
        }

    screen1_context = {
        'screen1_direction': args.direction,
        'screen1_score': args.score,
        'screen1_btc_price_basis': args.basis,
    }

    # Phase-M: memory_db prefetch（非阻塞，失败不影响主流程）
    mdb = _try_import_memory_db()
    historical_context = ''
    if mdb:
        try:
            historical_context = mdb.prefetch_context(current_price, args.direction)
            if historical_context:
                lines = historical_context.count('\n')
                print(f'[Phase-M] memory_db prefetch: {lines} 行历史背景注入 A1/A2', file=sys.stderr)
            else:
                print('[Phase-M] memory_db: 无相关历史记录（首次运行）', file=sys.stderr)
        except Exception as e:
            print(f'[Phase-M] prefetch 失败（降级跳过）: {e}', file=sys.stderr)

    # historical_context 注入 phase0_data，由 screen2_qwen.py 消费后剔除
    phase0_data['historical_context'] = historical_context

    # Phase-1
    print('[Phase-1] 调用 qwen-analyst (A1→A2→A3)...', file=sys.stderr)
    try:
        qwen_result = phase1_qwen(phase0_data, screen1_context)
    except Exception as e:
        print(f'[Phase-1] qwen-analyst 失败: {e}', file=sys.stderr)
        print('[Phase-1] 降级: 需要 Claude Code 内联完成 A1/A2/A3', file=sys.stderr)
        sys.exit(2)

    # Phase-V: V15 机械信号（影子计算）
    print('[Phase-V] 计算 V15 机械信号...', file=sys.stderr)
    v15_result = phase_v_signal(args.direction, current_price, POSITION_CAP_USDT)
    v15_sig = v15_result.get('v15_signal', {})
    print(f'[Phase-V] V15 signal={v15_sig.get("signal")} '
          f'position={v15_result.get("price_position")} '
          f'rsi={v15_result.get("rsi14")}', file=sys.stderr)

    # Phase-D: 裁决层（AI vs V15）
    decision = phase_decision(
        qwen_result['a2'], qwen_result['a3'], v15_result, args.direction, date_str
    )
    print(f'[Phase-D] 执行信号: {decision["execution"]} | {decision["reason"]}', file=sys.stderr)

    # Phase-4: A4 挂单计划
    print('[Phase-4] 生成 A4 挂单计划...', file=sys.stderr)
    a4_plan = phase4_order_plan(
        qwen_result['a3'], args.direction, current_price, date_str,
        position_cap_usdt=POSITION_CAP_USDT,
        decision=decision, v15_result=v15_result,
    )
    qwen_result['a4'] = a4_plan
    qwen_result['v15'] = v15_result
    qwen_result['decision'] = decision
    qwen_result['daily_presets']['a4_order_plan'] = a4_plan
    print(f'[Phase-4] source={a4_plan.get("source")} | {len(a4_plan["orders"])} 层挂单 '
          f'| 总敞口 {a4_plan["total_exposure_usdt"]} USDT '
          f'| TP={a4_plan["tp_target"]} SL={a4_plan["sl_trigger"]}', file=sys.stderr)

    # Phase-3: GitHub 写入
    if not GITHUB_TOKEN:
        print('[WARN] GH_TOKEN not set — skipping GitHub writes', file=sys.stderr)
        args.dry_run = True

    write_results = phase3_write_github(session_id, phase0_data, qwen_result, dry_run=args.dry_run)

    # Phase-M 写回：将 preset 索引到 memory_db
    if mdb and not args.dry_run:
        try:
            preset_data = qwen_result['daily_presets']
            mdb.index_preset(preset_data)
            print('[Phase-M] memory_db: preset 已索引', file=sys.stderr)
        except Exception as e:
            print(f'[Phase-M] index_preset 失败（不影响主流程）: {e}', file=sys.stderr)

    # 输出最终摘要 JSON
    output = {
        'session_id': session_id,
        'btc_price': current_price,
        'screen1_direction': args.direction,
        'recommended_action': qwen_result['daily_presets'].get('recommended_action'),
        'trend_confidence': qwen_result['a2'].get('trend_confidence'),
        'red_team_flag': qwen_result['a3'].get('red_team_analysis', {}).get('red_team_flag', False),
        'execution_source': decision.get('execution'),
        'v15_signal': decision.get('v15_signal'),
        'signals_agree': decision.get('signals_agree'),
        'a4_orders': len(a4_plan.get('orders', [])),
        'a4_exposure_usdt': a4_plan.get('total_exposure_usdt'),
        'phase2_skipped': True,
        'memory_context_injected': bool(historical_context),
        'github_files': write_results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
