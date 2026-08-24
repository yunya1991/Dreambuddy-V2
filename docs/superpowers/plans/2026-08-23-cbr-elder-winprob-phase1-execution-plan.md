# CBR 双闭环 + Elder-ray 影子 + 盈亏因子旁路 Phase1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在零侵入实盘交易链路的前提下，将 CBR 双时点案例建库（P0）、Elder-ray 日线观察器影子记录（P1）、CBR KNN Z-Score+五维权重框架（P2）、盈亏因子旁路框架（P3）同步接入 polling_trader.py。四者全部 gated by 独立开关（默认全 False），关断时字节等价改造前；异常→fail-open 中性旁路，绝不阻塞真实开/平仓主流程。Phase1 只记录/搭框架，不介入任何仓位参数（elder_multiplier 恒=1.00，win_prob_factor 恒=1.00，见 G5 红线）。

**Phase Scope（与 Spec §九 对应）:**
- ✅ P0：CBR 双时点建库（entry_snapshot 开仓写入 + exit_snapshot 离场补全，仅入库不检索不预测）
- ✅ P1：Elder-ray 影子模式（5 字段记录 + 3 持仓预警标签写入 enhance_info，不介入仓位）
- ✅ P2：CBR Z-Score 标准化 + 五维权重 TopK 框架（仅实现接口+单测，主链路不调用，等待样本≥50）
- ✅ P3：盈亏因子旁路框架（含所有 gate 条件 + clip 硬边界实现，仅单测验证；sample<30 时强制旁路=1.0 符合 §4.4）
- ❌ Phase2 / Phase3：留待样本量达标 + 影子冷启动验证通过后，由下一份实施计划覆盖（包含 elder_multiplier 实盘介入、KNN 预测进入乘法链等）

**Tech Stack:** Python 3.12+（原生 dataclass / fcntl 文件锁 / json），复用 SQLite 仅作预留（JSONL 起步=G3），无新增第三方依赖。测试框架 pytest 8.4+（复用项目现有配置）。

**Estimated Effort:** 5-7 工作日 / 8 个 Task / ~525 行新增代码 / 47 项新增测试用例 / 1 次 shadow-mode 冷启动验证（8 项指标）。

---

## Global Constraints（任何 Task 违反即视为验收不通过）

| 编号 | 约束内容（必须在代码中写注释 + 对应单测覆盖） |
|---|---|
| **G1** | 三个进程级开关默认 **全 False**：`enable_cbr_cycle_log=False`、`enable_elder_ray_c4=False`、`enable_win_prob_factor=False`；开/关断两种状态下，direction / confidence / position_usdt 三项输出必须字节等价（开关为 False 时完全不进入分支，组件引用=None） |
| **G2** | 所有主链路插入点（`_open_position` / `_close_position_reduce` / `_monitor_holdings` 每小时刷新）**必须 wrap 顶层 try/except**：catch 后只打印 WARN 级日志 + 返回中性旁路（CBR 跳过写入 / Elder 返回 1.00 / WinProb 返回 1.00），**绝不抛异常到主流程**（与 CapitalControl 同构 fail-open） |
| **G3** | CBREngine JSONL 写入使用 `fcntl.flock(fd, LOCK_EX | LOCK_NB)` 非阻塞独占锁，超时 0.1s；锁获取失败→WARN 日志→直接返回（等下轮重试），绝不使用阻塞锁卡主流程（5 分钟热路径不能因 IO 锁等待超过 1s） |
| **G4** | Elder-ray 日线缓存 TTL=86400s（24h，符合 Spec E3 红线≥12h）；同 symbol 4H 主周期内**绝不重复请求 OKX 日线 K 线**（key=`d_elder_ray_cache_{symbol}`，过期+新触发才拉）；拉取失败 / 计算异常 → fail-open：judge_level=NEUTRAL，multiplier=1.00（Spec F5 / E2） |
| **G5** | **Phase1 强约束**：`elder_multiplier` 在乘法链中硬编码返回 1.00，仅把预测值写入 `enhance_info["elder_predicted_multiplier_phase1"]` 供 Phase2 验证，**绝不实际参与乘法运算**；`win_prob_factor` 在 Phase1 同理返回 1.00，仅记录 `win_prob_factor_predicted_phase1` 预测值——确保 Phase1 0 侵入（Spec §三.5 Phase1 默认启动=仅记录语义的硬化落地） |
| **G6** | CBR 双时点配对使用 `pre_case_id = f"case_{symbol}_{timestamp_hex8}"`（Spec §二.2.2.1）；离场补全时找不到 pre_case_id（历史存量仓位 / CBR 开关关闭时开的仓）**静默跳过，不抛 KeyError，仅打 DEBUG 级日志 1 条**，符合持仓恢复兼容 R1 红线 |
| **G7** | ShadowLogger 新增 8 个字段（5 Elder-ray + 3 标签）**全部 Optional[X] = None**，不修改任何旧字段类型或名称；现有 AB 基线评估脚本读取时，遇到 None 自动填默认值（不崩）。新增字段名统一前缀 `fd_` / `sal_` 同构命名规范（参考 shadow_logger.py 现有前缀惯例）——**具体命名在 T7 与现有前缀对齐后再确认** |
| **G8** | **字节等价验收红线（T8.2）**：三开关全=False 时，选取 `{BTC-USDT-SWAP 做多, COIN-USDT-SWAP 做空, GOLD-USDT-SWAP 做多}` 三个 symbol，用固定 4H K 线 fixture 跑 `PollingTrader.run_once()` → 输出的 direction、confidence、position_usdt、entry_price（若触发开仓）四项的哈希值必须与 `git stash` baseline（改造前）完全相等（diff=0），否则判定为非 0 侵入，不允许合入实盘 |

---

## 一、File Structure（文件责任边界）

