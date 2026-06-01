"""
6-TRADING DeepSeek Analysis Tool
DeepSeek-V4 CoT 推理，与千问配合分工。

分工说明（当前路由）:
  A1 矛盾分析     → qwen3.7-max (主力，31s)；本文件 deepseek-v4-flash 为降级备用
  A2/A3          → qwen3.7-max (主力)；本文件 deepseek-v4-pro 为降级备用
  Gate C ACH     → deepseek-v4-pro   (35s, 深度 CoT 竞争性假设分析) [主力]
  Process D A8   → deepseek-v4-pro   (周级别，质量优先) [主力]

用法:
    python deepseek_analyst.py <task> '<json_data>'
    task: a1 | a2 | a3 | gate_c | process_d
"""
import urllib.request, json, ssl, sys, io, os, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
URL = 'https://api.deepseek.com/chat/completions'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

SYSTEM_BASE = (
    "你是 6-TRADING 量化交易分析师，专注 BTC 永续合约。"
    "分析简洁、结构化，直接输出 JSON，不要任何解释性文字包裹。"
    "JSON 字段全部英文 key，内容可中文。"
    "你有内置推理能力，请充分利用内部 CoT 进行严格逻辑推导，最终只输出结论 JSON。"
)


def deepseek_chat(messages, model='deepseek-v4-flash', temperature=0.3, max_tokens=1500):
    if not API_KEY:
        raise RuntimeError('DEEPSEEK_API_KEY not set')
    data = json.dumps({
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }).encode()
    req = urllib.request.Request(URL, data=data, headers={
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    })
    with urllib.request.urlopen(req, context=ctx, timeout=90) as r:
        result = json.loads(r.read())
    usage = result.get('usage', {})
    reasoning_tokens = usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)
    output_tokens = usage.get('completion_tokens', 0) - reasoning_tokens
    print(
        f'[deepseek] model={model} prompt={usage.get("prompt_tokens",0)} '
        f'reasoning={reasoning_tokens} output={output_tokens}',
        file=sys.stderr
    )
    return result['choices'][0]['message']['content']


def clean_json(text):
    """去除 ```json ``` 包裹"""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1]
        text = text.rsplit('```', 1)[0]
    return text.strip()


# ─── A1: 日线矛盾分析（deepseek-v4-flash） ────────────────────────────────────

def analyze_a1(ctx_data, historical_context: str = ''):
    history_section = f"""
## 历史记忆参考（memory_db 检索结果）
{historical_context}
""" if historical_context else ''

    prompt = f"""
基于以下 6-TRADING Phase-0 数据，执行 A1 日线矛盾分析。
{history_section}
## 输入数据
{json.dumps(ctx_data, ensure_ascii=False, indent=2)}

## 任务
识别当前 BTC 市场的主要矛盾（多空力量对比），结合 screen1_direction={ctx_data.get('screen1_direction')} 约束。
用你的内置推理能力严格审查多空证据，检测确认偏见（confirmation bias）。
如有历史参考，注意历史相似行情下多空力量的实际表现，但不要直接复制历史结论。

## 输出 JSON 格式
{{
  "primary_contradiction": "一句话描述主要矛盾",
  "bull_evidence": ["多方论据1", "多方论据2"],
  "bear_evidence": ["空方论据1", "空方论据2"],
  "contradiction_score": "空方:多方 比例，如 65:35",
  "bias_flags": ["CONFIRMATION_BIAS 等偏见标注，无则空数组"],
  "daily_constraints": {{
    "resistance": "阻力价格区间",
    "support": "支撑价格区间",
    "invalidation": "SHORT论点失效条件"
  }},
  "memory_used": {{"historical_refs": 0}},
  "reasoning_quality": "一句话说明 CoT 推理发现的关键洞察",
  "summary": "两句话结论"
}}
"""
    resp = deepseek_chat([
        {'role': 'system', 'content': SYSTEM_BASE},
        {'role': 'user', 'content': prompt}
    ], model='deepseek-v4-flash', max_tokens=1500)
    return json.loads(clean_json(resp))


# ─── A2: 第一性原理分析（deepseek-v4-pro，降级备用） ────────────────────────

