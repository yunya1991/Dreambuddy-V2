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


def batch_process_episodes(episodes_dir: str = None, limit: int = None) -> dict:
    """批量处理所有episode文件"""
    if episodes_dir is None:
        episodes_dir = _ROOT.parent / "data" / "episodes"
    else:
        episodes_dir = Path(episodes_dir)
    
    if not episodes_dir.exists():
        return {"error": f"Episodes directory not found: {episodes_dir}"}
    
    episode_files = sorted(episodes_dir.glob("sim_*.json"))
    
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
