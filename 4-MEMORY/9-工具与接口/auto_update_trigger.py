#!/usr/bin/env python3
"""
自动更新触发器 — 开发后自动执行 A8 校验 + 文档/记忆同步 + 贝叶斯更新

功能：
1. 对指定子系统执行 A8 校验
2. 如一致性得分 < 80%，生成文档更新建议
3. 将更新内容同步到对应记忆单元 MU-CORE
4. 使用贝叶斯定理更新记忆置信度（Beta 更新环节）

用法：
    python3 auto_update_trigger.py <子系统目录> [--sync-memory]

示例：
    python3 auto_update_trigger.py /path/to/16-调控系统 --sync-memory
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from a8_check_engine import run_a8_check, print_report
from bayesian_memory_updater import BayesianMemoryUpdater, create_default_memories


def generate_doc_update_suggestions(report_path: Path) -> list:
    """根据 A8 报告生成文档更新建议。"""
    if not report_path.exists():
        return []

    data = json.loads(report_path.read_text(encoding="utf-8"))
    suggestions = []

    # 建议1: 文档超前（未实现）— 需要确认是否已删除或改名
    for func in data.get("doc_only_functions", [])[:5]:
        suggestions.append({
            "type": "doc_ahead",
            "function": func,
            "action": "确认代码中是否已删除/改名，如已删除则从 API_SPEC 中移除",
            "priority": "P1",
        })

    # 建议2: 代码超前（未文档化）— 需要补充到 API_SPEC
    for func in data.get("code_only_functions", [])[:10]:
        suggestions.append({
            "type": "code_ahead",
            "function": func,
            "action": "新增到 API_SPEC.md 对应章节，补充签名、参数、返回值",
            "priority": "P2",
        })

    return suggestions


def sync_to_memory_unit(subsystem_name: str, score: float, suggestions: list) -> Path:
    """将 A8 校验结果同步到对应记忆单元 MU-CORE。"""

    # 路由到对应记忆单元
    mu_map = {
        "16-调控系统": "MU-DEV",
        "11-易经推理系统": "MU-TRD",
        "10-经典指标系统": "MU-TRD",
        "12-三屏趋势系统": "MU-TRD",
        "13-通用风控模块": "MU-TRD",
        "14-V15经典马丁策略": "MU-TRD",
    }
    mu_code = mu_map.get(subsystem_name, "MU-DEV")

    mu_dir = Path(__file__).parent.parent / {
        "MU-DEV": "1-开发记忆单元",
        "MU-TRD": "2-交易记忆单元",
        "MU-DOC": "3-文档记忆单元",
        "MU-INF": "4-信息记忆单元",
    }.get(mu_code, "1-开发记忆单元")

    core_path = mu_dir / f"{mu_code}-CORE.md"
    if not core_path.exists():
        return None

    # 读取现有 CORE
    content = core_path.read_text(encoding="utf-8")

    # 检查是否已有 A8 状态段落
    a8_section = f"\n## A8 校验状态（自动更新）\n\n"
    a8_section += f"- **子系统**: {subsystem_name}\n"
    a8_section += f"- **最后校验**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    a8_section += f"- **一致性得分**: {score}%\n"
    a8_section += f"- **待处理项**: {len(suggestions)} 项\n"

    if suggestions:
        a8_section += "- **重点问题**:\n"
        for s in suggestions[:5]:
            a8_section += f"  - [{s['priority']}] {s['function']}: {s['action']}\n"

    # 如果已有 A8 状态段落，替换它；否则追加到文件末尾
    if "## A8 校验状态" in content:
        content = re.sub(
            r"## A8 校验状态.*?\n(?=## |\Z)",
            a8_section + "\n",
            content,
            flags=re.DOTALL,
        )
    else:
        content = content.rstrip() + "\n" + a8_section

    core_path.write_text(content, encoding="utf-8")
    return core_path


def run_bayesian_update(subsystem_name: str, report_dict: dict) -> dict:
    """
    运行贝叶斯更新，基于 A8 校验结果更新记忆置信度。
    
    Args:
        subsystem_name: 子系统名称
        report_dict: A8 校验报告字典
        
    Returns:
        贝叶斯更新结果
    """
    mu_map = {
        "16-调控系统": "MU-DEV",
        "11-易经推理系统": "MU-TRD",
        "10-经典指标系统": "MU-TRD",
        "12-三屏趋势系统": "MU-TRD",
        "13-通用风控模块": "MU-TRD",
        "14-V15经典马丁策略": "MU-TRD",
    }
    mu_code = mu_map.get(subsystem_name, "MU-DEV")
    
    mu_dir = Path(__file__).parent.parent / {
        "MU-DEV": "1-开发记忆单元",
        "MU-TRD": "2-交易记忆单元",
        "MU-DOC": "3-文档记忆单元",
        "MU-INF": "4-信息记忆单元",
    }.get(mu_code, "1-开发记忆单元")
    
    if not mu_dir.exists():
        return {"status": "skip", "reason": f"记忆单元目录不存在: {mu_dir}"}
    
    updater = BayesianMemoryUpdater(mu_dir)
    
    # 如果没有记忆数据，初始化默认记忆
    if not updater.memories:
        updater = create_default_memories(mu_dir)
        print("   ℹ️  已初始化默认记忆")
    
    # 处理 A8 报告，更新置信度
    results = updater.process_a8_report(report_dict)
    
    # 获取统计信息
    stats = updater.get_stats()
    
    return {
        "status": "success",
        "updater": updater,
        "updated_count": len(results),
        "stats": stats,
        "results": {
            k: {"confidence": round(v[0], 4), "level": v[1]}
            for k, v in results.items()
        }
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 auto_update_trigger.py <子系统目录> [--sync-memory] [--bayes-update]")
        print("示例: python3 auto_update_trigger.py /path/to/16-调控系统 --sync-memory --bayes-update")
        return 1

    subsystem_dir = Path(sys.argv[1])
    sync_memory = "--sync-memory" in sys.argv
    bayes_update = "--bayes-update" in sys.argv

    if not subsystem_dir.exists():
        print(f"错误: 目录不存在: {subsystem_dir}")
        return 1

    subsystem_name = subsystem_dir.name
    print(f"🚀 自动更新触发: {subsystem_name}")
    print(f"{'='*60}")

    # Step 1: A8 校验
    print("\n[Step 1/4] 执行 A8 理论实践校验...")
    report = run_a8_check(subsystem_dir)
    print_report(report)

    # Step 2: 生成更新建议
    print("[Step 2/4] 生成文档更新建议...")
    report_path = subsystem_dir / "a8_report.json"
    report_dict = report.to_dict()
    suggestions = generate_doc_update_suggestions(report_path)

    if suggestions:
        print(f"\n📋 发现 {len(suggestions)} 项需要更新:")
        for s in suggestions[:10]:
            icon = "⚠️" if s["type"] == "doc_ahead" else "❓"
            print(f"   {icon} [{s['priority']}] {s['function']}: {s['action']}")
    else:
        print("   ✅ 无需更新")

    # Step 3: 同步到记忆单元
    if sync_memory:
        print("\n[Step 3/4] 同步到记忆单元 MU-CORE...")
        core_path = sync_to_memory_unit(subsystem_name, report.score, suggestions)
        if core_path:
            print(f"   ✅ 已同步: {core_path}")
        else:
            print(f"   ⚠️ 未找到对应记忆单元")
    else:
        print(f"\n[Step 3/4] 跳过记忆同步（加 --sync-memory 启用）")

    # Step 4: 贝叶斯更新（可选）
    if bayes_update:
        print("\n[Step 4/4] 执行贝叶斯记忆更新...")
        bayes_result = run_bayesian_update(subsystem_name, report_dict)
        
        if bayes_result["status"] == "success":
            stats = bayes_result["stats"]
            print(f"   ✅ 已更新 {bayes_result['updated_count']} 条记忆")
            print(f"   📊 记忆统计:")
            print(f"      - 总数: {stats['total']}")
            print(f"      - 质量分布: {stats['by_quality']}")
            print(f"      - 平均置信度: {stats['avg_confidence']}")
            
            # 显示更新详情
            if bayes_result["results"]:
                print(f"\n   📝 记忆更新详情:")
                for mid, info in list(bayes_result["results"].items())[:5]:
                    print(f"      - {mid}: 置信度 {info['confidence']:.2f} → 等级 {info['level']}")
        else:
            print(f"   ⚠️  {bayes_result.get('reason', '未知原因')}")
    else:
        print(f"\n[Step 4/4] 跳过贝叶斯更新（加 --bayes-update 启用）")

    # 最终判断
    print(f"\n{'='*60}")
    if report.score >= 80:
        print(f"✅ {subsystem_name} 一致性达标 ({report.score}%)，无需更新")
        return 0
    else:
        print(f"⚠️  {subsystem_name} 一致性未达标 ({report.score}%)，请按上述建议更新文档")
        if not sync_memory:
            print(f"💡 运行加 --sync-memory --bayes-update 可同步记忆并执行贝叶斯更新")
        return 1


if __name__ == "__main__":
    import re
    sys.exit(main())


# ============================================================
# P3: Suggestions 定时刷新（TTL + 动作计数 双触发）
# ============================================================

import os as _os
import re as _re
import time as _time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from cognitive_session import CognitiveSessionManager, CognitiveSession


DEFAULT_SUGGESTIONS_TTL = 15 * 60          # 15 分钟未刷新则强制刷新
DEFAULT_SUGGESTIONS_ACTION_THRESHOLD = 5   # 5 个新动作则触发刷新（即使 TTL 未到）
META_FILE = "suggestions_meta.json"


class SuggestionsRefresher:
    """
    会话级 suggestions 自动刷新器。

    设计原则：
    - 双触发：TTL 过期 OR 动作数>=阈值 任一即可
    - 持久化 refresh_count 到 <session_dir>/suggestions_meta.json（进程间共享计数）
    - 不重写 CognitiveSessionManager，只复用其 _inject_recall 生成 suggestions.md
    - NOOP 安全：无 session / 无 suggestions / 无 task_type 时直接返回 False
    """

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_SUGGESTIONS_TTL,
        action_threshold: int = DEFAULT_SUGGESTIONS_ACTION_THRESHOLD,
    ):
        self.ttl_seconds = int(ttl_seconds)
        self.action_threshold = int(action_threshold)

    # ---------- 内部：会话目录 / 元数据 ----------

    @staticmethod
    def _session_dir(manager: "CognitiveSessionManager") -> Optional[Path]:
        if not manager or not manager.current_session:
            return None
        return Path(manager.sessions_dir) / manager.current_session.id

    @staticmethod
    def _read_meta(sdir: Path) -> dict:
        meta_path = sdir / META_FILE
        if not meta_path.exists():
            return {"refresh_count": 0, "actions_at_last_refresh": 0,
                    "last_refresh_ts": 0.0}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"refresh_count": 0, "actions_at_last_refresh": 0,
                    "last_refresh_ts": 0.0}

    @staticmethod
    def _write_meta(sdir: Path, meta: dict) -> None:
        meta_path = sdir / META_FILE
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError:
            pass

    # ---------- should_refresh 判断 ----------

    def should_refresh(self, manager_or_session,
                       actions_since_last: int = 0) -> bool:
        """
        判断是否需要刷新。

        参数可以是 CognitiveSessionManager（可做 TTL 检查）或 CognitiveSession
       （仅做动作计数检查）。
        """
        session = None
        sdir = None

        # 解包 manager vs session
        cls_name = type(manager_or_session).__name__
        if cls_name == "CognitiveSessionManager":
            session = getattr(manager_or_session, "current_session", None)
            sdir = self._session_dir(manager_or_session)
        else:
            # 当作 session 直接使用
            session = manager_or_session

        if session is None:
            return False
        if not getattr(session, "id", None) or not getattr(session, "task_type", None):
            return False

        # 1) 动作计数（任何情况下都判定）
        if actions_since_last >= self.action_threshold:
            return True

        # 2) TTL 过期判定（需要 filesystem + session_dir）
        if sdir is not None:
            sug_file = sdir / "suggestions.md"
            if sug_file.exists():
                try:
                    age = _time.time() - sug_file.stat().st_mtime
                    if age > self.ttl_seconds:
                        return True
                except OSError:
                    pass
        return False

    # ---------- 核心：判断 + 执行 ----------

    def refresh_if_needed(self, manager: "CognitiveSessionManager",
                          actions_since_last: int = 0) -> bool:
        """
        如果需要刷新则执行并重写 suggestions.md，返回是否实际刷新。
        """
        sdir = self._session_dir(manager)
        if sdir is None:
            return False

        sug_file = sdir / "suggestions.md"
        if not sug_file.exists():
            # 尚无建议文件，交给正常的 _inject_recall 首次创建（此处不抢跑）
            return False

        # --- 双触发判断 ---
        need = False
        reason = ""
        now = _time.time()
        try:
            age = now - sug_file.stat().st_mtime
        except OSError:
            age = self.ttl_seconds + 1  # 读不到 mtime 按过期处理
        if age > self.ttl_seconds:
            need = True
            reason = f"TTL过期 ({int(age)}s > {self.ttl_seconds}s)"
        elif actions_since_last >= self.action_threshold:
            need = True
            reason = f"动作数触发 ({actions_since_last} >= {self.action_threshold})"

        if not need:
            return False

        # --- 执行刷新 ---
        session = manager.current_session
        meta = self._read_meta(sdir)
        meta["refresh_count"] = int(meta.get("refresh_count", 0)) + 1
        meta["actions_at_last_refresh"] = int(
            getattr(session, "total_actions", 0) or 0
        ) + actions_since_last
        meta["last_refresh_ts"] = now
        meta["last_refresh_reason"] = reason

        # 复用 manager._inject_recall：生成最新的 recall 结果并重写 suggestions.md
        # evolved=False → 覆盖（整体重写）
        try:
            # 临时 monkey-patch 一个 hook 确保我们的标记能被写入
            manager._inject_recall(session, evolved=False)
        except Exception:
            # 刷新失败不应阻塞；恢复为 False
            return False

        # 把 "🔄 刷新第 N 次" 加到 suggestions.md 头部
        self._stamp_refresh_marker(sug_file, meta["refresh_count"], reason)

        # 写 meta（计数持久化）
        self._write_meta(sdir, meta)
        return True

    @staticmethod
    def _stamp_refresh_marker(sug_file: Path, refresh_count: int, reason: str) -> None:
        """在 suggestions.md 首行之后插入刷新标记，方便人眼识别是第几轮刷新。"""
        try:
            text = sug_file.read_text(encoding="utf-8")
        except OSError:
            return
        stamp = (f"# 🔄 刷新第 {refresh_count} 次  "
                 f"| {_time.strftime('%Y-%m-%d %H:%M:%S')}  |  触发: {reason}\n")
        if text.startswith("# 💡"):
            first_nl = text.find("\n")
            if first_nl != -1:
                # 插在首行标题之后
                new_text = text[:first_nl] + "\n" + stamp + text[first_nl + 1:]
            else:
                new_text = text + "\n" + stamp
        else:
            new_text = stamp + "\n" + text
        try:
            sug_file.write_text(new_text, encoding="utf-8")
        except OSError:
            pass

