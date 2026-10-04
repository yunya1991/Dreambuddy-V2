# 30-真实环境交互系统

> 真实浏览器环境交互测试系统 — 突破沙箱限制，通过真实 Chrome 浏览器进行端到端测试

## 核心定位

本系统突破 `agent-browser` 沙箱限制，通过 **CDP 协议连接真实 Google Chrome**，模拟真实用户行为进行：
- **前端 UI 功能测试**
- **端到端系统能力测试**
- **AI 能力验证 / 反幻觉测试**

## 核心特性

### 1. 突破沙箱 — 真实浏览器连接

| 模式 | 说明 |
|------|------|
| `connect_cdp` | 连接已运行的 Chrome，复用登录态、cookie、扩展 |
| `launch_headed` | 启动带界面的独立 Chrome（真实指纹） |
| `launch_headless` | 启动 headless 独立 Chrome |

**关键区别**：不使用 Playwright 内置沙箱 Chromium，而是使用真实 Chrome + CDP 协议。

### 2. 真实用户行为模拟

- 鼠标移动：贝塞尔曲线轨迹 + 随机抖动
- 键盘输入：每字符随机延迟，模拟打字节奏
- 点击操作：移动→停留→按下→释放
- 滚动/拖拽：分步执行，模拟人类行为

### 3. 三重验证机制 — 反幻觉

不依赖 AI 主观判断，通过真实数据验证：
- **DOM 验证**：元素存在性、文本、属性、数量断言
- **截图验证**：像素级对比 + 差异可视化
- **网络验证**：请求/响应捕获 + 状态码/响应体断言

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 方式 A：连接已有 Chrome（复用登录态）

```bash
# 1. 启动 Chrome 并开启远程调试
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-real-env"

# 2. 检查连接状态
python cli.py check

# 3. 运行测试
python cli.py run --scenario scenarios/examples/frontend_smoke.yaml --mode connect --report
```

### 方式 B：启动独立 Chrome

```bash
# 自动启动真实 Chrome 并运行测试
python cli.py run --scenario scenarios/examples/frontend_smoke.yaml --mode launch_headed --report
```

## CLI 命令

```bash
# 运行单个场景
python cli.py run --scenario <场景文件> --mode <connect|launch_headed|launch_headless> --report

# 批量运行
python cli.py run-batch --scenarios <场景目录> --mode connect --report

# 检查 Chrome CDP 状态
python cli.py check

# 仅启动 Chrome（不运行测试）
python cli.py launch
```

## 场景编写

场景使用 YAML 定义，示例见 [scenarios/examples/](scenarios/examples/)。

```yaml
name: "测试场景"
steps:
  - name: "打开页面"
    action: navigate
    url: "http://localhost:3001"

  - name: "验证加载"
    action: verify
    assertions:
      dom:
        - selector: "body"
          action: exists
      network:
        - action: request_exists
          url_pattern: "/api/"
```

## 项目结构

```
30-真实环境交互系统/
├── core/                      # 核心模块
│   ├── browser_connector.py   # 浏览器连接层
│   ├── user_simulator.py      # 用户行为模拟层
│   ├── result_verifier.py     # 三重验证层
│   ├── scenario_runner.py     # 场景运行引擎
│   └── report_generator.py    # 报告生成层
├── utils/                     # 工具模块
│   ├── dom_assertions.py
│   ├── screenshot_diff.py
│   └── network_capture.py
├── scenarios/                 # 测试场景
│   └── examples/
├── tests/                     # 单元测试
├── config.yaml                # 配置文件
├── cli.py                     # CLI 入口
├── SKILL.md                   # Skill 定义
└── requirements.txt
```

## 测试

```bash
python -m pytest tests/ -v
```

## 与 agent-browser 的区别

| 特性 | agent-browser（沙箱） | 本系统（真实环境） |
|------|----------------------|-------------------|
| 浏览器 | Playwright 内置 Chromium | 真实 Google Chrome |
| 登录态 | 无法复用 | 可复用用户登录态 |
| 反爬虫 | 易被检测 | 真实指纹 + 人类行为 |
| 验证方式 | 依赖 AI 判断 | DOM+截图+网络三重验证 |
