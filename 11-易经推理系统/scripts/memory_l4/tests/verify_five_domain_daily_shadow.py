"""独立验证脚本：_run_once_five_domain_daily_update() 缓存 & 调用次数。

验证要点：
- 第1次调用：score_and_decide 被调用 >=1 次
- 第2、3次调用：若日期未变，score_and_decide 不被调用（缓存热路径）
"""
import os
import sys
import json
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
YIJING_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(YIJING_ROOT))


class FakeLog:
    def __init__(self):
        self.lines = []

    def _log(self, msg, level="INFO"):
        self.lines.append((level, msg))


class FakeTrader(FakeLog):
    """最小化模拟 PollingTrader，仅装配必要属性。"""

    def __init__(self, scorer):
        super().__init__()
        self._five_domain_scorer = scorer
        self._five_domain_state_cache = None
        # 注入目标方法（未绑定 -> 绑定）
        from scripts.memory_l4.polling_trader import PollingTrader
        self._run_once_five_domain_daily_update = (
            PollingTrader._run_once_five_domain_daily_update.__get__(self)
        )


def _patch_state_cache_path_to_tmp(monkeypatch, tmpdir: Path):
    """把 five_domain_state.json 重定向到 tmpdir，避免污染生产 runtime。"""
    import scripts.memory_l4.polling_trader as pt_mod

    original = Path(pt_mod.__file__).resolve()

    def _fake_file():
        return str(tmpdir / "polling_trader_shadow_fake.py")

    monkeypatch.setattr(pt_mod, "__file__", _fake_file())
    (tmpdir / "runtime").mkdir(parents=True, exist_ok=True)


def main():
    call_count = {"n": 0}
    real_cached_json_path = None

    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        _patch_state_cache_path_to_tmp(mp, tmpdir)

        from scripts.memory_l4.five_domain_scorer import (
            FiveDomainHeuristicScorer,
            FiveDomainState,
            CLASSES,
        )

        cache_path = tmpdir / "runtime" / "five_domain_state.json"
        real_cached_json_path = cache_path

        scorer = FiveDomainHeuristicScorer(enable=False, state_cache_path=cache_path)

        orig = scorer.score_and_decide

        def counting_wrapper(*args, **kwargs):
            call_count["n"] += 1
            return orig(*args, **kwargs)

        scorer.score_and_decide = counting_wrapper

        trader = FakeTrader(scorer)

        # ---- Call #1: 文件不存在 -> 必须重算 ----
        call_count["n"] = 0
        trader._run_once_five_domain_daily_update()
        first_call_count = call_count["n"]
        print(f"[验证] 第1次调用后 score_and_decide 调用次数 = {first_call_count}")
        assert first_call_count >= 1, f"第1次调用应当触发重算，实际仅 {first_call_count} 次"
        assert cache_path.exists(), "第1次调用后缓存文件应存在"
        with cache_path.open("r", encoding="utf-8") as f:
            d1 = json.load(f)
        import datetime as _dt
        today_str = _dt.date.today().isoformat()
        assert d1.get("_meta", {}).get("updated_date") == today_str, "缓存 _meta.updated_date 必须是今日"
        assert trader._five_domain_state_cache is not None, "state_cache 必须被赋值"
        print(f"[验证] 第1次调用：缓存 _meta.updated_date = {d1['_meta']['updated_date']} ✓")

        # 检查 5 行影子日志
        shadow_lines = [msg for (lv, msg) in trader.lines if lv == "INFO" and "[战略层影子]" in msg]
        print(f"[验证] 第1次调用后 INFO-[战略层影子] 行数 = {len(shadow_lines)}")
        assert len(shadow_lines) >= 5, f"影子日志应至少5行，实际 {len(shadow_lines)}: {shadow_lines}"
        required_tags = ["war_state", "total_score", "dao_score", "cap_mode", "mult_mode"]
        for tag in required_tags:
            hits = [l for l in shadow_lines if tag in l]
            assert len(hits) >= 1, f"影子日志缺失 {tag}"
        print(f"[验证] 第1次调用：5行影子日志（war/total/dao/cap/mult）全部齐全 ✓")

        # ---- Call #2: 缓存日期=今日 -> 不重算 ----
        call_count["n"] = 0
        trader._run_once_five_domain_daily_update()
        second_call_count = call_count["n"]
        print(f"[验证] 第2次调用后 score_and_decide 调用次数 = {second_call_count}")
        assert second_call_count == 0, f"第2次调用命中缓存，不应重算，实际 {second_call_count} 次"
        print("[验证] 第2次调用：命中日级缓存，未调用 score_and_decide ✓")

        # ---- Call #3: 同上 ----
        call_count["n"] = 0
        trader._run_once_five_domain_daily_update()
        third_call_count = call_count["n"]
        print(f"[验证] 第3次调用后 score_and_decide 调用次数 = {third_call_count}")
        assert third_call_count == 0, f"第3次调用命中缓存，不应重算，实际 {third_call_count} 次"
        print("[验证] 第3次调用：命中日级缓存，未调用 score_and_decide ✓")

        # ---- Call #4: 篡改 _meta.updated_date 为昨日 -> 必须重算 ----
        import datetime as _dt2
        yesterday = (_dt2.date.today() - _dt2.timedelta(days=1)).isoformat()
        with cache_path.open("r", encoding="utf-8") as f:
            d4 = json.load(f)
        d4["_meta"]["updated_date"] = yesterday
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(d4, f, ensure_ascii=False, indent=2)
        call_count["n"] = 0
        trader._run_once_five_domain_daily_update()
        fourth_call_count = call_count["n"]
        print(f"[验证] 第4次调用(伪造昨日)后 score_and_decide 调用次数 = {fourth_call_count}")
        assert fourth_call_count >= 1, f"缓存过期后应重算，实际 {fourth_call_count} 次"
        with cache_path.open("r", encoding="utf-8") as f:
            d4_after = json.load(f)
        assert d4_after.get("_meta", {}).get("updated_date") == today_str, "过期后重算应刷新 updated_date 为今日"
        print(f"[验证] 第4次调用：缓存过期触发重算，_meta.updated_date 已刷新为 {today_str} ✓")

        # ---- Call #5: 模拟异常 fail-open ----
        def boom(*a, **kw):
            raise RuntimeError("fake scorer error")
        scorer.score_and_decide = boom
        # 先把缓存删掉，强制进入重算分支
        cache_path.unlink(missing_ok=True)
        try:
            trader._run_once_five_domain_daily_update()
        except Exception as e:
            raise AssertionError(f"方法不应冒泡异常：{e}")
        # fail-open 验证
        assert trader._five_domain_state_cache is not None, "异常后 state_cache 应=default_fail_open 非 None"
        from dataclasses import asdict
        try:
            from scripts.memory_l4.five_domain_scorer import FiveDomainState as _FDS
            assert asdict(trader._five_domain_state_cache) == asdict(_FDS.default_fail_open()), (
                "异常后 state_cache 不是 default_fail_open"
            )
            print("[验证] 第5次调用：异常捕获后 fail-open = FiveDomainState.default_fail_open() ✓")
        except AssertionError:
            # 当 scorer=None 异常分支会置 None，再兜底也可接受
            if trader._five_domain_state_cache is not None:
                raise

        mp.undo()

    print("\n========== 所有独立验证通过 ==========")
    return 0


if __name__ == "__main__":
    sys.exit(main())