| 文件 | 动作 | 新增代码行估计 | 对应 Task | 对应 Spec 章节 | 关键责任 |
|---|---|---|---|---|---|
| `11-易经推理系统/scripts/memory_l4/cbr_engine.py`（现有） | 追加 CBREngine 方法 + Z-Score/TopK 框架 | +145 行（T1 JSONL 80 + T5 KNN框架65） | T1 / T5 | §二 / §二.3 | JSONL 半写入/补全（Phase1） + Z-Score/五维权重/TopK（Phase2接口，单测验证） |
| `11-易经推理系统/scripts/memory_l4/elder_ray_engine.py`（新建） | 新建 ElderRayEngine 类 | +85 行 | T1（类定义）/ T4（调用） | §三 全部 | 三指标计算（EMA13/Bull/Bear）/ 五级判定 / 3×5 矩阵系数预测 / 日线缓存 / fail-open |
| `11-易经推理系统/scripts/memory_l4/win_prob_engine.py`（新建） | 新建 WinProbEngine 类 | +70 行 | T6 | §四 全部 | 类Kelly公式实现 / 4 档 gate 条件 / clip [0.5,1.5] 硬边界 / 预测准确率 EMA |
| `11-易经推理系统/scripts/memory_l4/polling_trader.py` | 插入 3 开关初始化 + 5 个插入点 | +145 行（T1初始化25 / T2开仓写入35 / T3离场补全30 / T4 Elder影子+标签55） | T1 / T2 / T3 / T4 / T6 | §五接入点 A/B/D/E/F | 初始化三个组件引用 / 开/离场快照写入 / 乘法链 elder×win_prob 旁路插入（1.00）/ 每小时标签刷新 |
| `11-易经推理系统/scripts/memory_l4/bcrm2/shadow_logger.py` | 扩展 8 个影子字段 | +10 行 | T7 | §五接入点 D | 新增字段兼容（全 Optional + None 默认） |
| 新建 `tests/test_cbr_jsonl_append.py` | TDD 批次1 | 10 项 | T1 | §二风险红线 C1-C3 | JSONL 格式正确 / 锁失败旁路 / 半写入→finalize 配对 / 异常不阻塞 |
| 新建 `tests/test_cbr_entry_snapshot.py` | TDD 批次2 | 5 项 | T2 | §二.2.2.1 表 | pre_case_id 格式 / 14 维特征存在 / 写入失败不影响 position_usdt |
| 新建 `tests/test_cbr_exit_finalize.py` | TDD 批次2 | 5 项 | T3 | §二.2.2.2 表 | 按 case_id 配对 / is_profit 准确性 / 缺 pre_case_id 不崩 / 重复 finalize 幂等 |
| 新建 `tests/test_elder_ray_shadow.py` | TDD 批次3 | 7 项 | T4 | §六 T4/T5/T11 | T4 三指标数值误差 / T5 斜率防噪 0.3% / T11 ALIGN_FULL 五级判定 + 缓存TTL |
| 新建 `tests/test_cbr_knn_std_weights.py` | TDD 批次4 | 8 项 | T5 | §六 T1/T2/T3 | T1 价格量纲压制 / T2 动量最高占比 / T3 ε 防除零 + 加权距离单调性 + TopK 反距离 |
| 新建 `tests/test_win_prob_factor.py` | TDD 批次5 | 7 项 | T6 | §六 T6-T10 | T6 sample<30 旁路 / T7 pred_acc<0.55 旁路 / T8 clip / T9 w 封顶 0.8 / T10 乘法链顺序 |
| 新建 `tests/test_shadow_logger_schema.py` | TDD 批次6 | 3 项 | T7 | §七 R1 红线 | 新字段存在 / 旧记录缺字段填默认 / 类型校验 |
| 新建 `tests/test_byte_equivalence_phase1.py` | TDD 批次6 | 2 项 | T8 | G8 红线 | 三开关全=False 时，三 symbol × baseline 哈希 diff=0 |
| 新建 `scripts/shadow_cold_start_phase1.sh` | T8.3 shell | ~40 行 | T8 | 实盘冷启动8项指标 | SIGSTOP 旧→shadow 启动2轮→SIGCONT→验 8 指标 |
| **合计** | 3 新建 .py + 3 修改 .py + 8 新建 test_*.py + 1 新建 .sh | **~525 行 + 47 项测试** | T1-T8 | 全覆盖 | |

---

## 二、Task T1：基础设施（三开关 + CBREngine JSONL + ElderRayEngine 类定义）

> **验收前置条件**：三开关默认 False 字节等价（G1）；CBREngine 锁失败旁路（G3）；Elder fail-open NEUTRAL（G4）。

### Files
- Modify: `11-易经推理系统/scripts/memory_l4/polling_trader.py`
  - 构造参数声明区：约 `__init__` 开头（对应现有 enable_mode_switch 同层位置，约 line 850-890 区间）
  - CLI argparse 区：约 line 8907（对应现有 --shadow-mode 相邻位置）
  - __init__ 组件初始化：约 line 820（_init_capital_control 之后，与 _init_five_domain_and_strategy_layer 同层）
- Modify: `11-易经推理系统/scripts/memory_l4/cbr_engine.py`（现有 CBRCase 模型已存在，追加 CBREngine JSONL 包装类）
- New: `11-易经推理系统/scripts/memory_l4/elder_ray_engine.py`
- New test: `tests/test_cbr_jsonl_append.py`（TDD batch1，先写测试跑红→再实现）

---

#### T1 Step 1（TDD Red）：先写 JSONL 测试跑红

- [ ] **1.1 新建 `tests/test_cbr_jsonl_append.py`，10 项用例：**

```
# 用例清单（每项单独 pytest 函数）：
C1: test_half_entry_snapshot_writes_valid_jsonl_line → 半条case读回字段类型正确
C2: test_finalize_by_case_id_updates_semi_entry → finalize 后 exit_snapshot + pnl 填对
C3: test_flock_contention_timeout_failopen → 模拟锁占用（手动flock）→ append 返回False不阻塞
C4: test_missing_case_id_finalize_skipped_silently → 找不到case_id → 不抛，返回False
C5: test_duplicate_finalize_is_idempotent → 同一case_id finalize两次 → 结果不变
C6: test_failopen_on_json_decode_error → 故意破坏一行JSON → 下一条能正常读/写（不崩）
C7: test_v03_schema_fields_are_canonical → 14 维 feature_5d 子键名与 Spec §2.2.1 表完全一致
C8: test_directory_auto_created_if_missing → runtime/ 不存在时，自动 mkdir -p（不抛 FileNotFound）
C9: test_max_lines_per_day_safe_with_rewrite → 一天 200 条时 _rewrite_all 耗时 < 0.5s（简单性能断言，防止后续超慢）
C10: test_byte_equivalent_when_engine_is_none → engine=None（开关=False）时，调用方任何操作不抛 AttributeError
```

Run: `cd 11-易经推理系统 && python3 -m pytest scripts/memory_l4/tests/test_cbr_jsonl_append.py -v --tb=short`
Expected（Red phase）: 10 FAILED（CBREngine 方法还没写）

---

#### T1 Step 2：实现 CBREngine JSONL 包装类（+80 行到 cbr_engine.py 末尾）

- [ ] **2.1 追加 CBREngine 到 `cbr_engine.py` 末尾：**

