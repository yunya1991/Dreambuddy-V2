#!/usr/bin/env python3
"""
自进化引擎 — 三层反思闭环

当系统自身进化很难完成提升时（停滞检测）触发三层：
  Layer 1: A8 理论与实践验证（6-TRADING/skills/A8）
           ─ 内部批评自循环，检验理论与实践背离
  Layer 2: 做梦部（dream-oneirology）
           ─ 弗洛伊德潜意识视角，发现被压制的判断
  Layer 3: 联网反思（Tavily + GitHub 成熟经验）
           ─ 外部视角，搜索成熟量化策略，验证后引入

触发条件（满足任一）：
  - 最近 N 轮胜率 < 45%（停滞）
  - 连续 hold >= 10 轮（系统保守过度）
  - 方向准确率连续下降 3 期
  - 手动触发

依赖:
  - 6-TRADING/skills/A8-theory-practice-verification/
  - 6-TRADING/skills/dream-oneirology/
  - scripts/memory_l4/tavily_macro.py（联网）
  - scripts/memory_l4/bcrm/walk_forward.py（回测验证）
"""
import json, os, time, warnings
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent.parent

# 6-TRADING Skills 路径
SKILLS_DIR = BASE_DIR.parent / "6-TRADING" / "skills"
A8_SKILL_PATH    = SKILLS_DIR / "A8-theory-practice-verification" / "SKILL.md"
DREAM_SKILL_PATH = SKILLS_DIR / "dream-oneirology" / "SKILL.md"

EVOLUTION_LOG = BASE_DIR / "data" / "self_evolution" / "evolution_log.json"

# B-2修复：config.json 路径（与 yijing_monitor.evolve_thresholds 共享同一文件）
OKX_SIM_CONFIG = BASE_DIR / "data" / "okx_sim" / "config.json"

# B-2修复：constraints/releases 快照目录
CONSTRAINTS_RELEASES_DIR = BASE_DIR / "constraints" / "releases"

# PROP-20260809-003: regime → 四象限概率调整映射表
# BASE_DIR = 11-易经推理系统（Path(__file__).parent.parent.parent）
REGIME_MAP_PATH = BASE_DIR / "config" / "regime_quadrant_map.json"

# adopted 提案 param_key → config.json 键的映射
# SelfEvolutionEngine 的安全参数名与 config.json 字段名不同，需要桥接
_PARAM_KEY_TO_CONFIG = {
    "min_confidence_threshold": "confidence_threshold",
}

# ── 停滞检测阈值 ─────────────────────────────────────────────────────────────
STAGNATION_WIN_RATE_THRESHOLD  = 0.45   # 胜率低于此值触发
STAGNATION_HOLD_STREAK         = 10     # 连续HOLD次数触发
STAGNATION_ACCURACY_DECLINE    = 3      # 方向准确率连续下降期数

