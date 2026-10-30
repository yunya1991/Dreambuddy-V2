#!/usr/bin/env python3
"""模块租约规则单测（SPEC §3.3 R1-R7 / §3.5 check-pr）。"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("lease", HERE / "lease.py")
lease = importlib.util.module_from_spec(spec)
sys.modules["lease"] = lease
spec.loader.exec_module(lease)


def ns(**kw):
    base = {
        "module": "",
        "end": "local",
        "role": "dev",
        "task": "T-1",
        "session": "a",
        "ttl": 24,
        "base_sha": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DREAM_LEASE_DIR"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("DREAM_LEASE_DIR", None)
        self.tmp.cleanup()

    # R1：同模块第二个 dev 租约（另一端）被拒
    def test_r1_two_dev_blocked(self):
        self.assertEqual(lease.cmd_claim(ns(module="18-数据获取中心", end="local")), 0)
        self.assertEqual(lease.cmd_claim(ns(module="18-数据获取中心", end="cloud")), 2)

    # R1：同端同任务同会话 = 续期
    def test_r1_renew_allowed(self):
        self.assertEqual(lease.cmd_claim(ns(module="18-数据获取中心")), 0)
        self.assertEqual(lease.cmd_claim(ns(module="18-数据获取中心", ttl=48)), 0)

    # R2：无 dev 租约不能申请 test
    def test_r2_test_requires_dev(self):
        self.assertEqual(lease.cmd_claim(ns(module="18-数据获取中心", role="test", session="b")), 2)

    # R4：同端同会话的测试被拒（自证）
    def test_r4_same_end_same_session_blocked(self):
        lease.cmd_claim(ns(module="18-数据获取中心", end="local", session="a"))
        self.assertEqual(
            lease.cmd_claim(ns(module="18-数据获取中心", role="test", end="local", session="a")), 2
        )

    # R4：同端但独立会话允许（留痕）
    def test_r4_same_end_other_session_allowed(self):
        lease.cmd_claim(ns(module="18-数据获取中心", end="local", session="a"))
        self.assertEqual(
            lease.cmd_claim(
                ns(module="18-数据获取中心", role="test", end="local", session="reviewer-1")
            ),
            0,
        )

    # R6：TTL 上限
    def test_r6_ttl_bounds(self):
        self.assertEqual(lease.cmd_claim(ns(module="m", ttl=100)), 2)

    # R3：文档 review 不要求 dev 前置
    def test_r3_review_doc_without_dev(self):
        self.assertEqual(
            lease.cmd_claim(
                ns(module="docs:tech/SPEC-x.md", role="review", end="cloud", session="rev")
            ),
            0,
        )

    # R7：root:ci 只允许一个 active
    def test_r7_root_single(self):
        self.assertEqual(lease.cmd_claim(ns(module="root:ci", end="local", role="review")), 0)
        self.assertEqual(lease.cmd_claim(ns(module="root:ci", end="cloud", role="dev")), 2)

    # R8：文档终审（review/approved）只能由云端出具，本地被拒
    def test_r8_final_approval_cloud_only(self):
        self.assertEqual(
            lease.cmd_claim(ns(module="review:approved/SPEC-x.md", role="review", end="local")), 2
        )
        self.assertEqual(
            lease.cmd_claim(ns(module="review:approved/SPEC-x.md", role="review", end="cloud")), 0
        )

    # R8：待评审/评审意见目录不受限（本地可写 feedback）
    def test_r8_feedback_allows_local(self):
        self.assertEqual(
            lease.cmd_claim(ns(module="review:feedback/x-review.md", role="review", end="local")), 0
        )

    # R8：本地端把文档推进到 approved 的 PR 被阻断
    def test_r8_check_pr_local_approved_blocked(self):
        body = "Task ID: T-1\n端: local\n角色: review\n模块: review:approved/SPEC-x.md"
        lease.cmd_claim(
            ns(module="review:approved/SPEC-x.md", role="review", end="cloud", task="T-1")
        )
        self.assertEqual(
            self._pr(
                branch="feat/T-1@local",
                body=body,
                files=["44-三端协作架构系统/review/approved/SPEC-x.md"],
            ),
            2,
        )

    def test_module_mapping(self):
        self.assertEqual(lease.module_for_path("18-数据获取中心/a.py"), "18-数据获取中心")
        self.assertEqual(
            lease.module_for_path("44-三端协作架构系统/docs/tech/a.md"), "docs:tech/a.md"
        )
        self.assertEqual(lease.module_for_path("44-三端协作架构系统/github/leases/x.json"), "lease")
        self.assertEqual(lease.module_for_path(".github/workflows/ci.yml"), "root:ci")
        self.assertEqual(lease.module_for_path("CLAUDE.md"), "root:repo")

    def _pr(self, **kw):
        ctx = {
            "branch": "feat/T-1@local",
            "body": "Task ID: T-1\n端: local\n角色: dev\n模块: 18-数据获取中心",
            "files": ["18-数据获取中心/a.py"],
            "author_email": "",
        }
        ctx.update(kw)
        f = Path(self.tmp.name) / "pr.json"
        f.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
        return lease.cmd_check_pr(SimpleNamespace(json=str(f), identities=None))

    def test_check_pr_requires_lease(self):
        self.assertEqual(self._pr(), 2)
        lease.cmd_claim(ns(module="18-数据获取中心", task="T-1"))
        self.assertEqual(self._pr(), 0)

    def test_check_pr_lease_only_pr_safe(self):
        self.assertEqual(self._pr(files=["44-三端协作架构系统/github/leases/x.json"], body=""), 0)

    def test_check_pr_hotfix_safe(self):
        self.assertEqual(self._pr(branch="hotfix/P0-1", files=["18-数据获取中心/a.py"]), 0)

    def test_check_pr_branch_end_mismatch(self):
        lease.cmd_claim(ns(module="18-数据获取中心", task="T-1"))
        self.assertEqual(self._pr(branch="feat/T-1@cloud"), 2)

    def test_check_pr_missing_fields(self):
        self.assertEqual(self._pr(body="随便写点什么"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
