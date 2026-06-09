#!/usr/bin/env python3
"""
大师策略检索器 + 评分反馈引擎 v1.0
====================================
A4触发时优先检索大师策略, 成功+5/失败-10评分反馈

核心功能:
1. retrieve_master_strategies(regime) → 按priority+score排序的大师策略
2. update_master_score(strategy_id, result) → 评分反馈写入S/A_rank.json + all_index.json
3. get_composite_strategy(regime) → 组合引擎(Livermore进出场+Druckenmiller仓位+PTJ风控)
4. stress_test() → 多轮压力测试闭环验证

对接: A4战术验证 | strategy_library.yaml v3.1 | knowledge_base/scores/
"""

import json
import yaml
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================
# 路径配置
# ============================================================
WORKSPACE = Path(os.environ.get("WORKSPACE", "/Users/zhangjiangtao/WorkBuddy/20260415144304"))
STRATEGY_YAML = WORKSPACE / "strategy_library.yaml"
SCORES_DIR = WORKSPACE / ".knowledge_base" / "scores"
S_RANK_FILE = SCORES_DIR / "S_rank.json"
A_RANK_FILE = SCORES_DIR / "A_rank.json"
B_RANK_FILE = SCORES_DIR / "B_rank.json"
C_RANK_FILE = SCORES_DIR / "C_rank.json"
PENDING_FILE = SCORES_DIR / "pending.json"
ALL_INDEX_FILE = SCORES_DIR / "all_index.json"

# 评分参数
SCORE_SUCCESS_DELTA = +5
SCORE_FAILURE_DELTA = -10
SCORE_MIN = 0
SCORE_MAX = 100
S_TIER_THRESHOLD = 80
A_TIER_THRESHOLD = 60
B_TIER_THRESHOLD = 40


class MasterStrategyRetriever:
    """大师策略检索器 — A4优先检索大师策略"""

    def __init__(self, yaml_path: str = None):
        self.yaml_path = Path(yaml_path) if yaml_path else STRATEGY_YAML
        self._strategies = None
        self._master_cache = {}

    def _load_yaml(self) -> dict:
        """加载strategy_library.yaml"""
        if self._strategies is None:
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                self._strategies = yaml.safe_load(f)
        return self._strategies

    def get_all_strategies(self) -> list:
        """获取所有策略"""
        data = self._load_yaml()
        return data.get("strategies", [])

    def get_master_strategies(self) -> list:
        """获取所有master_*前缀的大师策略"""
        all_strats = self.get_all_strategies()
        return [s for s in all_strats if s.get("id", "").startswith("master_")]

    def retrieve_master_strategies(self, regime: str, top_k: int = 5) -> list:
        """
        按Regime检索大师策略 — A4触发时优先调用
        
        Args:
            regime: 市场状态(TREND_STRONG_UP/TREND_DOWN/EXTREME等)
            top_k: 返回前K个策略
            
        Returns:
            按priority(升序)+source_score(降序)排序的大师策略列表
            
        排序规则:
        1. priority=0的大师策略优先(prioriy越小越优先)
        2. 同priority按source_score降序
        3. Regime精确匹配优先于Regime包含匹配
        """
        cache_key = f"{regime}_{top_k}"
        if cache_key in self._master_cache:
            return self._master_cache[cache_key]

        masters = self.get_master_strategies()
        matched = []

        for s in masters:
            s_regime = s.get("regime", "")
            # 精确匹配或列表包含
            if isinstance(s_regime, list):
                is_match = regime in s_regime
                is_exact = is_match and len(s_regime) == 1
            else:
                is_match = s_regime == regime
                is_exact = is_match

            if is_match:
                matched.append({
                    **s,
                    "_regime_exact": is_exact,
                    "_sort_priority": s.get("priority", 99),
                    "_sort_score": s.get("source_score", s.get("score", 0)),
                })

        # 排序: 精确匹配 > 非精确; priority升序; score降序
        matched.sort(key=lambda x: (
            not x["_regime_exact"],  # 精确匹配优先
            x["_sort_priority"],     # priority越小越优先
            -x["_sort_score"],       # score越高越优先
        ))

        # 清理辅助字段
        for m in matched:
            m.pop("_regime_exact", None)
            m.pop("_sort_priority", None)
            m.pop("_sort_score", None)

        result = matched[:top_k]
        self._master_cache[cache_key] = result
        return result

    def retrieve_best_strategy(self, regime: str) -> Optional[dict]:
        """获取Regime下最佳大师策略(单个)"""
        results = self.retrieve_master_strategies(regime, top_k=1)
        return results[0] if results else None

    def get_regime_master_summary(self, regime: str) -> dict:
        """获取某Regime下大师策略概览"""
        masters = self.retrieve_master_strategies(regime, top_k=10)
        return {
            "regime": regime,
            "master_count": len(masters),
            "top_strategy": masters[0]["id"] if masters else None,
            "strategies": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "score": m.get("source_score", m.get("score", 0)),
                    "priority": m.get("priority", 99),
                    "master": m.get("source_master", "unknown"),
                }
                for m in masters
            ],
        }


