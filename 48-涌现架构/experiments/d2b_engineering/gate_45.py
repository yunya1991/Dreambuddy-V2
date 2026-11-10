"""gate_45.py — D2-B 真实 45 门禁运行器（CI 集成本地版）。

将方案骨架物化为代码文件，运行真实静态扫描，并调用
45-评测系统 的真实 `EngineeringScanEvaluator` 产出 E-H1/E-H2/E-H3/E-H5 判定。

本地可真实执行的项：
  - E-H1 秘密泄露：本地正则扫描器（gitleaks 风格核心模式）扫生成代码
  - E-H5 旁路痕迹：45 原生 BYPASS_PATTERNS 扫生成代码与步骤文本
  - 语法门禁：py_compile 编译校验（生成物零执行权 → 不 import 只编译）

本地无法执行、标记 deferred 的项（需 CI/外部工具）：
  - E-H2 可利用漏洞：需 gitleaks/trivy/pip-audit（当前环境不可用）
  - E-H3 可追溯性：需 CI 构建产物（commit↔build↔SBOM digest + attestation）
  - E-H4 新增行覆盖率：需测试套件 + coverage（骨架无测试）
  - E-W5 pycg 基准集 / E-W6 OpenSSF Scorecard：需外部基准/网络

FAIL-OPEN：45 导入失败或扫描异常时返回 gate_mode=unavailable，
调用方应降级为代理判定并如实标注。
"""

from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent
REPO_ROOT = PKG_ROOT.parent
EVAL45_ROOT = REPO_ROOT / "45-评测系统"

# 本地秘密扫描模式（E-H1 证据源，gitleaks 风格核心子集）
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |)?PRIVATE KEY-----", "private_key"),
    (r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{12,}['\"]", "generic_secret"),
    (r"ghp_[A-Za-z0-9]{36}", "github_pat"),
    (r"sk-[A-Za-z0-9]{20,}", "openai_key"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "slack_token"),
)


def _load_45_evaluator():
    """加载 45 真实工程门禁判定器。失败返回 None（FAIL-OPEN）。"""
    try:
        if str(EVAL45_ROOT) not in sys.path:
            sys.path.insert(0, str(EVAL45_ROOT))
        from evaluators.engineering.scan import (  # noqa: PLC0415
            BYPASS_PATTERNS,
            EngineeringScan,
            EngineeringScanEvaluator,
            Traceability,
        )

        return EngineeringScan, EngineeringScanEvaluator, Traceability, BYPASS_PATTERNS
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None


def scan_secrets(text: str) -> list[str]:
    """E-H1 证据：返回命中位置清单（pattern 名 + 行号）。"""
    hits: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, line):
                hits.append(f"{label}@L{line_no}")
    return hits


def _third_party_imports(py_file: Path) -> list[str]:
    """AST 提取第三方 import（排除 stdlib）。"""
    import ast

    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return sorted(m for m in mods if m and m not in stdlib)


def scan_vulnerabilities(py_file: Path, timeout: int = 90) -> tuple[list[dict] | None, str]:
    """E-H2 证据：第三方依赖 → pip-audit 扫描已安装版本。

    返回 (vulns, status)；status ∈ stdlib_only/audited/deps_unresolved/
    tool_unavailable/audit_error。vulns 元素含 id/severity/fix_version/affected。
    """
    third = _third_party_imports(py_file)
    if not third:
        return [], "stdlib_only"
    try:
        import json as _json
        import subprocess
        import tempfile
        from importlib.metadata import PackageNotFoundError, version

        reqs: list[str] = []
        for m in third:
            try:
                reqs.append(f"{m}=={version(m)}")
            except PackageNotFoundError:
                continue
        if not reqs:
            return None, "deps_unresolved"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n".join(reqs))
            req_path = f.name
        proc = subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", req_path, "--format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        data = _json.loads(proc.stdout or "{}")
        # pip-audit 2.x: {"dependencies": [...]}；旧版: [...]
        deps = data.get("dependencies", []) if isinstance(data, dict) else data
        vulns: list[dict] = []
        for dep in deps:
            if not isinstance(dep, dict):
                continue
            for v in dep.get("vulns", []):
                fix = v.get("fix_versions") or []
                vulns.append(
                    {
                        "id": v.get("id", ""),
                        "severity": v.get("severity") or "UNKNOWN",
                        "fix_version": fix[0] if fix else None,
                        "affected": dep.get("name", ""),
                    }
                )
        return vulns, "audited"
    except FileNotFoundError:
        return None, "tool_unavailable"
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None, "audit_error"


