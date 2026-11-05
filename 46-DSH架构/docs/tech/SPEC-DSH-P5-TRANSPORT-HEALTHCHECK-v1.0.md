# SPEC-DSH-P5: 跨进程 Transport + 壳自恢复

> **版本**: v1.0 ｜ **日期**: 2026-11-05 ｜ **状态**: ✅ 决议落定,进入 TDD ｜ **定位**: DSH 架构 P3 补齐项
> **承接**: DESIGN-DSH-ARCH-UPGRADE v0.2 + SPEC-L0-MCP-PACKAGING v0.3
> **前置**: P4 已落地 — stdio 真 launcher + ADR-10 单壳复用 + D4 延迟实测 (l2_full P50=0.487ms)

---

## 一、问题定义

registry `mcp_capabilities.yaml` 已声明 4 种 transport 枚举（stdio / ssh-stdio / http / in-process），`l0.cognition.mcp` 已声明 `transport: ssh-stdio`（D5 双模注释）。但 launcher 层仅实现 stdio；ShellHandleManager 零健康检查/自动重拉；call_worker_tool 零重试降级。这导致：

| 维度 | 影响 | 行业参照 |
|---|---|---|
| ssh-stdio 未实现 | 本地无法 SSH dreambuddy-remote 调云端壳（l0.cognition.mcp 意图流产） | arXiv 2512.01939: "performance optimization common shortcoming across all frameworks" |
| 壳死=永久 None | Shell 进程 crash → get_handle 永远返回 None | AutoGen Actor supervisor 可选健康检查 |
| 无重试降级 | call_worker_tool 抛异常直接击穿 Worker | LangGraph checkpoint 论文恢复率 83.3% |

---

## 二、Phase P3a: ssh-stdio launcher

### 2.1 设计

```python
# core/ssh_shell_launcher.py (新建)
# 复用 stdio launcher 的 _send/_read_line/_CLOSE_WAIT_S/initialize 握手
# 仅把 Popen(argv) 改为 SSH 隧道:
#   ssh -tt <host> <remote_cmd>
#   stdin/stdout 仍由 JSON-RPC 2.0 行分隔协议驱动

def ssh_launcher(
    spec: Dict[str, Any],
    *,
    call_timeout: float = 30.0,
    handshake_timeout: float = 10.0,
    ssh_host: str = None,  # registry shell_host 或显式注入
) -> StdioShell:  # 复用 stdio launcher 的 StdioShell 类!
    transport = spec["transport"]
    assert transport == "ssh-stdio"

    # 构造 SSH 命令: ssh -tt host "cd repo_root && python3 {shell_cmd}"
    ssh_host = ssh_host or spec.get("shell_host") or os.environ.get("DSH_SSH_HOST")
    remote_cmd = build_remote_cmd(spec)  # cd repo_root && python3 {shell_path}
    argv = ["ssh", "-tt", ssh_host, remote_cmd]

    # Popen 完全复用 stdio launcher 的参数:
    proc = subprocess.Popen(
        argv, stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
    )
    shell = StdioShell(proc, call_timeout)  # 复用类!
    shell.handshake(handshake_timeout)
    return shell
```

### 2.2 与 stdio launcher 的复用关系

```
                    ┌─ _send/_read_line/_CLOSE_WAIT_S ─┐
                    │  initialize 握手 / call() / close() │
   stdio_launcher ──┤                                   ├── StdioShell (类复用)
   ssh_launcher  ───┤                                   │
                    └─────────── 差异点: Popen argv ─────┘
                                  stdio: ["python3", "server.py"]
                                  ssh:   ["ssh", "-tt", host, "python3 server.py"]
```

### 2.3 协议不变

- **行分隔 JSON-RPC 2.0**（与真实壳 `mcp_shells/*/server.py` main() 一致）
- 唯一差异：传输介质从本地管道变成 SSH 隧道管道
- select.select 超时/读取逻辑 **完全不变**

### 2.4 假 SSH 测试策略

本地测 SSH launcher 不需要真 SSH 连接：用 `subprocess.Popen(["python3", "-c", "..." ])` 模拟 SSH 管道——stdout/stderr 合并，只需要确认 launcher 正确组装 `_send/_read_line` 即可。这与 stdio launcher 的测试策略一致（fake_mcp_server.py）。