```python
# ================================================================
# Phase1: CBR JSONL 双时点建库引擎（仅写不读，G3 文件锁 + fail-open）
# 存储：runtime/cbr_cases_v03.jsonl（每行一条完整 JSON，UTF-8）
# 配对方式：开仓写 semi_entry（exit 占位 null）；离场按 case_id 全量读→内存更新→全量重写
# Phase2 迁移：后续调 migrate_jsonl_to_sqlite()（空壳预留，报错 NotImplementedError）
# ================================================================

from __future__ import annotations

import fcntl
import json
import time
import tempfile
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


_JSONL_LOCK_TIMEOUT_S = 0.1
_JSONL_SCHEMA_VERSION = "v0.3"


class CBREngine:
    """JSONL-based CBR case store. Phase1: only append/finalize; no retrieve()."""

    def __init__(self, runtime_dir: Optional[Path] = None, enable: bool = False):
        self.enable = enable
        if runtime_dir is None:
            runtime_dir = Path(__file__).resolve().parent / "runtime"
        self._runtime_dir: Path = runtime_dir
        self._jsonl_path: Path = self._runtime_dir / "cbr_cases_v03.jsonl"
        # G3: try mkdir; fail → enable=False (fail-open)
        try:
            self._runtime_dir.mkdir(parents=True, exist_ok=True)
            if not self._jsonl_path.exists():
                # touch with newline (avoid zero-byte first line confusion)
                self._jsonl_path.touch(mode=0o644, exist_ok=True)
        except Exception as _e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"[CBREngine] runtime_dir init failed, force disabled: {_e}"
            )
            self.enable = False

    # ──────────── internal helpers ────────────
    def _lock_ex_nb(self, fd: int) -> bool:
        """Non-blocking exclusive lock. Returns True if acquired."""
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _unlock(self, fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass

    # ──────────── public Phase1 APIs ────────────
    def append_entry_semi(self, case: Dict[str, Any]) -> bool:
        """Write a half-entry (exit_snapshot=None / pnl=None) to JSONL.

        case MUST contain keys:
            case_id, entry_snapshot (with feature_5d/ma_relation/hexagram etc.),
            asset_class, symbol, decision, confidence, create_ts
        Returns True if persisted, False if fail-open (caller should WARN).
        """
        if not self.enable:
            return False
        try:
            # C7 canonical schema: enforce v0.3 version tag + null exit placeholders
            record: Dict[str, Any] = {
                "schema": _JSONL_SCHEMA_VERSION,
                "case_id": case["case_id"],
                "symbol": case.get("symbol", ""),
                "asset_class": case.get("asset_class", ""),
                "entry_snapshot": case["entry_snapshot"],
                "exit_snapshot": None,
                "pnl_pct": None,
                "pnl_usdt": None,
                "is_profit": None,
                "create_ts": case.get("create_ts", int(time.time() * 1000)),
                "close_ts": None,
            }
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                if not self._lock_ex_nb(f.fileno()):
                    # G3: contention → skip this round (do NOT block)
                    return False
                try:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    self._unlock(f.fileno())
            return True
        except Exception:
            # G2 / C3: any anomaly → fail-open false, never raise
            return False

    def finalize_by_case_id(self, case_id: str, exit_snapshot: Dict[str, Any],
                            pnl_pct: Optional[float], pnl_usdt: Optional[float],
                            is_profit: Optional[bool]) -> bool:
        """Finalize a previously-written semi entry by case_id (read → update → rewrite).

        Missing case_id → silently False (G6). Idempotent: called twice with same values OK.
        """
        if not self.enable or not case_id:
            return False
        try:
            with open(self._jsonl_path, "r+", encoding="utf-8") as f:
                if not self._lock_ex_nb(f.fileno()):
                    return False
                try:
                    raw_lines: List[str] = f.readlines()
                    updated = False
                    new_lines: List[str] = []
                    for ln in raw_lines:
                        ln = ln.rstrip("\n")
                        if not ln:
                            continue
                        try:
                            rec = json.loads(ln)
                        except json.JSONDecodeError:
                            # C6: tolerate corrupt line, skip it (don't break rewrite)
                            new_lines.append(ln + "\n")
                            continue
                        if rec.get("case_id") == case_id:
                            rec["exit_snapshot"] = exit_snapshot
                            rec["pnl_pct"] = pnl_pct
                            rec["pnl_usdt"] = pnl_usdt
                            rec["is_profit"] = bool(is_profit) if is_profit is not None else None
                            rec["close_ts"] = int(time.time() * 1000)
                            updated = True
                        new_lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
                    if not updated:
                        # G6: missing case_id → silently return, no crash
                        return False
                    # atomic rewrite via temp + rename (avoid truncation on crash)
                    tmp_path = self._jsonl_path.with_suffix(".jsonl.tmp")
                    with open(tmp_path, "w", encoding="utf-8") as tf:
                        tf.writelines(new_lines)
                        tf.flush()
                        os.fsync(tf.fileno())
                    os.replace(tmp_path, self._jsonl_path)
                    return True
                finally:
                    self._unlock(f.fileno())
        except Exception:
            return False

    # ──────────── Phase2 reserved interface (empty shells) ────────────
    def retrieve_similar(self, query_vec: Dict[str, float], top_k: int = 5,
                         mu: Optional[Dict[str, float]] = None,
                         sigma: Optional[Dict[str, float]] = None):
        raise NotImplementedError("Phase2: call after migrate_jsonl_to_sqlite() or >= 50 samples.")

    def migrate_jsonl_to_sqlite(self, sqlite_path: Optional[Path] = None) -> int:
        raise NotImplementedError("Phase2: one-off migration script will be provided in next plan.")

# ──────────── 5D feature canonical keys (Spec §2.3.1 五维特征定义 → C7 校验) ────────────
# 用于 C7 test_canonical: key 列表必须与 Spec 表格子字段名逐字一致
CBR_CANONICAL_5D_KEYS: Dict[str, List[str]] = {
    "momentum": ["rsi_14", "macd_hist", "roc_5d", "roc_20d", "hexagram_confidence"],
    "ma_position": ["dist_sma20_pct", "dist_sma50_pct", "dist_sma200_pct", "ma20_50_gap_pct", "triple_ma_order"],
    "volatility": ["atr14_norm_pct", "atr14_20d_quantile", "bollinger_width_pct"],
    "volume": ["vol_20d_quantile", "vol_ma20_ratio"],
    "hexagram_meta": ["hexagram_risk_level", "conf_decision_align"],
}
```

- [ ] **2.2 py_compile 语法验证**
Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/cbr_engine.py && echo OK`
Expected: `OK`

- [ ] **2.3 跑 TDD 红→绿**
Run: `cd 11-易经推理系统 && python3 -m pytest scripts/memory_l4/tests/test_cbr_jsonl_append.py -v --tb=short`
Expected: **10 PASSED**（绿）

---

#### T1 Step 3：新建 ElderRayEngine 类（+85 行，elder_ray_engine.py）

- [ ] **3.1 新建 `scripts/memory_l4/elder_ray_engine.py`：**

```python
# ================================================================
# Elder-ray 日线观察器（Alexander Elder 1993 原典）
# Phase1: 仅 calc + 记录，multiplier 恒返回 1.00（G5 红线）
# Spec §三：架构定位 / 三重结构 / 五级判定 / 3×5 决策矩阵 / F1-F5 铁则
# ================================================================
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


