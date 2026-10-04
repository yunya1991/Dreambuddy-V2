#!/usr/bin/env python3
"""千问对比基准 — 对比 DreamBuddy 和千问输出质量

用法:
    python qwen_benchmark.py [--host localhost] [--port 3847] [--cases all|10|20]

前置:
    1. DreamBuddy API server 运行在 localhost:3847
    2. 环境变量 QWEN_API_KEY 已配置
"""

from __future__ import annotations

import json
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Optional

# 路径设置
_SCRIPT_DIR = Path(__file__).resolve().parent  # tests/eval/
_BRIDGE_ROOT = _SCRIPT_DIR.parent.parent       # dream-harness-bridge/
_ARCH_DIR = _BRIDGE_ROOT.parent                # 1-ARCHITECTURE/（含 dreamos/）
for p in [str(_BRIDGE_ROOT), str(_ARCH_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

from dreamos.shared.llm_client import QwenLLMClient, make_messages  # noqa: E402


GOLDEN_SET_PATH = _SCRIPT_DIR / "golden_set.json"
REPORT_DIR = _SCRIPT_DIR / "reports"

# 5维评分系统提示词（对齐 dream-qwen-eval-collab SKILL）
SCORE_SYSTEM_PROMPT = """你是交易系统输出质量评估专家。请对以下两个系统的输出按5维评分（0-10分，保留1位小数）：

1. completeness: 完整性 — 是否覆盖意图识别+系统能力调用+内容输出
2. actionability: 可落地性 — 是否给出可执行的代码/操作路径
3. engineering: 工程适配性 — 是否适配模块化约束（HC-1a/FAIL-OPEN/零回归）
4. risk: 风险识别 — 是否识别潜在风险（FAIL-OPEN/零回归）
5. innovation: 创新性 — 是否引入模块化模式或新视角

输出JSON格式（不要markdown代码块，直接输出JSON）：
{"completeness": {"db": N, "qw": N}, "actionability": {"db": N, "qw": N}, "engineering": {"db": N, "qw": N}, "risk": {"db": N, "qw": N}, "innovation": {"db": N, "qw": N}}"""


class QwenBenchmark:
    """千问对比基准 — 对比 DreamBuddy 和千问输出质量"""

    def __init__(self, host: str = "localhost", port: int = 3847):
        self.db_url = f"http://{host}:{port}/api/intent/execute"
        self.qwen = QwenLLMClient()  # 千问 API（被对比方）
        self.judge = QwenLLMClient()  # 裁判（同一个模型，可换 DeepSeek 避免自评偏差）
        self.golden_set = self._load_golden_set()

        if not self.qwen.api_key:
            print("警告: QWEN_API_KEY 未配置，千问 API 调用将降级为 NoOp")

    def _load_golden_set(self) -> list:
        with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def run_dreambuddy(self, case: dict) -> dict:
        """调本地 /api/intent/execute 获取 DreamBuddy 输出"""
        try:
            resp = requests.post(
                self.db_url,
                json={"text": case["input"]},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except requests.exceptions.ConnectionError:
            return {"error": f"无法连接 {self.db_url}，请确认 API server 运行中"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def run_qwen(self, case: dict) -> dict:
        """调千问 API 获取千问输出"""
        try:
            msgs = make_messages(
                system="你是交易系统助手，请回答用户的问题。",
                user=case["input"],
            )
            resp = self.qwen.chat(msgs, temperature=0.3)
            return {
                "content": resp.content,
                "tokens_output": getattr(resp, "tokens_output", 0),
                "latency_ms": getattr(resp, "latency_ms", 0),
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def score_5dim(self, case: dict, db_out: dict, qw_out: dict) -> dict:
        """5维 LLM 评分"""
        try:
            prompt = (
                f"用户问题：{case['input']}\n"
                f"期望意图：{case['expected_intent']}\n\n"
                f"DreamBuddy输出：\n"
                f"{json.dumps(db_out, ensure_ascii=False, default=str)[:2000]}\n\n"
                f"千问输出：\n"
                f"{json.dumps(qw_out, ensure_ascii=False, default=str)[:2000]}\n"
            )
            msgs = make_messages(system=SCORE_SYSTEM_PROMPT, user=prompt)
            resp = self.judge.chat(msgs, temperature=0.1)
            content = resp.content.strip()
            # 清理 markdown 代码块
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            return json.loads(content)
        except json.JSONDecodeError as e:
            return {"error": f"JSON解析失败: {e}", "raw": resp.content[:500]}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def run(self, cases: str = "all") -> dict:
        """运行对比

        Args:
            cases: "all" 或数字（如 "10"）
        """
        golden = self.golden_set if cases == "all" else self.golden_set[: int(cases)]

        results = []
        correct_db = 0

        for i, case in enumerate(golden):
            print(f"[{i+1}/{len(golden)}] {case['id']}: {case['input']}")

            # DreamBuddy
            db_out = self.run_dreambuddy(case)
            db_intent = db_out.get("intent", {}).get("canon_intent", "unknown")
            is_correct = db_intent == case["expected_intent"]
            if is_correct:
                correct_db += 1

            # 千问
            qw_out = self.run_qwen(case)

            # 5维评分
            scores = self.score_5dim(case, db_out, qw_out)

            results.append({
                "id": case["id"],
                "input": case["input"],
                "expected_intent": case["expected_intent"],
                "db_intent": db_intent,
                "db_correct": is_correct,
                "db_mode": db_out.get("mode", "unknown"),
                "db_output_summary": self._summarize(db_out),
                "qw_output_summary": self._summarize(qw_out),
                "scores": scores,
            })

            # 简要输出
            status = "✓" if is_correct else "✗"
            print(f"  DB: {db_intent} {status} | mode={db_out.get('mode', '?')}")
            if "error" in scores:
                print(f"  评分失败: {scores['error']}")
            else:
                dims = ["completeness", "actionability", "engineering", "risk", "innovation"]
                for d in dims:
                    if d in scores:
                        s = scores[d]
                        print(f"  {d}: DB={s.get('db', '?')} | QW={s.get('qw', '?')}")

            time.sleep(1)  # 避免 API 限流

        # 汇总
        summary = {
            "total": len(golden),
            "db_accuracy": correct_db / len(golden) if golden else 0,
            "db_correct": correct_db,
            "results": results,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 保存报告
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"qwen_benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n报告已保存: {report_path}")
        print(f"DreamBuddy 意图准确率: {correct_db}/{len(golden)} ({summary['db_accuracy']:.0%})")

        return summary

    def _summarize(self, output: dict) -> str:
        """提取输出摘要"""
        if "error" in output:
            return f"[ERROR] {output['error'][:100]}"
        if "content" in output:
            return output["content"][:200]
        if "result" in output:
            return str(output["result"])[:200]
        return json.dumps(output, ensure_ascii=False, default=str)[:200]


def main():
    parser = argparse.ArgumentParser(description="千问对比基准")
    parser.add_argument("--host", default="localhost", help="DreamBuddy API host")
    parser.add_argument("--port", type=int, default=3847, help="DreamBuddy API port")
    parser.add_argument("--cases", default="all", help="all|10|20 用例数量")
    args = parser.parse_args()

    benchmark = QwenBenchmark(host=args.host, port=args.port)
    summary = benchmark.run(cases=args.cases)

    # 5维汇总
    print("\n=== 5维评分汇总 ===")
    dims = ["completeness", "actionability", "engineering", "risk", "innovation"]
    for dim in dims:
        db_scores = []
        qw_scores = []
        for r in summary["results"]:
            s = r.get("scores", {})
            if dim in s and isinstance(s[dim], dict):
                db_scores.append(s[dim].get("db", 0))
                qw_scores.append(s[dim].get("qw", 0))
        if db_scores:
            avg_db = sum(db_scores) / len(db_scores)
            avg_qw = sum(qw_scores) / len(qw_scores)
            winner = "DB" if avg_db > avg_qw else "QW" if avg_qw > avg_db else "平"
            print(f"  {dim:15s}: DB={avg_db:.1f} | QW={avg_qw:.1f} | {winner}")


if __name__ == "__main__":
    main()
