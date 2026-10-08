#!/usr/bin/env python3
"""
DSH IPC Adapter — 单次请求模式调用 dream-harness-bridge Python handler。

用法:
  python3 dsh_adapter.py technical '{"node_output": {...}}'
  python3 dsh_adapter.py c_drive '{"node_id":"C1","confidence":0.8,"direction":"LONG","signals":[],"intent_type":"deep_analysis"}'
  python3 dsh_adapter.py synthesizer '{"aggregated": {...}}'

stdout: 单行 JSON 响应（handler 原始返回值透传）
stderr: import 噪音和错误日志

设计:
  - 复刻 cognitive_adapter.py 的 stdout 重定向 + FAIL-OPEN 模式 (VM-1789618914215)
  - 路由到 python-server 的已有 handle_ 函数（不重复实现业务逻辑，避免重复造轮子）
  - handler 执行失败返回 {ok: false, error, traceback}
  - HC-1a: 不修改 dream-harness-bridge/ 代码，只通过 import 调用
"""
import sys
import os
import json
import traceback


def _resolve_python_server_dir():
    """解析 dream-harness-bridge/packages/python-server 绝对路径，支持多种 cwd。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 路径 1: 3.1-FRONTEND/scripts/ → ../../1-ARCHITECTURE/dream-harness-bridge/packages/python-server
    candidate1 = os.path.normpath(os.path.join(
        script_dir, '..', '..', '1-ARCHITECTURE',
        'dream-harness-bridge', 'packages', 'python-server'
    ))
    if os.path.exists(candidate1):
        return candidate1
    # 路径 2: 仓库根绝对路径（fallback）
    candidate2 = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server'
    if os.path.exists(candidate2):
        return candidate2
    return candidate1  # 返回不存在的路径，让 import 报错


# handler 路由表: handler_name → (module_name, function_name)
# 复用 python-server 已有 handle_ 函数，不重新实现业务逻辑
HANDLER_ROUTES = {
    # 8 个 SubAgent (subagent_registry.SUBAGENT_REGISTRY_CONFIG)
    'technical':   ('technical_agent',   'handle_technical_agent'),
    'sentiment':   ('sentiment_agent',   'handle_sentiment_agent'),
    'macro':       ('macro_agent',        'handle_macro_agent'),
    'flow':        ('flow_agent',         'handle_flow_agent'),
    'valuation':    ('valuation_agent',    'handle_valuation_agent'),
    'onchain':     ('onchain_agent',      'handle_onchain_agent'),
    'risk':        ('risk_agent',         'handle_risk_agent'),
    'portfolio':   ('portfolio_agent',    'handle_portfolio_agent'),
    # C-Drive 四步循环 (c_drive_agent.CDriveAgent)
    'c_drive':     ('c_drive_agent',      'handle_c_drive_agent'),
    # LLM 综合器 (synthesizer_agent.SynthesizerAgent)
    'synthesizer': ('synthesizer_agent',  'handle_synthesizer_agent'),
    # orchestrator_v2（SPEC §5.2 阶段4: dream-tactical-executor SKILL, node_id=A_ORCH）
    # 内联 handler: 直接 import OrchestratorV2 from dreamos（不经过 python-server，HC-1a 约束）
    'orchestrator': (None, '_handle_orchestrator_v2'),  # module_name=None → 内联 handler
}


def _safe_print(payload):
    """唯一向 stdout 输出的入口，确保单行 JSON。"""
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def _resolve_dreamos_root():
    """解析 dreambuddy-v2 仓库根路径（dreamos 模块的父目录）。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 3.1-FRONTEND/scripts/ → ../.. = 仓库根
    root = os.path.normpath(os.path.join(script_dir, '..', '..'))
    if os.path.exists(os.path.join(root, '1-ARCHITECTURE', 'dreamos')):
        return root
    # fallback: 绝对路径
    abs_root = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2'
    if os.path.exists(os.path.join(abs_root, '1-ARCHITECTURE', 'dreamos')):
        return abs_root
    return root