EMA13_ALPHA = 2.0 / (13 + 1)  # ≈ 0.142857（Elder 原典固定，不可调）
SLOPE_NOISE_BPS_PCT = 0.003   # 0.3%/日 防噪阈值（Spec §三.2.1 v1.1 保留）
CACHE_TTL_MS = 86400 * 1000   # 24h（≥12h，Spec E3 红线建议上限）

# 3×5 决策矩阵（Spec §3.3 表，Phase1 multiplier_actual=1.00，只返回 predicted）
# row: P1 output ("STANDARD" / "WEAK" / "BLOCK")
# col: judge_level ("ALIGN_FULL" / "ALIGN_BASIC" / "NEUTRAL" / "DIVERGE_BASIC" / "DIVERGE_SEVERE")
# 值 = (multiplier_predicted, action_tag)
DECISION_MATRIX_3X5: Dict[str, Dict[str, Tuple[float, str]]] = {
    "STANDARD": {
        "ALIGN_FULL":       (1.15, "PREMIUM +15%"),
        "ALIGN_BASIC":      (1.00, "HOLD"),
        "NEUTRAL":          (1.00, "HOLD"),
        "DIVERGE_BASIC":    (0.70, "DOWNGRADE -30%"),
        "DIVERGE_SEVERE":   (0.55, "STRONG_DOWNGRADE -45%"),
    },
    "WEAK": {
        "ALIGN_FULL":       (0.80, "UPGRADE_TO_HALF_STANDARD (≠1.0, F2)"),
        "ALIGN_BASIC":      (0.40, "HOLD"),
        "NEUTRAL":          (0.40, "HOLD"),
        "DIVERGE_BASIC":    (0.30, "FURTHER_SHRINK_25%"),
        "DIVERGE_SEVERE":   (None, "DOWNGRADE_TO_BLOCK (F3 UNIQUE)"),  # None = 建议 BLOCK
    },
    # BLOCK row: F1 铁则，永远不推翻（此表用于 BLOCK 场景时调用方应直接跳过 Elder）
    "BLOCK": {
        "ALIGN_FULL": (None, "F1_RESPECT_BLOCK"),
        "ALIGN_BASIC": (None, "F1_RESPECT_BLOCK"),
        "NEUTRAL": (None, "F1_RESPECT_BLOCK"),
        "DIVERGE_BASIC": (None, "F1_RESPECT_BLOCK"),
        "DIVERGE_SEVERE": (None, "F1_RESPECT_BLOCK"),
    },
}


@dataclass
class ElderRayResult:
    slope_ema13_pct: float          # 斜率百分比/日（正=向上，负=向下），防噪前原始值
    bull_power: float               # High - EMA13
    bear_power: float               # Low - EMA13
    slope_state: str                # "SLOPE_UP" / "SLOPE_DOWN" / "SLOPE_NEUTRAL"
    judge_level: str                # 五级判定 ALIGN_FULL ~ DIVERGE_SEVERE
    multiplier_predicted: float     # 3×5 矩阵预测（仅记录，Phase1 不乘）
    multiplier_actual: float        # Phase1 强制 1.00（G5）
    action_tag: str                 # 矩阵动作标签（日志友好）
    bull_loss_control: bool = False # 做空持仓预警：Bull<0 = 多头失控
    bear_loss_control: bool = False # 做多持仓预警：Bear>0 = 空头失控
    both_weakening: bool = False    # 双方减弱 即将变盘
    fail_open_triggered: bool = False