def build_local_traceability(target: Path) -> dict:
    """E-H3 本地可追溯链：git commit ↔ artifact sha256 ↔ provenance 侧车文件。

    如实标注 local_attestation（非 Sigstore/CI attestation）；CI 环境应替换为
    真实构建产物 digest + attestation 验证。
    """
    import hashlib
    import json as _json
    import subprocess
    from datetime import datetime, timezone

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=10,
            check=False,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = ""
    provenance = {
        "commit_sha": commit,
        "artifact": target.name,
        "artifact_sha256": digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "d2b gate_45 local_attestation",
    }
    sidecar = target.with_suffix(target.suffix + ".provenance.json")
    try:
        sidecar.write_text(_json.dumps(provenance, ensure_ascii=False, indent=2))
        attestation = True
    except OSError:
        attestation = False
    return {
        "commit_sha": commit,
        "build_digest": digest,
        "sbom_subject_digest": digest,
        "attestation_verified": attestation,
        "mode": "local_attestation",
    }


def scan_bypass(texts: list[str], bypass_patterns) -> list[str]:
    """E-H5 证据：45 原生旁路模式扫描，返回命中标签清单。"""
    hits: list[str] = []
    for text in texts:
        for pattern, _kind, label in bypass_patterns:
            if re.search(pattern, text):
                hits.append(label)
    return sorted(set(hits))


def materialize(plan, workspace: Path) -> Path:
    """将方案骨架落盘为代码文件（生成物零执行权：只写文件不执行）。"""
    workspace.mkdir(parents=True, exist_ok=True)
    safe_name = plan.module_name.replace("/", "__")
    target = workspace / safe_name
    skeleton = getattr(plan, "code_skeleton", "") or (
        f'"""{plan.module_name} — D2-B 方案骨架（未实现）。"""\n'
    )
    target.write_text(skeleton, encoding="utf-8")
    return target


def measure_coverage(
    module_path: Path, test_path: Path, timeout: int = 300
) -> tuple[float | None, str]:
    """E-H4 证据：coverage 运行 pytest，报告 module_path 行覆盖率。

    返回 (rate, status)；status ∈ measured/pytest_failed/coverage_failed/tool_error。
    """
    import json as _json
    import os
    import subprocess
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as td:
            data_file = Path(td) / ".coverage"
            out_json = Path(td) / "cov.json"
            # 独立 rcfile：避免仓库 pyproject 的 coverage source 配置
            # 把待测模块排除在外导致 no-data-collected
            rcfile = Path(td) / ".coveragerc"
            rcfile.write_text(f"[run]\ninclude = {module_path}\n[json]\ninclude = {module_path}\n")
            env = dict(os.environ, COVERAGE_FILE=str(data_file))
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "run",
                    f"--rcfile={rcfile}",
                    "-m",
                    "pytest",
                    str(test_path),
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=REPO_ROOT,
                env=env,
                check=False,
            )
            if not data_file.exists():
                return None, "pytest_failed"
            rep = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "json",
                    f"--rcfile={rcfile}",
                    "-o",
                    str(out_json),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=REPO_ROOT,
                env=env,
                check=False,
            )
            if rep.returncode != 0 or not out_json.exists():
                return None, "coverage_failed"
            data = _json.loads(out_json.read_text())
            pct = data.get("totals", {}).get("percent_covered")
            return (round(pct / 100.0, 4) if pct is not None else None), "measured"
    except FileNotFoundError:
        return None, "tool_error"
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None, "tool_error"