def _handle_orchestrator_v2(args):
    """内联 handler: 调用 OrchestratorV2.run_cycle()（SPEC §5.2 阶段4）

    参数格式（node_output 包装，与其他 SubAgent 一致）:
      {
        "node_output": {
          "symbol": "BTC",
          "market_data": { ... },  # 可选，默认从 symbol 构造
          "cognitive_context": { ... },  # 认知上下文（可选）
        }
      }

    返回:
      {
        "ok": true,
        "output": {
          "cycle_id": "cycle-0001",
          "status": "COMPLETED",
          "signal": { "direction": "LONG", "confidence": 0.8, ... },
          "execution": { "position": { ... } },
          "review": { ... },
          "bayesian_triggered": false,
          "errors": [],
          "confidence": 0.7,  # NodeResult.confidence
        }
      }
    """
    node_output = args.get('node_output', args) if isinstance(args, dict) else {}
    symbol = node_output.get('symbol', 'BTC')
    market_data = node_output.get('market_data') or {'symbol': symbol}

    # 确保 dreamos 在 sys.path 中
    root = _resolve_dreamos_root()
    dreamos_parent = os.path.join(root, '1-ARCHITECTURE')
    if dreamos_parent not in sys.path:
        sys.path.insert(0, dreamos_parent)

    try:
        from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2
    except Exception as e:
        return {
            'ok': False,
            'error': f'orchestrator_import_failed: {type(e).__name__}: {e}',
            'traceback': traceback.format_exc(),
        }

    try:
        orch = OrchestratorV2(use_hermes=False)
        cycle_result = orch.run_cycle(market_data)

        # 提取信号方向和置信度（与其他 SubAgent 输出格式一致）
        signal = cycle_result.get('signal', {})
        status = cycle_result.get('status', 'FAILED')
        confidence = 0.7 if status == 'COMPLETED' else 0.4

        return {
            'ok': True,
            'output': {
                'cycle_id': cycle_result.get('cycle_id', ''),
                'status': status,
                'selection': cycle_result.get('selection', {}),
                'signal': signal,
                'execution': cycle_result.get('execution', {}),
                'review': cycle_result.get('review', {}),
                'bayesian_triggered': cycle_result.get('bayesian_triggered', False),
                'errors': cycle_result.get('errors', []),
                # 统一输出字段（供 C-Drive/Summary 消费）
                'direction': signal.get('direction', 'HOLD'),
                'confidence': signal.get('confidence', confidence),
                'signals': signal.get('hexagram', []),
                'source': 'orchestrator-v2',
            },
        }
    except Exception as e:
        return {
            'ok': False,
            'error': f'orchestrator_error: {type(e).__name__}: {e}',
            'traceback': traceback.format_exc(),
        }


def main():
    if len(sys.argv) < 2:
        _safe_print({"ok": False, "error": "missing handler_name argument"})
        return

    handler_name = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else '{}'
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
        return

    if handler_name not in HANDLER_ROUTES:
        _safe_print({
            "ok": False,
            "error": f"unknown handler: {handler_name}. available: {sorted(HANDLER_ROUTES.keys())}",
        })
        return

    module_name, fn_name = HANDLER_ROUTES[handler_name]

    # === 关键: import 和 handler 执行期间把 stdout 重定向到 stderr ===
    # 避免任何 import 噪音或 handler 内部 print 污染真 stdout
    sys.stdout = sys.stderr

    # 内联 handler（module_name=None）: 直接调用本文件内定义的 handler 函数
    if module_name is None:
        try:
            # fn_name 是本文件内的函数名
            handler_fn = globals().get(fn_name)
            if handler_fn is None or not callable(handler_fn):
                _safe_print({
                    "ok": False,
                    "error": f"inline_handler_not_found: {fn_name}",
                })
                return
            result = handler_fn(args)
            _safe_print(result)
        except Exception as e:
            _safe_print({
                "ok": False,
                "error": f"inline_handler_error: {type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            })
        return

    try:
        server_dir = _resolve_python_server_dir()
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        mod = __import__(module_name)
        handler_fn = getattr(mod, fn_name)
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"import_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })
        return

    try:
        # handler (handle_technical_agent 等) 已返回 {ok: true, output: ...} 格式
        # 直接透传，不再包装
        result = handler_fn(args)
        _safe_print(result)
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"handler_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


if __name__ == "__main__":
    main()