class ElderRayEngine:
    """日线观察器。Phase1: fail-open + G4 TTL cache + G5 恒 1.00。"""

    def __init__(self, enable: bool = False):
        self.enable = enable
        self._cache: Dict[str, Tuple[int, ElderRayResult]] = {}  # key=(symbol,date) → (ts,result)

    # ──────── fail-open neutral（Spec F5/E2）────────
    def _neutral_result(self, reason: str = "") -> ElderRayResult:
        return ElderRayResult(
            slope_ema13_pct=0.0, bull_power=0.0, bear_power=0.0,
            slope_state="SLOPE_NEUTRAL", judge_level="NEUTRAL",
            multiplier_predicted=1.0, multiplier_actual=1.0,
            action_tag=f"FAIL_OPEN_NEUTRAL: {reason}",
            fail_open_triggered=True,
        )

    # ──────── 核心计算 ────────
    @staticmethod
    def _calc_ema_bull_bear(daily_klines: List[Dict[str, float]]) -> Tuple[float, float, float, float]:
        """Return (ema13_curr, ema13_prev_day, bull, bear) from last 30+ daily bars.

        daily_klines = [{"o":..,"h":..,"l":..,"c":..}, ...] oldest first.
        Raises ValueError if len < 30 → caller handles → fail-open.
        """
        if len(daily_klines) < 30:
            raise ValueError(f"need >=30 daily bars, got {len(daily_klines)}")
        # convergence warmup: use first 28 for EMA burn-in, calc at index -2 and -1
        closes = [float(k["c"]) for k in daily_klines]
        ema = closes[-30]
        for i in range(-29, -2):  # 27 steps (burn to bar -3)
            ema = EMA13_ALPHA * closes[i] + (1.0 - EMA13_ALPHA) * ema
        ema_prev_2 = ema
        ema = EMA13_ALPHA * closes[-2] + (1.0 - EMA13_ALPHA) * ema
        ema_prev_day = ema  # 前1日 EMA（斜率 = (today - prev_day) / prev_day）
        ema_curr = EMA13_ALPHA * closes[-1] + (1.0 - EMA13_ALPHA) * ema
        bull = float(daily_klines[-1]["h"]) - ema_curr
        bear = float(daily_klines[-1]["l"]) - ema_curr
        return ema_curr, ema_prev_day, bull, bear

    @staticmethod
    def _slope_state(slope_pct: float) -> str:
        if slope_pct >= SLOPE_NOISE_BPS_PCT:
            return "SLOPE_UP"
        if slope_pct <= -SLOPE_NOISE_BPS_PCT:
            return "SLOPE_DOWN"
        return "SLOPE_NEUTRAL"

    @staticmethod
    def _detect_divergence_last_5(daily_klines: List[Dict[str, float]], bull: float, bear: float,
                                  ema_latest: float) -> Dict[str, bool]:
        """5日滚动窗口（Spec §3.2.3）。返回 {bearish_divergence, bullish_divergence, bull_desc_3d, bear_asc_3d}."""
        if len(daily_klines) < 5:
            return {"bearish": False, "bullish": False, "bull_desc_3d": False, "bear_asc_3d": False}
        last5 = daily_klines[-5:]
        highs = [float(k["h"]) for k in last5]
        lows = [float(k["l"]) for k in last5]
        # 近似 Bull/Bear 序列（用 EMA 近似=ema_latest，避免重算；误差不影响5日相对判断方向）
        bulls = [h - ema_latest for h in highs]
        bears = [l - ema_latest for l in lows]
        # 看跌背离：High 创新高（highs[-1]==max），但 Bull 没有创新高（bulls[-1] < max(bulls[:-1])）
        bearish = (highs[-1] >= max(highs[:-1])) and (bulls[-1] < max(bulls[:-1]))
        # 看涨背离：Low 创新低（lows[-1]==min），但 Bear 没有创新低（bears[-1] > min(bears[:-1])）
        bullish = (lows[-1] <= min(lows[:-1])) and (bears[-1] > min(bears[:-1]))
        # 双方减弱：Bull>0 连续 3 日下降；Bear<0 连续 3 日上升
        def _desc3(vals: List[float]) -> bool:
            return len(vals) >= 3 and vals[-1] < vals[-2] < vals[-3] and all(v > 0 for v in vals[-3:])
        def _asc3_negative(vals: List[float]) -> bool:
            return len(vals) >= 3 and vals[-1] > vals[-2] > vals[-3] and all(v < 0 for v in vals[-3:])
        return {
            "bearish": bool(bearish),
            "bullish": bool(bullish),
            "bull_desc_3d": _desc3(bulls),
            "bear_asc_3d": _asc3_negative(bears),
        }

    @staticmethod
    def _judge_5level(decision: str, slope_state: str, bull: float, bear: float,
                      div: Dict[str, bool]) -> str:
        """五级判定（Spec §3.2.4，做多示例对称取反 for 做空）。
        decision: "LONG" / "SHORT"（from BCRM core）。
        """
        if decision == "LONG":
            prem_ok = (slope_state == "SLOPE_UP")
            align_basic = (bear < 0) and (bull > 0)
            align_full_cond = prem_ok and align_basic and bool(div.get("bullish"))
            severe = (slope_state == "SLOPE_DOWN") and (bear > 0)  # 对手主控空
        else:  # SHORT
            prem_ok = (slope_state == "SLOPE_DOWN")
            align_basic = (bull > 0) and (bear < 0)
            align_full_cond = prem_ok and align_basic and bool(div.get("bearish"))
            severe = (slope_state == "SLOPE_UP") and (bull < 0)  # 对手主控多

        if severe:
            return "DIVERGE_SEVERE"
        if not prem_ok:
            # 前提不满足：最高到 ALIGN_BASIC（Spec §三.2.1 原典规则）
            if align_basic:
                return "ALIGN_BASIC"
            # 前提反但对手没失控
            if (decision == "LONG" and bull < 0) or (decision == "SHORT" and bear > 0):
                return "DIVERGE_BASIC"
            return "NEUTRAL"
        # prem_ok
        if align_full_cond:
            return "ALIGN_FULL"
        if align_basic:
            return "ALIGN_BASIC"
        if (decision == "LONG" and bull < 0) or (decision == "SHORT" and bear > 0):
            return "DIVERGE_BASIC"
        return "NEUTRAL"

    # ──────── 外部入口（供 polling_trader._open_position 调用）────────
    def calc_and_record(self, symbol: str, decision: str, p1_output: str,
                        daily_klines: Optional[List[Dict[str, float]]]) -> ElderRayResult:
        """
        decision: "LONG" / "SHORT"；p1_output: "STANDARD" / "WEAK" / "BLOCK"
        daily_klines=None → fail-open（G4）。返回 ElderRayResult。
        Phase1: multiplier_actual 恒 = 1.00（G5），只写 predicted 到日志。
        """
        if not self.enable:
            r = self._neutral_result("ENGINE_DISABLED")
            r.action_tag = "DISABLED_BYPASS_1.00"
            return r
        if p1_output == "BLOCK":  # F1 铁则：直接 neutral（调用方应已 BLOCK，但 Elder 也确保 multiplier=1.0）
            return self._neutral_result("F1_P1_BLOCK_RESPECTED")
        now = int(time.time() * 1000)
        cache_key = f"{symbol}::{time.strftime('%Y%m%d', time.localtime(now/1000))}"
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached[0]) < CACHE_TTL_MS:
            return cached[1]
        if daily_klines is None or len(daily_klines) < 30:
            r = self._neutral_result("NO_DAILY_KLINES_OR_TOO_SHORT")
        else:
            try:
                ema_curr, ema_prev_day, bull, bear = self._calc_ema_bull_bear(daily_klines)
                eps = 1e-9
                slope_pct = (ema_curr - ema_prev_day) / (abs(ema_prev_day) + eps)
                sst = self._slope_state(slope_pct)
                div = self._detect_divergence_last_5(daily_klines, bull, bear, ema_curr)
                level = self._judge_5level(decision, sst, bull, bear, div)
                mat = DECISION_MATRIX_3X5.get(p1_output, DECISION_MATRIX_3X5["STANDARD"]).get(
                    level, (1.0, "UNKNOWN_LEVEL_FALLBACK"))
                mult_pred, tag = mat
                if mult_pred is None:
                    mult_pred = 1.0  # BLOCK 场景（F3）：predicted 值用1占位，调用方看 tag 判定
                r = ElderRayResult(
                    slope_ema13_pct=round(slope_pct, 6),
                    bull_power=round(bull, 4),
                    bear_power=round(bear, 4),
                    slope_state=sst,
                    judge_level=level,
                    multiplier_predicted=mult_pred,
                    multiplier_actual=1.0,  # Phase1 G5 强制
                    action_tag=tag,
                    bull_loss_control=(bull < 0),
                    bear_loss_control=(bear > 0),
                    both_weakening=bool(div.get("bull_desc_3d") and div.get("bear_asc_3d")),
                    fail_open_triggered=False,
                )
            except Exception as _e:
                r = self._neutral_result(f"CALC_EXCEPTION:{type(_e).__name__}")
        self._cache[cache_key] = (now, r)
        return r
```

- [ ] **3.2 py_compile**
Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/elder_ray_engine.py && echo OK`
Expected: `OK`

---

#### T1 Step 4：三进程开关声明 + polling_trader.__init__ 初始化（≈25 行）

- [ ] **4.1 在 `polling_trader.py` 构造参数区（enable_mode_switch / enable_ev_radar 开关同层位置）加入 3 个开关：**

