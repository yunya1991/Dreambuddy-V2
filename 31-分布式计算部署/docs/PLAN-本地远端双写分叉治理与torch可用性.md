# PLAN — 本地/远端双写分叉治理 与 torch 可用性补齐（实现计划）

- 关联 SPEC：[SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md)
- 原则：**先在本地实现与验证，全部通过后再同步远端**（用户明确要求）
- 执行方式：TDD（RED → GREEN → REFACTOR）；每阶段设验收门
- **本轮范围：阶段 0–5（Phase 1 过渡期）**；阶段 6（Phase 2 影子模式）**移出本轮**，由用户自行观察后再决定。

---

## 0. 约定

- 远端 SSH 封装（密码取自 `31-分布式计算部署/.env`）：`sshpass -p <PW> ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no ubuntu@43.160.201.117 "<cmd>"`
- 远端 SSH 用户 `ubuntu`，repo 属主 `luke`：**所有 repo 写操作以 `sudo -u luke -H` / `sudo -n -u luke -H` 执行**。
- 远端 SQLite 读/写均以 `luke` 身份；同步前用 `sqlite3 .backup` 生成快照（避免 WAL 半写）。
- 只 stage 本任务文件，勿带 `12-三屏趋势系统/signal_pool/pool.json`。

---

## 阶段 0 — 事实复核（只读）

| 步骤 | 命令/动作 | 验收 |
|---|---|---|
| 0.1 | 本地：`/opt/anaconda3/bin/python3 -c "import torch,torchsde;print(torch.__version__,torchsde.__version__)"` | 输出 `2.11.0 0.2.6` |
| 0.2 | 远端：`venv-trading` 确认无 torch | `ModuleNotFoundError: torch` |
| 0.3 | 定位 `23-四层闭环自进化交易架构` 的测试目录与既有 SDE 测试用例 | 记录路径，供 T4 复用 |
| 0.4 | 定位本工作区 MCP 配置文件（由 `4-MEMORY/9-工具与接口/deploy/install_cognitive_mcp.py` 生成）实际落盘位置 | 记录文件路径 |

---

## 阶段 1 — 本地代码改动

### T1 依赖声明（`pyproject.toml`）
- 在 `[project.optional-dependencies]` 下新增：
  ```toml
  sde = [
      "torch>=2.0",
      "torchsde>=0.2.6",
  ]
  ```
- 验收：`python -c "import tomllib,pathlib;print('sde' in tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['optional-dependencies'])"` → `True`

### T3+T4 可观测性 + 测试（TDD：先 RED）
1. **RED**：在 `23-四层闭环自进化交易架构` 测试目录新增用例，断言：
   - torch 可用时 `SDESolver().status()`（或 `_sde_backend_used`）后端 == `torchsde`；
   - 同时断言「启动可观测性」：`EvolutionPipeline`/`polling_trader` 初始化后有一条含后端名的日志/状态记录。
   先运行确认失败（RED）。
2. **GREEN**：实现最小可观测性——在 `23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py` 初始化处（及 `11-易经推理系统/scripts/memory_l4/polling_trader.py` 启动处）打印/记录：
   - `_TORCH_AVAILABLE`、`_TORCHSDE_AVAILABLE`、`SDESolver.status()`、`_sde_backend_used`。
3. **REFACTOR**：抽取一个 `log_runtime_backends()` 小函数，避免重复。
- 验收：新用例由 RED 转 GREEN；`1-ARCHITECTURE/dreamos`、`11-易经推理系统` 既有测试零回归。

### 阶段 2 — 本地验收门
- 运行相关 pytest（`test_*.py`），全绿；
- 本地 `SDESolver.status()` 后端 == `torchsde`；
- 本地 `polling_trader`（若启动）日志无降级告警。
- **门禁**：以上全过才进入远端阶段。

---

## 阶段 3 — 远端部署（幂等脚本 `31-分布式计算部署/phase7/07-deploy-torch-and-snapshots.sh`）

