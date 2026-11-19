# -*- coding: utf-8 -*-
"""P0-D3D Phase 2 RED→GREEN: 真实飞书审批客户端 + 授权服务。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.approval_bridge import ApprovalBridge  # noqa: E402
from core.feishu_approval_client import (  # noqa: E402
    FeishuApprovalClient,
    FeishuConfig,
)
from core.feishu_approval_service import (  # noqa: E402
    BLOCKED,
    GRANTED,
    PENDING,
    REJECTED,
    FeishuApprovalService,
    build_default_form,
)
from core.feishu_authorization_bridge import ApprovalRequest  # noqa: E402
from core.urgent_policy import UrgentPolicy, UrgentPolicyRegistry  # noqa: E402

NOW = 1000.0


class FakeFeishu:
    """按 URL 路由的假飞书；记录调用，不触网。"""

    def __init__(self):
        self.calls = []
        self.token_calls = 0
        self.instance_status = "PENDING"
        self.approver = "u-approver"
        self.fail_create = False
        self.fail_status = False
        self.fail_network_status = False

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, body))
        path = url.split("?", 1)[0]
        if "tenant_access_token" in path:
            self.token_calls += 1
            return 200, {"code": 0, "tenant_access_token": "t-1", "expire": 7200}
        if path.endswith("/open-apis/approval/v4/instances") and method == "POST":
            if self.fail_create:
                return 500, {"code": 500, "msg": "boom"}
            return 200, {"code": 0, "data": {"instance_code": "IC-1"}}
        if "/tasks/" in path and method == "POST":
            if path.endswith("/approve"):
                self.instance_status = "APPROVED"
            elif path.endswith("/reject"):
                self.instance_status = "REJECTED"
            return 200, {"code": 0, "data": {}}
        if "/approval/v4/instances/" in path and method == "GET":
            if self.fail_network_status:
                return 0, {"error": "network_down"}
            return 200, {
                "code": 0,
                "data": {
                    "status": self.instance_status,
                    "task_list": [
                        {
                            "id": "T-1",
                            "status": self.instance_status,
                            "user_id": self.approver,
                        }
                    ],
                },
            }
        if "/open-apis/im/v1/messages" in path:
            return 200, {"code": 0, "data": {"message_id": "m-1"}}
        return 404, {"code": 404, "msg": "not_found"}

    def methods(self):
        return [call[0] for call in self.calls]

    def create_payload(self):
        for method, url, body in self.calls:
            path = url.split("?", 1)[0]
            if method == "POST" and path.endswith("/open-apis/approval/v4/instances"):
                return json.loads(body.decode("utf-8"))
        return {}


def _request(**overrides):
    data = {
        "request_id": "AR-1",
        "gate_run_id": "GR-1",
        "node_id": "G2",
        "action": "rework.dispatch",
        "scope": ("rework.dispatch",),
        "ttl_s": 3600,
        "requested_by": "hermes_secretary",
        "reason": "Gate 驳回后重做",
        "high_risk": False,
    }
    data.update(overrides)
    return ApprovalRequest(**data)


def _client(fake, clock=lambda: NOW):
    return FeishuApprovalClient(
        FeishuConfig(app_id="app", app_secret="secret"),
        transport=fake,
        clock=clock,
    )


def _service(fake, secret="s", bridge=None, registry_path="", urgent=None):
    bridge = bridge or ApprovalBridge(secret=secret)
    return FeishuApprovalService(
        _client(fake),
        bridge,
        secret,
        approval_code="CODE-1",
        requester_user_id="u-requester",
        approver_user_id="u-approver",
        registry_path=registry_path,
        urgent=urgent,
        clock=lambda: NOW,
    )


# ── 客户端 ───────────────────────────────────────────────────────────────
def test_config_from_env_requires_credentials():
    assert FeishuConfig.from_env({}) is None
    assert FeishuConfig.from_env({"FEISHU_APP_ID": "a"}) is None
    config = FeishuConfig.from_env(
        {"FEISHU_APP_ID": "a", "FEISHU_APP_SECRET": "b", "FEISHU_BASE_URL": "https://x/"}
    )
    assert config.app_id == "a"
    assert config.base_url == "https://x"


def test_token_is_cached_between_calls():
    fake = FakeFeishu()
    client = _client(fake)
    assert client.get_tenant_access_token() == "t-1"
    assert client.get_tenant_access_token() == "t-1"
    assert fake.token_calls == 1


def test_client_create_status_execute_and_message():
    fake = FakeFeishu()
    client = _client(fake)

    created = client.create_approval_instance("CODE-1", [{"id": "x"}], "u-1", uuid="AR-1")
    assert created.ok
    assert created.data["instance_code"] == "IC-1"
    payload = fake.create_payload()
    assert payload["approval_code"] == "CODE-1"
    assert payload["user_id"] == "u-1"
    assert payload["uuid"] == "AR-1"
    assert json.loads(payload["form"]) == [{"id": "x"}]

    status = client.get_approval_status("IC-1")
    assert status.ok
    assert status.data["status"] == "PENDING"
    assert status.data["task_id"] == "T-1"

    executed = client.execute_approval("IC-1", "T-1", True, reason="ok", user_id="u-approver")
    assert executed.ok
    assert fake.instance_status == "APPROVED"

    message = client.send_message("oc-1", "hello")
    assert message.ok


def test_client_unconfigured_returns_error_not_exception():
    client = FeishuApprovalClient(None, transport=FakeFeishu())
    result = client.create_approval_instance("CODE", [], "u")
    assert not result.ok
    assert result.error == "feishu_not_configured"


# ── 提交 ─────────────────────────────────────────────────────────────────
def test_submit_creates_feishu_instance_and_registry_record(tmp_path):
    fake = FakeFeishu()
    registry = str(tmp_path / "registry.jsonl")
    service = _service(fake, registry_path=registry)

    outcome = service.submit(_request())
    assert outcome.status == PENDING
    assert outcome.instance_code == "IC-1"
    assert not outcome.auto_approved

    payload = fake.create_payload()
    assert payload["approval_code"] == "CODE-1"
    assert payload["user_id"] == "u-requester"
    assert payload["uuid"] == "AR-1"

    records = [json.loads(line) for line in open(registry, encoding="utf-8") if line.strip()]
    assert records[-1]["status"] == PENDING
    assert records[-1]["instance_code"] == "IC-1"


def test_submit_blocked_when_feishu_not_configured(tmp_path):
    fake = FakeFeishu()
    service = FeishuApprovalService(
        FeishuApprovalClient(None, transport=fake),
        ApprovalBridge(secret="s"),
        "s",
        approval_code="CODE-1",
        requester_user_id="u-requester",
        registry_path=str(tmp_path / "registry.jsonl"),
        clock=lambda: NOW,
    )
    outcome = service.submit(_request())
    assert outcome.status == BLOCKED
    assert outcome.error == "feishu_not_configured"
    assert fake.calls == []


def test_default_form_contains_request_identity():
    form = {item["id"]: item["value"] for item in build_default_form(_request())}
    assert form["request_id"] == "AR-1"
    assert form["gate_run_id"] == "GR-1"
    assert form["risk"] == "normal"


# ── 预授权：紧急运维 ─────────────────────────────────────────────────────
def _urgent():
    registry = UrgentPolicyRegistry()
    assert (
        registry.register(
            UrgentPolicy(
                policy_id="P-1",
                task_class="restart_worker",
                risk="low",
                reversible=True,
                audit=True,
            )
        )
        == []
    )
    return registry


def test_urgent_policy_auto_approves_without_feishu():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge, urgent=_urgent())

    outcome = service.submit(
        _request(action="restart_worker", scope=("restart_worker",)),
        policy_id="P-1",
        task_class="restart_worker",
    )
    assert outcome.status == GRANTED
    assert outcome.auto_approved
    assert outcome.grant_id
    assert fake.methods() == []  # 完全没有触达飞书
    assert bridge.sink[-1]["type"] == "approval.granted"


def test_approval_outbox_event_carries_gateflow_context():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge, urgent=_urgent())

    service.submit(
        _request(
            action="restart_worker",
            scope=("restart_worker",),
            task_id="TK-1",
            gate_id="G-1",
            gate_kind="acceptance",
        ),
        policy_id="P-1",
        task_class="restart_worker",
    )
    event = bridge.sink[-1]
    assert event["task_id"] == "TK-1"
    assert event["gate_id"] == "G-1"
    assert event["gate_kind"] == "acceptance"
    assert event["grant_id"] == event["grant"]["grant_id"]
    assert event["grant"]["signature"]


def test_high_risk_never_auto_approves():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge, urgent=_urgent())

    outcome = service.submit(
        _request(action="restart_worker", scope=("restart_worker",), high_risk=True),
        policy_id="P-1",
        task_class="restart_worker",
    )
    assert outcome.status == PENDING
    assert not outcome.auto_approved
    assert bridge.sink == []
    assert fake.create_payload()["approval_code"] == "CODE-1"


def test_hard_exclusion_never_auto_approves():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge, urgent=_urgent())

    outcome = service.submit(
        _request(action="live_trade", scope=("live_trade",)),
        policy_id="P-1",
        task_class="restart_worker",
    )
    assert outcome.status == PENDING
    assert bridge.sink == []


# ── 轮询回写 ─────────────────────────────────────────────────────────────
def test_poll_approved_writes_signed_grant():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge)

    submitted = service.submit(_request(task_id="TK-1", gate_id="G-1", gate_kind="acceptance"))
    fake.instance_status = "APPROVED"
    outcome = service.poll(submitted.instance_code)

    assert outcome.status == GRANTED
    assert outcome.grant_id
    assert bridge.sink[-1]["type"] == "approval.granted"
    assert bridge.sink[-1]["request_id"] == "AR-1"
    assert bridge.sink[-1]["task_id"] == "TK-1"
    assert bridge.sink[-1]["gate_id"] == "G-1"
    assert bridge.sink[-1]["grant_hash"].startswith("sha256:")
    assert bridge.sink[-1]["subject"] == "feishu:u-approver"


def test_poll_rejected_writes_no_grant():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge)

    submitted = service.submit(_request())
    fake.instance_status = "REJECTED"
    outcome = service.poll(submitted.instance_code)

    assert outcome.status == REJECTED
    assert bridge.sink == []


def test_poll_pending_keeps_waiting():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge)

    submitted = service.submit(_request())
    outcome = service.poll(submitted.instance_code)

    assert outcome.status == PENDING
    assert bridge.sink == []


def test_poll_transport_failure_stays_pending_fail_open():
    fake = FakeFeishu()
    bridge = ApprovalBridge(secret="s")
    service = _service(fake, bridge=bridge)

    submitted = service.submit(_request())
    fake.fail_network_status = True
    outcome = service.poll(submitted.instance_code)

    assert outcome.status == PENDING
    assert outcome.retryable
    assert bridge.sink == []


def test_poll_grant_write_failure_blocks():
    fake = FakeFeishu()
    # 服务端签名密钥与 Bridge 验签密钥不一致 → Bridge 拒绝写入。
    service = _service(fake, secret="s", bridge=ApprovalBridge(secret="other"))

    submitted = service.submit(_request())
    fake.instance_status = "APPROVED"
    outcome = service.poll(submitted.instance_code)

    assert outcome.status == BLOCKED
    assert outcome.error == "grant_write_failed"


def test_poll_unknown_instance_returns_not_found():
    service = _service(FakeFeishu(), bridge=ApprovalBridge(secret="s"))
    outcome = service.poll("IC-missing")
    assert not outcome.ok
    assert outcome.error == "request_not_found"


def test_poll_all_resumes_pending_after_restart(tmp_path):
    registry = str(tmp_path / "registry.jsonl")
    fake = FakeFeishu()
    first = _service(fake, bridge=ApprovalBridge(secret="s"), registry_path=registry)
    first.submit(_request())

    # 重启：新服务从 registry 恢复 pending。
    second = _service(fake, bridge=ApprovalBridge(secret="s"), registry_path=registry)
    pending = second.pending_requests()
    assert len(pending) == 1
    assert pending[0].request_id == "AR-1"

    fake.instance_status = "APPROVED"
    outcomes = second.poll_all()
    assert len(outcomes) == 1
    assert outcomes[0].status == GRANTED
    assert second.pending_requests() == []


def test_service_from_env_requires_secret_code_and_requester():
    assert FeishuApprovalService.from_env(environ={}) is None
    service = FeishuApprovalService.from_env(
        client=_client(FakeFeishu()),
        bridge=ApprovalBridge(secret="s"),
        environ={
            "FEISHU_APPROVAL_SECRET": "s",
            "FEISHU_APPROVAL_CODE": "CODE-1",
            "FEISHU_REQUESTER_USER_ID": "u-1",
        },
    )
    assert service is not None
    assert service.approval_code == "CODE-1"


def test_cli_exits_nonzero_without_secret(monkeypatch, capsys):
    from core.feishu_approval_service import main

    monkeypatch.delenv("FEISHU_APPROVAL_SECRET", raising=False)
    assert main(["--once"]) == 1
    assert "FEISHU_APPROVAL_SECRET" in capsys.readouterr().out