### 2.5 registry 配置

```yaml
# mcp_capabilities.yaml - l0.cognition.mcp 当前声明
- shell_id: l0.cognition.mcp
  transport: ssh-stdio          # D5 双模: 默认 ssh 云端
  shell_host: dreambuddy-remote  # 新增字段(launcher 读)
  shell_cmd: "python3 {path}"
  shell_path: "4-MEMORY/9-工具与接口/cognitive_mcp_server.py"
  status: available
```

---

## 三、Phase P3-A: ShellHandleManager 健康检查 + 自动重拉

### 3.1 新增硬约束

| 编码 | 名称 | 语义 |
|---|---|---|
| **HC-4** | 壳死自动重拉 | `get_handle(shell_id)` 发现壳 `is_alive()==False` → 关旧壳 → `launcher(spec)` 重新拉起 |
| **HC-5** | 同 id 重拉上限 | 每 shell_id 生命周期内最多重拉 3 次；超限后返回 None（HC-1 FAIL-OPEN） |

### 3.2 设计

```python
class ShellHandleManager:
    def __init__(...):
        ...
        self._restart_counts: Dict[str, int] = {}  # HC-5
        self.MAX_RESTARTS = 3

    def get_handle(self, shell_id):
        ...
        shell = self._shells.get(shell_id)
        # HC-4: 壳死了 → 重拉(而非 None)
        if shell is not None and not shell.is_alive():
            # 健康检查触发
            self._restart_counts[shell_id] = self._restart_counts.get(shell_id, 0) + 1
            if self._restart_counts[shell_id] > self.MAX_RESTARTS:
                return None  # HC-5: 超上限,FAIL-OPEN
            try:
                shell.close()  # 清理死壳
            except Exception:
                pass
            shell = None  # 让下面 launcher 重拉
        if shell is None:
            shell = self._launcher(spec)
            self._shells[shell_id] = shell
        ...
```

### 3.3 壳健康检查触发点

- **被动**：每次 `get_handle()` 时检查 `is_alive()`（零额外开销，属性访问级）
- **主动（P3b 可选）**：后台定时 watchdog 每 30s 检查所有壳 `is_alive()`

---

## 四、Phase P3-C: call_worker_tool try-retry-degrade 三态

### 4.1 新增硬约束

| 编码 | 名称 | 语义 |
|---|---|---|
| **HC-6** | 壳异常自动重试 | `handle.call()` 抛 `StdioShellError`（传输层失败）→ 重拉壳 → 重试 1 次 |
| **HC-7** | 重试超限 FAIL-OPEN | 重试仍失败 → 返回 `{ok: false, error_code: "shell_degraded", degraded: true}`（对齐 B1） |

### 4.2 设计

```python
# worker_tool_call.py call_worker_tool() 末尾:
try:
    envelope = handle.call(tool, args)
except Exception as exc:
    # HC-6: 传输层失败 → 重拉壳 + 重试
    handle = manager.get_handle(shell_id, force_new=True)
    if handle is not None:
        try:
            envelope = handle.call(tool, args)
        except Exception as retry_exc:
            # HC-7: 重试仍败 → degrade 信封
            return _fail_response(
                error_code="shell_degraded",
                degraded=True,
                meta={"reason": str(retry_exc), "original": str(exc)},
            )
    else:
        return _fail_response(
            error_code="shell_degraded",
            degraded=True,
            meta={"reason": str(exc)},
        )
```

### 4.3 三态语义

```
成功路径:
  handle.call() → envelope (ok=true/false) → 正常返回

失败重试路径 (HC-6):
  handle.call() → StdioShellError
    → manager.get_handle(force_new=True)  # P3-A 会重拉壳
    → new_handle.call() → envelope → 正常返回

最终降级路径 (HC-7):
  handle.call() → StdioShellError
    → retry 仍败 或 manager 无法重拉
    → {ok: false, error_code: "shell_degraded", degraded: true}
```

### 4.4 B1 对齐

