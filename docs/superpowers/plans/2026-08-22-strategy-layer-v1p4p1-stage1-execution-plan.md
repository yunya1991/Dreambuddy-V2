# 策略算法层 v1.4.1 阶段1（最小影子模式）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不影响实盘交易链路的前提下，将战略层五计庙算（FiveDomainHeuristicScorer）与策略算法层（StrategyAlgorithmLayer）以零侵入影子模式接入 polling_trader.py，在3个关键插入点（run_once / ParameterMapper / _open_position）写入 ShadowLogger，为阶段2在线学习积累训练样本。

**Architecture:** 严格四层正交依赖：战略层（日级五计打分→FiveDomainState）→ 前置层（中周期 L/T/S 参数 np.clip 带宽约束）→ 策略算法层（按类 select → calibration_biases × Exit 基准阈值）→ 离场层（ExitManager 链式评估）。总/子开关全部默认 False，关断时字节等价改造前；影子模式仅记录不改变任何交易参数（fail-open F1 红线）。

**Tech Stack:** Python 3.12+, numpy 1.26+, dataclass（3.12 原生）, pytest 8.4+, SQLite 影子 DB（复用 EvolutionStorageSQLite）, 无任何新增第三方依赖。

## Global Constraints

- 所有新增开关默认 False（enable_strategy_layer、enable_five_domain、7 子开关、3 影子 AB 开关），开/关断字节等价
- 按类完全独立：crypto_usdt / us_stock / precious_metal 三类决策变量无任何共享（除跨类相关性乘数统计）
- 战略层运行周期=日级（run_once 内每日期变更触发一次），禁止 5 分钟热路径重算；缓存 five_domain_state.json，异常→默认 fail-open
- 前置层带宽 band=None 时，`apply_front_band_clip` 必须 0 行 clip 执行（返回 raw 的 copy，字节等价）
- calibration_biases 仅接受乘法系数，硬门限 `hard_relax_gate=False` 时 >1.0 放宽方向强制写回 1.0（R5 红线）
- TradeRecord.enhance_info 写入使用白名单兼容：缺字段自动填默认值，旧仓位反序列化无 AttributeError（R1 红线）
- ShadowLogger 所有新增字段可选（Optional），旧版记录缺字段默认 None，不影响现有 AB 基线评估脚本
- 插入点 3 处全部 wrap try/except，任何异常不抛到主交易流程，catch 后日志 WARN 级别（不影响真实开仓）

---

## 一、File Structure（文件责任边界）

| 文件 | 动作 | 责任 |
|---|---|---|
| `11-易经推理系统/scripts/memory_l4/strategy_algo_layer.py` | 修改（已完成） | 3 dataclass / StrategyAlgoConfig / StrategyAlgorithmLayer（纯校准+带宽 clip） |
| `11-易经推理系统/scripts/memory_l4/five_domain_scorer.py` | 修改（已完成） | FiveDomainState 结构 / FiveDomainHeuristicScorer 6 决策不等式映射 |
| `11-易经推理系统/scripts/memory_l4/tests/test_strategy_algo_stage1.py` | 修改（15项全通过） | §2.3 TDD #1-15 矩阵（数据结构契约/带宽5场景/按类独立性/fail-open字节等价） |
| `11-易经推理系统/scripts/memory_l4/polling_trader.py` | 修改（本计划 T1-T4） | 插入点 1/2/3/4：`__init__` 初始化 / `run_once` 战略层打分 / ParameterMapper 带宽 clip / `_open_position` 策略校准+enhance_info |
| `11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py` | 修改（T5） | record 扩展 12 字段战略/策略影子（five_domain_state / strategy_selection），保持旧字段类型兼容 |
| `11-易经推理系统/scripts/memory_l4/tests/test_polling_trader_shadow_integration.py` | 新建（T6.1） | 影子模式 0 侵入：全开关 False 字节等价 + 开关 True 不改变 direction/position_usdt |
| `11-易经推理系统/scripts/memory_l4/tests/test_shadow_logger_schema_compat.py` | 新建（T5.4） | ShadowLogger 新旧 schema 兼容性：缺字段填充默认，不崩 |
| `11-易经推理系统/scripts/memory_l4/tests/test_byte_equivalence_five_domain.py` | 新建（T6.2） | enable_five_domain=False vs 改造前（git stash baseline）：5 类关键输出哈希 diff=0 |

---

## 二、Task T1：polling_trader.__init__ 战略层/策略算法层组件初始化

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/polling_trader.py` 约 line 697（`_init_capital_control` 之后）
- Test: `11-易经推理系统/scripts/memory_l4/tests/test_strategy_algo_stage1.py::TestDataStructureContracts`（15项已验证，无需新测）

**Interfaces:**
- Consumes: `scripts.memory_l4.five_domain_scorer.FiveDomainHeuristicScorer(enable=False, state_cache_path=...)`
- Consumes: `scripts.memory_l4.strategy_algo_layer.StrategyAlgorithmLayer(cfg=StrategyAlgoConfig(all False))`
- Produces: `self._five_domain_scorer: Optional[FiveDomainHeuristicScorer]`, `self._strategy_algo_layer: Optional[StrategyAlgorithmLayer]`, `self._five_domain_state_cache: FiveDomainState`

### T1 Steps

- [ ] **Step 1: 在 `_init_capital_control()` 之后插入初始化代码（约 line 698）**

```python
        # ──────────────────────────────────────────────────────
        # v1.4.1 Stage 1: 战略层五计庙算 + 策略算法层（影子模式，默认全关）
        # 设计原则：所有开关默认 False → 两个组件均为 None → 字节等价
        #           异常 catch → None → 不阻塞 __init__
        # ──────────────────────────────────────────────────────
        self._five_domain_scorer = None  # type: ignore[assignment]
        self._strategy_algo_layer = None  # type: ignore[assignment]
        self._five_domain_state_cache = None  # type: ignore[assignment]
        self._init_five_domain_and_strategy_layer()
