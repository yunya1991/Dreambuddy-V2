---
name: "real-environment-interaction"
description: "真实环境交互测试系统 — 五引擎架构（脚本引擎 + agent-browser CLI + Browser Use AI + 腾讯 BrowserSkill bsk CLI + trae 电脑控制/桌面原生）。通过连接真实 Chrome 浏览器（CDP）或启动独立 Chrome，模拟真实用户行为进行前端UI测试、端到端系统测试和AI能力验证。突破 agent-browser 沙箱限制，通过 DOM+截图+网络请求三重验证避免 AI 幻觉。线5 支持跨应用桌面任务（浏览器+终端+文件系统三端闭环）。Invoke when 需要真实浏览器环境测试、前端验收、端到端验证、反幻觉验证、AI语义化测试、省 token 测试、移动端模拟、人工接管验证码、跨应用桌面自动化时。"
version: "2.3.0"
category: "testing"
triggers:
  - "真实环境测试"
  - "浏览器测试"
  - "前端验收"
  - "端到端测试"
  - "反幻觉验证"
  - "CDP 连接"
  - "真实用户模拟"
  - "AI 语义化测试"
  - "Browser Use"
  - "双引擎测试"
  - "三引擎测试"
  - "四引擎测试"
  - "五引擎测试"
  - "省 token 测试"
  - "agent-browser CLI"
  - "腾讯 BrowserSkill"
  - "bsk CLI"
  - "request-help 人工接管"
  - "emulate 设备模拟"
  - "跨应用测试"
  - "桌面自动化"
  - "电脑控制"
  - "computer_use"
  - "desktop_native"
  - "pyautogui"
  - "osascript"
depends_on:
  - playwright
  - browser-use
  - pyyaml
  - Pillow
  - numpy
  - agent-browser
  - bsk
  # 线5 模式 B 桌面原生引擎（可选，CI 无人值守用）
  - pyautogui
  # 协同 skill（可选调用，非强依赖；通过 30/skills/ 符号链接引用 .trae/skills 源）
  - dream-qwen-eval-collab
  - dream-research-workflow
  - evolution-case-ingest
  - dream-self-iteration-workflow
  - dream-backtest-verify
provides:
  - browser_connector
  - user_simulator
  - scenario_runner
  - result_verifier
  - report_generator
  - ai_agent
  - llm_factory
  - agent_browser_runner
  - bsk_runner
  - computer_use_runner
  - desktop_assertions
---

# 真实环境交互测试系统

## 定位

突破 `agent-browser` 沙箱限制，连接**真实 Chrome 浏览器**进行端到端测试。
通过**五引擎架构**（脚本引擎 + agent-browser CLI + Browser Use AI + 腾讯 BrowserSkill bsk + trae 电脑控制/桌面原生）+ **DOM+截图+网络请求三重验证**，确保测试结果真实可信，避免 AI 幻觉。线5 进一步突破浏览器边界，支持**跨应用桌面任务**（浏览器+终端+文件系统三端闭环）。

## 五引擎架构

| 引擎 | 驱动方式 | LLM token | 适用场景 | 可复现性 |
|------|---------|-----------|---------|---------|
| **线1 脚本引擎** | YAML + user_simulator + Playwright | 零 | 确定性测试、回归测试、UI 冒烟 | 高（每步明确） |
| **线2 agent-browser 引擎** | YAML 原生命令 + agent-browser CLI + GLM-5.2 Bash 编排 | 零（GLM-5.2 自身） | 省token 测试、CI 自动化、DOM 文本验证 | 高（CLI 确定性） |
| **线3 AI 引擎** | Browser Use Agent + Qwen VL | 高（每步调用 LLM） | 语义化任务、复杂多步操作、探索性测试 | 中（依赖 LLM 输出） |
| **线4 bsk 引擎** | YAML 原生命令 + 腾讯 BrowserSkill CLI + GLM-5.2 Bash 编排 | 零（GLM-5.2 自身） | DSH 原生、多 session 并发、移动端模拟、反爬虫人工接管 | 高（CLI 确定性） |
| **线5 computer_use 引擎（v2.3 新增）** | 双模式：A) YAML 自然语言 prompt + trae Agent(subagent_type=computer_use)；B) YAML + pyautogui + osascript | 零（GLM-5.2 自身，模式 A 由 trae 主对话编排；模式 B 纯 Python） | 跨应用任务（浏览器+终端+文件系统）、系统设置、桌面自动化、CI 无人值守 | A: 中（依赖 subagent）；B: 高（pyautogui 确定性） |