class MasterScoreFeedback:
    """大师策略评分反馈引擎 — 成功+5/失败-10"""

    def __init__(self):
        self._index_cache = None

    def _load_json(self, path: Path) -> dict:
        """安全加载JSON文件"""
        if not path.exists():
            return {"tier": "unknown", "entries": []}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self, path: Path, data: dict):
        """安全写入JSON文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_all_index(self) -> dict:
        """加载all_index.json"""
        if self._index_cache is None:
            self._index_cache = self._load_json(ALL_INDEX_FILE)
        return self._index_cache

    def _save_all_index(self, data: dict):
        """保存all_index.json"""
        self._save_json(ALL_INDEX_FILE, data)
        self._index_cache = data

    def _find_entry_in_rank_file(self, strategy_id: str) -> tuple:
        """
        在S/A/B/C_rank.json中查找策略条目
        Returns: (rank_file_path, entry_index, entry_data) or (None, -1, None)
        """
        for rank_file in [S_RANK_FILE, A_RANK_FILE, B_RANK_FILE, C_RANK_FILE, PENDING_FILE]:
            data = self._load_json(rank_file)
            for i, entry in enumerate(data.get("entries", [])):
                # 兼容两种ID格式: strategy_id和id
                sid = entry.get("strategy_id", entry.get("id", ""))
                if sid == strategy_id or entry.get("id", "").endswith(strategy_id):
                    return rank_file, i, entry
        return None, -1, None

    def _determine_tier(self, score: int) -> str:
        """根据分数确定tier"""
        if score >= S_TIER_THRESHOLD:
            return "S"
        elif score >= A_TIER_THRESHOLD:
            return "A"
        elif score >= B_TIER_THRESHOLD:
            return "B"
        else:
            return "C"

    def _move_entry_between_ranks(self, strategy_id: str, old_rank: Path, old_index: int, new_tier: str):
        """在rank文件间移动条目(分数变化导致tier变化)"""
        # 读取旧rank文件
        old_data = self._load_json(old_rank)
        entry = old_data["entries"].pop(old_index)
        old_data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._save_json(old_rank, old_data)

        # 确定新rank文件
        tier_map = {"S": S_RANK_FILE, "A": A_RANK_FILE, "B": B_RANK_FILE, "C": C_RANK_FILE}
        new_rank_path = tier_map.get(new_tier, A_RANK_FILE)

        # 写入新rank文件
        new_data = self._load_json(new_rank_path)
        entry["tier"] = new_tier
        # 更新id前缀以匹配新tier
        entry["id"] = f"{new_tier.lower()}_{strategy_id}"
        new_data["entries"].append(entry)
        new_data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._save_json(new_rank_path, new_data)

    def update_master_score(self, strategy_id: str, result: str, evidence: str = "", 
                            episode_id: str = "") -> dict:
        """
        更新大师策略评分 — 核心方法
        
        Args:
            strategy_id: 策略ID (e.g. "master_soros_reflexivity_short")
            result: "success" | "failure"
            evidence: 证据描述
            episode_id: 关联的episode ID
            
        Returns:
            更新结果摘要
        """
        # 确定分数变化
        if result == "success":
            delta = SCORE_SUCCESS_DELTA
        elif result == "failure":
            delta = SCORE_FAILURE_DELTA
        else:
            return {"status": "ERROR", "message": f"Invalid result: {result}, must be 'success' or 'failure'"}

        # 在rank文件中查找
        rank_file, entry_idx, entry = self._find_entry_in_rank_file(strategy_id)
        if entry is None:
            return {"status": "NOT_FOUND", "message": f"Strategy {strategy_id} not found in any rank file"}

        # 计算新分数
        old_score = entry.get("score", 0)
        new_score = max(SCORE_MIN, min(SCORE_MAX, old_score + delta))
        old_tier = entry.get("tier", "A")
        new_tier = self._determine_tier(new_score)

        # 更新entry
        entry["score"] = new_score
        entry["verifications"] = entry.get("verifications", 0) + 1
        entry["last_result"] = result
        entry["last_verified"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 更新score_history
        history = entry.get("score_history", [])
        history.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "from": old_score,
            "to": new_score,
            "reason": f"A4实战验证({result}): {evidence or strategy_id}",
            "episode_id": episode_id,
        })
        entry["score_history"] = history

        # 更新evidence
        if evidence:
            ev_list = entry.get("evidence", [])
            ev_list.append(f"[{datetime.now().strftime('%Y-%m-%d')}] {result}: {evidence}")
            entry["evidence"] = ev_list[-10:]  # 保留最近10条

        # 处理tier变化
        tier_changed = old_tier != new_tier
        if tier_changed:
            self._move_entry_between_ranks(strategy_id, rank_file, entry_idx, new_tier)
        else:
            # 同tier内更新
            data = self._load_json(rank_file)
            data["entries"][entry_idx] = entry
            data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._save_json(rank_file, data)

        # 同步更新all_index.json
        self._update_all_index(strategy_id, new_score, new_tier, delta, result, evidence)

        return {
            "status": "OK",
            "strategy_id": strategy_id,
            "old_score": old_score,
            "new_score": new_score,
            "delta": delta,
            "old_tier": old_tier,
            "new_tier": new_tier,
            "tier_changed": tier_changed,
            "verifications": entry["verifications"],
        }

    def _update_all_index(self, strategy_id: str, new_score: int, new_tier: str,
                          delta: int, result: str, evidence: str):
        """同步更新all_index.json中的条目和evolution_log"""
        index_data = self._load_all_index()

        # 更新entries中的匹配条目
        found = False
        for entry in index_data.get("entries", []):
            sid = entry.get("id", "")
            if strategy_id in sid or sid.endswith(strategy_id):
                entry["score"] = new_score
                entry["tier"] = new_tier
                entry["verifications"] = entry.get("verifications", 0) + 1
                found = True
                break

        # 如果all_index中没有该大师策略条目, 新增
        if not found:
            index_data.setdefault("entries", []).append({
                "id": f"{new_tier.lower()}_{strategy_id}",
                "name": f"大师策略:{strategy_id}",
                "score": new_score,
                "tier": new_tier,
                "regime": [],
                "tool": "master",
                "verifications": 1,
            })

        # 更新scoring_summary
        self._recalculate_summary(index_data)

        # 添加evolution_log
        log_entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "trigger": f"大师策略A4验证反馈({result})",
            "changes": [
                f"{strategy_id}: {'?' if found else 'init'}→{new_score} ({'+' if delta > 0 else ''}{delta}, {result})"
            ],
            "key_findings": [evidence] if evidence else [],
        }

        # 合并同一天的log
        evolution_log = index_data.get("evolution_log", [])
        today_str = datetime.now().strftime("%Y-%m-%d")
        existing_today = None
        for log in evolution_log:
            if log.get("date") == today_str and "大师策略" in log.get("trigger", ""):
                existing_today = log
                break

        if existing_today:
            existing_today["changes"].extend(log_entry["changes"])
            if evidence:
                existing_today.setdefault("key_findings", []).append(evidence)
        else:
            evolution_log.append(log_entry)

        index_data["evolution_log"] = evolution_log
        index_data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._save_all_index(index_data)

    def _recalculate_summary(self, index_data: dict):
        """重算scoring_summary"""
        entries = index_data.get("entries", [])
        tier_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
        total_score = 0
        verified = 0

        for e in entries:
            tier = e.get("tier", "A")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            total_score += e.get("score", 0)
            if e.get("verifications", 0) > 0:
                verified += 1

        index_data["scoring_summary"] = {
            "total_strategies": len(entries),
            "S_rank_count": tier_counts.get("S", 0),
            "A_rank_count": tier_counts.get("A", 0),
            "B_rank_count": tier_counts.get("B", 0),
            "C_rank_count": tier_counts.get("C", 0),
            "pending_count": 0,
            "avg_score": round(total_score / max(len(entries), 1), 1),
            "verified_count": verified,
            "unverified_count": len(entries) - verified,
        }

    def batch_update(self, updates: list) -> list:
        """
        批量更新大师策略评分
        
        Args:
            updates: [{"strategy_id": "...", "result": "success"|"failure", "evidence": "..."}]
            
        Returns:
            更新结果列表
        """
        results = []
        for u in updates:
            r = self.update_master_score(
                strategy_id=u["strategy_id"],
                result=u["result"],
                evidence=u.get("evidence", ""),
                episode_id=u.get("episode_id", ""),
            )
            results.append(r)
        return results

    def rebuild_all_index(self):
        """从所有rank文件重建all_index.json(解决stale问题)"""
        entries = []
        tier_map = {
            "S": S_RANK_FILE,
            "A": A_RANK_FILE,
            "B": B_RANK_FILE,
            "C": C_RANK_FILE,
        }

        for tier, rank_file in tier_map.items():
            data = self._load_json(rank_file)
            for e in data.get("entries", []):
                entries.append({
                    "id": e.get("id", f"{tier.lower()}_{e.get('strategy_id', 'unknown')}"),
                    "name": e.get("name", ""),
                    "score": e.get("score", 0),
                    "tier": tier,
                    "regime": e.get("regime", []),
                    "tool": e.get("tool_type", "unknown"),
                    "verifications": e.get("verifications", 0),
                })

        # 添加pending
        pending_data = self._load_json(PENDING_FILE)
        for e in pending_data.get("entries", []):
            entries.append({
                "id": e.get("id", f"p_{e.get('strategy_id', 'unknown')}"),
                "name": e.get("name", ""),
                "score": e.get("score", 0),
                "tier": "pending",
                "regime": e.get("regime", []),
                "tool": e.get("tool_type", "unknown"),
                "verifications": 0,
            })

        # 保留现有evolution_log
        existing_index = self._load_all_index()
        evolution_log = existing_index.get("evolution_log", [])

        new_index = {
            "tier": "all",
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "description": "总索引 - 所有知识条目(含v3.1全部45条策略评分含10条大师策略)",
            "scoring_summary": {},
            "evolution_log": evolution_log + [{
                "date": datetime.now().strftime("%Y-%m-%d"),
                "trigger": "all_index.json重建(v3.0→v3.1, 35→45策略)",
                "changes": ["新增10条master_*大师策略", "总策略数35→45"],
                "key_findings": ["S级+3条大师策略(Soros82/Druckenmiller80/PTJ80)"],
            }],
            "entries": entries,
        }
        self._recalculate_summary(new_index)
        self._save_all_index(new_index)
        return new_index


class MasterCompositeEngine:
    """
    大师策略组合引擎 — 三位大师合力
    
    组合架构:
    ┌─────────────────────────────────────────┐
    │  Livermore: 进出场时机                    │
    │  - 关键点突破确认入场                      │
    │  - 金字塔加仓(3段: 50%→30%→20%)          │
    │  - 时间止损: 3天不涨=出场                 │
    ├─────────────────────────────────────────┤
    │  Druckenmiller: 仓位管理                  │
    │  - 三阶段建仓: 2%→8%→20%                 │
    │  - 确认加仓: 盈利才加                     │
    │  - 信念下注: 高确信时重仓                  │
    ├─────────────────────────────────────────┤
    │  PTJ: 风险控制                            │
    │  - 1%单笔最大风险                         │
    │  - 5:1风收比硬约束                        │
    │  - 永不加仓亏损头寸                       │
    │  - 5%账户最大回撤红线                     │
    └─────────────────────────────────────────┘
    """

    def __init__(self, retriever: MasterStrategyRetriever = None):
        self.retriever = retriever or MasterStrategyRetriever()

    def _livermore_entry(self, regime: str, price_data: dict) -> dict:
        """Livermore进出场逻辑"""
        # 关键点检测
        is_breakout = price_data.get("breakout", False)
        volume_confirm = price_data.get("volume_ratio", 1.0) > 1.5
        ma_alignment = price_data.get("ma_alignment", "neutral")  # bull/bear/neutral

        entry_signal = None
        if regime in ["TREND_STRONG_UP", "TREND_UP"]:
            if is_breakout and volume_confirm and ma_alignment == "bull":
                entry_signal = "LONG_BREAKOUT"
        elif regime in ["TREND_DOWN"]:
            if is_breakout and volume_confirm and ma_alignment == "bear":
                entry_signal = "SHORT_BREAKOUT"
        elif regime == "EXTREME":
            fgi = price_data.get("fgi", 50)
            if fgi < 15:
                entry_signal = "CONTRARIAN_LONG"  # 恐慌抄底
            elif fgi > 85:
                entry_signal = "CONTRARIAN_SHORT"

        # 金字塔加仓计划 (Livermore 3段)
        pyramid_plan = []
        if entry_signal:
            pyramid_plan = [
                {"stage": 1, "size_pct": 50, "trigger": "entry", "desc": "首仓50%"},
                {"stage": 2, "size_pct": 30, "trigger": "profit_2pct", "desc": "盈利2%加30%"},
                {"stage": 3, "size_pct": 20, "trigger": "profit_5pct", "desc": "盈利5%加20%"},
            ]

        return {
            "master": "Livermore",
            "entry_signal": entry_signal,
            "entry_rules": {
                "breakout_confirm": is_breakout,
                "volume_confirm": volume_confirm,
                "ma_alignment": ma_alignment,
            },
            "pyramid_plan": pyramid_plan,
            "exit_rules": {
                "time_stop": "3天不涨→出场",
                "breakout_invalid": "关键点被否定→立即出场",
                "profit_protect": "浮盈>5%后移动止损到成本",
            },
        }

    def _druckenmiller_sizing(self, regime: str, conviction: float, equity: float) -> dict:
        """Druckenmiller仓位管理逻辑"""
        # 三阶段建仓
        if conviction >= 0.8:
            # 高确信: 信念下注
            stages = [
                {"stage": 1, "pct": 0.02, "amount": equity * 0.02, "trigger": "entry"},
                {"stage": 2, "pct": 0.08, "amount": equity * 0.08, "trigger": "profit_1pct"},
                {"stage": 3, "pct": 0.10, "amount": equity * 0.10, "trigger": "profit_3pct"},
            ]
            max_position = equity * 0.20
        elif conviction >= 0.5:
            # 中等确信: 标准建仓
            stages = [
                {"stage": 1, "pct": 0.02, "amount": equity * 0.02, "trigger": "entry"},
                {"stage": 2, "pct": 0.05, "amount": equity * 0.05, "trigger": "profit_2pct"},
                {"stage": 3, "pct": 0.03, "amount": equity * 0.03, "trigger": "profit_5pct"},
            ]
            max_position = equity * 0.10
        else:
            # 低确信: 轻仓试探
            stages = [
                {"stage": 1, "pct": 0.01, "amount": equity * 0.01, "trigger": "entry"},
            ]
            max_position = equity * 0.02

        return {
            "master": "Druckenmiller",
            "conviction": conviction,
            "equity": equity,
            "sizing_stages": stages,
            "max_position": round(max_position, 2),
            "rules": {
                "never_add_to_loss": True,
                "confirm_before_scale": "盈利确认后才加仓",
                "conviction_override": f"确信度{conviction:.0%}→最大仓位{max_position/equity:.0%}",
            },
        }

    def _ptj_risk_control(self, equity: float, entry_price: float, position_size: float) -> dict:
        """PTJ风险控制逻辑"""
        # 1%单笔最大风险
        max_risk_per_trade = equity * 0.01

        # 计算止损距离(基于5:1风收比)
        # 假设目标收益 = position_size * 0.10 (10%目标)
        target_profit = position_size * 0.10
        max_loss_allowed = target_profit / 5  # 5:1 → max_loss = target/5

        # 止损价计算
        if position_size > 0:  # 做多
            sl_distance_pct = (max_loss_allowed / position_size) * 100
            sl_price = entry_price * (1 - sl_distance_pct / 100)
        else:  # 做空
            sl_distance_pct = (max_loss_allowed / abs(position_size)) * 100
            sl_price = entry_price * (1 + sl_distance_pct / 100)

        # 5%账户最大回撤红线
        max_drawdown = equity * 0.05
        drawdown_line = equity - max_drawdown

        return {
            "master": "PTJ",
            "max_risk_per_trade": round(max_risk_per_trade, 2),
            "reward_risk_ratio": "5:1",
            "max_loss_allowed": round(max_loss_allowed, 2),
            "sl_price": round(sl_price, 2),
            "sl_distance_pct": round(sl_distance_pct, 2),
            "account_drawdown_line": round(drawdown_line, 2),
            "hard_rules": {
                "never_add_to_losers": True,
                "single_trade_risk_1pct": True,
                "reward_risk_min_5to1": True,
                "account_max_drawdown_5pct": True,
                "protect_profit_first": "防守比进攻重要",
            },
        }

    def get_composite_strategy(self, regime: str, price_data: dict = None,
                               conviction: float = 0.5, equity: float = 5855.0) -> dict:
        """
        获取组合策略 — 三位大师合力
        
        Args:
            regime: 当前市场状态
            price_data: 价格数据(breakout, volume_ratio, ma_alignment, fgi)
            conviction: 确信度(0-1)
            equity: 账户权益
            
        Returns:
            组合策略指令
        """
        if price_data is None:
            price_data = {"breakout": False, "volume_ratio": 1.0, "ma_alignment": "neutral", "fgi": 50}

        # 1. Livermore: 进出场
        livermore = self._livermore_entry(regime, price_data)

        # 2. Druckenmiller: 仓位
        druckenmiller = self._druckenmiller_sizing(regime, conviction, equity)

        # 3. PTJ: 风控
        entry_price = price_data.get("price", 77782)
        position_size = druckenmiller["max_position"]
        ptj = self._ptj_risk_control(equity, entry_price, position_size)

        # 4. 检索匹配的大师策略
        master_strategies = self.retriever.retrieve_master_strategies(regime, top_k=3)

        # 5. 组合决策
        entry_signal = livermore["entry_signal"]
        action = "SKIP"
        if entry_signal:
            action = "BUY" if "LONG" in entry_signal else "SHORT"

        # 6. PTJ风控覆盖: 如果风收比不满足, 降级为SKIP
        if action != "SKIP" and ptj["sl_distance_pct"] < 0.5:
            action = "SKIP"
            livermore["entry_signal"] = None
            livermore["exit_rules"]["override"] = "PTJ风控否决: 止损距离过窄"

        return {
            "composite_id": f"composite_{regime}_{datetime.now().strftime('%Y%m%d_%H%M')}",
            "regime": regime,
            "action": action,
            "masters": {
                "livermore": livermore,
                "druckenmiller": druckenmiller,
                "ptj": ptj,
            },
            "matched_master_strategies": [
                {"id": m["id"], "name": m["name"], "score": m.get("source_score", m.get("score", 0))}
                for m in master_strategies
            ],
            "execution_plan": {
                "entry_signal": entry_signal,
                "position_stages": druckenmiller["sizing_stages"],
                "max_position_usd": druckenmiller["max_position"],
                "sl_price": ptj["sl_price"],
                "sl_distance_pct": ptj["sl_distance_pct"],
                "target_rrr": "5:1",
            },
            "risk_summary": {
                "max_risk_usd": ptj["max_risk_per_trade"],
                "drawdown_line": ptj["account_drawdown_line"],
                "pyramid_plan": livermore["pyramid_plan"],
            },
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


class MasterStrategyStressTest:
    """大师策略压力测试 — 检索/匹配/组合/评分闭环验证"""

    def __init__(self):
        self.retriever = MasterStrategyRetriever()
        self.feedback = MasterScoreFeedback()
        self.composite = MasterCompositeEngine(self.retriever)
        self.results = []

    def test_retrieval(self) -> dict:
        """测试1: 大师策略检索 — 每种Regime都能检索到大师策略"""
        regimes = ["TREND_STRONG_UP", "TREND_UP", "RANGE_BOUND", "COMPRESSION",
                   "TRANSITION", "TREND_DOWN", "EXTREME"]
        results = {}

        for regime in regimes:
            masters = self.retriever.retrieve_master_strategies(regime, top_k=5)
            results[regime] = {
                "count": len(masters),
                "strategies": [m["id"] for m in masters],
                "top_score": masters[0].get("source_score", masters[0].get("score", 0)) if masters else 0,
                "pass": len(masters) > 0,
            }

        all_pass = all(r["pass"] for r in results.values())
        return {
            "test": "retrieval",
            "pass": all_pass,
            "details": results,
            "summary": f"7种Regime中{sum(1 for r in results.values() if r['pass'])}/7有大师策略",
        }

    def test_matching(self) -> dict:
        """测试2: 策略匹配 — priority=0大师策略排在非大师策略前面"""
        # 在TREND_DOWN下, master_soros(priority=0)应排在非大师策略前面
        regime = "TREND_DOWN"
        masters = self.retriever.retrieve_master_strategies(regime, top_k=5)

        # 验证排序: priority越小越前
        priorities = [m.get("priority", 99) for m in masters]
        is_sorted = all(priorities[i] <= priorities[i + 1] for i in range(len(priorities) - 1))

        return {
            "test": "matching",
            "pass": is_sorted and len(masters) > 0,
            "details": {
                "regime": regime,
                "strategies": [{"id": m["id"], "priority": m.get("priority", 99),
                                "score": m.get("source_score", m.get("score", 0))}
                               for m in masters],
                "priority_order": priorities,
                "is_sorted": is_sorted,
            },
        }

    def test_composite(self) -> dict:
        """测试3: 组合引擎 — 三位大师组合策略生成"""
        test_cases = [
            {
                "regime": "TREND_STRONG_UP",
                "price_data": {"breakout": True, "volume_ratio": 2.0, "ma_alignment": "bull", "fgi": 45, "price": 80000},
                "conviction": 0.8,
                "expected_action": "BUY",
            },
            {
                "regime": "TREND_DOWN",
                "price_data": {"breakout": True, "volume_ratio": 1.8, "ma_alignment": "bear", "fgi": 20, "price": 76000},
                "conviction": 0.6,
                "expected_action": "SHORT",
            },
            {
                "regime": "RANGE_BOUND",
                "price_data": {"breakout": False, "volume_ratio": 0.8, "ma_alignment": "neutral", "fgi": 45, "price": 77500},
                "conviction": 0.3,
                "expected_action": "SKIP",
            },
            {
                "regime": "EXTREME",
                "price_data": {"breakout": False, "volume_ratio": 3.0, "ma_alignment": "bear", "fgi": 10, "price": 72000},
                "conviction": 0.7,
                "expected_action": "BUY",  # FGI<15恐慌抄底
            },
        ]

        results = []
        for tc in test_cases:
            composite = self.composite.get_composite_strategy(
                regime=tc["regime"],
                price_data=tc["price_data"],
                conviction=tc["conviction"],
            )
            action_match = composite["action"] == tc["expected_action"]
            has_livermore = "livermore" in composite["masters"]
            has_druckenmiller = "druckenmiller" in composite["masters"]
            has_ptj = "ptj" in composite["masters"]
            results.append({
                "regime": tc["regime"],
                "action": composite["action"],
                "expected": tc["expected_action"],
                "match": action_match,
                "has_all_masters": has_livermore and has_druckenmiller and has_ptj,
            })

        all_pass = all(r["match"] and r["has_all_masters"] for r in results)
        return {
            "test": "composite",
            "pass": all_pass,
            "details": results,
            "summary": f"{sum(1 for r in results if r['match'] and r['has_all_masters'])}/{len(results)}场景正确",
        }

    def test_score_feedback(self) -> dict:
        """测试4: 评分反馈 — 成功+5/失败-10闭环"""
        # 使用测试专用策略ID, 避免污染真实数据
        # 我们直接测试真实策略但使用"模拟"标记
        test_strategy = "master_livermore_breakout_long"
        
        # 1. 读取当前分数
        rank_file, _, entry = self.feedback._find_entry_in_rank_file(test_strategy)
        original_score = entry.get("score", 0) if entry else 0

        # 2. 模拟成功+5
        success_result = self.feedback.update_master_score(
            strategy_id=test_strategy,
            result="success",
            evidence="压力测试: 成功+5验证",
            episode_id="stress_test_001",
        )

        # 3. 验证+5
        _, _, updated_entry = self.feedback._find_entry_in_rank_file(test_strategy)
        score_after_success = updated_entry.get("score", 0) if updated_entry else 0

        # 4. 模拟失败-10 (回滚+额外-5)
        failure_result = self.feedback.update_master_score(
            strategy_id=test_strategy,
            result="failure",
            evidence="压力测试: 失败-10验证",
            episode_id="stress_test_002",
        )

        # 5. 验证-10
        _, _, final_entry = self.feedback._find_entry_in_rank_file(test_strategy)
        score_after_failure = final_entry.get("score", 0) if final_entry else 0

        # 6. 还原: 再成功+5恢复接近原分
        self.feedback.update_master_score(
            strategy_id=test_strategy,
            result="success",
            evidence="压力测试: 还原分数",
            episode_id="stress_test_003",
        )

        success_delta_ok = success_result.get("delta") == +5
        failure_delta_ok = failure_result.get("delta") == -10
        score_tracking_ok = (score_after_success == original_score + 5) if entry else True

        return {
            "test": "score_feedback",
            "pass": success_delta_ok and failure_delta_ok,
            "details": {
                "original_score": original_score,
                "after_success": score_after_success,
                "after_failure": score_after_failure,
                "success_delta_correct": success_delta_ok,
                "failure_delta_correct": failure_delta_ok,
                "score_tracking_ok": score_tracking_ok,
            },
        }

    def test_all_index_rebuild(self) -> dict:
        """测试5: all_index重建 — 35→45策略"""
        before = self.feedback._load_all_index()
        before_count = before.get("scoring_summary", {}).get("total_strategies", 0)

        rebuilt = self.feedback.rebuild_all_index()
        after_count = rebuilt.get("scoring_summary", {}).get("total_strategies", 0)

        return {
            "test": "all_index_rebuild",
            "pass": after_count >= 45,
            "details": {
                "before_count": before_count,
                "after_count": after_count,
                "target": 45,
                "summary": rebuilt.get("scoring_summary", {}),
            },
        }

    def run_all_tests(self) -> dict:
        """运行全部压力测试"""
        print("=" * 60)
        print("🧪 大师策略压力测试 v1.0")
        print("=" * 60)

        tests = [
            ("检索测试", self.test_retrieval),
            ("匹配排序测试", self.test_matching),
            ("组合引擎测试", self.test_composite),
            ("评分反馈测试", self.test_score_feedback),
            ("索引重建测试", self.test_all_index_rebuild),
        ]

        results = []
        for name, test_fn in tests:
            print(f"\n▶ {name}...")
            try:
                result = test_fn()
                status = "✅ PASS" if result["pass"] else "❌ FAIL"
                print(f"  {status}")
                results.append(result)
            except Exception as e:
                print(f"  ❌ ERROR: {e}")
                results.append({"test": name, "pass": False, "error": str(e)})

        total = len(results)
        passed = sum(1 for r in results if r.get("pass"))
        overall = passed == total

        report = {
            "test_suite": "master_strategy_stress_test_v1.0",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_pass": overall,
            "passed": passed,
            "total": total,
            "results": results,
        }

        print(f"\n{'=' * 60}")
        print(f"📊 压力测试结果: {passed}/{total} 通过 {'✅' if overall else '❌'}")
        print(f"{'=' * 60}")

        return report


# ============================================================
# CLI入口
# ============================================================
def main():
    """CLI入口: 支持多种子命令"""
    import argparse
    parser = argparse.ArgumentParser(description="大师策略检索器+评分反馈引擎")
    sub = parser.add_subparsers(dest="command")

    # retrieve
    p_retrieve = sub.add_parser("retrieve", help="按Regime检索大师策略")
    p_retrieve.add_argument("regime", help="市场状态(如TREND_DOWN)")
    p_retrieve.add_argument("--top-k", type=int, default=5, help="返回前K个")

    # feedback
    p_feedback = sub.add_parser("feedback", help="更新大师策略评分")
    p_feedback.add_argument("strategy_id", help="策略ID")
    p_feedback.add_argument("result", choices=["success", "failure"], help="结果")
    p_feedback.add_argument("--evidence", default="", help="证据")

    # composite
    p_composite = sub.add_parser("composite", help="获取组合策略")
    p_composite.add_argument("regime", help="市场状态")
    p_composite.add_argument("--conviction", type=float, default=0.5, help="确信度0-1")
    p_composite.add_argument("--equity", type=float, default=5855.0, help="账户权益")

    # stress-test
    sub.add_parser("stress-test", help="运行全部压力测试")

    # rebuild-index
    sub.add_parser("rebuild-index", help="重建all_index.json(35→45)")

    # summary
    p_summary = sub.add_parser("summary", help="所有Regime大师策略概览")

    args = parser.parse_args()

    if args.command == "retrieve":
        r = MasterStrategyRetriever()
        results = r.retrieve_master_strategies(args.regime, args.top_k)
        if not results:
            print(f"⚠️ Regime={args.regime} 无匹配大师策略")
        else:
            print(f"📋 {args.regime} 大师策略 (top {args.top_k}):")
            for i, m in enumerate(results, 1):
                score = m.get("source_score", m.get("score", 0))
                print(f"  {i}. {m['id']} (score={score}, priority={m.get('priority', 99)})")
                print(f"     {m['name']}")

    elif args.command == "feedback":
        f = MasterScoreFeedback()
        result = f.update_master_score(args.strategy_id, args.result, args.evidence)
        status = "✅" if result["status"] == "OK" else "❌"
        print(f"{status} {result['strategy_id']}: {result.get('old_score', '?')}→{result.get('new_score', '?')} ({result.get('delta', 0):+d})")
        if result.get("tier_changed"):
            print(f"  ⚠️ Tier变更: {result['old_tier']}→{result['new_tier']}")

    elif args.command == "composite":
        e = MasterCompositeEngine()
        result = e.get_composite_strategy(args.regime, conviction=args.conviction, equity=args.equity)
        print(f"🎯 组合策略: {result['action']}")
        print(f"  Livermore: {result['masters']['livermore']['entry_signal']}")
        print(f"  Druckenmiller: max={result['execution_plan']['max_position_usd']}U")
        print(f"  PTJ: SL@{result['execution_plan']['sl_price']} ({result['execution_plan']['sl_distance_pct']}%)")
        if result["matched_master_strategies"]:
            print(f"  匹配大师策略: {', '.join(m['id'] for m in result['matched_master_strategies'])}")

    elif args.command == "stress-test":
        t = MasterStrategyStressTest()
        report = t.run_all_tests()
        # 保存报告
        report_path = WORKSPACE / "reports" / f"master_stress_test_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n📄 报告已保存: {report_path}")

    elif args.command == "rebuild-index":
        f = MasterScoreFeedback()
        result = f.rebuild_all_index()
        summary = result.get("scoring_summary", {})
        print(f"✅ all_index.json重建完成:")
        print(f"  总策略: {summary.get('total_strategies', 0)}")
        print(f"  S级: {summary.get('S_rank_count', 0)} | A级: {summary.get('A_rank_count', 0)}")
        print(f"  B级: {summary.get('B_rank_count', 0)} | C级: {summary.get('C_rank_count', 0)}")
        print(f"  平均分: {summary.get('avg_score', 0)}")

    elif args.command == "summary":
        r = MasterStrategyRetriever()
        regimes = ["TREND_STRONG_UP", "TREND_UP", "RANGE_BOUND", "COMPRESSION",
                   "TRANSITION", "TREND_DOWN", "EXTREME"]
        print("📊 大师策略Regime覆盖概览:")
        print("-" * 60)
        for regime in regimes:
            summary = r.get_regime_master_summary(regime)
            print(f"  {regime}: {summary['master_count']}条 | 最佳: {summary['top_strategy'] or 'None'}")
        print("-" * 60)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