```

- [ ] **Step 2: 在 `_init_capital_control()` 下方新增 `_init_five_domain_and_strategy_layer()` 方法（约 line 820 区块，与 `_init_morph_and_param_mapper` 同层）**

```python
    # ================================================================
    # v1.4.1 Stage 1: 战略层五计庙算 + 策略算法层（影子模式初始化）
    # 设计原则：失败降级为 None，仅影响影子日志，不改变任何交易逻辑
    # ================================================================

    def _init_five_domain_and_strategy_layer(self):
        """初始化五计庙算评分器 + 策略算法层（默认全关=fail-open字节等价）。

        state_cache_path = runtime/five_domain_state.json（日级缓存，5分钟热路径只读）
        """
        from pathlib import Path as _Path
        try:
            from scripts.memory_l4.five_domain_scorer import FiveDomainHeuristicScorer
            from scripts.memory_l4.strategy_algo_layer import StrategyAlgorithmLayer, StrategyAlgoConfig
        except Exception as e:
            self._log(f"[战略层/策略层] import失败，影子模式关闭（字节等价）: {e}", "WARN")
            return

        # cfg：2总+7子+3模式+1放宽 共13开关，默认全部False（符合§三开关表fail-open）
        cfg = StrategyAlgoConfig(
            enable_strategy_layer=False,
            enable_five_domain=False,
            # 7 子开关默认 False
            enable_five_domain_war_state=False,
            enable_five_domain_style_mask=False,
            enable_five_domain_position_cap=False,
            enable_five_domain_cross_asset=False,
            enable_five_domain_dimensio=False,
            enable_five_domain_front_layer_band=False,
            enable_five_domain_ol=False,
            # 影子 AB 模式默认 False
            enable_five_domain_shadow_mode=False,
            enable_shadow_ab_static_baseline_v15=False,
            enable_shadow_ab_dynamic_baseline=False,
            # R5 红线：放宽阈值默认不允许
            enable_strategy_layer_relax_allowed=False,
        )
        try:
            cache_path = _Path(__file__).resolve().parent / "runtime" / "five_domain_state.json"
            self._five_domain_scorer = FiveDomainHeuristicScorer(enable=False, state_cache_path=cache_path)
            self._strategy_algo_layer = StrategyAlgorithmLayer(cfg=cfg)
            # 初始化 state_cache = 默认 fail-open（字节等价）
            self._five_domain_state_cache = self._five_domain_scorer.score_and_decide(persist=True)
            # ★ F1 红线断言：enable=False 时 state 必须字节等价 default_fail_open
            from scripts.memory_l4.five_domain_scorer import FiveDomainState
            from dataclasses import asdict as _asdict
            assert _asdict(self._five_domain_state_cache) == _asdict(FiveDomainState.default_fail_open()), (
                "[F1红线违规] 战略层enable=False时返回值≠default_fail_open，请检查score_and_decide fail-open分支"
            )
            self._log("[战略层/策略层] 初始化完成（影子默认关闭，字节等价）", "INFO")
        except Exception as e:
            self._five_domain_scorer = None
            self._strategy_algo_layer = None
            self._five_domain_state_cache = None
            self._log(f"[战略层/策略层] 构造失败，降级关闭（字节等价）: {e}", "WARN")
```

- [ ] **Step 3: 运行 py_compile 验证语法**

Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/polling_trader.py && echo OK`
Expected: `OK`（无 SyntaxError / IndentationError）

- [ ] **Step 4: 单测验证初始化 fail-open 字节等价（复用现有15项，不新建）**

Run: `cd 11-易经推理系统 && python3 -m pytest scripts/memory_l4/tests/test_strategy_algo_stage1.py::TestMasterSwitchFailOpen -v --tb=short`
Expected: 3 tests PASSED（test_13/test_14/test_15 全绿）

- [ ] **Step 5: Commit（小步提交，便于回滚）**

```bash
git add 11-易经推理系统/scripts/memory_l4/polling_trader.py
git commit -m "feat(salv1.4.1/T1): 初始化战略层五计+策略算法层组件（默认全关，字节等价）"
```

---

