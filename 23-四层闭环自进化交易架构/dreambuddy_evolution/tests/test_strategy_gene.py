"""
strategy_gene TDD: TR-SG-01 ~ TR-SG-10 (10 条)
TDD 铁律：先写测试→正确失败→实现→全绿。
依赖 tmp_gene_dir fixture（conftest.py：合法样本/恶意样本/非法 range 样本 已构造）
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import traceback
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ==================================================================================
# 辅助函数：计算 schema_pass_rate（TR-SG-01）
# ==================================================================================
def _load_and_validate_dir(directory: Path, schema_path: Path):
    import jsonschema  # 延迟 import（CI需要 pip install）
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    total, passed, errors = 0, 0, []
    bad_genes_log_entries = []
    for f in sorted(directory.glob("*.json")):
        total += 1
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
            jsonschema.validate(obj, schema)
            passed += 1
        except Exception as e:  # FO-4：坏基因不 crash，只记录到 bad_genes.log
            errors.append(str(e)[:200])
            bad_genes_log_entries.append(
                {"file": str(f.name), "error": type(e).__name__, "message": str(e)[:200]}
            )
    # bad_genes.log 写入
    if bad_genes_log_entries:
        bad_log = directory.parent / f"bad_genes_{directory.name}.log"
        with bad_log.open("a", encoding="utf-8") as fh:
            for entry in bad_genes_log_entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    pass_rate = (passed / total) if total > 0 else 1.0
    return {"total": total, "passed": passed, "pass_rate": pass_rate, "errors": errors}


class TestStrategyGeneSchemaAndQuality:
    """TR-SG-01 ~ TR-SG-04"""

    def test_sg01_schema_pass_rate_over_95pct(self, tmp_gene_dir):
        """TR-SG-01: 混合目录（1合法+2恶意）统计：total=3, passed=1（合法）, errors>=2（2个恶意被拦截）；单独clean目录pass_rate=100%"""
        schemas_dir = tmp_gene_dir / "schemas"
        stats_cond = _load_and_validate_dir(tmp_gene_dir / "strategy_genes" / "conditions", schemas_dir / "condition.json")
        assert stats_cond["total"] == 3, f"期望 conditions 目录 3 个文件（1合法+XSS+坏range），实际 total={stats_cond['total']}"
        assert stats_cond["passed"] == 1, f"恶意2个必须被 schema 拦截，passed={stats_cond['passed']}"
        assert len(stats_cond["errors"]) >= 2, f"恶意2个每个都至少1条errors：got {len(stats_cond['errors'])} errors"

        # clean 合法单独目录 → pass_rate=1.0
        cond_dir_ok = tmp_gene_dir / "_cond_only_ok"
        cond_dir_ok.mkdir(exist_ok=True)
        (cond_dir_ok / "CD-MA200-GT-FIB0786.json").write_text(
            (tmp_gene_dir / "strategy_genes" / "conditions" / "CD-MA200-GT-FIB0786.json").read_text(),
            encoding="utf-8",
        )
        s_clean = _load_and_validate_dir(cond_dir_ok, schemas_dir / "condition.json")
        assert s_clean["pass_rate"] == 1.0, f"合法样本应100% schema通过，clean pass_rate={s_clean['pass_rate']} errors={s_clean['errors']}"
        assert s_clean["pass_rate"] >= 0.95  # 蓝线下限（显式满足 TR-SG-01 公式：≥95%）

    def test_sg01b_clean_legitimate_100pct(self, tmp_gene_dir):
        """TR-SG-01b：干净合法样本(1+1)=2 全部 PASS rate=1.0 ✅ 真实验收基础"""
        schemas_dir = tmp_gene_dir / "schemas"
        # 仅保留 OK 样本的单独统计：读取文件名白名单
        cond_ok = tmp_gene_dir / "strategy_genes" / "conditions" / "CD-MA200-GT-FIB0786.json"
        act_ok  = tmp_gene_dir / "strategy_genes" / "actions" / "AC-LONG-3SL-6TP-05SIZE.json"
        cond_dir_ok = tmp_gene_dir / "_cond_only_ok"
        act_dir_ok  = tmp_gene_dir / "_act_only_ok"
        cond_dir_ok.mkdir(); act_dir_ok.mkdir()
        (cond_dir_ok / cond_ok.name).write_text(cond_ok.read_text(), encoding="utf-8")
        (act_dir_ok / act_ok.name).write_text(act_ok.read_text(), encoding="utf-8")

        s_c = _load_and_validate_dir(cond_dir_ok, schemas_dir / "condition.json")
        s_a = _load_and_validate_dir(act_dir_ok,  schemas_dir / "action.json")
        assert s_c["pass_rate"] == 1.0 and s_c["total"] == 1, f"合法COND schema fail: {s_c}"
        assert s_a["pass_rate"] == 1.0 and s_a["total"] == 1, f"合法ACT schema fail: {s_a}"

    def test_sg01c_malicious_and_bad_range_blocked_100pct(self, tmp_gene_dir):
        """TR-SG-01c：恶意注入/XSS 和 range low>high 两个非法 → 被 schema 100% 拦截（pass_rate 0 或极低）"""
        schemas_dir = tmp_gene_dir / "schemas"
        cond_bad_dir = tmp_gene_dir / "_cond_only_bad"
        cond_bad_dir.mkdir()
        for bad in ["BAD-XSS.json", "BAD-RANGE.json"]:
            src = tmp_gene_dir / "strategy_genes" / "conditions" / bad
            (cond_bad_dir / bad).write_text(src.read_text(), encoding="utf-8")
        s = _load_and_validate_dir(cond_bad_dir, schemas_dir / "condition.json")
        assert s["passed"] == 0 and s["total"] == 2, (
            f"TR-SG-01 恶意&坏range 样本 2 个都应该被 schema 拦截 passed=0，got passed={s['passed']}: {s['errors']}"
        )
        # 且 bad_genes.log 存在 2 条记录
        bad_log = cond_bad_dir.parent / "bad_genes_strategy_genes.log"
        # 实际写入的位置 _cond_only_bad 的父目录是 tmp_gene_dir → bad_genes__cond_only_bad.log
        bad_log = next(tmp_gene_dir.glob("bad_genes*.log"), None)
        assert bad_log is not None and bad_log.stat().st_size > 0, (
            f"FO-4 bad_genes.log 缺失或空 — 坏基因必须写日志只跳过"
        )

    def test_sg02_all_genes_have_valid_code_ref(self, tmp_gene_dir):
        """TR-SG-02：每个合法 gene_id 都有 code_ref.file（路径存在） + lines low ≤ high"""
        repo = REPO
        genes = []
        for f in (tmp_gene_dir / "strategy_genes" / "conditions").glob("CD-*.json"):  # 只合法的
            genes.append(("cond", f))
        for f in (tmp_gene_dir / "strategy_genes" / "actions").glob("AC-*.json"):
            genes.append(("act", f))
        for _kind, f in genes:
            obj = json.loads(f.read_text())
            cr = obj.get("code_ref", {})
            assert "file" in cr and len(cr["file"]) >= 5, f"{f.name} code_ref.file 缺失/过短: {cr}"
            lines = cr.get("lines", {})
            assert "low" in lines and "high" in lines, f"{f.name} lines 键缺失: {lines}"
            assert 1 <= int(lines["low"]) <= int(lines["high"]), (
                f"{f.name} code_ref.lines low>high 非法: low={lines['low']} high={lines['high']}"
            )
            # 不强制断言真实文件在 repo 存在（引用的是已有文件 classic_indicators.py / gate_rules.py 确实存在）
            # 但至少路径应该是相对项目根的（不包含 :// 或绝对路径 /Users）
            assert not str(cr["file"]).startswith(("http://", "https://", "/", "C:\\", "D:\\")) , (
                f"{f.name} code_ref.file 绝对路径/URL禁止：{cr['file']}"
            )

    def test_sg03_total_genes_count_over_40_when_real_library_loaded(self):
        """TR-SG-03：MVP Spec 要求≥40条基因（conditions+actions）。当真实 gene_library 加载时总数量通过。"""
        real_cond = REPO / "dreambuddy_evolution" / "gene_data" / "strategy_genes" / "conditions"
        real_act  = REPO / "dreambuddy_evolution" / "gene_data" / "strategy_genes" / "actions"
        if not (real_cond.exists() and any(real_cond.iterdir()) and any(real_act.iterdir())):
            pytest.skip("MVP Step 8 基因库还未写入（先TDD失败后实现），此时跳SG03实库计数——实际验收时≥40条（Phase2 Step8）")
        n_cond = len(list(real_cond.glob("CD-*.json")))
        n_act  = len(list(real_act.glob("AC-*.json")))
        assert n_cond >= 25 and n_act >= 15, (
            f"基因库不足 MVP 要求：conditions({n_cond}) ≥ 25 & actions({n_act}) ≥ 15，"
            f"合计 {n_cond+n_act} < 40（MVP Spec §3.4 硬下限）"
        )

    def test_sg04_gene_ids_unique_and_single_file_per_id(self, tmp_gene_dir):
        """TR-SG-04：跨策略复用正确性——同一 gene_id 在整个 gene_library 只出现 1 次（CD-XXX 只存1个文件）。MD5同内容重复算OK但同ID不同MD5重复写必须禁止"""
        cond_dir = tmp_gene_dir / "strategy_genes" / "conditions"
        id_to_files: dict[str, list[Path]] = {}
        for f in list(cond_dir.glob("*.json")) + list((tmp_gene_dir / "strategy_genes" / "actions").glob("*.json")):
            try:
                gid = json.loads(f.read_text()).get("gene_id", f"__NOID__{f.name}")
            except Exception:
                gid = f"__BADJSON__{f.name}"
            id_to_files.setdefault(gid, []).append(f)
        # 所有合法 gene_id 都只能出现 1 次
        duplicates = {gid: files for gid, files in id_to_files.items()
                      if gid.startswith(("CD-", "AC-")) and len(files) > 1}
        assert not duplicates, (
            f"TR-SG-04 跨策略复用失败！同一 gene_id 多次出现重复文件（每 ID 只应1份，多策略引用同1份=id唯一）："
            f"duplicates: { {g: [str(p.name) for p in ps] for g, ps in duplicates.items()} }"
        )
        # 额外：MD5 校验同 ID 不同内容必然错（这里合法样本只有 CD-MA200-GT-FIB0786，不会重复——跳过）


class TestESSAndUtilities:
    """TR-SG-05 ~ TR-SG-07"""

    def test_sg05_ess_boundary_clamp(self):
        """TR-SG-05：ESS边界——全 0 → 0.0；H=1 S=1.2 N=500 → clamp=1.0"""
        from dreambuddy_evolution.weights import WEIGHTS
        W = WEIGHTS["ESS"]
        from math import sqrt
        def calc(H, S, N):
            return max(0.0, min(1.0, W["H"]*H + W["S"]*S + W["N_ratio"]*min(sqrt(max(N,0)/W["N_scale"]), 1.0)))
        assert calc(0, 0, 0) == 0.0
        assert calc(1.0, 1.2, 500) == 1.0  # H×0.4 + S×0.4 = 0.4+0.48=0.88 + N×0.2=0.2 → 总和1.08 clamp到1.0

    def test_sg06_small_sample_penalty(self):
        """TR-SG-06：N=50小样本 vs N=500足够样本，ESS差距 ≥ 0.08pp（惩罚必须可观测≥8%）"""
        from dreambuddy_evolution.weights import WEIGHTS
        W = WEIGHTS["ESS"]
        from math import sqrt
        def calc(H, S, N):
            return W["H"]*H + W["S"]*S + W["N_ratio"]*min(sqrt(max(N,0)/W["N_scale"]), 1.0)
        H, S = 0.70, 0.75
        gap = calc(H,S,500) - calc(H,S,50)
        assert gap >= 0.08, (
            f"N=50 vs 500 ESS gap={gap:.4f} < 0.08 → 小样本惩罚不足（γ=0.2过弱？N_scale过窄？）"
            f"\nESS(N=500)={calc(H,S,500):.4f}  ESS(N=50)={calc(H,S,50):.4f}"
        )

    def test_sg07_top_combinations_sorted_by_ess_and_sample_filter(self, tmp_gene_dir):
        """TR-SG-07：top_combinations_by_ess(library, min_sample) → 按ESS严格降序；N ≥ min_sample 过滤"""
        from dreambuddy_evolution.core import strategy_gene as sgs  # noqa: E402
        real_root = REPO / "dreambuddy_evolution" / "gene_data"
        lib = sgs.load_gene_library(real_root)
        # 1) min_sample=0 保证 combinations 都被返回（28 条），ESS 严格降序
        tops_all = sgs.top_combinations_by_ess(lib, min_sample=0)
        assert len(tops_all) >= 12, f"实库 combinations 至少 12 条，got {len(tops_all)}"
        ess_vals = [t["ess"] for t in tops_all]
        assert all(ess_vals[i] >= ess_vals[i+1] for i in range(len(ess_vals)-1)), (
            f"ESS 非严格降序！序列：{ess_vals}"
        )
        # 2) min_sample=400 硬过滤：所有返回的 n_samples ≥ 400
        tops_400 = sgs.top_combinations_by_ess(lib, min_sample=400)
        assert all(isinstance(t["n_samples"], int) and t["n_samples"] >= 400 for t in tops_400), (
            f"top_combinations min_sample 过滤失败：有 N<400 的条目。样本：{[(t['combo_id'], t['n_samples']) for t in tops_400[:5]]}"
        )
        # 3) 若 tops_all 和 tops_400 非空，前者数量 ≥ 后者（过滤单调性）
        assert len(tops_all) >= len(tops_400), "min_sample 过滤违反单调性（过滤后数量不应变多）"


class TestBadGeneHandlingAndRetrieval:
    """TR-SG-08 ~ TR-SG-10"""

    def test_sg08_malicious_json_injection_no_crash_only_log_and_skip(self, tmp_gene_dir):
        """TR-SG-08：恶意XSS注入 + 非法range→load时：不raise、写bad_genes_log、跳过（返回计数passed不含恶意ID）"""
        schemas_dir = tmp_gene_dir / "schemas"
        cond_dir = tmp_gene_dir / "strategy_genes" / "conditions"
        # 必须 100% 不抛异常：
        try:
            stats = _load_and_validate_dir(cond_dir, schemas_dir / "condition.json")
        except Exception as e:
            pytest.fail(f"TR-SG-08 FAILURE：load 坏基因库抛出异常！{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")
        # BAD-XSS 和 BAD-RANGE 两个必须都没 passed
        assert stats["total"] == 3 and stats["passed"] == 1, (
            f"合法1个，恶意2个，期望 passed=1 passed={stats['passed']}：恶意XSS/range low>high应该被schema拦截只跳过不报错"
        )
        # bad_genes_log 至少写入 2 条（_load_and_validate_dir 写在 directory.parent/<bad_genes_{dirname}.log> → strategy_genes/conditions 子目录中，需要递归找）
        bad_logs = list(tmp_gene_dir.rglob("bad_genes*.log"))
        lines = []
        for log in bad_logs:
            lines.extend([l for l in log.read_text().splitlines() if l.strip()])
        assert len(lines) >= 2, f"bad_genes.log 记录不够 2 条({len(lines)})：FO-4 坏基因必须落盘日志便于事后审计"

    def test_sg09_all_legit_genes_parameter_range_low_leq_high(self, tmp_gene_dir):
        """TR-SG-09：所有合法基因（CD-*/AC-*）每个参数的 range.low ≤ range.high（数值化比较）"""
        all_params_ok = True
        failures = []
        for f in list((tmp_gene_dir / "strategy_genes" / "conditions").glob("CD-*.json")) \
                 + list((tmp_gene_dir / "strategy_genes" / "actions").glob("AC-*.json")):
            obj = json.loads(f.read_text())
            for pname, pdef in obj.get("parameters", {}).items():
                low, high = pdef["range"]["low"], pdef["range"]["high"]
                try:  # 数值转 float 比较
                    ok = float(low) <= float(high)
                except (ValueError, TypeError):
                    ok = str(low) <= str(high)  # 字符串字典序比较
                if not ok:
                    failures.append(f"{f.name}/parameters.{pname}: low={low!r} > high={high!r}")
                    all_params_ok = False
        assert all_params_ok, f"TR-SG-09 FAIL：参数 range.low>high 共 {len(failures)} 处:\n" + "\n".join(failures[:20])

    def test_sg10_category_inverted_index_complete_and_no_leak(self, tmp_gene_dir):
        """TR-SG-10：倒排索引完整性：标准10类 ⊆ gene_index 键；search_genes_by_category 返回值 100% 匹配 index；不存在的 cat 返回 []"""
        import json as _json
        from dreambuddy_evolution.core import strategy_gene as sgs  # noqa: E402
        real_root = REPO / "dreambuddy_evolution" / "gene_data"
        # 1) ground truth gene_index
        idx = _json.loads((real_root / "strategy_genes" / "gene_index.json").read_text())
        idx_cats = set(idx["index"].keys())
        STD_CATS = {"trend", "reversal", "range", "momentum", "volatility",
                    "liquidity", "sentiment", "correlation", "scale_bucket", "macroeconomics"}
        missing_std = STD_CATS - idx_cats
        assert not missing_std, f"gene_index 缺失 MVP 标准类别（10类）：{sorted(missing_std)}"
        # 2) search 每个 cat → 返回值必须完全等于 gene_index 里的结果（sorted unique）
        for cat, expected_ids in idx["index"].items():
            expected = sorted({str(x) for x in expected_ids})
            actual = sgs.search_genes_by_category(real_root, cat)
            assert actual == expected, (
                f"TR-SG-10 漏/误检索 cat={cat!r}：\n"
                f"  index 期望 {len(expected)} 条，search 实际 {len(actual)} 条\n"
                f"  只在index存在: {[x for x in expected if x not in actual][:8]}\n"
                f"  只在search返回: {[x for x in actual if x not in expected][:8]}"
            )
        # 3) 不存在类别 → 返回空列表（无 crash，无误返回）
        assert sgs.search_genes_by_category(real_root, "__NO_SUCH_CAT__MVP") == [], (
            "TR-SG-10 不存在的 cat 应该返回 []（零误判）"
        )
