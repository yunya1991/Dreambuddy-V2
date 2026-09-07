# P1 · C1④ 三条信息截止护栏（odaily 基本面事件驱动）
**Date**: 2026-09-01 · **Author**: C1 Cognitive Component · **Scope**: 数据采集中心 odaily_newsflash.py + 易经推理 polling_trader.py（两文件，P0基础设施上的护栏夹）
**Goal**: 压吹票黑嘴 + 防未来函数 + 一周内（168h）信息截止 = 不绕过卦一致性硬门槛
**Fail-Open 铁律**：任何 DB / 导入 / 时间解析 / 公式越界异常 → 回退 baseline（Score_B=0.60cont+0.40conf / strength=0 / boost=0），绝不阻塞主循环

---

## §1. 三条护栏定义与生效位置（方案X·用户确认）

| 编号 | 名称 | 硬约束公式 | 存在位置（代码） | 生效位置（调用链·开仓前关键路径） |
|------|------|-----------|----------------|--------------------------------|
| G1 | 卦×0.70 + 0.85硬地板（**生产已永久生效**·不改） | **查表方向≠决策** → eff_conf = confidence × `lookup_conflict_conf_mult=0.70`<br>**再地板抬升** `max(eff_conf, 0.85)` > 开仓门槛0.7955 → 永远硬拦截<br>**查表+历史滑窗双一致反对** → block=True直接HOLD | `_check_hexagram_consistency_for_entry` [polling_trader.py#L4289-L4426](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L4289-L4426)（默认参数L4296/L4297） | P0-4 开仓前一致性段 [polling_trader.py#L9235-L9268](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L9235-L9268) |
| G2 | EV 门槛 > 0.05（掐弱正面·吹票新闻） | 算完boost后 **夹阈值**：<br>`if boost ≤ 0.050 → boost = 0 ; Score_B = baseline（0.60*cont+0.40*conf）`<br>仍保留P0原 `strength>0.35` 前置门槛 = **两层夹（0.35→0.05→0.10硬上限）** | `compute_score_b_with_event_boost` [polling_trader.py#L102-150](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L102-L150)（新增返回前1行夹） | 方案C Score_B段 [polling_trader.py#L9555-L9560](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L9555-L9560)（已注入） |
| G3 | Vintage≤168h（一周内）+ 未来函数冷却120s | 两层防：<br>**(A) DB桥 WHERE 过滤**（不读超龄/未来数据）<br>`published_ms <= (now_ms - 120_000)  -- 120s冷却，防时钟/API未来穿越`<br>`published_ms >= (now_ms - 168*3600_000)  -- 一周内=168h截止`<br>**(B) DC侧强度函数二次断言**（对传入的recs逐条）<br>`dt_hrs < 0 OR dt_hrs > 168 → 该rec weight=0`（FAIL-OPEN丢单条不整体回退） | (A) `_polling_get_coin_event_positive_strength` WHERE子句 [polling_trader.py#L240-280](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L240-L280)<br>(B) `compute_coin_event_positive_strength` dt_hrs判定 [odaily_newsflash.py#L207-298](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心/data_center/collectors/news/odaily_newsflash.py#L207-L298) | A→polling_trader开仓链路前读DB就过滤；B→第三方直接传recs也仍被夹（双保险） |

---

## §2. 数据流与中间量公式（零新模型·零外部依赖）

### §2.1 护栏②（G2）EV门槛的精确公式（续P0原公式在夹一层）

```python
def compute_score_b_with_event_boost(cont, conf_norm, strength) -> (score_b, boost_applied):
    # ── P0 公式（未改）──
    if not strength_ok or strength_val <= 0.35:
        return 0.60*cont + 0.40*conf, 0.0          # Fail-Open baseline（100% v3.0等价）
    raw_boost = 0.10 * max(0.0, (strength_val - 0.35)) / 0.65
    boost = max(0.0, min(0.10, raw_boost))
    Score_new = 0.58*cont + 0.37*conf + 0.05*s + boost

    # ── 🆕 P1 G2：EV门槛 夹阈值（0.05以下=弱快讯=清零回baseline）──
    if boost <= 0.050:
        boost = 0.0
        Score_new = 0.60 * cont + 0.40 * conf_norm   # 回baseline（字节等价原v3.0）

    return clip[0,1](Score_new), round(boost, 4)
```

**边界验证表（压吹票最小影响）**：
| strength（OD正面） | raw_boost | clamp后boost | G2 EV>0.05判断 | 最终boost | 行为 |
|---|---|---|---|---|---|
| 0.40（小合作/次升级=典型吹票黑嘴） | 0.0077 | 0.008 | ≤0.05 → 清零 | 0.0 ✅ | 完全不抬升，baseline不影响 |
| 0.50（中等正面快讯） | 0.0231 | 0.023 | ≤0.05 → 清零 | 0.0 ✅ | 弱正面不抬，防干扰 |
| 0.60（强代币里程碑 如ARC主网重要级） | 0.0385 | 0.038 | ≤0.05 → 清零 | 0.0 ⚠️ | 刚好在门槛下→看是否调整为0.038？（TDD后再议·默认按设计先卡严）|
| 0.68（sentiment=0.95 + important=true + 2h内） | 0.0508 | 0.051 | >0.05 → 放行 | 0.051 ✅ | 只抬+0.051 Score_B=仓位弹性+~12%（保守） |
| 0.85（2条强正面叠加） | 0.0769 | 0.077 | >0.05 → 放行 | 0.077 ✅ | +0.077 Score_B=弹性+~18% |
| 1.00（强正面上限） | 0.100 | 0.100（硬上限） | >0.05 → 放行 | 0.100 ✅ | +0.100 Score_B=弹性+~25%（P0原硬上限不变） |

### §2.2 护栏③（G3）Vintage截止+未来函数冷却 精确范围

| 范围 | 毫秒 | 小时 | 判定 | 权重 |
|---|---|---|---|---|
| 未来泄漏 | now_ms - 120_000 > published_ms 为 FALSE | t<120s | ❌ 丢弃 | weight=0 |
| 一周内（含） | 0 ≤ dt_hours ≤ 168 | 168h = 7天 | ✅ 有效参与strength | 指数半衰期=0.5^(dt/decay) |
| 超龄（一周以上） | dt_hours > 168 | >7 天 | ❌ 丢弃 | weight=0（即使decay算出来也强制清零）|
| dt<0解析失败（Fail-Open） | dt_hours < 0 | 非法 | ❌ 单条丢弃 | weight=0 |

---

## §3. 错误处理（Fail-Open 三层回退）

1. **护栏G1（卦地板）** → Fail-Open 原P0-4：`lookup_dir`为空（卦缺失=SIXTY_FOUR_GUAS未匹配）→ `confidence_multiplier=1.0` + `raise_a_floor_to=None` = **不罚不抬**。
2. **护栏G2（EV门槛）** → 任何 strength 传None / NaN / ≤0 / boost计算异常（ZeroDivision）→ 走P0 baseline回退分支（boost=0，Score_B=0.60cont+0.40conf），**EV门槛判断也跳过不执行**=防异常误卡。
3. **护栏G3（Vintage/未来函数）** →
   - A DB桥：WHERE published_ms解析失败（SQL NULL / 列不存在老schema）→ `IFNULL(published_ms,0)=0` → dt超大（>168h）→ 自然被G3的dt范围挡掉（Fail-Open不抬升=保守）。
   - B DC侧强度函数：单条rec的published_ms字段缺失 → try/except捕获 → 单条weight=0（不影响其他N条）。

---

## §4. 测试矩阵（TDD RED → GREEN 要求）

### §4.1 新增文件：`11-易经推理系统/tests/test_p1_c14_three_guards.py`

| 类 & 方法（parametrize） | RED 预期失败原因 | GREEN 判据 |
|---|---|---|
| `TestG2EVThresholdGuard`（7条） | compute_score_b_with_event_boost 无G2夹→boost 0.038被返回 | strength=0.40→boost=0回baseline（Δ<1e-6）；strength=0.60→boost=0回baseline；strength=0.70→boost=0.054>0；boost=0.050边界→清零；boost=0.0501→放行 |
| `TestG3VintageFutureLeak`（6条） | _polling_get_coin_event_positive_strength WHERE 无时间过滤→超龄/未来快讯参与计算 | published_ms=now()+60s(未来)=hit=0；published_ms=now()-200h(超龄)=hit=0；published_ms=now()-169h=hit=0；now()-120s内=hit=0；now()-121s~167h=正常进入 |
| `TestG3DCSideWeightAssert`（3条） | compute_coin_event_positive_strength dt_hrs>168仍有正贡献 → GREEN：dt=170h→weight=0→strength=0 | 同上 |
| `TestThreeGuardsBackwardCompat`（3条） | 原test_p0_score_b_event_boost.py 9条T因G2新增夹逻辑变失败 | 实际上strength=0.85/1.00 → boost>0.05 → 原断言仍PASS；FAIL-OPEN strength=None→baseline 仍=原公式 |

### §4.2 原回归仍通过（**不破坏**）

- 18-DC：test_odaily_collector.py 5/5 + test_odaily_p0_token_milestone.py 19/19
- 11-推理：test_p0_score_b_event_boost.py 9/9 + test_polling_trader_prediction.py 2/2

---

## §5. 改动文件锚点（最小3处Edit+1新TDD，共4文件）

| # | 路径 | 改动段 | 说明 |
|---|------|--------|------|
| 1 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` | compute_score_b_with_event_boost 最后段夹G2 EV>0.05 | 最小10行（if boost≤0.05→清零回baseline） |
| 2 | 同上 | _polling_get_coin_event_positive_strength → SQL WHERE加published_ms范围条件 | WHERE子句加2个BETWEEN，加IFNULL保护 |
| 3 | `18-数据获取中心/data_center/collectors/news/odaily_newsflash.py` | compute_coin_event_positive_strength dt_hrs>168/<0单条weight=0 | 指数半衰期计算后夹1行if |
| 4 | 新增：`11-易经推理系统/tests/test_p1_c14_three_guards.py` | 上§4.1 4类19条 TDD | RED→GREEN验证 |

---

## §6. Spec Self-Review（自检）

| 检查项 | 结果 | 备注 |
|---|---|---|
| TBD/TODO/模糊要求？ | 🟢 无 | G2=boost>0.05；G3=168h+120s；G1=原不变，均已精确到数值 |
| 内部矛盾？（例：要求boost>0.05又不改变baseline） | 🟢 无 | G2对boost≤0.05=**回baseline**=对baseline 100%等价，未改变原v3.0行为 |
| 作用范围是否够聚焦？（仅护栏3处，不改其他） | 🟢 是 | 3处最小Edit，4文件总估计改<50行 |
| 边界条件是否全覆盖？ | 🟢 是 | strength=0/0.35/0.40/0.60/0.68/0.70/1.00 7档；dt=-60s/0/60s/119s/120s/168h/169h/200h 8档 |
| FAIL-OPEN 保护是否写进每条护栏？ | 🟢 是 | §3逐条确认三层回退 |

---

## §7. 对CRCL的实际影响（今日=2026-09-01 T-15d ARC主网上线）

- **当odaily未抓到CRCL快讯**（当前状态）→ strength=0 → boost=0 → Score_B=baseline 0.624 → 行为与P0改前**100%一致**=三条护栏未触发（Fail-Open基线不改变）。
- **当odaily抓到1条"CRCL ARC主网上线important=true"sentiment=0.90 dt=3h** →
  - strength=0.65 → raw_boost=0.0462 → boost=0.046 ≤0.05 → **G2 清零→boost=0回baseline**（保守，一条快讯不抬）
- **当抓到2条**（第一条+第二天CRCL跨链迁移通道开启sentiment=0.85 important=false）→
  - strength=0.80 → raw_boost=0.069 → boost=0.069 >0.05 → **G2放行→Score_B +0.069 +0.05*0.8=+0.109=0.624→0.733**
  - ElasticGate consensus Δ=+0.027，但BCRM conf=0.63仍<A_SAFETY_FLOOR=0.70 → 仍A项过滤（**G1卦地板硬门槛不绕过**，符合设计目标）