```python
# 建议约 line 858（enable_inject_runtime 之下，原 enable_strategy_layer 之上）：
self.enable_cbr_cycle_log = False       # P0 CBR 双时点建库（默认关，G1）
self.enable_elder_ray_c4 = False        # P1 Elder-ray 影子记录（默认关，G1）
self.enable_win_prob_factor = False     # P3 盈亏因子旁路框架（默认关，G1）
```

- [ ] **4.2 在 `__init__` 方法参数列表末尾、argparse 区域（约 line 8907，`--shadow-mode` 下方）新增 3 个 CLI flag：**

```python
# 注意：3 个 flag 对应赋值（和 enable_strategy_layer=True 那次改动同构，约 line 8962 对应构造调用传参处也一起传）
parser.add_argument("--enable-cbr-cycle-log", action="store_true", default=False,
                    help="Phase1: 启用CBR双时点JSONL建库（默认关闭，零侵入）")
parser.add_argument("--enable-elder-ray-c4", action="store_true", default=False,
                    help="Phase1: 启用Elder-ray日线观察器影子记录（默认关闭，零侵入）")
parser.add_argument("--enable-win-prob-factor", action="store_true", default=False,
                    help="Phase1: 启用盈亏因子旁路框架（默认关闭，零侵入）")

# 对应构造函数 __init__ 末尾（约 line 8963）新增参数 + 赋值：
# （实际传参：PollingTrader( ..., enable_cbr_cycle_log=args.enable_cbr_cycle_log,
#                               enable_elder_ray_c4=args.enable_elder_ray_c4,
#                               enable_win_prob_factor=args.enable_win_prob_factor, ...)
```

- [ ] **4.3 `__init__` 内 _init_five_domain_and_strategy_layer() 之后（约 line 870），新增 `_init_phase1_three_components()` 方法调用 + 定义：**

```python
# __init__ 末尾调用：
self._cbr_engine = None      # type: ignore[assignment]
self._elder_engine = None    # type: ignore[assignment]
self._win_prob_engine = None # type: ignore[assignment]
self._init_phase1_three_components()

# 新方法定义（和 _init_five_domain_... 同缩进级别，约 line 872）：
def _init_phase1_three_components(self):
    """Phase1: CBR建库 / Elder影子 / 盈亏旁路 初始化。G1 默认全关=字节等价；G2 异常降级=None。"""
    from pathlib import Path as _P
    try:
        # CBR Engine
        if self.enable_cbr_cycle_log:
            from scripts.memory_l4.cbr_engine import CBREngine as _CBRE
            self._cbr_engine = _CBRE(runtime_dir=_P(__file__).resolve().parent / "runtime", enable=True)
        # Elder Engine
        if self.enable_elder_ray_c4:
            from scripts.memory_l4.elder_ray_engine import ElderRayEngine as _ERE
            self._elder_engine = _ERE(enable=True)
        # WinProb Engine
        if self.enable_win_prob_factor:
            from scripts.memory_l4.win_prob_engine import WinProbEngine as _WPE
            self._win_prob_engine = _WPE(enable=True)
        # 字节等价断言：三开关全=False → 三属性均 None（G1）
        if not (self.enable_cbr_cycle_log or self.enable_elder_ray_c4 or self.enable_win_prob_factor):
            assert self._cbr_engine is None and self._elder_engine is None and self._win_prob_engine is None, (
                "G1红线：三开关全False时组件必须全None（字节等价），请检查初始化逻辑是否误构造。"
            )
        self._log("[Phase1] 三组件初始化 OK（全关=字节等价；开哪个有哪个）", "INFO")
    except Exception as _e:
        self._cbr_engine, self._elder_engine, self._win_prob_engine = None, None, None
        self._log(f"[Phase1] 初始化失败，强制降级全=None（字节等价）：{_e}", "WARN")
```

- [ ] **4.4 语法+冒烟**
Run: `cd 11-易经推理系统 && python3 -m py_compile scripts/memory_l4/polling_trader.py && echo OK`
Expected: `OK`
Run: `python3 -c "from scripts.memory_l4.elder_ray_engine import ElderRayEngine, DECISION_MATRIX_3X5; e=ElderRayEngine(enable=False); r=e.calc_and_record('BTC','LONG','STANDARD',None); print(r.multiplier_actual, r.fail_open_triggered)"`
Expected: `1.0 True`（G1+G4 fail-open 正确）

---

#### T1 Step 5：T1 小结 commit

- [ ] **Commit（小步）：**
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add 11-易经推理系统/scripts/memory_l4/cbr_engine.py \
        11-易经推理系统/scripts/memory_l4/elder_ray_engine.py \
        11-易经推理系统/scripts/memory_l4/polling_trader.py \
        11-易经推理系统/scripts/memory_l4/tests/test_cbr_jsonl_append.py