def analyze_a2(ctx_data, a1_result, historical_context: str = ''):
    history_section = f"""
## 历史记忆参考（memory_db 检索结果）
{historical_context}
""" if historical_context else ''

    prompt = f"""
基于 Phase-0 数据和 A1 矛盾分析结论，执行 A2 第一性原理分析。
{history_section}
## Phase-0 数据
{json.dumps(ctx_data, ensure_ascii=False, indent=2)}

## A1 矛盾分析结论
{json.dumps(a1_result, ensure_ascii=False, indent=2)}

## 任务
用第一性原理推导：screen1_direction={ctx_data.get('screen1_direction')} 的宏观基础是否仍成立？
最小阻力路径是什么？列出可能推翻方向的门槛。
用你的内置推理能力严格审查每条推导步骤，不要跳过逻辑环节。
如有历史参考，注意历史相似行情的趋势置信度校准情况。

## 输出 JSON 格式
{{
  "foundation_intact": true,
  "reasoning_chain": ["推导步骤1", "推导步骤2", "推导步骤3"],
  "minimum_resistance_path": "最小阻力路径描述",
  "invalidation_threshold": "推翻 screen1_direction 需要满足的条件",
  "trend_confidence": 0.62,
  "screen1_alignment_pct": 85,
  "bias_flags": [],
  "memory_calibration_note": "历史相似行情对本次置信度的校准说明，无历史数据则空字符串",
  "summary": "两句话结论"
}}
"""
    resp = deepseek_chat([
        {'role': 'system', 'content': SYSTEM_BASE},
        {'role': 'user', 'content': prompt}
    ], model='deepseek-v4-pro', max_tokens=1500)
    return json.loads(clean_json(resp))


# ─── A3: 日线沙盘推演（deepseek-v4-pro，降级备用） ───────────────────────────

def analyze_a3(ctx_data, a1_result, a2_result):
    prompt = f"""
基于 Phase-0 数据、A1 矛盾分析、A2 第一性原理结论，执行 A3 三情景沙盘推演。

## Phase-0 数据
{json.dumps(ctx_data, ensure_ascii=False, indent=2)}

## A1 结论摘要
{a1_result.get('summary', '')}

## A2 结论摘要
{a2_result.get('summary', '')} trend_confidence={a2_result.get('trend_confidence')}

## 任务
推演三个情景 S1/S2/S3（基准/对立/极端），给出每个情景的概率、价格路径、马丁格参数。
用你的内置推理能力构造红队最强反向论据，不要为主方向辩护。

## 输出 JSON 格式
{{
  "S1": {{
    "scenario": "情景名称",
    "probability": 0.45,
    "trigger": "触发条件",
    "price_path": "价格路径描述",
    "entry_zone": [77500, 78000],
    "TP": 74200,
    "SL": 80600,
    "L0_position_pct": 30,
    "grid_spacing_pct": 1.5
  }},
  "S2": {{
    "scenario": "情景名称",
    "probability": 0.30,
    "trigger": "触发条件",
    "price_path": "价格路径描述",
    "action": "应对措施",
    "L0_position_pct": 20,
    "TP_pct": 5.0,
    "SL_pct": 3.0
  }},
  "S3": {{
    "scenario": "情景名称",
    "probability": 0.25,
    "trigger": "触发条件",
    "price_path": "价格路径描述",
    "TP_pct": 8.0,
    "SL_pct": 5.0,
    "grid_spacing_pct": 3.0,
    "L0_position_pct": 25
  }},
  "red_team_analysis": {{
    "top3_counterarguments": ["最强反向论据1", "最强反向论据2", "最强反向论据3"],
    "red_team_strength_pct": 32,
    "red_team_flag": false
  }},
  "phase7_contingency": {{
    "trigger": "黑天鹅触发条件",
    "action": "应急处置"
  }}
}}
"""
    resp = deepseek_chat([
        {'role': 'system', 'content': SYSTEM_BASE},
        {'role': 'user', 'content': prompt}
    ], model='deepseek-v4-pro', max_tokens=2500)
    return json.loads(clean_json(resp))


# ─── Gate C: ACH 竞争性假设分析（deepseek-v4-pro） ───────────────────────────