五引擎共享**三重验证层**和**报告生成层**，确保无论用哪种引擎执行，结果都经过真实数据校验。线5 还共享**桌面断言层**（`utils/desktop_assertions.py`），支持文件/终端/UI 视觉断言。

### 五引擎选择决策树

```
是否需要跨应用任务（Chrome 浏览器之外，如终端/访达/系统设置）？
├── 是 → 线5 computer_use 引擎（双模式 A+B）
│        ├── 需 trae 协作 / 多模态视觉 → 模式 A (mode: computer_use, plan-only)
│        └── 需 CI 无人值守 / 纯 Python → 模式 B (mode: desktop_native)
└── 否（仅浏览器内） → 是否需要语义化任务（自然语言描述）？
    ├── 是 → 线3 AI 引擎（Browser Use + Qwen VL）
    └── 否 → 是否需要 DSH 原生 / 多 session / 移动端模拟 / 反爬虫人工接管？
        ├── 是 → 线4 bsk 引擎（腾讯 BrowserSkill CLI）
        └── 否 → 是否需要省 token（无外部 LLM）？
            ├── 是 → 线2 agent-browser 引擎（GLM-5.2 + CLI）
            └── 否 → 线1 脚本引擎（YAML + Playwright）
```

## 线2 agent-browser 引擎（v2.1 新增）

### 设计原理

**省 token 原理**：
- `agent-browser snapshot -i` 输出结构化 DOM 文本（`@e1 [input type='email']`）
- GLM-5.2 读文本比 Qwen VL 读截图省 ~10× tokens
- 所有 LLM 编排在 TRAE 主对话中完成（GLM-5.2 自身），无需调用外部 LLM

**反幻觉设计**：
- GLM-5.2 编排每步后可注入 callback 判断（是否继续）
- `_run_verification` 用 agent-browser `snapshot`/`screenshot`/`network` 做三重验证
- 不依赖 LLM 主观判断，所有断言基于真实 CLI 输出

### 原生命令风格 YAML

YAML step 与 agent-browser CLI 命令 1:1 映射：

```yaml
mode: agent_browser
session: form_test
steps:
  - open: https://example.com/login          # agent-browser open <url>
  - snapshot: {interactive: true}            # agent-browser snapshot -i
  - fill: {ref: "@e1", value: "user@x.com"}  # agent-browser fill @e1 "user@x.com"
  - click: {ref: "@e3"}                      # agent-browser click @e3
  - wait: {load: networkidle}               # agent-browser wait --load networkidle
  - screenshot: "/tmp/out.png"              # agent-browser screenshot /tmp/out.png
  - get: "url"                               # agent-browser get url
```

### agent-browser CLI 命令支持

| YAML 键 | CLI 命令 | 必需参数 |
|---------|---------|---------|
| `open` | `open <url>` | url |
| `snapshot` | `snapshot [-i]` | interactive（可选） |
| `click` | `click <ref>` | ref |
| `fill` | `fill <ref> <value>` | ref, value |
| `wait` | `wait [--load X] [--text X] [sel] [--state X]` | load/text/selector |
| `screenshot` | `screenshot <path>` | path |
| `get` | `get <what> [ref]` | what（url/title/text） |

### batch 模式

