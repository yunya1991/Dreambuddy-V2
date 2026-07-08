import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scripts.memory_l4.failure_analyzer import analyze_failure_memory
from scripts.memory_l4.memory_graph import build_memory_graph
from scripts.memory_l4.meta_learning_tasks import enqueue_meta_learning_tasks
from scripts.memory_l4.migration_mapper import build_cross_market_migration
from scripts.memory_l4.shared_memory_bus import publish_shared_memory_event
from workflows.memory.memory_engine.consistency import check_consistency_report
from workflows.memory.memory_engine.health import compute_health_score
from workflows.memory.memory_engine.optimizer import score_with_ucb, update_bandit_scores, write_bandit_audit_artifact
from workflows.memory.memory_engine.retrievers.structured import retrieve_structured
from workflows.memory.memory_engine.retrievers.semantic import retrieve_semantic, write_vector_artifacts


StructuredRetriever = Callable[[Dict[str, Any], int], List[Dict[str, Any]]]
SemanticRetriever = Callable[[Dict[str, Any], int], List[Dict[str, Any]]]
PineconeRetriever = Callable[[Dict[str, Any], int], List[Dict[str, Any]]]


class MemoryEngine:
    def __init__(
        self,
        structured_retriever: Optional[StructuredRetriever] = None,
        semantic_retriever: Optional[SemanticRetriever] = None,
        pinecone_retriever: Optional[PineconeRetriever] = None,
        index_data: Optional[Dict[str, Any]] = None,
        index_path: Optional[Path] = None,
        vector_dir: Optional[Path] = None,
        audit_dir: Optional[Path] = None,
        max_audit_files_per_day: int = 200,
        bandit_state_path: Optional[Path] = None,
        cases: Optional[List[Dict[str, Any]]] = None,
        distills: Optional[List[Dict[str, Any]]] = None,
        stats: Optional[Dict[str, Any]] = None,
        episodes_by_path: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._structured_retriever = structured_retriever
        self._semantic_retriever = semantic_retriever
        self._pinecone_retriever = pinecone_retriever
        self._index_data = index_data
        self._index_path = index_path or Path(".workbuddy/memory_l4/index/latest.json")
        self._vector_dir = vector_dir or Path(".workbuddy/memory_l4/index/vector")
        self._audit_dir = audit_dir or Path("artifacts/memory_engine")
        self._max_audit_files_per_day = max(1, int(max_audit_files_per_day))
        self._bandit_state_path = Path(bandit_state_path) if bandit_state_path is not None else Path(".workbuddy/memory_l4/bandit_state/latest.json")
        self._cases = cases
        self._distills = distills
        self._stats = stats
        self._episodes_by_path = episodes_by_path

    def retrieve_for_decision(self, context: Dict[str, Any], topk: int = 10) -> Dict[str, Any]:
        structured_source = {"kind": "index_engine", "index_path": str(self._index_path)}
        if self._structured_retriever is not None:
            structured = self._structured_retriever(context, int(topk))
            structured_source = {"kind": "custom_retriever"}
        else:
            structured = retrieve_structured(context, int(topk), self._index_data, self._index_path)

        semantic_source = {"kind": "memory_fallback"}
        if self._semantic_retriever is not None:
            semantic = self._semantic_retriever(context, int(topk))
            semantic_source = {"kind": "custom_retriever"}
        else:
            use_pinecone = bool(context.get("use_pinecone"))
            pinecone_error: Optional[str] = None
            semantic = []
            if use_pinecone and self._pinecone_retriever is not None:
                try:
                    semantic = self._pinecone_retriever(context, int(topk))
                    semantic_source = {"kind": "pinecone"}
                except Exception as e:
                    pinecone_error = str(e)

            if not semantic:
                semantic = retrieve_semantic(
                    context,
                    int(topk),
                    self._cases or [],
                    self._distills or [],
                    vector_dir=self._vector_dir,
                )
                if semantic:
                    semantic_source = dict((semantic[0].get("vector_source") or {"kind": "memory_fallback"}))
                if pinecone_error:
                    semantic_source["pinecone_error"] = pinecone_error

        merged = self._merge_rankings(structured, semantic)
        out = {
            "structured_topk": structured,
            "semantic_topk": semantic,
            "merged": merged,
            "audit": {
                "structured_source": structured_source,
                "semantic_source": semantic_source,
                "merge_rule": {
                    "version": "v0.1",
                    "formula": "0.7*structured + 0.3*semantic",
                    "semantic_fallback": "structured_only",
                },
                "artifact_path": None,
            },
        }

        if bool(context.get("write_audit_artifact")):
            try:
                out["audit"]["artifact_path"] = self._write_retrieve_audit(context, out)
            except Exception as e:
                out["audit"]["artifact_error"] = str(e)
        return out

    def _merge_rankings(self, structured: List[Dict[str, Any]], semantic: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        for item in structured:
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            by_id[item_id] = {
                "id": item_id,
                "kind": item.get("kind"),
                "refs": item.get("refs") or {},
                "structured_score": float(item.get("score") or 0.0),
                "semantic_score": 0.0,
            }
        for item in semantic:
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            current = by_id.get(item_id)
            if current is None:
                current = {
                    "id": item_id,
                    "kind": item.get("kind"),
                    "refs": item.get("refs") or {},
                    "structured_score": 0.0,
                    "semantic_score": 0.0,
                }
                by_id[item_id] = current
            current["semantic_score"] = float(item.get("score") or 0.0)
            if not current.get("refs"):
                current["refs"] = item.get("refs") or {}

        merged: List[Dict[str, Any]] = []
        for item in by_id.values():
            structured_score = float(item.get("structured_score") or 0.0)
            semantic_score = float(item.get("semantic_score") or 0.0)
            if semantic_score <= 0.0:
                merged_score = structured_score
            else:
                merged_score = 0.7 * structured_score + 0.3 * semantic_score
            out = dict(item)
            out["merged_score"] = round(float(merged_score), 2)
            merged.append(out)

        merged.sort(key=lambda x: float(x.get("merged_score") or 0.0), reverse=True)
        return merged

    def _write_retrieve_audit(self, context: Dict[str, Any], result: Dict[str, Any]) -> str:
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        stamp = ts.replace(":", "").replace("-", "")
        day = ts[:10]
        day_dir = self._audit_dir / day
        day_dir.mkdir(parents=True, exist_ok=True)
        trace_id = str(context.get("trace_id") or "no-trace")
        filename = f"retrieve_audit_{trace_id}_{stamp}.json"
        path = day_dir / filename

        payload = {
            "audit_schema_version": "v0.1",
            "ts": ts,
            "trace_id": trace_id,
            "request": context,
            "result": result,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._rotate_audit_files(day_dir)
        return str(path)

    def _rotate_audit_files(self, day_dir: Path) -> None:
        files = sorted([p for p in day_dir.glob("*.json") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[self._max_audit_files_per_day :]:
            p.unlink(missing_ok=True)

    def check_consistency(self) -> Dict[str, Any]:
        return check_consistency_report(
            index_data=self._index_data,
            index_path=self._index_path,
            cases=self._cases,
            distills=self._distills,
            stats=self._stats,
            episodes_by_path=self._episodes_by_path,
        )

    def get_health_score(self) -> float:
        report = self.check_consistency()
        return compute_health_score(report, self._index_data)

    def build_vector_artifacts(self, vector_dir: Path) -> Dict[str, Any]:
        index_metadata = None
        if isinstance(self._index_data, dict):
            meta = self._index_data.get("metadata")
            if isinstance(meta, dict):
                index_metadata = meta
        return write_vector_artifacts(
            vector_dir=Path(vector_dir),
            cases=self._cases or [],
            distills=self._distills or [],
            index_metadata=index_metadata,
        )

    def build_relevance_matrix(self, context: Dict[str, Any], topk: int = 10) -> Dict[str, Any]:
        decision = self.retrieve_for_decision(context, topk=topk)
        perf_weight_by_id = context.get("performance_weight_by_id") or {}
        use_bandit = bool(context.get("use_bandit"))
        bandit_state = self._load_bandit_state() if use_bandit else {}
        total_steps = sum(max(0, int((v or {}).get("n") or 0)) for v in (bandit_state or {}).values())

        items: List[Dict[str, Any]] = []
        for row in (decision.get("merged") or []):
            item_id = str(row.get("id") or "")
            structured_score = float(row.get("structured_score") or 0.0)
            semantic_score = float(row.get("semantic_score") or 0.0)
            merged_score = float(row.get("merged_score") or 0.0)
            perf_w = float(perf_weight_by_id.get(item_id) or 0.0)
            bandit_w = score_with_ucb(item_id, bandit_state, total_steps=max(1, total_steps)) if use_bandit else 0.0
            relevance = 0.5 * merged_score + 0.1 * semantic_score + 0.4 * perf_w + 0.1 * bandit_w
            items.append(
                {
                    "id": item_id,
                    "kind": row.get("kind"),
                    "refs": row.get("refs") or {},
                    "components": {
                        "structured": round(structured_score, 4),
                        "semantic": round(semantic_score, 4),
                        "performance_weight": round(perf_w, 4),
                        "bandit_weight": round(bandit_w, 4),
                    },
                    "relevance": round(relevance, 4),
                }
            )

        items.sort(key=lambda x: float(x.get("relevance") or 0.0), reverse=True)
        matrix = [[item["components"]["structured"], item["components"]["semantic"], item["components"]["performance_weight"], item["relevance"]] for item in items]
        return {
            "version": "v0.1",
            "query": {"query_text": str(context.get("query_text") or "")},
            "columns": ["structured", "semantic", "performance_weight", "relevance"],
            "items": items,
            "matrix": matrix,
        }

    def update_bandit_from_episodes(
        self,
        events: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        unrealized_discount: float = 0.7,
    ) -> Dict[str, Any]:
        reason = str((context or {}).get("reason") or "")
        state = self._load_bandit_state()
        new_state, updates = update_bandit_scores(
            events=events,
            state=state,
            unrealized_discount=unrealized_discount,
            default_reason=reason,
        )
        self._save_bandit_state(new_state)
        audit_path = write_bandit_audit_artifact(
            updates=updates,
            context=context or {},
            audit_dir=self._audit_dir / "bandit",
        )
        self._update_bandit_daily_rollup(audit_path)
        return {
            "state_path": str(self._bandit_state_path),
            "audit_path": str(audit_path),
            "updates_count": len(updates),
        }

    def _load_bandit_state(self) -> Dict[str, Dict[str, Any]]:
        path = Path(self._bandit_state_path)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                out[str(key)] = value
        return out

    def _save_bandit_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        path = Path(self._bandit_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _update_bandit_daily_rollup(self, audit_path: str) -> None:
        audit_file = Path(audit_path)
        if not audit_file.exists():
            return
        try:
            payload = json.loads(audit_file.read_text(encoding="utf-8"))
        except Exception:
            return

        ts = str(payload.get("ts") or "")
        day = ts[:10] if len(ts) >= 10 else datetime.now().astimezone().strftime("%Y-%m-%d")
        day_dir = audit_file.parent / day
        day_dir.mkdir(parents=True, exist_ok=True)
        dest_file = day_dir / audit_file.name
        try:
            if dest_file != audit_file:
                dest_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            return

        summary_path = day_dir / "summary.json"
        summary = {"total_updates": 0, "reason_counts": {}}
        if summary_path.exists():
            try:
                old = json.loads(summary_path.read_text(encoding="utf-8"))
                if isinstance(old, dict):
                    summary["total_updates"] = int(old.get("total_updates") or 0)
                    rc = old.get("reason_counts") or {}
                    if isinstance(rc, dict):
                        summary["reason_counts"] = {str(k): int(v) for k, v in rc.items()}
                    summary["recommended_alert_threshold_pct"] = float(old.get("recommended_alert_threshold_pct") or 40.0)
            except Exception:
                pass

        updates = payload.get("updates") or []
        summary["total_updates"] += len(updates)
        for u in updates:
            reason = str((u or {}).get("reason") or payload.get("reason") or "unknown")
            summary["reason_counts"][reason] = int(summary["reason_counts"].get(reason) or 0) + 1

        day_dirs = sorted([p for p in audit_file.parent.iterdir() if p.is_dir()])
        daily_ratios: List[float] = []
        for d in day_dirs[-7:]:
            s = d / "summary.json"
            if not s.exists():
                continue
            try:
                sp = json.loads(s.read_text(encoding="utf-8"))
            except Exception:
                continue
            rc = (sp or {}).get("reason_counts") or {}
            realized = float(rc.get("episode_close_realized") or 0.0)
            estimated = float(rc.get("episode_ingest_estimated") or 0.0)
            denom = realized + estimated
            if denom <= 0:
                continue
            daily_ratios.append((realized / denom) * 100.0)
        current_summary_file = day_dir / "summary.json"
        if not current_summary_file.exists():
            rc = summary.get("reason_counts") or {}
            realized = float(rc.get("episode_close_realized") or 0.0)
            estimated = float(rc.get("episode_ingest_estimated") or 0.0)
            denom = realized + estimated
            if denom > 0:
                daily_ratios.append((realized / denom) * 100.0)

        recommended, meta = self._compute_recommended_threshold(daily_ratios)
        summary["recommended_alert_threshold_pct"] = recommended
        summary["threshold_meta"] = meta
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _compute_recommended_threshold(self, daily_ratios: List[float]) -> tuple[float, Dict[str, Any]]:
        min_cap = 30.0
        max_cap = 70.0
        default = 40.0
        sample_size = len(daily_ratios or [])
        if sample_size < 3:
            return default, {
                "window_days": 7,
                "sample_size": sample_size,
                "percentile": 25,
                "raw_percentile": None,
                "min_cap": min_cap,
                "max_cap": max_cap,
                "fallback_used": True,
            }

        xs = sorted(float(x) for x in daily_ratios)
        p = 0.25
        pos = (len(xs) - 1) * p
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        frac = pos - lo
        raw = xs[lo] + (xs[hi] - xs[lo]) * frac
        clamped = max(min_cap, min(max_cap, raw))
        return round(clamped, 2), {
            "window_days": 7,
            "sample_size": sample_size,
            "percentile": 25,
            "raw_percentile": round(raw, 4),
            "min_cap": min_cap,
            "max_cap": max_cap,
            "fallback_used": False,
        }

    def analyze_failure_memory(
        self,
        snapshot_ts: Optional[str] = None,
        episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        ts = str(snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds"))
        cases = self._cases or []
        if episodes_by_case_id is None:
            episodes_by_case_id = {}
        return analyze_failure_memory(
            snapshot_ts=ts,
            cases=cases,
            episodes_by_case_id=episodes_by_case_id,
            output_dir=Path(output_dir) if output_dir is not None else None,
        )

    def analyze_cross_market_migration(
        self,
        snapshot_ts: Optional[str],
        source_market: str,
        target_market: str,
        episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        ts = str(snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds"))
        return build_cross_market_migration(
            snapshot_ts=ts,
            source_market=source_market,
            target_market=target_market,
            source_items=self._cases or [],
            episodes_by_case_id=episodes_by_case_id or {},
            output_dir=Path(output_dir) if output_dir is not None else None,
        )

    def publish_shared_memory_event(
        self,
        snapshot_ts: Optional[str],
        agent_id: str,
        event_type: str,
        payload: Dict[str, Any],
        output_dir: Optional[Path] = None,
        acl_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        ts = str(snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds"))
        return publish_shared_memory_event(
            snapshot_ts=ts,
            agent_id=agent_id,
            event_type=event_type,
            payload=payload,
            output_dir=Path(output_dir) if output_dir is not None else None,
            acl_config=acl_config,
        )

    def build_shared_memory_graph(
        self,
        snapshot_ts: Optional[str],
        events: List[Dict[str, Any]],
        output_dir: Optional[Path] = None,
        require_evidence_refs: bool = True,
    ) -> Dict[str, Any]:
        ts = str(snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds"))
        return build_memory_graph(
            snapshot_ts=ts,
            events=events,
            output_dir=Path(output_dir) if output_dir is not None else None,
            require_evidence_refs=require_evidence_refs,
        )

    def enqueue_meta_learning_tasks(
        self,
        snapshot_ts: Optional[str],
        risk_signals: List[Dict[str, Any]],
        migration_mappings: List[Dict[str, Any]],
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        ts = str(snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds"))
        return enqueue_meta_learning_tasks(
            snapshot_ts=ts,
            risk_signals=risk_signals or [],
            migration_mappings=migration_mappings or [],
            output_dir=Path(output_dir) if output_dir is not None else None,
        )
