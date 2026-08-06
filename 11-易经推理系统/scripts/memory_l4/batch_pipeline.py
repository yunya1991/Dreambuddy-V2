"""
批量执行L4 Pipeline处理所有episode文件
"""
import sys
from pathlib import Path
import json
from datetime import datetime

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.pipeline import run_pipeline
from scripts.memory_l4.kg_store import KGStore
from scripts.memory_l4.paths import episodes_dir as _default_episodes_dir, workspace_root


def evaluate_candidates():
    """B-5修复：M4 候选评估器 — 扫描 feedback/CAND_*.json，执行 C0→C3 升级。

    状态流转：
      C0_COLLECTED → C1_AUDIT_PASS → C2_SANDBOX_PASS → C3_APPROVED

    评估规则：
      - C0→C1 (audit): claim 非空 + actionable_rules 非空 + quadrant.y >= 0
      - C1→C2 (sandbox): quadrant.x >= 0（一致性通过）或 source 为 sim
      - C2→C3 (approved): quadrant.y >= 0.3（足够高质量）

    C3_APPROVED 的候选的 actionable_rules 会被收集，
    供 SelfEvolutionEngine 在下次 run_full_cycle 时作为额外 proposal 源。
    """
    feedback_dir = workspace_root() / "artifacts" / "evolution" / "feedback"
    if not feedback_dir.exists():
        return {"evaluated": 0, "approved": 0}

    cand_files = sorted(feedback_dir.glob("CAND_*.json"))
    evaluated = 0
    promoted = {"C1_AUDIT_PASS": 0, "C2_SANDBOX_PASS": 0, "C3_APPROVED": 0}
    approved_rules = []

    for cf in cand_files:
        try:
            cand = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            continue

        current_status = cand.get("evolution_status", "C0_COLLECTED")
        if current_status == "C3_APPROVED":
            # 已批准，收集 rules
            for r in cand.get("actionable_rules", []):
                approved_rules.append(r)
            continue

        changed = False

        # C0→C1: audit
        if current_status == "C0_COLLECTED":
            claim = cand.get("claim", "")
            rules = cand.get("actionable_rules", [])
            y = cand.get("quadrant", {}).get("y", 0)
            if claim and rules and y >= 0:
                cand["evolution_status"] = "C1_AUDIT_PASS"
                cand.setdefault("audit_result", {
                    "pass": True,
                    "checked_at": datetime.now().isoformat(),
                })
                changed = True
                promoted["C1_AUDIT_PASS"] += 1
                current_status = "C1_AUDIT_PASS"

        # C1→C2: sandbox
        if current_status == "C1_AUDIT_PASS":
            x = cand.get("quadrant", {}).get("x", 0)
            case_id = cand.get("case_id", "")
            # sim case 自动通过 sandbox（已有回测数据）
            if x >= 0 or "sim_" in case_id:
                cand["evolution_status"] = "C2_SANDBOX_PASS"
                cand.setdefault("sandbox_result", {
                    "pass": True,
                    "checked_at": datetime.now().isoformat(),
                })
                changed = True
                promoted["C2_SANDBOX_PASS"] += 1
                current_status = "C2_SANDBOX_PASS"

        # C2→C3: approved
        if current_status == "C2_SANDBOX_PASS":
            y = cand.get("quadrant", {}).get("y", 0)
            if y >= 0.3:
                cand["evolution_status"] = "C3_APPROVED"
                cand.setdefault("approval_result", {
                    "pass": True,
                    "checked_at": datetime.now().isoformat(),
                })
                changed = True
                promoted["C3_APPROVED"] += 1
                for r in cand.get("actionable_rules", []):
                    approved_rules.append(r)

        if changed:
            cf.write_text(json.dumps(cand, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
            evaluated += 1

    # 将 approved rules 保存为 SelfEvolutionEngine 可消费的文件
    if approved_rules:
        rules_dir = workspace_root() / "data" / "self_evolution"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules_file = rules_dir / "approved_rules.json"
        rules_file.write_text(
            json.dumps(approved_rules, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8"
        )

    print(f"\n[B-5] 候选评估完成: {evaluated} promoted, {promoted}")
    if approved_rules:
        print(f"[B-5] {len(approved_rules)} 条 approved rules 已保存")

    return {
        "evaluated": evaluated,
        "promoted": promoted,
        "approved_rules_count": len(approved_rules),
    }


def batch_process_episodes(episodes_dir: str = None, limit: int = None) -> dict:
    """批量处理所有episode文件"""
    if episodes_dir is None:
        episodes_dir = _default_episodes_dir()
    else:
        episodes_dir = Path(episodes_dir)

    if not episodes_dir.exists():
        return {"error": f"Episodes directory not found: {episodes_dir}"}

    episode_files = sorted(episodes_dir.glob("*.json"))
    
    if limit:
        episode_files = episode_files[:limit]
    
    print(f"Found {len(episode_files)} episode files to process\n")
    
    results = []
    success_count = 0
    fail_count = 0
    
    for i, ep_path in enumerate(episode_files, 1):
        print(f"[{i}/{len(episode_files)}] Processing: {ep_path.name}")
        try:
            result = run_pipeline(ep_path)
            results.append({
                "episode": str(ep_path),
                "status": "success",
                "case_id": result.get("case", {}).get("case_id"),
                "l4_status": result.get("case", {}).get("l4_status"),
            })
            success_count += 1
            print(f"  ✅ Success: {result.get('case', {}).get('l4_status')}")
        except Exception as e:
            results.append({
                "episode": str(ep_path),
                "status": "failed",
                "error": str(e),
            })
            fail_count += 1
            print(f"  ❌ Failed: {e}")
    
    # KG stats
    kg_stats = {}
    try:
        store = KGStore()
        kg_stats = store.get_stats()
    except Exception as e:
        kg_stats = {"error": str(e)}
    
    summary = {
        "total": len(episode_files),
        "success": success_count,
        "failed": fail_count,
        "results": results,
        "kg_stats": kg_stats,
        "processed_at": datetime.now().isoformat(),
    }
    
    print(f"\n{'='*60}")
    print(f"Batch Pipeline Summary")
    print(f"{'='*60}")
    print(f"Total: {len(episode_files)}")
    print(f"Success: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"\nKG Stats:")
    if "error" not in kg_stats:
        print(f"  Triples: {kg_stats.get('triple_count', 'N/A')}")
        print(f"  Entities: {kg_stats.get('entity_count', 'N/A')}")
        print(f"  Predicates: {list(kg_stats.get('predicate_distribution', {}).keys())[:5]}")

    # B-5修复：批量处理完成后自动执行候选评估
    eval_result = evaluate_candidates()
    summary["candidate_evaluation"] = eval_result

    return summary


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Batch L4 Pipeline")
    parser.add_argument("--episodes-dir", type=str, default=None, help="Episodes directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of episodes to process")
    parser.add_argument("--out", type=str, default=None, help="Output result file")
    args = parser.parse_args()
    
    result = batch_process_episodes(args.episodes_dir, args.limit)
    
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\nResult saved to: {out_path}")


if __name__ == "__main__":
    main()
