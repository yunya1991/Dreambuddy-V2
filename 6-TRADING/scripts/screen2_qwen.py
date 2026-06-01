"""
6-TRADING Screen 2 日线预设 — 千问驱动版
Claude Code 调用此脚本完成 Phase-1 全部分析（A1+A2+A3），返回结构化 JSON。
Claude Code 只需负责：Phase-0 Tavily 搜索 + 调用本脚本 + 写入 GitHub。

用法:
    python screen2_qwen.py '<phase0_data_json>'
"""
import sys, io, json, subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

QWEN = 'C:/tmp/qwen_analyst.py'
DEEPSEEK = 'C:/tmp/deepseek_analyst.py'

# 路由策略（模型分工）:
#   A1 / A2 / A3  → qwen3.7-max（主），qwen 失败时降级到 deepseek-v4-flash
#   Gate C        → deepseek-v4-pro（主），失败时降级到 qwen3.7-max
#   Process D     → deepseek-v4-pro（主），失败时降级到 qwen3.7-max
DEEPSEEK_PRIMARY_TASKS = {'gate_c', 'process_d'}
QWEN_WITH_DS_FALLBACK  = {'a1', 'a2', 'a3'}  # qwen 主力，deepseek-v4-flash 备用


def call_analyst(task, data_dict):
    arg = json.dumps(data_dict, ensure_ascii=True)

    if task in DEEPSEEK_PRIMARY_TASKS:
        primary, fallback = DEEPSEEK, QWEN
        fallback_label = 'qwen3.7-max'
    else:
        primary, fallback = QWEN, None
        fallback_label = None
        if task in QWEN_WITH_DS_FALLBACK:
            fallback = DEEPSEEK
            fallback_label = 'deepseek-v4-flash'

    r = subprocess.run(
        ['python', primary, task, arg],
        capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    if r.returncode != 0:
        if fallback:
            print(f'[screen2] {task} primary failed, falling back to {fallback_label}: '
                  f'{r.stderr[:150]}', file=sys.stderr)
            r = subprocess.run(
                ['python', fallback, task, arg],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            if r.returncode != 0:
                raise RuntimeError(f'{task} fallback({fallback_label}) failed: {r.stderr[:300]}')
        else:
            raise RuntimeError(f'{task} failed: {r.stderr[:300]}')
    return json.loads(r.stdout)


def call_qwen(task, data_dict):
    """Legacy alias — now routes via call_analyst."""
    return call_analyst(task, data_dict)


def run(phase0: dict) -> dict:
    ctx = phase0
    hist = ctx.pop('historical_context', '')  # 从 phase0 提取，不传给 A3

    print('[1/3] A1 矛盾分析 → qwen3.7-max ...', file=sys.stderr)
    a1 = call_analyst('a1', {'context': ctx, 'historical_context': hist})

    print('[2/3] A2 第一性原理 → qwen3.7-max ...', file=sys.stderr)
    a2 = call_analyst('a2', {'context': ctx, 'a1': a1, 'historical_context': hist})

    print('[3/3] A3 三情景推演 → qwen3.7-max ...', file=sys.stderr)
    a3 = call_analyst('a3', {'context': ctx, 'a1': a1, 'a2': a2})

    # 组装 daily-presets 结构
    presets = {
        'session_id': ctx.get('session_id', 'UNKNOWN'),
        'date': ctx.get('date', ''),
        'screen1_direction': ctx.get('screen1_direction'),
        'screen1_score': ctx.get('screen1_score'),
        'driven_by': 'qwen3.7-max+deepseek',
        'phase0_data': ctx,
        'phase1_analysis': {
            'a1_summary': a1.get('summary'),
            'a1_contradiction_score': a1.get('contradiction_score'),
            'a1_bias_flags': a1.get('bias_flags', []),
            'a2_trend_confidence': a2.get('trend_confidence'),
            'a2_screen1_alignment_pct': a2.get('screen1_alignment_pct'),
            'a2_summary': a2.get('summary'),
            'a3_scenarios': {
                'S1': a3.get('S1'),
                'S2': a3.get('S2'),
                'S3': a3.get('S3'),
            },
            'red_team_flag': a3.get('red_team_analysis', {}).get('red_team_flag', False),
            'phase7_contingency': a3.get('phase7_contingency'),
        },
        'martingale_presets': {
            'primary_direction': ctx.get('screen1_direction'),
            'S1': a3.get('S1'),
            'S2': a3.get('S2'),
            'S3': a3.get('S3'),
        },
        'phase2_skipped': True,
        'phase2_skip_reason': 'no_data_analysis_report_available',
        'recommended_action': 'WAIT_FOR_ENTRY_SIGNAL',
    }

    return {
        'a1': a1,
        'a2': a2,
        'a3': a3,
        'daily_presets': presets,
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python screen2_qwen.py \'<phase0_json>\'')
        sys.exit(1)

    phase0_data = json.loads(sys.argv[1])
    result = run(phase0_data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