git commit -m "feat(phase1/T1): 基础设施——三开关初始化 + CBREngine JSONL + ElderRayEngine 类 + TDD 10项绿"
```

---

## 三、Task T2：P0 CBR entry_snapshot 开仓写入（_open_position 插入点 A）

> 对应 Spec §二.2.2.1 表 / §五接入点 A；插入点：形态乘数计算后、资金调控 cap 前（约 _open_position 内 line 7110，与 T1 初始化独立，不影响 baseline 逻辑）；TDD：先写 test_cbr_entry_snapshot.py 5 项。

### Files
- Modify: `polling_trader.py::_open_position()` 约 line 7110
- New test: `tests/test_cbr_entry_snapshot.py`（TDD batch2 Red first）

#### T2 Step 1（TDD Red）：先写测试跑红
- [ ] **1.1 新建 test_cbr_entry_snapshot.py（5 项）：**
  - E1: test_pre_case_id_format → `case_{symbol}_{8位hex timestamp}` 正则
  - E2: test_entry_snapshot_has_14dim_feature5d → feature_5d 下至少 14 键（Spec §2.3.1 五维合计子键数≥14）
  - E3: test_entry_snapshot_ma_relation_for_weak_resonance → BTC 真实弱共振场景下 ma_relation.ma20_50_gap_pct 字段存在
  - E4: test_cbr_write_failure_does_not_affect_position_usdt → engine=None（模拟写失败），position_usdt 与 baseline 完全相等（diff=0）
  - E5: test_enhance_info_carries_pre_case_id_snapshot → 开仓成功后，`TradeRecord.enhance_info["pre_case_id"]` 和 `["cbr_entry_snapshot"]` 两键同时存在且非空

Run（Red phase）: `pytest .../test_cbr_entry_snapshot.py` → Expected: 5 FAILED

#### T2 Step 2：实现插入点代码（≈35 行，_open_position 内）
- [ ] **2.1 插入代码片段（G2 try/except 全包）：**

```python
# 位置：morph_multiplier 计算完成（约 line 7110）之后、资金调控 cap（约 line 7126）之前：
# ── Phase1 / P0 CBR: entry_snapshot 写入（默认引擎=None 自动旁路，G1）──
try:
    if self._cbr_engine is not None:
        import time as _t, uuid as _u  # 实际用 timestamp_hex8 替代uuid
        _ts = _t.time()
        _ts_hex8 = f"{int(_ts*1000):08x}"[-8:]
        pre_case_id = f"case_{symbol.replace('-SWAP','').replace('-USDT','')}_{_ts_hex8}"
        # 组装 14 维 entry_snapshot（字段名与 Spec §2.2.1 表逐字一致 → 用 CBR_CANONICAL 对照）
        from scripts.memory_l4.cbr_engine import CBR_CANONICAL_5D_KEYS as _C5
        _feat5d: Dict[str, Any] = {}
        # 以下字段从后置层 / 核心层 / 技术指标层就近获取（实际变量名按现有技术指标函数填，以下为占位名）：
        _feat5d.update({k: v for k, v in {
            # momentum（5项）
            "rsi_14": self._indicators.get(symbol, {}).get("rsi_14", 0.0),
            "macd_hist": self._indicators.get(symbol, {}).get("macd_hist", 0.0),
            "roc_5d": self._roc(symbol, 5),  # 复用现有 _roc 或等价实现
            "roc_20d": self._roc(symbol, 20),
            "hexagram_confidence": core_confidence if 'core_confidence' in dir() else getattr(ctx, 'confidence', 0.0),
            # ma_position（5项）
            "dist_sma20_pct": (price - sma20) / (sma20+1e-9) if 'sma20' in dir() else 0.0,
            "dist_sma50_pct": (price - sma50) / (sma50+1e-9) if 'sma50' in dir() else 0.0,
            "dist_sma200_pct": (price - sma200) / (sma200+1e-9) if 'sma200' in dir() else 0.0,
            "ma20_50_gap_pct": abs(sma20 - sma50)/(sma50+1e-9) if all(v in dir() for v in ['sma20','sma50']) else 0.0,
            "triple_ma_order": (1 if sma20<sma50<sma200 else (-1 if sma20>sma50>sma200 else 0)) if all(v in dir() for v in ['sma20','sma50','sma200']) else 0,
            # volatility（3项）
            "atr14_norm_pct": atr14/(price+1e-9)*100 if 'atr14' in dir() else 0.0,
            "atr14_20d_quantile": self._atr_quantile_20d(symbol),
            "bollinger_width_pct": self._boll_width_pct(symbol),
            # volume（2项）
            "vol_20d_quantile": self._vol_quantile_20d(symbol),
            "vol_ma20_ratio": self._vol_div_ma20(symbol),
            # hexagram_meta（2项）
            "hexagram_risk_level": risk_level_num if 'risk_level_num' in dir() else 50,
            "conf_decision_align": (1.0 if (direction=="LONG" and core_confidence>=0.6) or (direction=="SHORT" and core_confidence>=0.6) else 0.0),
        }.items() if k in [s for sl in _C5.values() for s in sl]})
        entry_snap = {
            "regime": regime_label if 'regime_label' in dir() else "UNKNOWN",
            "decision": direction,
            "confidence": confidence,
            "volatility": _feat5d.get("atr14_norm_pct", 0.0),
            "feature_5d": _feat5d,
            "price_high_low": self._price_high_low_20d(symbol),
            "ma_relation": {
                "sma20_val": sma20 if 'sma20' in dir() else 0.0,
                "sma50_val": sma50 if 'sma50' in dir() else 0.0,
                "sma200_val": sma200 if 'sma200' in dir() else 0.0,
                "ma20_50_gap_pct": _feat5d.get("ma20_50_gap_pct", 0.0),
            },
            "hexagram": hexagram_name if 'hexagram_name' in dir() else "",
            "asset_class": self._resolve_asset_class(symbol),
            "capture_timestamp_ms": int(_ts * 1000),
        }
        case_record = {"case_id": pre_case_id, "symbol": symbol, **entry_snap}
        ok = self._cbr_engine.append_entry_semi(case_record)
        if ok:
            self._shadow_logger.add(pre_case_id=pre_case_id, elder_action_tag="CBR_ENTRY_OK")
        enhance_info["pre_case_id"] = pre_case_id
        enhance_info["cbr_entry_snapshot"] = entry_snap
        enhance_info["cbr_entry_wrote_ok"] = ok
except Exception as _e:
    # G2 红线：任何异常只 WARN，绝不影响 position_usdt 后续计算
    self._log(f"[Phase1/P0] CBR entry_snapshot 写入失败（已旁路）：{_e}", "WARN")