HC-6/HC-7 **严格对齐 B1 FAIL-OPEN 分型**：
- 传输层失败（壳 crash/SSH 断连/超时）是"主功能禁 FAIL-OPEN"类——必须重试后降级，不能 silently skip
- 重试 + degrade 信封是 B1 语义的自然扩展（原来只有"失败→降级"，现在加了"失败→重试→降级"）

---

## 五、TDD 落地计划

### 5.1 P3a ssh-stdio launcher（3 tests）

| # | RED 断言 | GREEN 实现 |
|---|---|---|
| 1 | `from core.ssh_shell_launcher import ssh_launcher` → ModuleNotFoundError | 写模块 |
| 2 | `ssh_launcher(spec)` → `StdioShell` 实例，handshake 通过 | Popen 组装 SSH 隧道 + 复用 StdioShell |
| 3 | 传 `ssh_host` env → 正确组装 `-tt host` argv | 支持 `DSH_SSH_HOST` env fallback |

**假 SSH 测试**：用 `fake_mcp_server.py` 作为远程命令，通过 `subprocess.Popen` 模拟 SSH 管道——零真 SSH 依赖。

### 5.2 P3-A 健康检查 + 自动重拉（4 tests）

| # | RED 断言 | GREEN 实现 |
|---|---|---|
| 1 | 壳被 kill → `get_handle()` 返回 **非 None**（旧壳被关 + 新壳拉起） | 加 healthcheck 逻辑 |
| 2 | 5 次 kill → 第 4 次开始返回 None（MAX_RESTARTS=3） | 加 `_restart_counts` + HC-5 上限 |
| 3 | 壳正常 → `_restart_counts[shell_id]==0` 或不存在 | 初始状态不计数 |
| 4 | 重拉后 `handles_issued` 继续累加 | 重拉不影响 issued 计数 |

**模拟 crash**：拿到 Shell 实例后调 `shell._proc.kill()` → `os.kill(pid, 9)` 或模拟 `is_alive()` 返回 False。

### 5.3 P3-C try-retry-degrade（4 tests）

| # | RED 断言 | GREEN 实现 |
|---|---|---|
| 1 | 壳被 kill → `call_worker_tool` **不抛异常**（自动重试） | 加 try-retry 逻辑 |
| 2 | 重试上限后 → `{ok: false, error_code: "shell_degraded"}` | HC-7 degrade 信封 |
| 3 | 壳正常 → 零重试额外开销 | 正常路径不加逻辑 |
| 4 | manager 开关关 → `get_handle(force_new=True)` 仍返回 None → degrade 信封 | 三态降级 |

---

## 六、验收判据

| 判据 | 值 |
|---|---|
| 新增测试 | ≥ 11（3 ssh + 4 healthcheck + 4 retry） |
| 全套件回归 | 原有 1051 tests + 新增 ≥ 11 = ≥ 1062 passed |
| 云端三端一致 | HEAD + PYTEST_EXIT=0 |
| P3a 真 SSH 验证 | SSH dreambuddy-remote 调 l0.cognition.mcp → call 成功 |
| 壳 crash 自恢复 | 真实 kill -9 壳进程 → 自动重拉 → 下一次 call 成功 |
| benchmark 不退化 | l2_full P50 仍 ≤ 1ms（重试开销可忽略） |

---

## 七、风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| SSH 横幅污染 stdout | 高 | 协议解析失败 | SSH `-tt` 合并 stderr 到管道前需要过滤 banner；或 SSH 配置 `LogLevel ERROR` |
| 壳进程 systemd 重启时间 | 中 | 重试期间 timeout 触发 | HC-6 重试时用更长 timeout（60s vs 30s） |
| 健康检查开销 | 低 | 每次 get_handle 多一次 is_alive() | is_alive() 是属性访问，零额外开销 |
| SSH key 认证失败 | 中 | ssh_launcher 抛异常 → None | SSH `-o BatchMode=yes` 强制非交互，早失败 |
| 重拉次数超过 HC-5 上限但壳实际好的 | 低 | 误判 FAIL-OPEN | P3b 后台 watchdog 主动拉活 + 定期重置 restart_count |