def analyze_gate_c(ctx_data, a7_score, signal_score_pct):
    prompt = f"""
执行 Gate C ACH（竞争性假设分析），判断当前是否应该入场。

## 当前状态
{json.dumps(ctx_data, ensure_ascii=False, indent=2)}

## 评分输入
- A7 实践门禁得分: {a7_score}/40
- 信号综合得分: {signal_score_pct}%
- screen1_direction: {ctx_data.get('screen1_direction')}
- 当前价格: {ctx_data.get('btc_price_current')}
- 入场区: {ctx_data.get('entry_zone', [77500, 78000])}

## 三项诊断（按 TRIGGER_PROMPTS 规范）
1. 资金费率方向是否与入场方向一致？
2. screen1_btc_price_basis 偏差是否 <5%？
3. A7 gate score 是否 >30/40？

## 竞争性假设分析
请用内置 CoT 推理构造两个对立假设并严格评估证据：
- Hypothesis A（支持入场）: 列举所有支持入场的证据
- Hypothesis B（反对入场）: 列举所有反对入场的证据
哪个假设与证据更一致？做出裁决。

## 输出 JSON 格式
{{
  "diagnostic_1_funding_aligned": true,
  "diagnostic_2_price_drift_ok": true,
  "diagnostic_3_a7_pass": false,
  "hypothesis_a_count": 2,
  "hypothesis_b_count": 3,
  "ach_result": "HYPOTHESIS_B_WINS",
  "composite_confidence": 57,
  "threshold": 60,
  "result": "SKIP",
  "skip_reason": "ENTRY_ZONE_NOT_REACHED",
  "ach_summary": "一句话 ACH 摘要",
  "reasoning_quality": "一句话说明 CoT 推理关键决策点"
}}
"""
    resp = deepseek_chat([
        {'role': 'system', 'content': SYSTEM_BASE},
        {'role': 'user', 'content': prompt}
    ], model='deepseek-v4-pro', max_tokens=3000)
    return json.loads(clean_json(resp))


# ─── Process D: A8 复盘分析（deepseek-v4-pro） ───────────────────────────────

def analyze_process_d(episodes_summary, weekly_data):
    prompt = f"""
执行 Process D A8 知行合一批评分析。

## 上周 Episodes 摘要
{json.dumps(episodes_summary, ensure_ascii=False, indent=2)}

## 周度数据
{json.dumps(weekly_data, ensure_ascii=False, indent=2)}

## 任务
1. 偏见审计：确认偏见/群体思维/过度自信
2. 知行一致性评分
3. 关键发现和改进建议

用你的内置推理能力进行严格自我批评，不要为过去的决策辩护。

## 输出 JSON 格式
{{
  "retrospective_score": 72,
  "bias_audit": {{
    "confirmation_bias": "发现/无",
    "groupthink": "发现/无",
    "overconfidence": "发现/无"
  }},
  "key_findings": ["发现1", "发现2"],
  "improvement_suggestions": ["建议1", "建议2"],
  "reasoning_quality": "一句话说明推理发现的最重要盲点",
  "summary": "两句话总结"
}}
"""
    resp = deepseek_chat([
        {'role': 'system', 'content': SYSTEM_BASE},
        {'role': 'user', 'content': prompt}
    ], model='deepseek-v4-pro', max_tokens=3000)
    return json.loads(clean_json(resp))


# ─── CLI 入口 ─────────────────────────────────────────────────────────────────

TASKS = {
    'a1': lambda d: analyze_a1(d['context'], d.get('historical_context', '')),
    'a2': lambda d: analyze_a2(d['context'], d['a1'], d.get('historical_context', '')),
    'a3': lambda d: analyze_a3(d['context'], d['a1'], d['a2']),
    'gate_c': lambda d: analyze_gate_c(d['context'], d['a7_score'], d['signal_score_pct']),
    'process_d': lambda d: analyze_process_d(d['episodes'], d['weekly']),
}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('task', choices=list(TASKS.keys()))
    parser.add_argument('data', help='JSON string with input data')
    args = parser.parse_args()

    try:
        input_data = json.loads(args.data)
        result = TASKS[args.task](input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        print(json.dumps({'error': f'JSON parse failed: {e}'}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