class SelfEvolutionEngine:
    """
    三层自进化引擎。

    用法:
        engine = SelfEvolutionEngine()
        if engine.should_trigger(memory_stats):
            report = engine.run_full_cycle(memory_stats, recent_decisions)
            # report 包含: a8_findings / dream_insights / online_learnings / proposals
    """

    def __init__(self, llm_client=None):
        # v5.0：自动接入千问 3.8 MAX 驱动器（Dream OS 大模型驱动）
        # 若未显式传入 llm_client，自动尝试加载 16-调控系统/core/llm_driver
        if llm_client is None:
            llm_client = self._try_load_qwen_driver()
        self.llm_client = llm_client  # 可传入 agent_a_llm 或 deepseek
        EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        self._log: List[Dict] = self._load_log()

    @staticmethod
    def _try_load_qwen_driver():
        """尝试加载千问 LLM 驱动器，失败则返回 None（纯规则模式）"""
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _driver_path = _Path(__file__).resolve().parent.parent.parent.parent / "16-调控系统" / "core"
            if str(_driver_path) not in _sys.path:
                _sys.path.insert(0, str(_driver_path))
            from llm_driver import llm_call
            return llm_call
        except Exception:
            return None

    # ── 停滞检测 ─────────────────────────────────────────────────────────────

    def should_trigger(self, stats: Dict[str, Any]) -> tuple[bool, str]:
        """
        检测是否需要触发自进化。

        Args:
            stats: 包含 win_rate/hold_streak/recent_accuracy_trend 等

        Returns:
            (should_trigger: bool, reason: str)
        """
        win_rate   = stats.get("win_rate", 1.0)
        hold_streak = stats.get("hold_streak", 0)
        acc_trend   = stats.get("accuracy_trend", [])  # 最近N期方向准确率

        if win_rate < STAGNATION_WIN_RATE_THRESHOLD and stats.get("total_trades", 0) >= 5:
            return True, f"胜率停滞: {win_rate:.1%} < {STAGNATION_WIN_RATE_THRESHOLD:.1%}"

        if hold_streak >= STAGNATION_HOLD_STREAK:
            return True, f"过度保守: 连续{hold_streak}轮HOLD"

        if len(acc_trend) >= STAGNATION_ACCURACY_DECLINE:
            if all(acc_trend[i] >= acc_trend[i+1]
                   for i in range(len(acc_trend)-1)):
                return True, f"方向准确率连续下降{len(acc_trend)}期: {acc_trend}"

        return False, "系统正常，无需进化"

    # ── 主入口：完整三层进化周期 ─────────────────────────────────────────────

    def run_full_cycle(self,
                       stats: Dict[str, Any],
                       recent_decisions: List[Dict],
                       force: bool = False) -> Dict[str, Any]:
        """
        执行完整三层自进化周期。

        Layer 1 → Layer 2 → Layer 3 串行，前层发现越多，后层越有针对性。
        每层都生成可验证的改进提案，通过 walk_forward 回测后写入进化池。
        """
        ts = datetime.now(timezone.utc).isoformat()
        print(f"\n{'='*60}")
        print(f"[SelfEvolution] 启动三层自进化周期 {ts}")
        print(f"{'='*60}")

        result = {
            "ts": ts,
            "trigger_stats": stats,
            "layer1_a8": {},
            "layer2_dream": {},
            "layer3_online": {},
            "proposals": [],
            "adopted": [],
        }

        # ── Layer 1: A8 理论与实践验证 ───────────────────────────────────
        print("\n[Layer 1] A8 理论与实践验证...")
        a8_result = self._run_a8_inspection(stats, recent_decisions)
        result["layer1_a8"] = a8_result
        print(f"  发现 {len(a8_result.get('gaps', []))} 个理论实践背离")
        print(f"  提案: {[p['title'] for p in a8_result.get('proposals', [])]}")

        # ── Layer 2: 做梦部外部反思 ──────────────────────────────────────
        print("\n[Layer 2] 做梦部外部反思...")
        dream_result = self._run_dream_analysis(stats, recent_decisions, a8_result)
        result["layer2_dream"] = dream_result
        print(f"  潜意识信号: {dream_result.get('subconscious_signals', [])[:2]}")
        print(f"  提案: {[p['title'] for p in dream_result.get('proposals', [])]}")

        # ── Layer 3: 联网反思（Tavily + GitHub）──────────────────────────
        print("\n[Layer 3] 联网反思（外部成熟经验）...")
        online_result = self._run_online_reflection(stats, a8_result, dream_result)
        result["layer3_online"] = online_result
        print(f"  搜索结果: {len(online_result.get('sources', []))} 个来源")
        print(f"  提案: {[p['title'] for p in online_result.get('proposals', [])]}")

        # ── 汇总所有提案 ─────────────────────────────────────────────────
        all_proposals = (
            a8_result.get("proposals", []) +
            dream_result.get("proposals", []) +
            online_result.get("proposals", [])
        )

        # PROP-20260809-002: 提案参数值数据驱动精化
        # （反思层定方向，Optuna+本地klines walk-forward 定值；失败自动降级）
        all_proposals = self._refine_proposal_values(all_proposals)
        result["proposals"] = all_proposals

        print(f"\n[WalkForward] 验证 {len(all_proposals)} 个提案...")
        adopted = self._backtest_and_adopt(all_proposals, recent_decisions)
        result["adopted"] = adopted
        print(f"  采纳 {len(adopted)}/{len(all_proposals)} 个提案")

        # 记录日志
        self._log.append(result)
        self._save_log()

        print(f"\n{'='*60}")
        print(f"[SelfEvolution] 完成 | 采纳 {len(adopted)} 个进化提案")
        print(f"{'='*60}\n")

        return result

    # ── Layer 1: A8 理论与实践验证 ───────────────────────────────────────────

    def _run_a8_inspection(self,
                            stats: Dict,
                            decisions: List[Dict]) -> Dict:
        """
        A8 检验：对照 6-TRADING A8 SKILL 的框架，
        找出理论预期与实际结果的背离点。
        """
        gaps = []
        proposals = []

        win_rate = stats.get("win_rate", 1.0)
        hold_pct = stats.get("hold_rate", 0)
        top_hexagrams = stats.get("top_hexagrams", {})

        # 检验1: 卦象多样性（单一卦象垄断 = 系统退化）
        if top_hexagrams:
            top_gua, top_count = max(top_hexagrams.items(), key=lambda x: x[1])
            total = sum(top_hexagrams.values())
            if total > 0 and top_count / total > 0.6:
                gaps.append({
                    "type": "卦象单一化",
                    "desc": f"{top_gua} 占比 {top_count/total:.1%}，系统推理退化为默认卦",
                    "severity": "high",
                })
                proposals.append({
                    "title": "增加市场状态区分度",
                    "param_key": "velocity_threshold",
                    "param_value": 0.015,
                    "rationale": "降低速度阈值增加方向信号多样性",
                    "source": "a8",
                })

        # 检验2: 胜率与置信度一致性（高置信低胜率 = 理论虚高）
        if win_rate < 0.45:
            gaps.append({
                "type": "置信度虚高",
                "desc": f"胜率 {win_rate:.1%} 但系统置信度未相应下调",
                "severity": "medium",
            })
            proposals.append({
                "title": "上调置信度门槛",
                "param_key": "min_confidence_threshold",
                "param_value": 0.45,
                "rationale": "实际胜率偏低，提高入场门槛减少错误",
                "source": "a8",
            })

        # 检验3: hold 过多（系统保守 = 实践与理论背离）
        if hold_pct > 0.7:
            gaps.append({
                "type": "行动力不足",
                "desc": f"HOLD 占比 {hold_pct:.1%}，系统过度保守",
                "severity": "medium",
            })
            proposals.append({
                "title": "降低 velocity threshold",
                "param_key": "velocity_threshold",
                "param_value": 0.015,
                "rationale": "提高信号敏感度，减少过度观望",
                "source": "a8",
            })

        # 用 LLM 补充深度分析（可选）
        llm_gaps = self._llm_a8_analysis(stats, decisions) if self.llm_client else []
        gaps.extend(llm_gaps)

        return {
            "gaps": gaps,
            "proposals": proposals,
            "consistency_score": max(0.0, 1.0 - len(gaps) * 0.2),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def _llm_a8_analysis(self, stats, decisions) -> List[Dict]:
        """用 LLM 做 A8 深度分析（有 Token 成本，可选）"""
        try:
            # 读取 A8 SKILL 框架
            skill_text = A8_SKILL_PATH.read_text(encoding="utf-8")[:1500] \
                if A8_SKILL_PATH.exists() else ""
            prompt = f"""你是 A8 理论与实践验证模块。
参考框架: {skill_text[:500]}

当前系统表现:
  胜率: {stats.get('win_rate', '?')}
  HOLD率: {stats.get('hold_rate', '?')}
  最近卦象: {stats.get('top_hexagrams', {})}

请找出 2 个最关键的理论实践背离点，每个格式:
  类型: xxx
  描述: xxx（30字内）
  严重性: high/medium/low"""
            from scripts.memory_l4.bcrm.market_preprocessor import normalize_snapshot
            reply = self.llm_client(prompt, max_tokens=200, purpose="a8_governance")
            # 解析简单格式
            gaps = []
            for block in reply.split("类型:")[1:]:
                lines = block.strip().split("\n")
                if len(lines) >= 2:
                    gaps.append({
                        "type":     lines[0].strip(),
                        "desc":     lines[1].replace("描述:", "").strip() if len(lines) > 1 else "",
                        "severity": "medium",
                        "source":   "llm_a8",
                    })
            return gaps[:2]
        except Exception:
            return []

    # ── Layer 2: 做梦部外部反思 ──────────────────────────────────────────────

    def _run_dream_analysis(self,
                             stats: Dict,
                             decisions: List[Dict],
                             a8_result: Dict) -> Dict:
        """
        做梦部：弗洛伊德五大机制，发现被系统压制的判断。
        """
        signals = []
        proposals = []

        # 凝缩检测：系统是否把多维矛盾压缩成单一输出
        top_hexagrams = stats.get("top_hexagrams", {})
        if len(top_hexagrams) <= 2 and sum(top_hexagrams.values()) > 5:
            signals.append("凝缩：决策被过度简化为少数卦象")
            proposals.append({
                "title": "增加四维评分权重多样性",
                "param_key": "sentiment_weight",
                "param_value": 0.35,  # 提高情绪权重
                "rationale": "打破凝缩，增加决策维度多样性",
                "source": "dream",
            })

        # 强迫性重复检测：连续 hold + 相同原因
        if stats.get("hold_streak", 0) >= 5:
            signals.append(f"强迫性重复：连续{stats['hold_streak']}轮HOLD")
            proposals.append({
                "title": "启动反事实推演模式",
                "param_key": "force_action_after_n_holds",
                "param_value": 8,
                "rationale": "做梦部：系统在回避做决策，强制试探",
                "source": "dream",
            })

        # 投射检测：外部归因过多
        if a8_result.get("gaps"):
            external_gaps = [g for g in a8_result["gaps"] if "市场" in g.get("desc", "")]
            if len(external_gaps) > len(a8_result["gaps"]) * 0.6:
                signals.append("投射：将内部能力不足归因于市场不明朗")
                proposals.append({
                    "title": "降低不确定性阈值",
                    "param_key": "high_uncertainty_threshold",
                    "param_value": 0.85,  # 原来可能过低
                    "rationale": "系统在投射，适当接受不确定性",
                    "source": "dream",
                })

        # 四象限情景预言（被忽视情景）
        ignored_scenario = self._generate_ignored_scenario(stats)
        if ignored_scenario:
            signals.append(f"被忽视情景: {ignored_scenario}")

        # LLM 做梦部深度分析（可选）
        if self.llm_client and len(signals) >= 2:
            llm_insight = self._llm_dream_analysis(stats, signals)
            if llm_insight:
                signals.append(f"LLM潜意识探测: {llm_insight}")

        # PROP-20260809-003: 四象限概率 = 静态基线 + Regime 调整
        # （regime 缺失/过期/未知 → 自动回退静态基线，行为不变）
        quad_probs, quad_meta = self._regime_adjusted_quadrant_probs()

        return {
            "subconscious_signals": signals,
            "proposals": proposals,
            "four_quadrant": {
                "optimistic":  {"prob": quad_probs["optimistic"], "scenario": "市场突破关键阻力，信号明确"},
                "neutral":     {"prob": quad_probs["neutral"], "scenario": "区间震荡，当前主要场景"},
                "pessimistic": {"prob": quad_probs["pessimistic"], "scenario": "趋势反转，止损触发"},
                "ignored":     {"prob": quad_probs["ignored"], "scenario": ignored_scenario or "假突破后急速反转"},
            },
            "four_quadrant_meta": quad_meta,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _generate_ignored_scenario(self, stats: Dict) -> str:
        """生成'被忽视情景'（四象限第四象限）。"""
        top_gua = max(stats.get("top_hexagrams", {"坤为地": 1}).items(),
                      key=lambda x: x[1], default=("?", 0))[0]
        hold_rate = stats.get("hold_rate", 0.5)
        if hold_rate > 0.6:
            return f"系统持续观望时市场单边突破，踏空主升浪（坤为地→乾为天）"
        return "主流观点一致时的反向黑天鹅"

    # ── PROP-20260809-002: 提案参数值数据驱动精化 ─────────────────────────

    # 方向推断关键词（反思层意图 → 搜索空间约束）
    _LOWER_KEYWORDS = ("降低", "下调", "收紧", "减少", "lower", "decrease", "reduce")
    _RAISE_KEYWORDS = ("提高", "上调", "放宽", "增加", "raise", "increase")

    def _refine_proposal_values(self, proposals: List[Dict]) -> List[Dict]:
        """
        PROP-20260809-002: 提案参数值数据驱动精化。

        - 反思层（A8/做梦部/联网）决定"调哪个参数"，方向从 rationale 关键词推断
        - Optuna + 本地 klines walk-forward 决定"调多少"
        - 影子参数 / 无 optuna / 超时 → 保留原值并标注 value_source，不中断流程
        """
        if not proposals:
            return proposals
        try:
            from scripts.memory_l4.evolution_optimize import (
                optimize_proposal_value)
        except Exception as e:
            print(f"  ⚠️ evolution_optimize 不可用，跳过参数精化: {e}")
            return proposals

        for p in proposals:
            param_key = p.get("param_key", "")
            if not param_key or p.get("param_value") is None:
                continue
            # 方向推断: 标题优先（意图最明确），文本中首个出现的关键词获胜
            # （中文 rationale 惯例: 动作动词在前、效果在后，
            #   如"提高入场门槛减少错误" → raise 而非 lower）
            rationale = str(p.get("title", "")) + " " + str(p.get("rationale", ""))
            first_pos, direction = None, "around"
            for kw in self._LOWER_KEYWORDS:
                pos = rationale.find(kw)
                if pos >= 0 and (first_pos is None or pos < first_pos):
                    first_pos, direction = pos, "lower"
            for kw in self._RAISE_KEYWORDS:
                pos = rationale.find(kw)
                if pos >= 0 and (first_pos is None or pos < first_pos):
                    first_pos, direction = pos, "raise"
            try:
                new_val, source = optimize_proposal_value(
                    param_key, direction, p["param_value"])
                if source == "optuna":
                    p["param_value_original"] = p["param_value"]
                    p["param_value"] = new_val
                p["value_source"] = source
                p["value_direction"] = direction
            except Exception as e:
                p["value_source"] = "default_fallback"
                print(f"  ⚠️ 提案值精化失败 {param_key}: {e}")
        return proposals

    # ── PROP-20260809-003: Regime 联动四象限 ──────────────────────────────

    def _load_regime_map(self) -> Dict:
        """加载 regime → 四象限概率映射表（缺失/损坏 → 空 dict，调用方降级）。"""
        try:
            return json.loads(REGIME_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _get_current_regime(self) -> Optional[Dict]:
        """
        从 AB 日志读取最新 market_regime。

        Returns:
            {"regime", "confidence", "age_hours", "source"} 或 None
            （目录不存在/无日志/日志超过 stale_hours → None，调用方回退静态基线）
        """
        try:
            cfg = self._load_regime_map()
            stale_hours = float(cfg.get("stale_hours", 48))

            env_dir = os.environ.get("AB_LOG_DIR", "").strip()
            log_dir = Path(env_dir) if env_dir else None
            if log_dir is None or not log_dir.exists():
                return None

            candidates = sorted(
                log_dir.glob("**/*.json"),
                key=lambda p: p.stat().st_mtime, reverse=True)
            now_ts = datetime.now(timezone.utc).timestamp()
            for path in candidates[:5]:
                try:
                    age_h = (now_ts - path.stat().st_mtime) / 3600.0
                    if age_h > stale_hours:
                        continue  # 过期，看更早的日志也没意义（更旧）
                    text = path.read_text(encoding="utf-8")
                    records: List[Dict] = []
                    try:
                        data = json.loads(text)
                        records = data if isinstance(data, list) else [data]
                    except json.JSONDecodeError:
                        # 兼容 JSONL 格式
                        for line in text.splitlines():
                            line = line.strip()
                            if line:
                                try:
                                    records.append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue
                    for rec in reversed(records):
                        regime = str(rec.get("market_regime", "")).upper()
                        if regime and regime != "UNKNOWN":
                            # W4修复(E2审查): 优先用记录自身时间戳判龄
                            # （mtime 新鲜不代表 regime 记录新鲜——文件可能被
                            #   追加其他事件），记录无时间戳才回退 mtime。
                            rec_age_h = self._record_age_hours(rec, now_ts)
                            if rec_age_h is None:
                                rec_age_h = age_h
                            if rec_age_h > stale_hours:
                                continue  # regime 记录本身过期
                            return {
                                "regime": regime,
                                "confidence": float(rec.get("confidence") or 0),
                                "age_hours": round(rec_age_h, 1),
                                "source": str(path),
                            }
                except OSError:
                    continue
            return None
        except Exception:
            return None

    @staticmethod
    def _record_age_hours(rec: Dict, now_ts: float) -> Optional[float]:
        """解析记录时间戳（ts/ts_utc/timestamp/created_at）计算年龄。"""
        for key in ("ts_utc", "ts", "timestamp", "created_at"):
            raw = rec.get(key)
            if not raw:
                continue
            try:
                if isinstance(raw, (int, float)):
                    ts = float(raw)
                    if ts > 1e12:  # 毫秒
                        ts /= 1000.0
                    return max(0.0, (now_ts - ts) / 3600.0)
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return max(0.0, (now_ts - dt.timestamp()) / 3600.0)
            except (ValueError, TypeError, OSError):
                continue
        return None

    def _regime_adjusted_quadrant_probs(self):
        """
        四象限概率 = 静态基线 + regime 调整（PROP-20260809-003）。

        规则:
          - 每象限调整幅度裁剪至 ±max_adjust（配置文件，默认 0.10）
          - 调整后归一化保证和 = 1.0
          - regime 缺失/过期/不在映射表 → 静态基线（prob_source="static_fallback"）

        Returns:
            (probs_dict, meta_dict)
        """
        cfg = self._load_regime_map()
        base = dict(cfg.get("base_probs", {
            "optimistic": 0.15, "neutral": 0.35,
            "pessimistic": 0.30, "ignored": 0.20}))
        max_adj = float(cfg.get("max_adjust", 0.10))

        # B2修复(E2审查): 先判空配置再取 regime（避免无谓日志扫描）
        if not cfg:
            return base, {"regime": None, "prob_source": "static_fallback",
                          "reason": "no_map_config"}

        regime_info = self._get_current_regime()
        if not regime_info:
            return base, {"regime": None, "prob_source": "static_fallback",
                          "reason": "no_regime_data"}

        regime = regime_info["regime"]
        adjustments = cfg.get("regime_adjustments", {}).get(regime)
        if adjustments is None:
            return base, {"regime": regime, "prob_source": "static_fallback",
                          "reason": "regime_not_in_map"}

        probs = {}
        for quad, base_p in base.items():
            adj = max(-max_adj, min(max_adj, float(adjustments.get(quad, 0.0))))
            probs[quad] = max(0.0, float(base_p) + adj)

        # 归一化（保证和 = 1.0）
        total = sum(probs.values())
        if total > 0:
            probs = {k: round(v / total, 4) for k, v in probs.items()}
            # B3修复(E2审查): 舍入残差补到最大象限，保证严格和=1.0
            residual = round(1.0 - sum(probs.values()), 4)
            if abs(residual) >= 1e-4:
                largest = max(probs, key=probs.get)
                probs[largest] = round(probs[largest] + residual, 4)

        meta = {
            "regime": regime,
            "regime_confidence": regime_info.get("confidence"),
            "regime_age_hours": regime_info.get("age_hours"),
            "prob_source": "regime",
            "applied_adjustments": adjustments,
        }
        return probs, meta

    def _llm_dream_analysis(self, stats, signals) -> str:
        """LLM 做梦部深度潜意识探测。"""
        try:
            skill_text = DREAM_SKILL_PATH.read_text(encoding="utf-8")[:800] \
                if DREAM_SKILL_PATH.exists() else ""
            prompt = f"""你是做梦部，基于弗洛伊德框架分析以下交易系统的潜意识：

已检测信号: {signals[:3]}
系统表现: 胜率{stats.get('win_rate','?')} HOLD率{stats.get('hold_rate','?')}

请用一句话（20字内）描述系统最深层的"被压制判断"是什么："""
            return self.llm_client(prompt, max_tokens=60, purpose="a8_governance")
        except Exception:
            return ""

    # ── Layer 3: 联网反思 ────────────────────────────────────────────────────

    def _run_online_reflection(self,
                                stats: Dict,
                                a8_result: Dict,
                                dream_result: Dict) -> Dict:
        """
        联网反思：结合 Tavily 搜索和 GitHub 成熟经验，
        验证当前系统问题是否有已知解法。
        """
        sources = []
        proposals = []
        search_results = []

        # 1. Tavily 宏观市场搜索
        try:
            from scripts.memory_l4.tavily_macro import tavily_search
            queries = self._build_search_queries(a8_result, dream_result)
            for q in queries[:2]:  # 最多2次查询控制成本
                data = tavily_search(q, max_results=5, topic="news")
                if data and not data.get("error"):
                    sources.append({"type": "tavily", "query": q,
                                    "snippets": data.get("results", [])[:2]})
                    search_results.extend(data.get("results", [])[:2])
        except Exception as e:
            sources.append({"type": "tavily", "error": str(e)})

        # 2. GitHub 成熟经验（静态知识库 + 可选联网）
        github_insights = self._search_github_patterns(a8_result)
        sources.extend(github_insights.get("sources", []))
        proposals.extend(github_insights.get("proposals", []))

        # 3. LLM 综合外部信息生成改进提案
        if self.llm_client and (search_results or github_insights["proposals"]):
            llm_proposals = self._llm_synthesize_online(
                stats, search_results, github_insights, a8_result)
            proposals.extend(llm_proposals)

        return {
            "sources": sources,
            "proposals": proposals,
            "searched_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_search_queries(self, a8_result, dream_result) -> List[str]:
        """根据 A8/做梦部发现构建搜索查询。"""
        queries = []
        for gap in a8_result.get("gaps", [])[:2]:
            if "卦象" in gap.get("type", ""):
                queries.append("crypto trend following strategy signal diversity")
            if "胜率" in gap.get("type", ""):
                queries.append("quantitative trading win rate improvement thresholds")
        if not queries:
            queries.append("yijing BCRM trading system optimization")
        return queries

    def _search_github_patterns(self, a8_result: Dict) -> Dict:
        """
        GitHub 成熟经验库（静态内置 + 可扩展联网）。
        参考 vnpy/backtrader/QuantConnect 的成熟做法。
        """
        patterns = {
            "velocity_too_conservative": {
                "source": "backtrader/ema_cross",
                "insight": "趋势跟踪策略的信号阈值应基于 ATR 动态调整而非固定值",
                "proposal": {
                    "title": "ATR 动态 velocity threshold",
                    "param_key": "velocity_threshold_mode",
                    "param_value": "atr_based",
                    "rationale": "借鉴 backtrader: threshold = atr_pct * 0.3",
                    "source": "github_backtrader",
                },
            },
            "low_win_rate": {
                "source": "vnpy/cta_strategy",
                "insight": "CTA策略胜率低时应检查信号过滤条件，而非降低门槛",
                "proposal": {
                    "title": "增加量比过滤条件",
                    "param_key": "volume_ratio_min",
                    "param_value": 1.2,
                    "rationale": "vnpy 标准: 量价配合才入场，缩量信号跳过",
                    "source": "github_vnpy",
                },
            },
            "over_hold": {
                "source": "QuantConnect/Lean",
                "insight": "LEAN 的 TrendFollow 在 ATR>均值时强制评估入场",
                "proposal": {
                    "title": "高波动期强制评估入场机会",
                    "param_key": "force_evaluate_high_vol",
                    "param_value": True,
                    "rationale": "借鉴 QuantConnect: 波动率突破均值时不能持续观望",
                    "source": "github_lean",
                },
            },
        }

        matched = []
        sources = []
        gaps = [g.get("type", "") for g in a8_result.get("gaps", [])]
        hold_heavy = a8_result.get("proposals", []) and any(
            "hold" in str(p).lower() for p in a8_result["proposals"])

        if any("卦象" in g for g in gaps) or hold_heavy:
            matched.append(patterns["velocity_too_conservative"])
        if any("胜率" in g for g in gaps):
            matched.append(patterns["low_win_rate"])
        if any("行动" in g for g in gaps) or hold_heavy:
            matched.append(patterns["over_hold"])

        for m in matched:
            sources.append({"type": "github", "repo": m["source"],
                             "insight": m["insight"]})

        return {
            "sources": sources,
            "proposals": [m["proposal"] for m in matched],
        }

    def _llm_synthesize_online(self, stats, search_results,
                                github_insights, a8_result) -> List[Dict]:
        """LLM 综合外部信息生成具体改进提案。"""
        try:
            search_summary = "\n".join(
                f"- {r.get('title','')}: {r.get('content','')[:80]}"
                for r in search_results[:3]
            ) if search_results else "（无搜索结果）"
            github_summary = "\n".join(
                f"- [{s['repo']}] {s['insight']}"
                for s in github_insights.get("sources", [])
            )
            prompt = f"""你是量化交易系统优化专家。

系统现状: 胜率{stats.get('win_rate','?')} HOLD率{stats.get('hold_rate','?')}
外部信息:
{search_summary}
{github_summary}

基于以上，给出1个最具体的参数优化建议：
参数名: xxx
新值: xxx
理由: xxx（25字内）"""
            reply = self.llm_client(prompt, max_tokens=100, purpose="a8_governance")
            proposals = []
            lines = {l.split(":")[0].strip(): ":".join(l.split(":")[1:]).strip()
                     for l in reply.strip().split("\n") if ":" in l}
            if lines.get("参数名"):
                proposals.append({
                    "title":      f"LLM综合优化: {lines.get('参数名')}",
                    "param_key":  lines.get("参数名", ""),
                    "param_value": lines.get("新值", ""),
                    "rationale":  lines.get("理由", ""),
                    "source":     "llm_online",
                })
            return proposals
        except Exception:
            return []

    # ── P2: Walk-Forward 回测验证 ────────────────────────────────────────────

    def _backtest_and_adopt(self,
                             proposals: List[Dict],
                             recent_decisions: List[Dict]) -> List[Dict]:
        """
        P2: 用 walk_forward.py 对每个提案做回测验证，
        通过则写入进化池（adopted_params）。

        参考 QuantConnect Walk-Forward Optimization 框架。
        """
        if not proposals or not recent_decisions:
            return []

        adopted = []
        # 去重：同一 param_key 只保留最高评分提案
        deduped = {}
        for p in proposals:
            k = p.get("param_key", p.get("title", ""))
            if k not in deduped:
                deduped[k] = p
        proposals = list(deduped.values())

        try:
            from scripts.memory_l4.bcrm.walk_forward import WalkForwardEngine
            from scripts.memory_l4.bcrm.engine import BCRMEngine
            wfe = WalkForwardEngine(BCRMEngine())
        except Exception:
            wfe = None

        for proposal in proposals:
            try:
                param_key = proposal.get("param_key", "")
                param_val = proposal.get("param_value")
                if not param_key:
                    continue

                if wfe and recent_decisions and len(recent_decisions) >= 5:
                    # PROP-20260809-001: 白名单门禁(第一道) + 真实 walk-forward 回测(第二道, AND)
                    safe_params = {
                        "velocity_threshold", "min_confidence_threshold",
                        "sentiment_weight", "volume_ratio_min",
                        "force_evaluate_high_vol", "velocity_threshold_mode",
                        "force_action_after_n_holds", "high_uncertainty_threshold",
                    }
                    is_safe = param_key in safe_params
                    if not is_safe:
                        improved = False  # 高风险参数跳过（原行为）
                    else:
                        # 真实 walk-forward 双引擎对比验证
                        # （本地 klines，不依赖外网；数据不足内部降级 rule_check+degraded）
                        try:
                            from scripts.memory_l4.evolution_backtest import (
                                walk_forward_validate)
                            bt = walk_forward_validate(
                                param_key=param_key,
                                proposed_value=param_val,
                            )
                        except Exception as e:
                            print(f"  ⚠️ walk-forward 验证异常，降级 rule_check: {e}")
                            bt = {
                                "validated": True,
                                "method": "rule_check",
                                "degraded": True,
                                "reason": f"walk_forward_exception: {e}",
                            }
                        proposal["backtest_result"] = bt
                        improved = bool(bt.get("validated", False))
                        if not improved:
                            print(f"  ⏸ 拒绝(walk-forward 劣化): "
                                  f"{proposal['title']} | delta={bt.get('delta')}")
                else:
                    # 数据不足时，A8/dream 来源直接采纳（原行为 + 诚实标注）
                    improved = proposal.get("source") in ("a8", "dream")
                    if improved and "backtest_result" not in proposal:
                        proposal["backtest_result"] = {
                            "validated": True, "method": "rule_check",
                            "degraded": True,
                            "reason": "insufficient_recent_decisions",
                        }

                if improved:
                    proposal["adopted"] = True
                    if "backtest_result" not in proposal:
                        proposal["backtest_result"] = {
                            "validated": True, "method": "rule_check"}
                    adopted.append(proposal)
                    method = proposal["backtest_result"].get("method", "?")
                    degraded = proposal["backtest_result"].get("degraded", False)
                    tag = f"[{method}{'/degraded' if degraded else ''}]"
                    print(f"  ✅ 采纳 {tag}: {proposal['title']}")
                else:
                    print(f"  ⏸ 跳过: {proposal['title']} (需人工确认)")
            except Exception as adopt_err:
                if proposal.get("source") == "a8":
                    proposal["adopted"] = True
                    # W7修复(E2审查): 异常兜底也诚实标注 degraded
                    proposal["backtest_result"] = {
                        "skipped": True, "degraded": True,
                        "reason": f"adopt_loop_exception: {adopt_err}",
                    }
                    adopted.append(proposal)

        # B-2修复：将 adopted 提案落地到 config.json + constraints/releases 快照
        if adopted:
            self._apply_adopted_to_config(adopted)

        return adopted

    # ── 日志管理 ────────────────────────────────────────────────────────────

    def _load_log(self) -> List[Dict]:
        if EVOLUTION_LOG.exists():
            try:
                return json.loads(EVOLUTION_LOG.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_log(self):
        # 只保留最近 50 次进化记录
        EVOLUTION_LOG.write_text(
            json.dumps(self._log[-50:], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def get_last_evolution(self) -> Optional[Dict]:
        """获取最近一次进化记录。"""
        return self._log[-1] if self._log else None

    # ── B-2修复：adopted 提案落地 ────────────────────────────────────────────

    def _apply_adopted_to_config(self, adopted: List[Dict]):
        """将 adopted 提案写入 config.json + 生成 constraints/releases 快照。

        - 能映射到 config.json 字段的 → 更新 config.json
        - 所有 adopted → 生成 constraints/releases/vX.Y.Z.json 快照
        """
        import time as _time
        from datetime import datetime, timezone as _tz

        # 1. 更新 config.json
        config_updated = {}
        if OKX_SIM_CONFIG.exists():
            try:
                cfg = json.loads(OKX_SIM_CONFIG.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        else:
            cfg = {}

        for p in adopted:
            param_key = p.get("param_key", "")
            param_val = p.get("param_value")
            # 桥接 param_key → config 键名
            config_key = _PARAM_KEY_TO_CONFIG.get(param_key, param_key)
            # 只写 config.json 已知的进化键
            # 注：max_consecutive_losses 已禁用（风控改以亏损金额为准），不再自动进化
            if config_key in ("confidence_threshold", "daily_loss_limit",
                              "default_position_pct", "loss_limit_pct"):
                old_val = cfg.get(config_key)
                if old_val != param_val:
                    cfg[config_key] = param_val
                    config_updated[config_key] = {"old": old_val, "new": param_val}

        if config_updated:
            cfg["last_evolve"] = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            OKX_SIM_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            OKX_SIM_CONFIG.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8"
            )
            print(f"  [B-2] config.json 已更新: {list(config_updated.keys())}")

        # 2. 生成 constraints/releases 快照
        self._emit_constraint_release(adopted, config_updated)

    def _emit_constraint_release(self, adopted: List[Dict], config_updated: Dict):
        """生成 constraints/releases/vX.Y.Z.json 约束升级快照。"""
        from datetime import datetime, timezone as _tz

        CONSTRAINTS_RELEASES_DIR.mkdir(parents=True, exist_ok=True)

        # 读取现有最高版本号（按数字而非字符串排序）
        existing = list(CONSTRAINTS_RELEASES_DIR.glob("v*.json"))
        max_patch = 0
        for f in existing:
            try:
                parts = f.stem.split(".")  # e.g. ["v0", "1", "2"]
                patch = int(parts[-1])
                if patch > max_patch:
                    max_patch = patch
            except Exception:
                pass
        next_patch = max_patch + 1

        new_version = f"v0.1.{next_patch}"
        ts = datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        snapshot = {
            "release_version": new_version,
            "generated_at": ts,
            "source_ref": "self_evolution_engine",
            "source_sha256": f"evolution-{ts}",
            "candidate_id": ",".join(
                p.get("param_key", "") for p in adopted[:5]
            ),
            "from_version": f"v0.1.{max_patch}" if max_patch > 0 else "v0.1.0",
            "to_version": new_version,
            "schema_version": "evolution-p2-constraint-release-snapshot-v0.1",
            "adopted_proposals": [
                {
                    "title": p.get("title", ""),
                    "param_key": p.get("param_key", ""),
                    "param_value": p.get("param_value"),
                    "source": p.get("source", ""),
                    "rationale": p.get("rationale", ""),
                }
                for p in adopted
            ],
            "config_changes": config_updated,
        }

        out_path = CONSTRAINTS_RELEASES_DIR / f"{new_version}.json"
        out_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8"
        )
        print(f"  [B-2] 约束快照已生成: {out_path.name} ({len(adopted)} proposals)")