| 步骤 | 动作 | 验收 |
|---|---|---|
| T2-1 | 远端装 CPU torch：`pip install torch --index-url https://download.pytorch.org/whl/cpu`；再 `pip install torchsde` | `python -c "import torch,torchsde"` 成功 |
| T2-2 | 远端 `SDESolver.status()` 后端 == `torchsde` | 输出 `torchsde` |
| T5 | 远端 `pip install mcp`，并冒烟：`PYTHONPATH=<repo>/4-MEMORY/9-工具与接口 python -c "import cognitive_mcp_server"` | 导入成功 |
| T7-1 | 远端新增 `dreambuddy-snapshot.service/.timer`：定时对 `4-MEMORY/data/cognitive_memory.db`、`19-数据访问层/data/dreambuddy_core.db` 执行 `.backup` 到 `/home/luke/sync-snapshots/` | 快照文件生成、`integrity_check=ok` |
| T7-2 | 新增 `31-分布式计算部署/phase7/` 脚本写回并 commit+push，远端 `git pull` 后执行 | 服务 `is-active`、`NRestarts=0` |

- 回滚：`systemctl disable --now dreambuddy-snapshot.timer`；pip 安装可用 `pip uninstall` 回退（不影响既有 FAIL-OPEN 链）。

---

## 阶段 4 — 认知库 SSH stdio 托管（T6）

1. 本地生成专用 key：`ssh-keygen -t ed25519 -f ~/.ssh/dreambuddy_remote -N ""`。
2. 追加公钥到远端 `ubuntu` 的 `~/.ssh/authorized_keys`；本地 `~/.ssh/config` 增别名 `dreambuddy-remote`。
3. 修改 MCP 配置（阶段 0.4 定位的落盘文件 / 或更新 `install_cognitive_mcp.py` 生成逻辑）：
   ```
   command: ssh
   args: ["-o","BatchMode=yes","dreambuddy-remote",
          "sudo -n -u luke -H env PYTHONPATH=/home/luke/dreambuddy/4-MEMORY/9-工具与接口 /home/luke/venv-trading/bin/python /home/luke/dreambuddy/4-MEMORY/9-工具与接口/cognitive_mcp_server.py"]
   ```
   **保留原本地配置为可切换回退**（改名备份）。
4. 验收（接口级）：
   - 调用 `record` 后，远端 `cognitive_memory.db` 行数 **增长**、本地库 **不变**；
   - `recall` 命中远端新写入内容；
   - 断网时明确报错而非静默写本地。
5. 回滚：恢复备份的本地 MCP 配置。

---

## 阶段 5 — 镜像与 gene_data 过渡期同步

| 步骤 | 动作 | 验收 |
|---|---|---|
| T7-3 | 本地 LaunchAgent：定时 `rsync` 拉取远端快照 → 本地 `4-MEMORY/data/`、`19-数据访问层/data/`（只读镜像） | 本地文件 mtime 更新、内容与远端一致 |
| T8 | 过渡期 gene_data 收敛脚本：本地新增**上行合并** → 远端 → **下行**（`rsync` 不加 `--delete`） | 一个周期后两侧均无新增丢失（merge 生效） |

- 回滚：停用 LaunchAgent；`gene_data` 保留 `.bak`。

---

## 阶段 6 — Phase 2 影子模式（**本轮不执行 / 移出范围**）

> 用户决定：**本轮不实施影子模式**，需自行观察一段时间后再决定是否切换。本阶段仅保留设计登记，不在本次执行序列内；T9 不执行。
> 启动条件：用户观察后明确指示「本地与远端稳定一致」再另行推进。

- T9：本地新增开关停用 `gene_data` 写入（本地 `polling_trader` 影子化）；
- 同步切纯下行单向（`rsync --delete`）；
- 切换前强制「先对齐一次 + 留 `.bak`」。

---

## 验收总表

| 项 | 证据 | 阶段 |
|---|---|---|
| 依赖声明 | `pyproject.toml` 含 `sde` 组 | 1 |
| 可观测性 | 启动日志含 torch/SDE 后端状态 | 1 |
| SDE 后端（本地/远端） | `SDESolver.status()` == `torchsde` | 2 / 3 |
| 认知单写方 | record 后远端 +N、本地不变 | 4 |
| 快照与镜像 | 快照 `integrity_check=ok`；本地镜像 mtime 更新 | 3 / 5 |
| 过渡期不丢数据 | merge 后两侧新增均在 | 5 |

---

## 风险与回滚

见 SPEC §4。执行中出现 SSH `Permission denied`/exit 255 属已知偶发，重试 1–2 次。
