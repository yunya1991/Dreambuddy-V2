"""执行器文档按需检索（SPEC-41-L1 §2.3）。

L1 注册表与路由热路径保持常驻；执行器规范、边界条件和评估语料仅在
调用方指定 intent_id 时读取。所有文件异常均 FAIL-OPEN，不影响意图路由。
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_INDEX_ROOT = Path(__file__).resolve().parent.parent
UNITS_DIR = _INDEX_ROOT / "intent_units"
_INTENT_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _read_jsonl(path: Path) -> Tuple[List[dict], List[str]]:
    if not path.exists():
        return [], []
    rows: List[dict] = []
    errors: List[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [], [f"{path.name}: {exc}"]
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("row must be a JSON object")
            rows.append(value)
        except (ValueError, TypeError) as exc:
            errors.append(f"{path.name}:{line_no}: {exc}")
    return rows, errors


class IntentDocRetriever:
    """按 intent_id 懒加载单个意图单元，并缓存已加载内容。"""

    def __init__(self, units_dir: Optional[Path] = None):
        self.units_dir = Path(units_dir) if units_dir else UNITS_DIR
        self._cache: Dict[str, dict] = {}

    def retrieve(self, intent_id: str) -> dict:
        """返回执行器文档及完整正例/反例；缺失或损坏时显式降级。"""
        intent_id = (intent_id or "").strip()
        if not _INTENT_ID.fullmatch(intent_id):
            return self._empty(intent_id, ["invalid_intent_id"])
        if intent_id not in self._cache:
            self._cache[intent_id] = self._load(intent_id)
        return self._cache[intent_id]

    @staticmethod
    def _empty(intent_id: str, errors: List[str]) -> dict:
        return {
            "intent_id": intent_id,
            "found": False,
            "degraded": bool(errors),
            "metadata": {},
            "executor_doc": "",
            "examples": {"zh": [], "en": []},
            "negatives": {"zh": [], "en": []},
            "errors": errors,
        }

    def _load(self, intent_id: str) -> dict:
        unit = self.units_dir / intent_id
        if not unit.is_dir():
            return self._empty(intent_id, ["intent_unit_not_found"])

        result = self._empty(intent_id, [])
        metadata_path = unit / "intent.yaml"
        try:
            for line in metadata_path.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    result["metadata"][key.strip()] = value.strip()
        except (OSError, UnicodeError) as exc:
            result["errors"].append(f"intent.yaml: {exc}")

        doc_path = unit / "executor.md"
        try:
            result["executor_doc"] = doc_path.read_text(encoding="utf-8")
            result["found"] = True
        except (OSError, UnicodeError):
            result["errors"].append("executor_doc_not_found")

        for group, prefix in (("examples", "examples"), ("negatives", "negatives")):
            for lang in ("zh", "en"):
                rows, errors = _read_jsonl(unit / f"{prefix}_{lang}.jsonl")
                result[group][lang] = rows
                result["errors"].extend(errors)

        result["degraded"] = bool(result["errors"])
        if result["degraded"]:
            logger.warning("意图文档降级 %s: %s", intent_id, result["errors"])
        return result