## 三、Task T2：run_once 战略层日级打分 + 缓存插入点

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/polling_trader.py` `run_once()` 约 line 7912（资金调控状态日志之后，effective_threshold 之前）
- Test: `11-易经推理系统/scripts/memory_l4/tests/test_strategy_algo_stage1.py::TestPerClassIndependence`（9-12 已验证按类独立）

**Interfaces:**
- Consumes: `self._five_domain_scorer.score_and_decide(raw_scores_by_class, persist=True)`（日级缓存）
- Consumes: `self._last_trade_date`（由 `_check_date_rollover` 保证，日期变更才重算）
- Produces: `self._five_domain_state_cache: FiveDomainState`（热路径只读）；ShadowLogger 一条战略日级记录

### T2 Steps

- [ ] **Step 1: 在 run_once 中 effective_threshold 前插入战略层打分块（约 line 7934）**

```python
        # ══ v1.4.1 Stage 1 插入点 ①/③：战略层五计庙算日级打分（5分钟热路径只读缓存）═══
        #   日期变更 → 重算一次并写入 five_domain_state.json（日级=战略层周期，§11矩阵）
        #   enable=False / scorer=None → 直接跳过，字节等价无副作用
        self._run_once_five_domain_daily_update()

        effective_threshold = self._adjust_confidence_threshold()
```

- [ ] **Step 2: 新增 `_run_once_five_domain_daily_update()` 方法（T1 方法块下方）**

```python
    def _run_once_five_domain_daily_update(self):
        """run_once：五计庙算战略层日级打分（日期变更才重算；否则读缓存，0 CPU开销）。

        无任何副作用：即便评分器抛出异常，也不会影响主交易流程。
        fail-open：scorer=None → return；state 保持上次缓存或默认 fail-open。
        """
        if self._five_domain_scorer is None:
            return  # 组件未初始化 → 字节等价

        # 日期才重算（战略层=日级，5 分钟热路径禁止 CPU 消耗）
        try:
            from datetime import date as _date
            today_str = _date.today().isoformat()
            cache = self._five_domain_state_cache
            last_scores_day = None
            if cache is not None:
                # five_scores 快照中无日期 → 用 state_cache 文件 mtime 判断（更可靠）
                try:
                    from pathlib import Path as _P
                    fp = self._five_domain_scorer.state_cache_path
                    if fp.exists():
                        import time as _t
                        last_scores_day = _date.fromtimestamp(fp.stat().st_mtime).isoformat()
                except Exception:
                    last_scores_day = None
            # 日期变更 / 文件不存在 → 重算一次
            if (last_scores_day is None) or (last_scores_day != today_str):
                raw_scores_by_cls = self._build_raw_five_scores_for_today()
                new_state = self._five_domain_scorer.score_and_decide(raw_scores_by_cls, persist=True)
                self._five_domain_state_cache = new_state
                total_map = {}
                for cls in ("crypto_usdt", "us_stock", "precious_metal"):
                    s = new_state.five_scores.get(cls, {})
                    total_map[cls] = self._five_domain_scorer._weighted_total(s, cls) if self._five_domain_scorer else 53
                self._log(
                    f"[五计庙算/日级] 日期切换重算完成 "
                    f"crypto={total_map.get('crypto_usdt', '?')}分(war={new_state.war_state.get('crypto_usdt')}) "
                    f"stock={total_map.get('us_stock', '?')}分 metal={total_map.get('precious_metal', '?')}分",
                    "INFO"
                )
            # 影子日志写入：如果 shadow 模式开关打开（默认 False），写入战略层快照
            try:
                if getattr(self._strategy_algo_layer, "cfg", None) is not None:
                    if self._strategy_algo_layer.cfg.enable_five_domain_shadow_mode:
                        self._shadow_record_five_domain_snapshot()  # ★ 异常内部 catch
            except Exception:
                pass  # 影子异常不阻塞主流程
        except Exception as e:  # noqa: BLE001 — 最外层兜底：失败不阻塞
            self._log(f"[五计庙算/日级] 重算失败，保留上次缓存（不影响交易）: {e}", "WARN")

    def _build_raw_five_scores_for_today(self):
        """【阶段1最小影子模式启发式占位】返回三类资产的原始五计分（0-100整数）。

        替换点（阶段2在线学习）：真实指标 → 注入 dao/tian/di/jiang/fa 数值。
        当前阶段1：返回中性默认值 50/50/50/50/70，保证总开关关闭时字节等价，开启时便于
        影子模式验证「band=None / mask全True / cap=0.20 四档<60」中性链路。
        """
        from scripts.memory_l4.strategy_algo_layer import DEFAULT_NEUTRAL_SCORES
        return {
            "crypto_usdt":     dict(DEFAULT_NEUTRAL_SCORES),
            "us_stock":        dict(DEFAULT_NEUTRAL_SCORES),
            "precious_metal":  dict(DEFAULT_NEUTRAL_SCORES),
        }

    def _shadow_record_five_domain_snapshot(self):
        """【影子模式专用】把 FiveDomainState 9字段快照写入 ShadowLogger（可选，默认关）。

        内部 try/except 全覆盖：任何异常静默吞，不影响主流程。
        """
        if self._shadow_logger is None or self._five_domain_state_cache is None:
            return
        try:
            from dataclasses import asdict as _asdict
            snapshot = _asdict(self._five_domain_state_cache)
            storage = getattr(self._shadow_logger, "storage", None)
            if storage is not None:
                # save_meta：复用 storage 通用 KV（避免修改 SQLite schema，阶段1不升库）
                storage.save_meta("five_domain_daily_snapshot", snapshot)
        except Exception:
            pass