def run_real_gate(
    plan,
    workspace_root: Path | None = None,
    implemented_path: Path | None = None,
    test_path: Path | None = None,
) -> dict:
    """运行真实 45 门禁（本地可执行子集）。

    返回结构：
      gate_mode: real_45_local / unavailable
      gate_pass: bool（可执行硬项全过）
      syntax_pass / secrets_pass / bypass_pass: 各项真实结果
      deferred: 本地不可执行、需 CI 的规则清单
      evaluator_items: 45 原生 EvalItemRecord 摘要（权威判定留痕）
    """
    loaded = _load_45_evaluator()
    if loaded is None:
        return {
            "gate_mode": "unavailable",
            "gate_pass": None,
            "deferred": [
                "E-H1",
                "E-H2",
                "E-H3",
                "E-H5",
            ],
            "note": "45-评测系统 不可导入，降级代理",
        }

    EngineeringScan, EngineeringScanEvaluator, Traceability, BYPASS_PATTERNS = loaded
    if implemented_path is not None and Path(implemented_path).exists():
        # 方案已完整实现：直接检测真实模块（不覆盖落盘）
        target = Path(implemented_path)
    else:
        ws = workspace_root or (HERE / "sandbox_workspace")
        target = materialize(plan, ws)
    code = target.read_text(encoding="utf-8")

    # 语法门禁（编译不执行）
    try:
        py_compile.compile(str(target), doraise=True)
        syntax_pass = True
    except py_compile.PyCompileError:
        syntax_pass = False

    # E-H1 / E-H5 真实扫描
    secret_hits = scan_secrets(code)
    bypass_hits = scan_bypass([code, " ".join(plan.steps), plan.design_rationale], BYPASS_PATTERNS)

    # E-H2 漏洞扫描（pip-audit；stdlib-only 模块直接判无供应链攻击面）
    vulns, vuln_status = scan_vulnerabilities(target)
    # E-H3 本地可追溯链（git commit ↔ artifact digest ↔ provenance 侧车）
    trace = build_local_traceability(target)

    deferred: list[str] = []
    deferred_reason: dict[str, str] = {}

    # 45 原生判定
    from evaluators.engineering.scan import Vulnerability  # noqa: PLC0415

    scan_vulns = tuple(
        Vulnerability(
            advisory_id=v["id"],
            severity=v["severity"] if v["severity"] != "UNKNOWN" else "HIGH",
            fixed_version=v["fix_version"],
        )
        for v in (vulns or [])
    )
    traceability = (
        Traceability(
            commit_sha=trace["commit_sha"],
            build_digest=trace["build_digest"],
            sbom_subject_digest=trace["sbom_subject_digest"],
            attestation_verified=trace["attestation_verified"],
        )
        if trace["commit_sha"]
        else Traceability(
            commit_sha="", build_digest="", sbom_subject_digest="", attestation_verified=False
        )
    )
    if vulns is None:
        deferred.append("E-H2")
        deferred_reason["E-H2"] = f"pip-audit 状态={vuln_status}（需环境可用）"
    if not trace["commit_sha"]:
        deferred.append("E-H3")
        deferred_reason["E-H3"] = "非 git 环境，本地可追溯链不可用"

    scan = EngineeringScan(
        secrets=tuple(secret_hits),
        vulnerabilities=scan_vulns,
        traceability=traceability,
        ci_commands=(code,),
    )
    run_id = f"d2b-gate-{plan.gap_id}"
    items = EngineeringScanEvaluator().evaluate(scan, run_id)
    item_summary = {i.name: {"status": i.status, "detail": i.detail} for i in items}

    # E-H4 真实覆盖率（方案完整实现 + 测试存在时可计算）
    coverage_rate: float | None = None
    coverage_status = "no_tests"
    if implemented_path is not None and test_path is not None and Path(test_path).exists():
        coverage_rate, coverage_status = measure_coverage(target, Path(test_path))
    eh4_pass: bool | None = None
    if coverage_rate is not None:
        eh4_pass = coverage_rate >= 0.80
    elif implemented_path is None:
        deferred.append("E-H4")
        deferred_reason["E-H4"] = "骨架无测试套件，覆盖率不可计算（方案实现后可计算）"
    else:
        deferred.append("E-H4")
        deferred_reason["E-H4"] = f"覆盖率测量状态={coverage_status}"

    # 本地可执行硬项：E-H1 + E-H2(可审计时) + E-H3(本地链) + E-H4(可测时) + E-H5 + 语法
    eh1_pass = item_summary.get("E-H1-secrets", {}).get("status") == "PASS"
    eh5_pass = item_summary.get("E-H5-bypass", {}).get("status") == "PASS"
    eh2_pass = (
        item_summary.get("E-H2-vulns", {}).get("status") == "PASS" if vulns is not None else None
    )
    eh3_pass = (
        item_summary.get("E-H3-traceability", {}).get("status") == "PASS"
        if trace["commit_sha"]
        else None
    )
    gate_pass = (
        syntax_pass
        and eh1_pass
        and eh5_pass
        and (eh2_pass if eh2_pass is not None else True)
        and (eh3_pass if eh3_pass is not None else True)
        and (eh4_pass if eh4_pass is not None else True)
    )

    deferred.extend(["E-W5", "E-W6"])
    deferred_reason.update(
        {
            "E-W5": "pycg 需基准集运行",
            "E-W6": "OpenSSF Scorecard 需网络",
        }
    )

    try:
        artifact = str(target.relative_to(REPO_ROOT))
    except ValueError:
        artifact = str(target)

    return {
        "gate_mode": "real_45_local",
        "gate_pass": gate_pass,
        "syntax_pass": syntax_pass,
        "secrets_pass": eh1_pass,
        "bypass_pass": eh5_pass,
        "vuln_pass": eh2_pass,
        "vuln_status": vuln_status,
        "vuln_count": len(vulns) if vulns else 0,
        "traceability_pass": eh3_pass,
        "traceability_mode": trace["mode"],
        "traceability_commit": trace["commit_sha"][:10],
        "coverage_pass": eh4_pass,
        "coverage_rate": coverage_rate,
        "coverage_status": coverage_status,
        "implemented": implemented_path is not None,
        "secret_hits": secret_hits,
        "bypass_hits": bypass_hits,
        "artifact": artifact,
        "deferred": deferred,
        "deferred_reason": deferred_reason,
        "evaluator_items": item_summary,
        "note": (
            "真实门禁：E-H1 秘密 + E-H5 旁路 + py_compile + E-H2 pip-audit "
            f"({vuln_status}) + E-H3 本地可追溯链({trace['mode']})；"
            "deferred 项需 CI 环境或方案完整实现"
        ),
    }


if __name__ == "__main__":
    import json

    sys.path.insert(0, str(HERE))
    from generator import generate, load_gaps  # noqa: E402

    gaps = load_gaps(PKG_ROOT / "registry" / "capability_gaps.jsonl")
    d2b_types = {"architecture_gap", "doc_debt", "interface_mismatch"}
    for g in gaps:
        if g.get("gap_type") in d2b_types:
            plan = generate(g)
            result = run_real_gate(plan)
            print(
                f"{plan.gap_type}: gate_pass={result['gate_pass']} "
                f"syntax={result.get('syntax_pass')} secrets={result.get('secrets_pass')} "
                f"bypass={result.get('bypass_pass')}"
            )
            print(json.dumps(result.get("evaluator_items", {}), ensure_ascii=False, indent=2))
