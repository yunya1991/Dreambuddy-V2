"""引擎相似度自动化准入检查（SPEC-自进化系统逆向解析改进.md 维度C · P2-2）。

背景：engines/ 引擎数量爆炸的动机是"每个新需求开一个引擎文件"，缺少"合并
同类项"的周期。本脚本在 CI 中自动检测"新引擎与现有引擎的概念重叠"：
两引擎的领域 import 集 + 调用集加权 Jaccard 相似度 > 阈值（默认 0.7）时
输出告警"建议并入现有引擎 X"（非阻塞，不使 CI 失败）。

v0.3 修订（深度调研建议7）：Jaccard 相似度存在 false positive——两引擎
import 相同基础模块（numpy/logging/dataclasses）会虚高相似度。因此：
1. 排除标准库 + 基础第三方库，只保留领域模块 import
2. 加权 Jaccard：领域模块 import 权重 3x，调用权重 1x

用法:
    python scripts/engine_similarity_check.py \
        --target-dir '23-四层闭环自进化交易架构/dreambuddy_evolution/engines' \
        --threshold 0.7 [--json report.json]

退出码恒为 0（告警非阻塞，写入 CI 检查报告即可）。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime
from pathlib import Path

# 领域模块 import 权重（SPEC v0.3: 加权 Jaccard 降低基础库同质化干扰）
DOMAIN_IMPORT_WEIGHT = 3.0
CALL_WEIGHT = 1.0

# 基础第三方库排除集（v0.3 修订明确列出 numpy/pandas；补充仓库实际使用的
# 常见科学计算/网络库，均为与领域无关的同质化依赖）
BASE_THIRD_PARTY = {"numpy", "pandas", "scipy", "sklearn", "torch", "requests"}

# 高频内建调用排除（与基础库排除同源：避免并集被通用调用稀释）
COMMON_CALLS = frozenset({
    "print", "len", "range", "isinstance", "str", "int", "float", "bool",
    "list", "dict", "set", "tuple", "super", "getattr", "setattr", "hasattr",
    "min", "max", "abs", "sum", "sorted", "enumerate", "zip", "any", "all",
    "open", "round", "type", "isinstance", "Exception", "ValueError",
    "TypeError", "KeyError", "RuntimeError",
})

DEFAULT_TARGET_DIR = Path(__file__).resolve().parents[2] / (
    "23-四层闭环自进化交易架构/dreambuddy_evolution/engines"
)

try:
    _STDLIB_TOP_LEVEL = frozenset(sys.stdlib_module_names)  # Python 3.10+
except AttributeError:  # pragma: no cover
    _STDLIB_TOP_LEVEL = frozenset({
        "abc", "argparse", "ast", "asyncio", "collections", "contextlib",
        "copy", "csv", "dataclasses", "datetime", "decimal", "enum", "functools",
        "glob", "hashlib", "heapq", "io", "itertools", "json", "logging", "math",
        "os", "pathlib", "pickle", "queue", "random", "re", "shutil", "signal",
        "statistics", "string", "subprocess", "sys", "threading", "time",
        "traceback", "typing", "unittest", "urllib", "uuid", "warnings", "weakref",
    })


def _domain_module(module: str) -> str | None:
    """import 模块路径归一化：领域模块返回标识，基础库返回 None。

    - dreambuddy_evolution.core.x → core.x（去包前缀）
    - logging / numpy / dataclasses → None（标准库+基础第三方库排除）
    - event_driven.x → 原样保留（未知包按领域依赖处理）
    """
    top = module.split(".")[0]
    if top == "dreambuddy_evolution":
        rest = module[len("dreambuddy_evolution."):].strip(".")
        return rest or module
    if top in _STDLIB_TOP_LEVEL or top in BASE_THIRD_PARTY:
        return None
    return module


def _call_name(func: ast.expr) -> str | None:
    """ast.Call.func → 点路径；剥离链首 self. 前缀。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        parts = (base.split(".") if base else []) + [func.attr]
        if parts and parts[0] == "self":
            parts = parts[1:]
        return ".".join(parts) if parts else None
    return None