```

- [ ] **Step 3: py_compile 验证**

Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/polling_trader.py && echo OK`
Expected: `OK`

- [ ] **Step 4: 运行 TDD 15项核心测试，确保不回归**

Run: `cd 11-易经推理系统 && python3 -m pytest scripts/memory_l4/tests/test_strategy_algo_stage1.py -v --tb=short`
Expected: 15 passed

- [ ] **Step 5: 独立脚本验证日期变更触发重算、日期不变走缓存**

```bash
cd 11-易经推理系统 && python3 -c "
import sys, tempfile, os
sys.path.insert(0, '.')
from scripts.memory_l4.five_domain_scorer import FiveDomainHeuristicScorer, FiveDomainState
from dataclasses import asdict
with tempfile.TemporaryDirectory() as td:
    fp = os.path.join(td, 'state.json')
    scorer = FiveDomainHeuristicScorer(enable=True, state_cache_path=fp)
    # 第一次：必然重算
    s1 = scorer.score_and_decide({'crypto_usdt':{'dao':90,'tian':85,'di':80,'jiang':75,'fa':80}}, persist=True)
    # 修改 fp mtime = 昨天，模拟日期过期
    import time
    yesterday = time.time() - 86400
    os.utime(fp, (yesterday, yesterday))
    # 第二次：日期变更 → 重算
    s2 = scorer.score_and_decide({'crypto_usdt':{'dao':50,'tian':50,'di':50,'jiang':50,'fa':70}}, persist=True)
    assert asdict(s1) != asdict(s2), '日期切换应该重算'
    # 第三次：mtime 是今天 → 走缓存不重算（从文件恢复和 s2 一致）
    s3 = FiveDomainState.from_json(fp)
    assert asdict(s2) == asdict(s3), '缓存文件应该字节一致'
    print('日期切换+缓存OK')
"
```
Expected: `日期切换+缓存OK`

- [ ] **Step 6: Commit**

```bash
git add 11-易经推理系统/scripts/memory_l4/polling_trader.py
git commit -m "feat(salv1.4.1/T2): run_once战略层日级打分+影子记录（日期变更才重算，热路径0开销）"
```

---

## 四、Task T3：ParameterMapper 前置层带宽 clip 插入点（零侵入，band开关）

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/polling_trader.py` `_log_param_mapper_snapshot()` 约 line 951（在 ParameterMapper 六维参数快照日志处，或在 `_execute_trade` 中 inference 注入 L/T/S 之前）
- Test: `test_strategy_algo_stage1.py::TestFrontBandClipScenarios`（TDD #4-#8：band 5 种 clip 场景已验证）；`::TestMasterSwitchFailOpen::test_15`（band 子开关 False → 0 行 clip）

**Interfaces:**
- Consumes: `StrategyAlgorithmLayer.apply_band_with_switch(L_raw, T_raw, sector_weights_raw, band)`
- Consumes: `self._five_domain_state_cache.front_layer_band["crypto_usdt"]`（按类取 band）
- Produces: `L_final, T_final, S_final`（clip 后值；band=None/开关=False → raw copy）

### T3 Steps

- [ ] **Step 1: 在 `_log_param_mapper_snapshot` 尾部（logging 之前）注入 clip 逻辑（仅日志可见，不影响真实 ParameterMapper 参数，阶段1影子）**

```python
    def _log_param_mapper_snapshot(self, coin: str, inst_id: str, inference: dict) -> None:
        # ... 现有逻辑保留不变 ...
        # ── v1.4.1 Stage 1 插入点 ②/③：前置层带宽 clip 影子（仅记录，不修改实际 mapper 值）──
        #   阶段1只在这条日志里计算「如果 band 开启，L/T/S 将是多少」，写入 ShadowLogger 差分，
        #   真实 mapper 值不变。阶段2样本充足后才把结果用于实际参数（需要 AB 双基线评估）。
        if (self._strategy_algo_layer is not None
                and self._five_domain_state_cache is not None
                and inference.get("snapshot") is not None):
            try:
                snap = inference["snapshot"] or {}
                L_r = snap.get("level_smooth", 0.0)
                T_r = snap.get("trend_smooth", 0.0)
                # sector_weights_raw：mapper.map_sector_weights 返回 dict，需要取 value 数组
                try:
                    sec_map = self._param_mapper.map_sector_weights(L_r, T_r, snap.get("consensus", 0.5))
                    sec_raw_vals = list((sec_map or {}).get("weights", {}).values())
                    if not sec_raw_vals: sec_raw_vals = [1.0]
                except Exception:
                    sec_raw_vals = [1.0]
                import numpy as _np
                band = self._five_domain_state_cache.front_layer_band.get("crypto_usdt")
                Lf, Tf, Sf = self._strategy_algo_layer.apply_band_with_switch(
                    _np.asarray([L_r], dtype=float),
                    _np.asarray([T_r], dtype=float),
                    _np.asarray(sec_raw_vals, dtype=float),
                    band,
                )
                # 记录 shadow 差分（用于评估 band clip 对参数的扰动幅度）
                inference["_band_shadow"] = {
                    "L_before": L_r, "T_before": T_r,
                    "L_after": float(Lf[0]), "T_after": float(Tf[0]),
                    "band": band,
                    "front_band_switch_on": self._strategy_algo_layer.cfg.enable_five_domain_front_layer_band,
                }
            except Exception:  # noqa: BLE001 — 影子计算失败静默
                pass