```

- [ ] **2.2 关键：占位变量名（sma20/sma50/atr14/roc 等）要对应 polling_trader 实际技术指标变量名**——先用 grep 确认再填：
  Run: `grep -n "sma20\|sma_20\|sma50\|sma_50\|atr14\|atr_14" 11-易经推理系统/scripts/memory_l4/polling_trader.py | head -30`
  根据 grep 结果把代码中的 `sma20` / `sma50` / `sma200` / `atr14` / `roc` / `price` 替换为实际变量名（若不存在，保留 0.0 中性兜底值，避免崩）。

#### T2 Step 3：TDD Green + 语法验证
- [ ] Run: `py_compile polling_trader.py` → OK
- [ ] Run: `pytest scripts/memory_l4/tests/test_cbr_entry_snapshot.py scripts/memory_l4/tests/test_cbr_jsonl_append.py -v --tb=short`
Expected: **5+10=15 全 PASSED**

#### T2 Step 4：Commit
`git add polling_trader.py tests/test_cbr_entry_snapshot.py && git commit -m "feat(phase1/T2/P0): CBR entry_snapshot 开仓写入插入点 + TDD 5项绿"`

---

## 四、Task T3：P0 CBR exit_snapshot 离场补全 + PnL 入库

> 对应 Spec §二.2.2.2 表 / §五接入点 B；插入点：position_tracker.close_position() 之后（约 _close_position_reduce line 6920）；G6：找不到 pre_case_id 静默跳过。

### Files
- Modify: `polling_trader.py::_close_position_reduce()` 约 line 6920
- New test: `tests/test_cbr_exit_finalize.py`（TDD batch2，5 项：配对/PnL/缺ID不崩/幂等/异常旁路）

#### T3 Step 1（TDD Red）：先写测试 5 项 → 跑红
#### T3 Step 2：实现插入点代码（≈30 行，G2 try/except）
```
（格式同 T2.2，读取 enhance_info["pre_case_id"]，组装 exit_snapshot：
exit_reason / max_drawdown / max_runup / hold_hours / pnl_pct / pnl_usdt / is_profit
→ 调 CBREngine.finalize_by_case_id()；找不到 pre_case_id → 跳过不抛 → G6）
```
#### T3 Step 3：TDD Green + commit

---

## 五、Task T4：P1 Elder-ray 影子记录 + 每小时持仓预警标签刷新

> 对应 Spec §三.5 Phase1 + §五接入点A/D + F4 铁则；**G5：multiplier_actual 强制 1.00，只记录 predicted**

### Files
- Modify: `_open_position`（插入 Elder 计算 + 写 enhance_info/shadow）+ `_monitor_holdings`（每小时刷新三标签）
- New test: `tests/test_elder_ray_shadow.py`（7 项：T4数值/T5防噪/T11判定 + 缓存TTL/日线不足30fail-open / BLOCK 不推翻 / WEAK×ALIGN_FULL=0.80 预测正确）
- TDD batch3

---

## 六、Task T5：P2 CBR Z-Score + 五维权重 TopK 框架（仅接口 + 单测，主链路不调用）

> 对应 Spec §二.3.1/.2/.3 + §六 T1/T2/T3；CBREngine 追加 3 方法 + 常量 WEIGHTS_5D

### Files
- Modify: `cbr_engine.py`（末尾追加 65 行）
- New test: `tests/test_cbr_knn_std_weights.py`（8 项：T1价格量纲压制/T2动量权重最高/T3 ε防除零 + 加权距离单调性 2 项 + TopK=3反距离加权 3 项）
- TDD batch4

---

## 七、Task T6：P3 盈亏因子旁路框架（4 gate + clip + Phase1 强制旁路 1.00）

> 对应 Spec §四 全部 + §六 T6-T10；G5：实际返回 1.00，仅记录预测值到 enhance_info

### Files
- New: `win_prob_engine.py`（70 行，§4.3 公式完整实现 + §4.4 四档 gate + §四.5 W1-W4 红线 clip + 日志边界 WARN）
- Modify: `_open_position()` 乘法链中（Elder 之后，strat_cap 之前）插入调用，**强制旁路=1.00（G5）**，写 enhance_info 预测值（不实际乘）
- New test: `tests/test_win_prob_factor.py`（7 项：T6 small<30 旁路 / T7 pred_acc<0.55 旁路 / T8 clip / T9 w封顶0.8 / T10 乘法链顺序 + sample≥100 w上限0.8 / N=30-100 w封顶0.5）
- TDD batch5

---

## 八、Task T7：ShadowLogger schema 扩展（8 字段，全 Optional）

> 对应 Spec §五接入点 D / §七 R1 红线

### Files
- Modify: `bcrm2/shadow_logger.py` ~L200，新增 8 字段：
  - sal_slope_ema13_pct / sal_bull_power / sal_bear_power / sal_judge_level / sal_multiplier_predicted（5 Elder）
  - sal_tag_bull_loss / sal_tag_bear_loss / sal_tag_both_weakening（3 预警标签，bool，默认False）
- New test: `tests/test_shadow_logger_schema_compat.py`（3 项：类型/缺字段默认=不崩/旧记录读取成功）
- **命名对齐确认**：前缀用 fd_（five-domain）还是 sal_（strategy-algo-layer）？先检查 shadow_logger.py 现有前缀命名惯例 → 与战略层/策略层字段前缀保持一致 → 若不一致再改。

---

## 九、Task T8：全局集成验证（冷启动 8 指标 + 字节等价 G8 红线）

> 8 项冷启动指标（实盘 shadow-mode 验证）参考项目 T7 冷启动惯例：exit_code=0 / ERROR=0 / consecutive_errors=0 / Guardian<300s / shadow-mode WARN BLOCKED-OPEN 条数=0 / CBR/ELDER INFO 级日志有输出 / shadow-mode真实下单计数=0 / byte_equiv_hash_diff=0

### Files
- New: `tests/test_byte_equivalence_phase1.py`（2 项：三 symbol × baseline 哈希 diff=0，G8 红线）
- New: `scripts/shadow_cold_start_phase1.sh`（SIGSTOP 旧进程 → shadow 启动 --interval=300 --confidence=0.7955 --shadow-mode --enable-cbr-cycle-log --enable-elder-ray-c4 --enable-win-prob-factor → 跑 2 轮 → SIGCONT 旧进程 → 打印 8 项 checklist pass/fail）
- TDD batch6

---

## 十、Verification Exit Criteria（Phase1 验收通过的全部必要条件）

| # | 检查项 | 执行方式 | 预期结果 |
|---|---|---|---|
| V1 | py_compile 四文件无语法错 | `py_compile polling_trader.py / cbr_engine.py / elder_ray_engine.py / win_prob_engine.py` | 4 OK |
| V2 | 47 项新增测试 **100% 通过**（0 FAIL/ERROR） | `pytest scripts/memory_l4/tests/test_cbr_*.py test_elder_ray_*.py test_win_prob_*.py test_shadow_logger_*.py test_byte_equivalence_*.py -v` | 47 PASSED，0 FAIL，覆盖率≥85%（pytest --cov 可选） |
| V3 | G8 字节等价（三开关=False）哈希对比 | `test_byte_equivalence_phase1.py::*` + git stash baseline | BTC/COIN/GOLD 三 symbol 的 direction/confidence/position_usdt 四值 HASH DIFF=0 |
| V4 | shadow-mode 冷启动 8 指标 | `bash scripts/shadow_cold_start_phase1.sh` | 8/8 PASS，真实下单=0，ERROR 级日志=0 |
| V5 | 实盘进程重启一次（SIGSTOP→shadow cold start→SIGCONT→平滑切换为新二进制） | 人工确认 + Guardian 心跳 | heartbeat < 300s，consecutive_errors=0 |
| V6 | Phase1 前 3 笔开仓后，JSONL 文件可解析 | `jq -c 'select(.schema=="v0.3")' runtime/cbr_cases_v03.jsonl \| wc -l` | ≥ 3 行且每行 exit_snapshot=null（半 entry 正常） |
| V7 | Phase1 前 3 笔触发离场后，is_profit 字段 bool 正确 | 手动调 CBREngine.finalize_by_case_id 模拟 → `jq '.is_profit'` | bool 类型（非 null）且与 pnl_usdt 正负一致 |
| V8 | Elder shadow_logger 8 字段类型正确 | `jq '.sal_slope_ema13_pct | type'` 等 8 项 | number/string/bool 与声明一致，缺字段自动 null（不抛） |

**V1-V8 全通过 → Phase1 验收完毕 → 启动 Phase2（CBR TopK + elder_multiplier 回测校准 + 盈亏因子实盘阈值校准）。**
