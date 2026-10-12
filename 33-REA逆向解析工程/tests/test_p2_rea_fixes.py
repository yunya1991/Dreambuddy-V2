"""RED 测试：P2-3/P2-4/P2-5 REA 工具修复（SPEC 维度 F）。

- P2-3: investigation_workflow evidence 按 evidence_id 去重
- P2-4: git_history 路径解析失败返回 unknown 而非静默空
- P2-5: algorithm_reducer 模式库扩展（梯度更新/相似性检索/贝叶斯更新/状态机）
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.evidence import Evidence
from core.investigation_workflow import investigate, InvestigationWorkflow


# ---------------------------------------------------------------------------
# P2-3: evidence 去重
# ---------------------------------------------------------------------------

SAMPLE_PROJECT = '''
def main():
    svc = UserService()
    users = svc.get_users()
    for u in users:
        print(u)
'''


def _setup_project(d):
    Path(os.path.join(d, "main.py")).write_text(
        "from service import UserService\n\n" + SAMPLE_PROJECT.strip()
    )
    Path(os.path.join(d, "service.py")).write_text(
        "class UserService:\n"
        "    def get_users(self):\n"
        "        data = self._fetch()\n"
        "        return data\n"
        "    def _fetch(self):\n"
        "        return [1]\n"
    )


def test_investigate_top_level_evidence_no_duplicate_ids():
    """P2-3: investigate 顶层 evidence 不应有重复 evidence_id（8 条≠16 条）。"""
    with tempfile.TemporaryDirectory() as d:
        _setup_project(d)
        result = investigate(d)

    ids = [e.evidence_id for e in result["evidence"]]
    assert len(ids) > 0
    assert len(ids) == len(set(ids)), (
        f"evidence 存在重复: {len(ids)} 条中仅 {len(set(ids))} 唯一"
    )


def test_phase_annotate_dedup_keeps_first_occurrence():
    """P2-3: _phase_annotate 聚合时按 evidence_id 去重且保持首次出现顺序。"""
    shared = Evidence(result="共享证据", level="observation")
    only_a = Evidence(result="仅A证据", level="observation")
    only_b = Evidence(result="仅B证据", level="observation")

    phases = {
        "locate": {"evidence": [shared, only_a]},
        "trace": {"evidence": [shared, only_b]},
    }

    wf = InvestigationWorkflow()
    annotate = wf._phase_annotate(phases, "/tmp/fake", None)

    ids = [e.evidence_id for e in annotate["evidence"]]
    assert len(ids) == len(set(ids)), "标注阶段 evidence 未去重"
    # 共享证据应只出现一次，且顺序为首次出现（locate 在前）
    assert ids[0] == shared.evidence_id
    assert set(ids) == {shared.evidence_id, only_a.evidence_id, only_b.evidence_id}
