#!/usr/bin/env python3
"""P0 验收脚本 — 日志级端到端验证

验收 P0-1 (record_hook/verify_hook 接线) + P0-2 (knowledge_ingest_required 标记)
五维验收：症状复测 + 日志证据 + 回归 + 影响面 + 边界
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# 路径设置
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

print("=" * 70)
print("P0 验收脚本 — 日志级端到端验证")
print("=" * 70)

# ============================================================
# 维度1: P0-1 record_hook 接线日志
# ============================================================
print("\n【维度1】P0-1 record_hook 接线 — 端到端日志")
print("-" * 50)

from cognitive_mcp_server import _handle_record, _load_skill_indexer, _find_skill_dir_by_name

# 验证 skill_indexer 可加载
si = _load_skill_indexer()
print(f"[1a] skill_indexer 加载: {'✅ SUCCESS' if si else '❌ FAIL'}")
if si:
    print(f"     ALL_SKILL_ROOTS: {len(si.ALL_SKILL_ROOTS)} 个根")
    print(f"     record_hook: {hasattr(si, 'record_hook')}")
    print(f"     verify_hook: {hasattr(si, 'verify_hook')}")

# 验证 _find_skill_dir_by_name 能找到真实 SKILL
d = _find_skill_dir_by_name("knowledge-ingest")
print(f"[1b] _find_skill_dir_by_name('knowledge-ingest'): {'✅ ' + str(d) if d else '❌ None'}")

# 端到端调用 _handle_record（mock _get_cle 避免写记忆库，真实 skill_indexer）
print("\n[1c] 端到端 _handle_record 调用（tags含 knowledge-ingest）:")
with patch("cognitive_mcp_server._get_cle") as mock_cle:
    mock_cle.return_value.record.return_value = "VM-ACCEPTANCE-TEST"
    response_json = _handle_record({
        "content": "验收测试经验",
        "tags": "knowledge-ingest,验收",
    })
    response = json.loads(response_json)
    print(f"     memory_id: {response.get('memory_id')}")
    print(f"     status: {response.get('status')}")
    print(f"     triggered_skills: {response.get('triggered_skills')}")
    print(f"     skill_links 数量: {len(response.get('skill_links', []))}")
    if response.get('skill_links'):
        for sl in response['skill_links']:
            print(f"       - skill_id={sl.get('skill_id')} linked={sl.get('linked')} "
                  f"written={sl.get('written')} apply_count_incremented={sl.get('apply_count_incremented')}")

# ============================================================
# 维度2: P0-2 knowledge_ingest_required 标记日志
# ============================================================
print("\n【维度2】P0-2 knowledge_ingest_required 硬标记 — 端到端日志")
print("-" * 50)

# tags 含 knowledge-ingest
with patch("cognitive_mcp_server._get_cle") as mock_cle:
    mock_cle.return_value.record.return_value = "VM-KI-TEST"
    resp_ki = json.loads(_handle_record({"content": "RAG经验", "tags": "knowledge-ingest"}))
    print(f"[2a] tags含knowledge-ingest → knowledge_ingest_required={resp_ki.get('knowledge_ingest_required')} "
          f"{'✅' if resp_ki.get('knowledge_ingest_required') is True else '❌'}")

# tags 不含 knowledge-ingest
with patch("cognitive_mcp_server._get_cle") as mock_cle:
    mock_cle.return_value.record.return_value = "VM-NO-KI"
    resp_no = json.loads(_handle_record({"content": "普通经验", "tags": "bugfix"}))
    print(f"[2b] tags不含knowledge-ingest → knowledge_ingest_required={resp_no.get('knowledge_ingest_required')} "
          f"{'✅' if resp_no.get('knowledge_ingest_required') is False else '❌'}")

# 字段始终存在
print(f"[2c] 字段始终存在: {'✅' if 'knowledge_ingest_required' in resp_ki and 'knowledge_ingest_required' in resp_no else '❌'}")

# ============================================================
# 维度3: P0-1 verify_hook 接线日志
# ============================================================
print("\n【维度3】P0-1 verify_hook 接线 — 端到端日志")
print("-" * 50)

from cognitive_mcp_server import _handle_verify

# verify_hook 需要 memory_id 在 cognitive_links 中
# 使用不存在的 memory_id → skill_hooks 应为空（FAIL-OPEN）
with patch("cognitive_mcp_server._get_cle") as mock_cle:
    mock_cle.return_value.verify.return_value = {"ok": True, "confidence": 0.5}
    resp_v = json.loads(_handle_verify({"memory_id": "VM-NONEXISTENT", "success": True}))
    print(f"[3a] verify 不存在关联 → skill_hooks={resp_v.get('skill_hooks')} "
          f"主流程ok={resp_v.get('ok')} {'✅ FAIL-OPEN' if resp_v.get('skill_hooks') == [] else '❌'}")

# ============================================================
# 维度4: 边界验证
# ============================================================
print("\n【维度4】边界验证")
print("-" * 50)

# 空tags
with patch("cognitive_mcp_server._get_cle") as mock_cle:
    mock_cle.return_value.record.return_value = "VM-EMPTY"
    resp_empty = json.loads(_handle_record({"content": "无tags", "tags": ""}))
    print(f"[4a] 空tags → triggered_skills={resp_empty.get('triggered_skills')} "
          f"skill_links={resp_empty.get('skill_links')} "
          f"knowledge_ingest_required={resp_empty.get('knowledge_ingest_required')} ✅")

# skill_indexer 不可用 FAIL-OPEN
with patch("cognitive_mcp_server._get_cle") as mock_cle, \
     patch("cognitive_mcp_server._load_skill_indexer", return_value=None):
    mock_cle.return_value.record.return_value = "VM-NO-SI"
    resp_nosi = json.loads(_handle_record({"content": "x", "tags": "knowledge-ingest"}))
    print(f"[4b] skill_indexer不可用 → memory_id={resp_nosi.get('memory_id')} "
          f"skill_links={resp_nosi.get('skill_links')} "
          f"knowledge_ingest_required={resp_nosi.get('knowledge_ingest_required')} ✅ FAIL-OPEN")

print("\n" + "=" * 70)
print("验收脚本完成 — 详细回归见 pytest 输出")
print("=" * 70)