```python
runner.run_batch([
    ["open", "https://example.com"],
    ["snapshot", "-i"],
    ["click", "@e1"],
])  # 一次性通过 stdin 传 JSON 数组，减少进程启动开销
```

## 线4 bsk 引擎（v2.2 新增）

### 设计原理

腾讯 [BrowserSkill](https://github.com/Tencent/BrowserSkill) 通过 DSH 插件 `@wxg-prc-cpg/browser-skill-dsh-plugin@^0.3.0` 接入，CLI 工具为 `bsk`（v0.3.2，路径 `/Users/zhangjiangtao/.local/bin/bsk`）。

**与线2 的差异**：
- 线2 用 `agent-browser` CLI（Trae 官方）
- 线4 用 `bsk` CLI（腾讯 BrowserSkill），DSH 原生插件
- 两者都是 GLM-5.2 + Bash 编排，省 token 原理相同

### 独特能力（agent-browser 没有的）

| 能力 | bsk 命令 | 用途 |
|------|---------|------|
| Multi-session 并发 | `bsk session start/stop/list` | 一对话驱动 5 个浏览器会话 |
| Multi-tab + borrow | `bsk tab` 命令组 | 借用用户已开标签页操作后归还 |
| request-help 人工接管 | `bsk request-help --prompt "..."` | 反爬虫关键：验证码/人脸/二次确认 |
| emulate 设备模拟 | `bsk emulate --device "iPhone 14"` | 移动端测试 |
| back/forward/reload | `bsk navigate-back/forward`/`reload` | 历史导航 |
| console 控制台 | `bsk console` | 读取浏览器 console.log/error |
| html 原始 HTML | `bsk get-html [--ref @eN]` | 获取页面或元素 HTML |
| observe 语义观察 | `bsk observe` | VOM 感知探针，比 snapshot 更语义化 |
| 9 种交互 | `hover/wheel/scroll-to/focus/blur/press/select/upload/download` | 比 click/fill 多 7 种 |
| evaluate JS | `bsk evaluate "document.title"` | 在 Agent Window 执行 JS |

### 原生命令风格 YAML

```yaml
mode: bsk
session: form_test
steps:
  - emulate: {device: "iPhone 14"}            # bsk emulate --device "iPhone 14"
  - navigate: https://example.com/login      # bsk navigate <url>
  - snapshot: {}                              # bsk snapshot
  - fill: {ref: "@e1", value: "user@x.com"}  # bsk fill @e1 "user@x.com"
  - click: {ref: "@e3"}                       # bsk click @e3
  - wait-for-navigation: {}                   # bsk wait-for-navigation
  - request-help: {prompt: "请完成验证码"}    # bsk request-help --prompt "..."
  - console: {}                               # bsk console
  - get-html: {ref: "@e1"}                    # bsk get-html @e1
```

### Session 管理

bsk 不支持全局 `--session` flag，session 通过子命令管理：
```python
runner.start_session(name="form_test")  # bsk session start --name form_test --json
runner.list_sessions()                   # bsk session list --json
runner.stop_session(session_id="...")    # bsk session stop <id>
```
创建后自动成为 "current session"，后续命令隐式使用，maxSessions 默认 5。

## 线5 computer_use 引擎（v2.3 新增）

### 设计原理

线5 是 30 系统从「浏览器内」扩展到「整个桌面」的关键引擎，补两个空白：
1. **跨应用验证**：浏览器+终端+文件系统三端闭环（如「点导出按钮→终端看到日志→下载夹出现文件」）
2. **非浏览器场景**：系统设置/访达/终端操作

### 双模式架构（用户决策：A+B 混合）

**关键物理限制**：trae 电脑控制插件（trae-remote-official:computer-use 0.0.5）**无 CLI 可执行文件**（plugin.json 仅声明 interface），只能由 trae 主对话通过 Agent 工具 `subagent_type=computer_use` 调用。Python 进程无法直接 spawn trae subagent。因此线5 设计为双模式：

| 模式 | mode 字段 | 控制流 | CLI 命令 | CI 可用 | trae 介入 |
|------|----------|--------|---------|---------|----------|
| **A** | `computer_use` | 反转：Python 退化为「计划生成器+结果聚合器+验证器」，桌面操作由 trae 主对话介入 | `python cli.py computer-use-run --scenario <yaml>` 仅打印 JSON plan | ❌ | ✅ 必需 |
| **B** | `desktop_native` | 与线1-4 一致：Python 直接执行 | `python cli.py desktop-run --scenario <yaml>` 直接跑 | ✅ | ❌ |

### 模式 A 工作流（trae 协作场景）

1. `python cli.py computer-use-run --scenario <yaml>` → 输出 JSON plan（每条 step 转自然语言 prompt）
2. trae 主对话读 plan，对每条 prompt 调用 `Agent(subagent_type=computer_use)` 启动 subagent
3. 收集 subagent 文本响应 → `runner.parse_step_response(raw, step)` → `ComputerUseStep`
4. 全部步骤执行完 → `runner._run_verification(assertions, steps)` → `VerificationResult`
5. 报告层复用 `ReportGenerator.generate_ai_report`（已支持 `result.to_dict()`）

### 模式 B 工作流（CI 无人值守）

1. `python cli.py desktop-run --scenario <yaml>` 直接执行
2. Runner 内部调 `pyautogui`（图像匹配 `locateOnScreen` + 点击/键盘）+ `osascript`（macOS `open -a` + Terminal.app 读取）
3. bail-on-error：步骤失败立即停止
4. `DesktopAssertions` 跑文件/终端/UI 视觉断言
5. 报告层复用 `ReportGenerator`

### 模式 A YAML 格式（自然语言 prompt 风格）

```yaml
mode: computer_use
default_app: "Google Chrome"
steps:
  - activate: {app: "Google Chrome"}
  - click: {target: "刷新按钮", expect: "页面重新加载"}
  - type: {target: "地址栏", text: "http://localhost:3001/dashboard"}
  - screenshot: {path: "/tmp/cu_step1.png"}
  - open_app: {name: "Terminal"}
  - type: {target: "终端输入区", text: "tail -f ~/.workbuddy/logs/exec.log"}
assertions:
  - file_exists: {path: "~/.workbuddy/artifacts/trading/index.json"}
  - file_contains: {path: "~/.workbuddy/logs/exec.log", text: "execution_complete"}
  - terminal_contains: {text: "execution_complete"}
  - ui_visual_match: {baseline: "/tmp/cu_step1.png", threshold: 0.05}
```

### 模式 B YAML 格式（pyautogui 原生命令风格）

```yaml
mode: desktop_native
steps:
  - open_app: {name: "Google Chrome"}              # open -a Google Chrome
  - click_image: {image: "/tmp/refresh_btn.png", confidence: 0.8}  # pyautogui.locateOnScreen
  - type_text: {text: "http://localhost:3001/dashboard"}
  - press_key: {key: "return"}
  - screenshot: {path: "/tmp/cu_step1.png"}
  - open_app: {name: "Terminal"}
  - type_text: {text: "tail -f ~/.workbuddy/logs/exec.log"}
  - press_key: {key: "return"}
assertions:
  - file_exists: {path: "~/.workbuddy/artifacts/trading/index.json"}
  - terminal_contains: {text: "execution_complete"}
  - ui_visual_match: {baseline: "/tmp/cu_step1.png", threshold: 0.05}
```

### 桌面断言层（双模式共享）

`utils/desktop_assertions.py` 提供 5 类静态方法，复用 `VerificationResult` dataclass：

| 断言类型 | 方法 | 模式 A 实现 | 模式 B 实现 |
|---------|------|------------|------------|
| `file_exists` | `DesktopAssertions.file_exists(path)` | 纯 Python `Path.exists()` | 同 |
| `file_contains` | `DesktopAssertions.file_contains(path, text)` | 纯 Python `open/read` | 同 |
| `file_size_gt` | `DesktopAssertions.file_size_gt(path, size)` | 纯 Python `stat.st_size` | 同 |
| `terminal_contains` | `DesktopAssertions.terminal_contains(text, subagent_response?)` | 搜 subagent 文本响应 | `osascript` 读 Terminal.app |
| `ui_visual_match` | `DesktopAssertions.ui_visual_match(current, baseline, threshold)` | 文件路径 vs 文件路径，复用 `utils/screenshot_diff.py` | 同 |

### 与其他引擎的关系

| 特性 | 线1-4 浏览器引擎 | 线5 computer_use |
|------|-----------------|------------------|
| 作用域 | 浏览器内 | 整个 macOS 桌面 |
| 驱动 | Playwright/CLI/AI Agent | A) trae subagent；B) pyautogui+osascript |
| 跨应用 | ❌ | ✅ |
| 反检测 | 贝塞尔鼠标+随机键盘（线1） | 无（系统级 accessibility，非模拟） |
| 验证机制 | DOM+截图+网络三重 | 文件+终端+UI 视觉三重 |
| LLM token | 线1/2/4 零，线3 高 | 模式 A 由 trae 主对话编排（GLM-5.2 自身）；模式 B 纯 Python |
| 调用方式 | Python CLI `python cli.py xxx-run` | A) `python cli.py computer-use-run` 输出 plan；B) `python cli.py desktop-run` 直接执行 |

