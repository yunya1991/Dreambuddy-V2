# SHADOW-REPORT-L0-REA — M3⑨ REA shadow 双跑窗口报告

- **版本**: v0.1 ｜ **更新日期**: 2026-11-02
- **壳**: mcp_shells/l0_rea/server.py（REA_MCP_SHADOW=1）
- **依据**: PLAN-L0-MCP-P0-P3-v0.1 M3⑨ ｜ SPEC-L0-MCP-PACKAGING §3.2
- **双跑窗口**: 单次窗口，三工具各 1 job（analyze / trace / compare）

## 一、双跑方法

- **新路径**: 壳两段式（submit_* → 后台线程执行节点 → poll_* 取结果）
- **旧路径**: 直调 dsh_nodes 节点函数（既有 REA client 方式），同参数重放
- **比对方式**: 双方输出经规范化（剥离非确定性字段：ts / created_at / evidence_id / replay_tree_id）后，JSON 序列化（sort_keys）逐字节比对 + SHA-256 指纹
- **测试参数**: target=mcp_shells/l0_rea/server.py（compare 另取 _shared/envelope_wrap.py），trace_id 固定 shadow-m3-window

## 二、窗口结果

| Tool | job_id | state | match | new_sha256 = old_sha256 |
|---|---|---|---|---|
| submit_rea_analyze | job-dfedff868d1d | success | ✅ true | fdcaa9c1…36cf22 |
| submit_rea_trace | job-74e11f039328 | success | ✅ true | 7a905ec3…2ef7f704 |
| submit_rea_compare | job-6f4947d81a2e | success | ✅ true | 23539207…4efa95c |

**结论: 三工具规范化比对全部一致，无差异。**

## 三、规范化说明（重要）

首轮双跑曾出现 match=false，经诊断（同参数直调节点两次 diff）确认差异**全部**来自节点自身非确定性字段：

- 时间戳: ts / created_at（毫秒级执行时间）
- 随机 ID: evidence_id（uuid4）/ replay_tree_id

剥离上述字段后比对即一致，属预期噪声而非壳逻辑缺陷。壳内比对已内置该规范化（_normalize），后续 shadow 窗口直接可比。

## 四、出口判据

- ✅ M3⑨ shadow 报告落档（本文件）
- ✅ REA 壳契约测试 5 项全绿（shadow 逻辑无回归）
- ✅ M3 出口判据达成：V6 + shadow 报告无差异
