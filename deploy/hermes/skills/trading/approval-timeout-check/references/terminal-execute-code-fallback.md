# Terminal vs execute_code 降级模式

## 问题

在 Windows + MSYS (git-bash) 环境下，Hermes 的 `terminal` 工具可能因 session CWD 为 Windows 风格路径（如 `C:\tmp`）而反复失败，报错：

```
/bin/bash: line 2: cd: C:\tmp: No such file or directory
exit_code: 126
```

## 根因

- MSYS bash 将路径中的 `C:\tmp` 字面量传递给 `cd`，但 bash 期望 Unix 风格路径（`/c/tmp`）。
- `terminal` 工具的 `workdir` 参数同样会经过此路径转换，可能失败。
- 这与 Hermes 配置的 `project_dir` 或 session CWD 有关，属于环境级问题。

## 解决方案：execute_code 降级

当 `terminal` 连续失败（≥ 2 次 `cd:` 错误，exit_code=126）时，切换到 `execute_code`。

**降级链优先级**: `execute_code` > `terminal` > `read_file` > `search_files`。一旦 `terminal` 失败 2 次，直接跳到 `execute_code` 完成全部文件读写和子进程调用，不要再尝试 `read_file` 或 `search_files` — `execute_code` 内的 Python `open()` / `os.walk()` / `subprocess.run()` 可替代所有原生工具。

```python
import subprocess, sys

result = subprocess.run(
    [sys.executable, "<script_path>", "<arg1>", ...],
    capture_output=True, text=True, timeout=60
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr)
```

## 适用场景

| 操作 | terminal 命令 | execute_code 替代 |
|------|-------------|-------------------|
| approval_agent.py | `python C:/tmp/.../approval_agent.py check` | `subprocess.run([sys.executable, "C:/tmp/.../approval_agent.py", "check"], ...)` |
| screen2_runner.py | `python C:/tmp/screen2_runner.py --date ...` | `subprocess.run([sys.executable, "C:/tmp/screen2_runner.py", "--date", ...], ...)` |
| feishu_notify.py | `python C:/tmp/.../feishu_notify.py screen2 ...` | `subprocess.run([sys.executable, "C:/tmp/.../feishu_notify.py", "screen2", ...], ...)` |
| git 命令 | `git add ...` | `subprocess.run(["git", "add", ...], cwd="C:/tmp/Dreambuddy-V2")` |

## 注意事项

- `execute_code` 内部使用 Python 原生路径，不受 MSYS bash 限制。
- `cwd` 参数使用 Windows 原生路径在 subprocess 中正常工作。
- 不要试图在代码中检测 bash 环境——直接尝试 terminal 然后再降级。
- `read_file` 和 `search_files` 在 Windows 环境下同样可能失败（`search_files` 依赖 ripgrep，`read_file` 路径解析可能异常）。遇到这些工具反复失败时，立即切换到 `execute_code` 使用 Python `open()` / `os.walk()` / `glob` 替代。
- 关键：`execute_code` 确认文件存在后，不要切回失败的 native tool——直接在 execute_code 中完成全部读取和解析。