## 核心能力

### 1. 浏览器连接层 — 突破沙箱

两种模式，均不使用 Playwright 内置沙箱 Chromium：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `connect_cdp` | 通过 CDP 连接已运行的 Chrome | 复用用户登录态、cookie、扩展 |
| `launch_headed` | 启动带界面的独立 Chrome | 真实环境测试、反爬虫检测 |
| `launch_headless` | 启动 headless 独立 Chrome | CI/CD 自动化测试 |

**关键区别**：`agent-browser` 使用沙箱内的 headless Chromium，无法复用登录态、可能被反爬虫检测；本系统使用真实 Chrome + CDP，完全突破沙箱限制。

### 2. 用户行为模拟层 — 反检测（线1 脚本引擎用）

- **鼠标移动**：贝塞尔曲线轨迹 + 随机抖动，模拟真实手部运动
- **键盘输入**：每字符随机延迟，模拟真实打字节奏
- **点击操作**：移动→停留→按下→释放，非直接 element.click()
- **滚动行为**：分步滚动 + 随机步长
- **拖拽操作**：贝塞尔曲线拖拽轨迹

### 3. 三重验证机制 — 反幻觉

不依赖 AI 主观判断，通过真实数据验证：

| 验证层 | 方法 | 用途 |
|--------|------|------|
| DOM 验证 | 选择器断言（exists/text/attribute/count等） | 验证元素状态和内容 |
| 截图验证 | 像素级对比 + 差异可视化 | 检测视觉变化 |
| 网络验证 | 请求/响应捕获 + 状态码/响应体断言 | 验证 API 数据真实性 |