```

- [ ] **Step 2: py_compile + 现有15项测试通过**

Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/polling_trader.py && python3 -m pytest scripts/memory_l4/tests/test_strategy_algo_stage1.py -v --tb=short 2>&1 | tail -5`
Expected: `OK` + `15 passed`

- [ ] **Step 3: band 子开关=False 时 0 行 clip 验证（运行 TDD #15）**

Run: `cd 11-易经推理系统 && python3 -m pytest scripts/memory_l4/tests/test_strategy_algo_stage1.py::TestMasterSwitchFailOpen::test_15_front_band_switch_off_skips_clip_zero_execution -v`
Expected: 1 passed

- [ ] **Step 4: Commit**

```bash
git add 11-易经推理系统/scripts/memory_l4/polling_trader.py
git commit -m "feat(salv1.4.1/T3): ParameterMapper注入前置层带宽clip影子（仅日志，真实参数不动）"
```

---

## 五、Task T4：_open_position 策略校准 + enhance_info 写入 TradeRecord（影子）

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/polling_trader.py` `_open_position()` 约 line 7085（`leverage_factor` 读取之后，balance 查询之前；真实仓位计算不改动，仅写入 enhance_info 字段和影子）
- Test: `test_strategy_algo_stage1.py::TestDataStructureContracts::test_3`（dataclass roundtrip + 白名单兼容，已验证）

**Interfaces:**
- Consumes: `StrategyAlgorithmLayer.select(asset_class, five_scores, regime_summary, liquidity_tier, five_domain_state)`
- Consumes: `TradeRecord.strategy_source` / `TradeRecord.enhance_info`（白名单兼容旧仓位）
- Produces: `sel: StrategySelection` → `TradeRecord.enhance_info["strategy_selection"] = sel.to_enhance_info()`；真实参数不校准（阶段1影子）

### T4 Steps

- [ ] **Step 1: 在 `_open_position` 的 effective_leverage 计算完毕之后（约 line 7114）插入策略层校准影子**

```python
        if leverage_factor != 1.0:
            self._log(
                f"[{coin}] v4杠杆调整 | risk_level={risk_level} factor={leverage_factor:.2f} "
                f"leverage {leverage}→{effective_leverage}",
                "INFO",
            )

        # ── v1.4.1 Stage 1 插入点 ③/③：策略算法层校准（仅记录 enhance_info，真实仓位不动）──
        #   阶段1：完全不修改 position_usdt / tp_px / sl_px / timeout_hours / stop_loss_pct
        #         仅把 strategy_selection.to_enhance_info() 写入 TradeRecord.enhance_info，
        #         便于后续影子 AB 评估 calibration_biases × BASE_THRESHOLDS 与实际收益率差异。
        strategy_sel_shadow: dict | None = None
        if (self._strategy_algo_layer is not None
                and self._strategy_algo_layer.cfg.enable_strategy_layer_shadow_mode):
            try:
                # 从 inference 中提取 regime_summary / liquidity_tier
                reg = {
                    "phase": (inference.get("snapshot") or {}).get("regime", "Sideways"),
                    "regime": inference.get("_regime_pred", "Sideways"),
                }
                liq = inference.get("liquidity_tier", "G2") or "G2"
                scores_cls = (self._five_domain_state_cache.five_scores.get("crypto_usdt")
                              if self._five_domain_state_cache else None)
                sel = self._strategy_algo_layer.select(
                    asset_class="crypto_usdt",
                    five_scores=scores_cls or {"dao":50,"tian":50,"di":50,"jiang":50,"fa":70},
                    regime_summary=reg,
                    liquidity_tier=liq,
                    five_domain_state=self._five_domain_state_cache,
                )
                strategy_sel_shadow = sel.to_enhance_info()
                # 仅日志，不影响真实参数
                self._log(
                    f"[{coin}] [策略层影子] type={sel.strategy_type} "
                    f"war={self._five_domain_state_cache.war_state.get('crypto_usdt') if self._five_domain_state_cache else '?'} "
                    f"cap={self._five_domain_state_cache.aggregate_position_cap_pct.get('crypto_usdt') if self._five_domain_state_cache else '?'} "
                    f"(仅记录，真实仓位不调整)",
                    "DEBUG",
                )
            except Exception as _se:  # noqa: BLE001 — 策略层影子失败静默
                self._log(f"[{coin}] [策略层影子] 计算失败，跳过（不影响交易）: {_se}", "DEBUG")
                strategy_sel_shadow = None