class EngineSimilarityChecker:
    """提取引擎特征（领域 import + 调用集）并计算加权 Jaccard 相似度。"""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    # -- 特征提取 -----------------------------------------------------------

    def extract_features(self, source: str) -> dict[str, set[str]]:
        """解析源码 → {"imports": 领域模块集, "calls": 调用名集}。"""
        imports: set[str] = set()
        calls: set[str] = set()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {"imports": imports, "calls": calls}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    m = _domain_module(alias.name)
                    if m:
                        imports.add(m)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:  # 相对导入 → 同包领域模块
                    if node.module:
                        imports.add(node.module)
                    continue
                if node.module:
                    m = _domain_module(node.module)
                    if m:
                        imports.add(m)
            elif isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name and name not in COMMON_CALLS:
                    calls.add(name)
        return {"imports": imports, "calls": calls}

    # -- 加权 Jaccard -------------------------------------------------------

    @staticmethod
    def _pool(features: dict[str, set[str]]) -> dict[str, float]:
        """特征 → {元素: 权重}（领域 import 3x，调用 1x）。"""
        pool: dict[str, float] = {}
        for imp in features["imports"]:
            pool[f"import:{imp}"] = DOMAIN_IMPORT_WEIGHT
        for call in features["calls"]:
            pool[f"call:{call}"] = CALL_WEIGHT
        return pool

    def weighted_jaccard(self, fa: dict[str, set[str]], fb: dict[str, set[str]]) -> float:
        """加权 Jaccard = Σw(A∩B) / Σw(A∪B)，元素权重由其类别固定。"""
        pa, pb = self._pool(fa), self._pool(fb)
        inter_w = sum(min(pa[e], pb.get(e, 0.0)) for e in pa if e in pb)
        union_w = sum(pa.values()) + sum(pb.values()) - inter_w
        return inter_w / union_w if union_w > 0 else 0.0

    # -- 目录扫描 -----------------------------------------------------------

    def scan(self, target_dir: str | Path) -> dict:
        """扫描目录（递归，排除 __init__.py）→ 两两相似度报告。"""
        target = Path(target_dir)
        engines: dict[str, dict] = {}
        for path in sorted(target.rglob("*.py")):
            if path.name == "__init__.py" or "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(target).as_posix()
            engines[rel] = {
                "features": self.extract_features(source),
                "lines": source.count("\n") + 1,
            }

        names = sorted(engines)
        pairs: list[dict] = []
        warnings: list[dict] = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                sim = self.weighted_jaccard(engines[a]["features"], engines[b]["features"])
                exceeds = sim > self.threshold
                pair = {"a": a, "b": b, "similarity": round(sim, 4), "exceeds_threshold": exceeds}
                if exceeds:
                    target_engine = self._merge_target(engines[a], engines[b], a, b)
                    pair["suggestion"] = f"建议并入现有引擎 {target_engine}"
                    warnings.append(pair)
                pairs.append(pair)

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "target_dir": str(target),
            "threshold": self.threshold,
            "engine_count": len(engines),
            "pairs": pairs,
            "warnings": warnings,
        }

    @staticmethod
    def _merge_target(ea: dict, eb: dict, na: str, nb: str) -> str:
        """合并建议方向：行数较大者视为现有主引擎（小并入大）。"""
        return na if ea["lines"] >= eb["lines"] else nb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="引擎相似度自动化准入检查（非阻塞告警）")
    parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR), help="引擎目录（默认 engines/）")
    parser.add_argument("--threshold", type=float, default=0.7, help="相似度告警阈值（默认 0.7）")
    parser.add_argument("--json", default=None, help="JSON 报告输出路径（可选）")
    args = parser.parse_args(argv)

    checker = EngineSimilarityChecker(threshold=args.threshold)
    report = checker.scan(args.target_dir)

    print(f"[engine-similarity] 扫描 {report['target_dir']}")
    print(f"[engine-similarity] 引擎数={report['engine_count']} 阈值={args.threshold}")
    for w in report["warnings"]:
        print(
            f"::warning::[engine-similarity] {w['a']} ↔ {w['b']} "
            f"相似度 {w['similarity']:.2f} > {args.threshold}，{w['suggestion']}"
        )
    if not report["warnings"]:
        print("[engine-similarity] 无相似引擎对，检查通过")
    else:
        print(f"[engine-similarity] 共 {len(report['warnings'])} 对相似引擎（非阻塞告警）")
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[engine-similarity] 报告已写入 {args.json}")
    return 0  # 非阻塞：告警不使 CI 失败


if __name__ == "__main__":
    sys.exit(main())