**验证模式**：`all`（全部通过）| `any`（任一通过）| `majority`（多数通过）

**线2 agent-browser 引擎验证**：
- DOM 断言：调用 `snapshot -i`，从 stdout 文本检查 selector
- url_contains 断言：调用 `get url`，从 stdout 检查 URL
- 网络断言：调用 `network requests`（未实现）

### 4. AI Agent 引擎 — Browser Use（v2.0 新增）

以 [Browser Use](https://github.com/browser-use/browser-use)（106K★，MIT）为核心引擎，AI 自动规划多步操作。

**核心能力**：
- `Agent(task=..., llm=..., browser=...)`：自然语言任务驱动
- `Browser.from_system_chrome()`：复用系统 Chrome 登录态
- `@tools.action`：自定义工具扩展（集成三重验证）
- 视觉+DOM 混合理解：截图分析 + 选择器定位
- 错误自动恢复

**LLM 提供商**（[官方支持 15+](https://docs.browser-use.com/open-source/supported-models)）：

| Provider | 模型 | 环境变量 | 备注 |
|----------|------|---------|------|
| **Qwen**（默认） | `qwen-vl-max` | `ALIBABA_CLOUD` | ⚠️ 官方仅推荐 VL 版本 |
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` | 通用 |
| Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | 浏览器任务强 |
| Ollama | `llama3.1:8b` | 无需 | 本地免费，受硬件限制 |
| Browser Use BU2 | `bu-2-0` | `BROWSER_USE_API_KEY` | 专为浏览器优化 |

**反幻觉设计**：AI Agent 负责执行（可能出错），三重验证层独立校验。即便 Agent 报告"任务完成"，验证层未通过仍判定失败。

## 使用方式

### 前置准备

**方式 A：连接已有 Chrome（复用登录态）**

```bash
# 1. 启动 Chrome 时开启远程调试
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-real-env"

# 2. 在 Chrome 中登录需要的账号
# 3. 运行测试（会自动复用登录态）
python cli.py run --scenario scenarios/examples/frontend_smoke.yaml --mode connect
```

**方式 B：启动独立 Chrome**

```bash
# 自动启动带 CDP 的真实 Chrome
python cli.py run --scenario scenarios/examples/frontend_smoke.yaml --mode launch_headed
```

### CLI 命令

```bash
# === 线1 脚本引擎 ===
# 运行单个场景
python cli.py run --scenario <场景文件> --mode <connect|launch_headed|launch_headless> --report

# 批量运行场景
python cli.py run-batch --scenarios <场景目录> --mode connect --report

# 检查 Chrome CDP 状态
python cli.py check

# 启动独立 Chrome（仅启动浏览器，不运行测试）
python cli.py launch

# === 线2 agent-browser 引擎（v2.1 新增，省 token）===
# 运行 agent-browser 原生命令风格 YAML 场景
python cli.py agent-browser-run --scenario scenarios/examples/agent_browser_form.yaml

# 指定 session 名（覆盖 config）
python cli.py agent-browser-run --scenario ... --session my_sess

# === 线4 bsk 引擎（v2.2 新增，腾讯 BrowserSkill，DSH 原生）===
# 运行 bsk 原生命令风格 YAML 场景（含 emulate/request-help 独特能力）
python cli.py bsk-run --scenario scenarios/examples/bsk_form.yaml

# 指定任务名（用于 bsk session start --name）
python cli.py bsk-run --scenario ... --session my_task

# === 线3 AI 引擎（v2.0 新增）===
# 运行 AI 驱动的语义化场景（自然语言任务）
python cli.py ai-run --scenario scenarios/examples/ai_semantic_task.yaml --report

# 直接传入自然语言任务
python cli.py ai-run --task "打开 example.com 并报告页面标题"

# 指定浏览器模式（默认 from_system_chrome 复用登录态）
python cli.py ai-run --task "..." --browser-mode playwright_chromium
```

### Python API

```python
import yaml
from core.browser_connector import BrowserConnector, BrowserMode
from core.user_simulator import UserSimulator
from core.result_verifier import ResultVerifier
from core.scenario_runner import ScenarioRunner
from core.agent_browser_runner import AgentBrowserRunner

# 加载配置
with open("config.yaml") as f:
    config = yaml.safe_load(f)

# === 线1 脚本引擎 ===
connector = BrowserConnector(config)
simulator = UserSimulator(config)
verifier = ResultVerifier(config)
runner = ScenarioRunner(config, simulator, verifier)

# === 线2 agent-browser 引擎（省 token）===
ab_runner = AgentBrowserRunner(config, session_name="form_test")
result = ab_runner.run_task_from_yaml({
    "name": "登录测试",
    "mode": "agent_browser",
    "steps": [
        {"open": "https://example.com/login"},
        {"snapshot": {"interactive": True}},
        {"fill": {"ref": "@e1", "value": "user@example.com"}},
        {"click": {"ref": "@e3"}},
    ],
    "assertions": {"url_contains": "/dashboard"},
})
```

## 场景编写指南

### 线1 脚本引擎场景（YAML）

支持以下 action：

| Action | 说明 | 必需参数 |
|--------|------|---------|
| `navigate` | 导航到 URL | `url` |
| `click` | 点击元素 | `selector` |
| `type` | 输入文本 | `selector`, `text` |
| `select` | 选择下拉 | `selector`, `value`/`label` |
| `scroll` | 滚动 | `direction`, `distance` |
| `hover` | 悬停 | `selector` |
| `wait` | 等待 | `selector`/`ms`/`seconds` |
| `verify` | 三重验证 | `assertions` |
| `screenshot` | 截图 | `path` |
| `assert` | JS 断言 | `expression` |
| `javascript` | 执行 JS | `expression` |

### 线2 agent-browser 引擎场景（YAML）

原生命令风格，键=命令，值=参数。详见 [agent-browser SKILL.md](file:///Users/zhangjiangtao/.trae-cn/skills/agent-browser/SKILL.md)。

### 验证断言类型

**DOM 断言**：
- `exists` / `not_exists` — 元素是否存在
- `text_contains` / `text_equals` — 文本匹配
- `attribute_equals` — 属性值匹配
- `is_visible` / `is_enabled` — 状态检查
- `count_equals` / `count_greater_than` — 数量检查
- `has_class` — CSS 类检查
- `value_equals` — 输入值检查

**截图断言**：
```yaml
screenshot:
  baseline: "baseline.png"      # 基准截图
  threshold: 0.05               # 差异阈值
  full_page: false              # 是否全页截图
  save_diff: true               # 保存差异图
  diff_path: "diff.png"
```

**网络断言**：
- `request_exists` — 请求是否存在
- `response_status` — 响应状态码
- `response_body_contains` — 响应体包含

## 与 agent-browser 的关系

| 特性 | agent-browser CLI（线2） | 本系统脚本引擎（线1） |
|------|--------------------------|---------------------|
| 驱动方式 | GLM-5.2 + Bash | YAML + Playwright |
| 浏览器 | 真实 Chrome（CLI 管理） | 真实 Chrome（CDP） |
| 登录态 | `--auto-connect` 复用 | CDP 复用 |
| 验证方式 | `snapshot`/`diff`/`network` | DOM+截图+网络三重 |
| LLM token | 零（GLM-5.2 自身） | 零（无 LLM） |
| 适用场景 | CI 自动化、省 token | 确定性测试、回归 |

## 反幻觉保障

1. **真实数据验证**：所有验证基于真实 DOM、截图、网络请求，不依赖 AI 主观判断
2. **三重交叉验证**：DOM 状态、视觉截图、API 响应三方印证
3. **可复现性**：测试场景 YAML 定义，结果可复现
4. **证据留存**：截图、网络日志、验证报告全部归档

## 文件结构

```
30-真实环境交互系统/
├── core/
│   ├── browser_connector.py    # 浏览器连接层（脚本引擎 + Browser Use 适配）
│   ├── user_simulator.py       # 用户行为模拟层（脚本引擎用）
│   ├── result_verifier.py      # 结果验证层（三重验证，五引擎共享，v2.3 接 screenshot_diff）
│   ├── scenario_runner.py      # 场景运行引擎（线1 脚本引擎）
│   ├── report_generator.py     # 报告生成层（五引擎共享）
│   ├── ai_agent.py             # AI Agent 引擎（线3，Browser Use 包装，v2.0 新增）
│   ├── llm_factory.py           # LLM 工厂（多提供商，v2.0 新增）
│   ├── agent_browser_runner.py # agent-browser 引擎（线2，GLM-5.2+CLI，v2.1 新增）
│   ├── bsk_runner.py            # bsk 引擎（线4，腾讯 BrowserSkill+CLI，v2.2 新增）
│   └── computer_use_runner.py   # computer_use 引擎（线5，trae 电脑控制+桌面原生，v2.3 新增）
├── utils/
│   ├── dom_assertions.py       # DOM 断言工具
│   ├── screenshot_diff.py      # 截图对比工具（v2.3 抽离共享，供 ResultVerifier + DesktopAssertions 调用）
│   ├── network_capture.py     # 网络请求捕获工具
│   └── desktop_assertions.py   # 桌面断言工具（v2.3 新增，file/terminal/ui_visual_match）
├── scenarios/
│   └── examples/               # 示例场景（含五引擎示例，含 computer_use_cross_app.yaml 双模式对照）
├── tests/                      # 单元测试（ai_agent + agent_browser_runner + bsk_runner + computer_use_runner）
├── config.yaml                 # 配置文件（含 llm + ai_agent + agent_browser + bsk + computer_use + desktop_native 段）
├── cli.py                      # CLI 入口（含 run/ai-run/agent-browser-run/bsk-run/computer-use-run/desktop-run 命令）
├── skills/                    # 协同 skill 符号链接（→ .trae/skills 源，避免重复造轮子）
│   ├── dream-qwen-eval-collab/      # 千问调研（4 维：金融+github+模块化+代码）
│   ├── dream-research-workflow/     # 通用多源研究
│   ├── evolution-case-ingest/       # 自进化训练案例入库（CBR/KNN）
│   ├── dream-self-iteration-workflow/ # L4 自迭代（hermes 反思+参数优化）
│   └── dream-backtest-verify/       # 事后回测验证
└── requirements.txt            # 依赖
```

## 协同 skill 调用（v2.2 新增）

真实环境交互系统作为「模拟真实用户」的执行层，跑完场景后常需把采集到的数据/案例送外部 skill 做评估或入库。下列 skill 通过 `30/skills/` 符号链接引用 `.trae/skills/` 源（单一事实源、零漂移、避免重复造轮子），调用时由 Skill 工具按 `name` 发现：

| 协同 skill | 触发场景 | 输入 | 输出 |
|-----------|---------|------|------|
| `dream-qwen-eval-collab` | 场景跑完发现反爬虫/验证码/复杂 UI 模式，需送千问二轮评估 | 调研任务包（YAML） | spec + 用户审阅 |
| `dream-research-workflow` | 对测试结果做多源交叉研究（finance+github+modular+code） | 需求文本 | 研究报告 + hermes 反思 |
| `evolution-case-ingest` | 测试中采到 washout/pump-dump 行情样本，入库 CBR/KNN 案例库 | 13 维特征 + pnl_pct | case_id + reward |
| `dream-self-iteration-workflow` | 累积案例触发 L4 自迭代（hermes 反思→参数优化→doc sync） | 24h events | 反思报告 + 升级记忆 |
| `dream-backtest-verify` | 对策略类场景做事后回测验证（klines+detector gate） | 交易记录 + 时间窗 | 反弹归因 + 价值报告 |

**调用方式**：在 30 系统运行时通过 Skill 工具或 `recall` 触发，例如：
```
recall(context="反爬虫案例 千问评估", top_k=3)  # 命中则复用，否则触发 dream-qwen-eval-collab
```

**治理约束**：
- 符号链接指向 `.trae/skills/<name>`，源 skill 更新时 30 系统自动同步（零漂移）
- 30 系统不修改源 skill 内容，只做调用方
- 若需 30 系统专属逻辑，在 `core/` 新建模块，不污染源 skill