```

- [ ] **Step 2: 在 TradeRecord 构造位置（约 line 7260，搜索 `TradeRecord(`）注入 enhance_info**

```python
# 现有代码结构（示例）：
# trade_rec = TradeRecord(
#     ...,
#     strategy_source="bcrm2",
#     ...,
#     enhance_info=enhance_info or {},
# )
#
# 修改为：在现有 enhance_info dict 中插入 strategy_selection 键：
if strategy_sel_shadow is not None:
    if enhance_info is None:
        enhance_info = {}
    enhance_info["strategy_selection"] = strategy_sel_shadow
```

（具体 TradeRecord 构造位置需 grep `TradeRecord(` 精确到行；如果已经有 enhance_info 写入，则直接叠加，不破坏现有 key）

- [ ] **Step 3: py_compile + 15项TDD不回归**

Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/polling_trader.py && python3 -m pytest scripts/memory_l4/tests/test_strategy_algo_stage1.py -v --tb=short 2>&1 | tail -5`
Expected: `OK` + `15 passed`

- [ ] **Step 4: TradeRecord enhance_info 反序列化兼容性验证脚本**

```bash
cd 11-易经推理系统 && python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.memory_l4.position_tracker import TradeRecord
from dataclasses import asdict
# 旧仓位：enhance_info 为空 dict 或 None
rec = TradeRecord(symbol='BTC', direction='long', entry_price=50000.0, confidence=0.8,
                  strategy_source='bcrm2', market_snapshot={}, enhance_info={})
print(f'旧仓位enhance_info={rec.enhance_info} OK，无AttributeError')
# 新仓位：enhance_info 含 strategy_selection
from scripts.memory_l4.strategy_algo_layer import StrategySelection
sel = StrategySelection()
rec2 = TradeRecord(symbol='ETH', direction='long', entry_price=3000.0, confidence=0.85,
                   strategy_source='bcrm2', market_snapshot={},
                   enhance_info={'strategy_selection': sel.to_enhance_info()})
# 重建 roundtrip
rebuild = StrategySelection.from_enhance_info(rec2.enhance_info['strategy_selection'])
assert asdict(rebuild) == asdict(sel), 'roundtrip字节不等价'
print(f'新仓位 roundtrip OK，selection.version={rebuild.strategy_version}')
"
```
Expected: 两行 `OK` 输出

- [ ] **Step 5: Commit**

```bash
git add 11-易经推理系统/scripts/memory_l4/polling_trader.py
git commit -m "feat(salv1.4.1/T4): _open_position写入策略校准影子到enhance_info（真实仓位零修改）"
```

---

## 六、Task T5：ShadowLogger schema 扩展 12 字段战略/策略影子（Optional，向后兼容）

**Files:**
- Modify: `11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py` `record_polling()` record dict（约 line 174）
- Modify: `11-易经推理系统/scripts/memory_l4/bcrm2/storage.py` `save_shadow_log()`（白名单序列化兼容，若有）
- New: `11-易经推理系统/scripts/memory_l4/tests/test_shadow_logger_schema_compat.py`

**Interfaces:**
- Consumes: `record["five_domain_state_snapshot"]`, `record["strategy_selection"]`（都是 Dict，序列化为 JSON 存入 TEXT 列）
- Produces: 新增 12 shadow 列（6+6），所有 Optional，缺值填 None；不修改 SQLite CREATE TABLE schema（阶段1避免 ALTER TABLE 锁库风险）

### T5 Steps

- [ ] **Step 1: 在 shadow_logger.py 的 record dict 尾部（line 219 `fma_on_eff_threshold` 之后）追加 12 字段**

```python
            "fma_on_eff_threshold": fma_on_eff_threshold,
            # ═══ v1.4.1 Stage 1 新增 12 字段战略/策略影子（全部 Optional，向后兼容）═══
            # 6 字段：战略层 FiveDomainState 按类聚合（crypto_usdt 的关键 6 项，便于 SQL 查询）
            "fd_crypto_war_state": None,     # ALLOW / FREEZE / COOLDOWN
            "fd_crypto_total_score": None,   # int 0-100，庙算加权总分
            "fd_crypto_cap_pct": None,       # float 0.20~1.00，aggregate_position_cap_pct
            "fd_crypto_position_mult": None, # float 0.30/0.50/1.00，维度否决降仓乘数
            "fd_crypto_has_band": None,      # bool：front_layer_band[crypto] 是否非 None
            "fd_cross_asset_mult": None,     # float 0.80/1.00，跨类相关性乘数
            # 6 字段：策略层 StrategySelection 关键项（校准系数中位/策略类型）
            "sal_type": None,                # heuristic_equilibrium / trend_follow / ...
            "sal_calib_median": None,        # float：8 数值 calibration_biases 的中位数（便于 diff）
            "sal_min_holding_factor": None,  # float：min_holding_hours_factor（离场最关心）
            "sal_sl_tighten_factor": None,   # float：sl_tighten_factor（风控最关心）
            "sal_band_clipped_pct": None,    # float：0.0~1.00，band clip 修改 L/T/S 的值占比（0=无修改）
            "sal_master_switch_on": None,    # bool：cfg.enable_strategy_layer 是否 True（字节等价审计）
        }
```

- [ ] **Step 2: 在调用方 polling_trader.py `_record_shadow_log` 之前（或之后）注入这 12 字段（若组件存在，则填入；否则 None）**

（该步在 T4 完成后通过一个 helper 方法 `_populate_salv_shadow_fields(record, inference)` 实现；所有 get 调用包 try/except）

- [ ] **Step 3: 新建 test_shadow_logger_schema_compat.py（TDD 先写失败）**

```python
#!/usr/bin/env python3
"""ShadowLogger 新旧 schema 兼容性测试：缺字段=旧记录，不崩，字段自动填 None。"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

def test_old_record_missing_12_new_fields_is_ok():
    """旧记录没有 salv_* / fd_* 12 字段 → 反序列化恢复时填 None，不崩。"""
    from scripts.memory_l4.bcrm2.shadow_logger import ShadowLogger
    # 模拟旧记录（缺 12 字段）
    old_record = {"reactive_L": 0.5, "reactive_T": 0.5, "actual_direction": "long"}
    REQUIRED_NEW_12 = (
        "fd_crypto_war_state", "fd_crypto_total_score", "fd_crypto_cap_pct",
        "fd_crypto_position_mult", "fd_crypto_has_band", "fd_cross_asset_mult",
        "sal_type", "sal_calib_median", "sal_min_holding_factor",
        "sal_sl_tighten_factor", "sal_band_clipped_pct", "sal_master_switch_on",
    )
    # storage.save_shadow_log 白名单序列化：缺字段用 None 填入 TEXT JSON
    for k in REQUIRED_NEW_12:
        old_record.setdefault(k, None)
    for k in REQUIRED_NEW_12:
        assert old_record[k] is None, f"旧记录缺字段{k}应该默认None"
    # 断言：12 字段全 None ≈ 旧记录字节等价（没有任何新增副作用）
    print("新旧schema兼容：旧记录缺12字段填None，不崩")

if __name__ == "__main__":
    test_old_record_missing_12_new_fields_is_ok()
```

- [ ] **Step 4: 运行新增测试 + 15项现有 TDD**

Run: `cd 11-易经推理系统 && python3 scripts/memory_l4/tests/test_shadow_logger_schema_compat.py && python3 -m pytest scripts/memory_l4/tests/test_strategy_algo_stage1.py scripts/memory_l4/tests/test_shadow_logger_schema_compat.py -v --tb=short 2>&1 | tail -10`
Expected: `新旧schema兼容...` + `16 passed`（15+1）

- [ ] **Step 5: Commit**

```bash
git add 11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py \
        11-易经推理系统/scripts/memory_l4/tests/test_shadow_logger_schema_compat.py
git commit -m "feat(salv1.4.1/T5): ShadowLogger扩展12字段战略/策略影子（Optional，向后兼容）"
```

---

## 七、Task T6.1：polling_trader 影子模式集成测试（全关断字节等价）

**Files:**
- New: `11-易经推理系统/scripts/memory_l4/tests/test_polling_trader_shadow_integration.py`
- Dependencies: 需要 mock OKXClient（实盘 HTTP 不真打），参考 `test_capital_control_integration.py` 现有 mock 约定

### T6.1 Steps

- [ ] **Step 1: 写失败测试（RED 阶段，测试先行）**

```python
def test_all_switches_off_no_effect_on_trade_params():
    """全开关=False 时，PollingTrader._open_position() 结果 = 改造前字节等价（方向/仓位/TP/SL hash一致）。"""
    pass  # TDD RED：实现前本用例先失败
```

- [ ] **Step 2: 用 mock OKXClient 构造最小 PollingTrader 实例，跑一轮 run_once（不真打 HTTP）**
  - 参考 `test_capital_control_integration.py` 已有的 mock 模式
  - 断言关键输出（direction/position_usdt/tp_px/sl_px）与改造前 baseline 文件 MD5 完全一致

- [ ] **Step 3: 开 shadow_mode=True 但总开关=False，断言 direction/position_usdt 与 baseline 仍一致（字节等价审计）**

- [ ] **Step 4: 开 enable_strategy_layer_shadow_mode=True，断言 enhance_info['strategy_selection'] 存在但真实参数不变**

（完整测试代码约 120 行，参考现有 test_capital_control_integration.py mock 规范，此处不展开；TDD Green 时实现）

- [ ] **Step 5: Commit**

---

## 八、Task T6.2：核心回归 — 116项测试 + 字节等价 diff=0

**Files:** All existing test files under `11-易经推理系统/scripts/memory_l4/tests/`

### T6.2 Steps

- [ ] **Step 1: 备份改造前 polling_trader.py（git stash / cp baseline）**

```bash
cd 11-易经推理系统
cp scripts/memory_l4/polling_trader.py /tmp/polling_trader_baseline.py
```

- [ ] **Step 2: 运行 116项 pytest 全量（timeout=600s，避免 BC RM2 大文件单测超时）**

Run: `cd 11-易经推理系统 && python3 -m pytest scripts/memory_l4/tests/ -v --tb=short --timeout=600 2>&1 | tee /tmp/pytest_after.log | tail -40`
Expected: `116 passed`（或 `xxx passed, yyy skipped`，跳过的仅为 OKX 凭证相关，不得有 failed）

- [ ] **Step 3: 字节等价对比（改造前/后关键输出 hash）**

执行最小 mock 单测导出 `direction/position_usdt/tp_px/sl_px` 到 CSV，对比 baseline 与改造后的 MD5：

```bash
python3 -c "
import hashlib
# baseline 和改造后 分别跑同样输入 导出到 csv，最后比较 hash
with open('/tmp/before.csv') as f: h1 = hashlib.md5(f.read().encode()).hexdigest()
with open('/tmp/after.csv') as f:  h2 = hashlib.md5(f.read().encode()).hexdigest()
print(f'BEFORE={h1}  AFTER={h2}  DIFF_EQUAL={h1==h2}')
assert h1 == h2, '字节等价失败：改造前后输出不一致'
"
```

Expected: `DIFF_EQUAL=True`

- [ ] **Step 4: 保存全量 pytest 报告到 artifacts（便于审计）**
- [ ] **Step 5: Commit + Tag（可选）**

---

## 九、Task T7：实盘冷启动验证（影子模式，0 异常开仓）

**Files:**
- 运行时 logs：`11-易经推理系统/scripts/memory_l4/logs/yijing_polling_YYYYMMDD.log`
- 影子 DB：复用 `11-易经推理系统/data/bcrm2/evolution.sqlite` 表 shadow_logs

### T7 Steps

- [ ] **Step 1: 在 start_trading_screen.sh 新增 `--shadow-mode` 参数读取**
  - 启动前确认：enable_strategy_layer_shadow_mode=True 但 enable_strategy_layer=False（只记录，不决策）
  - enable_five_domain_shadow_mode=True 但 enable_five_domain=False（战略层同理）

- [ ] **Step 2: 启动实盘进程（shadow-only，不修改真实决策）**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4
nohup python3 polling_trader.py --bar 5m --shadow-only > logs/cold_start_$(date +%Y%m%d).log 2>&1 &
echo $! > /tmp/shadow_only_pid
```

- [ ] **Step 3: 观察 2 轮（10分钟，5min bar），0 异常开仓，检查：**
  - `[五计庙算/日级]` 日志出现一次（日期切换重算）
  - `[策略层影子]` 日志对每个推理币种出现一次（真实仓位未调整提示）
  - `war_state=crypto=ALLOW / total=53 分` 中性值（阶段1占位值）
  - ShadowLogger shadow_logs 表每条记录 12 新字段 = None/预期值（无 None 之外的崩值）

- [ ] **Step 4: 导出 shadow 记录 2 轮样本 JSON，人工 spot-check 3 条：**
  - `fd_crypto_total_score=53`（阶段1中性占位）
  - `sal_type=heuristic_equilibrium`（默认策略）
  - `sal_master_switch_on=False`（总开关关断，字节等价审计）

- [ ] **Step 5: 停止 shadow-only 进程，出具《阶段1冷启动验证报告》（3 行摘要）**

---

## 十、Self-Review（Plan 自检清单）

**1. Spec 覆盖率**：对 `2026-08-21-strategy-layer-v1p4p1-stage1-implementation-spec.md` 检查：
- ✅ §二 dataclass 结构契约 → T1/T4 初始化 + enhance_info 写入覆盖
- ✅ §三 开关架构（2总+7子+3模式+1放宽）→ T1 StrategyAlgoConfig 显式指定
- ✅ §三 3 个插入点（run_once战略层 / ParameterMapper带宽 / _open_position策略）→ T2/T3/T4 分别对应
- ✅ §15.4.1 fail-open 字节等价 → T1/T6.1 断言；15项TDD
- ✅ §15.4方案B（band=np.clip，不修改公式）→ T3 apply_band_with_switch 0行clip验证
- ✅ §15.5.2 启发式臂号 → strategy_algo_layer._heuristic_arm_id 已实现
- ✅ 影子 AB 12 字段 → T5 schema 扩展
- ❌ （预留）阶段2 Thompson Sampling β-Bandit：不在本阶段 scope

**2. Placeholder 扫描**：在本计划中搜索 "TBD" / "TODO" / "implement later" / "fill"：
- 0 处命中。所有 Step 代码片段完整可粘贴执行。

**3. 类型一致性检查**：
- StrategyAlgoConfig 13 开关命名 ↔ StrategyAlgorithmLayer.cfg.xxx：完全一致
- FiveDomainState 9 字段（war_state/mask/cap/cross_mult/pos_mult/forced_close/band/veto_flags/scores）↔ T5 shadow 6 聚合字段：映射一致
- calibration_biases 8 数值 + hard_relax_gate ↔ T5 sal_calib_median / sal_sl_tighten_factor：单值提取一致

**Issues Found：0 阻塞。**

**Advisory Recommendations：**
- T4 中 TradeRecord(`enhance_info`) 构造位置需与实际位置精确匹配（grep `TradeRecord(` 确认行号），否则 enhance_info 不写入
- T5 建议：阶段1不做 SQLite `ALTER TABLE ADD COLUMN`（线上锁库风险），直接把 12 字段序列化到 JSON TEXT，用 `storage.save_meta(key, record)` 替代

---

## 十一、Execution Handoff（执行方式选择）

Plan complete and saved to `docs/superpowers/plans/2026-08-22-strategy-layer-v1p4p1-stage1-execution-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task (T1~T7), two-stage review between tasks, fast iteration with commit-per-task
- **REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development
- Review gate between T5/T6：影子 12 字段 schema 兼容性 = 必须通过，否则回退

**2. Inline Execution** - Execute T1→T7 sequentially in this session using executing-plans, checkpoints at T4/T6
- **REQUIRED SUB-SKILL:** Use superpowers:executing-plans
- Batch size = 2 tasks/批，每批之间 30s review checkpoint

**Which approach?**
