# L0 MCP 分发包（P3a）

> 目标：干净机器上**一条命令**启动角色网关；镜像只含代码与契约，数据运行时挂载。

## 1. 本地镜像（代码 + 空数据）

```bash
docker build -f deploy/mcp/Dockerfile -t l0-mcp .
docker run -i --rm l0-mcp --role verifier
```

宿主 MCP 配置：

```json
{
  "mcpServers": {
    "l0-verifier": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "l0-mcp", "--role", "verifier"]
    }
  }
}
```

## 2. 云端单一事实源（推荐）

镜像内不含认知库；需要 `recall/record` 的真实数据时，挂载 SSH 密钥并让网关走 ssh-stdio：

```bash
docker run -i --rm \
  -v "$HOME/.ssh:/root/.ssh:ro" \
  l0-mcp --role research --ssh-host dreambuddy-remote
```

## 3. 本地数据挂载

```bash
docker run -i --rm \
  -v "$PWD/4-MEMORY/data:/app/4-MEMORY/data" \
  -v "$PWD/33-REA逆向解析工程/reflection_data:/app/33-REA逆向解析工程/reflection_data" \
  l0-mcp --role research
```

## 4. 已验证内容（CI）

`.github/workflows/l0-contracts.yml` 的 `mcp-docker` job：

1. `docker build -f deploy/mcp/Dockerfile -t l0-mcp .`
2. 管道发送 `initialize`（`protocolVersion=2025-06-18`）+ `tools/list`
3. 断言协议版本回显、`verifier` 工具面精确匹配

## 5. 边界

- **官方 MCP SDK 未迁移**：镜像使用内置 `shell_runtime`；SDK 迁移需先引入 `mcp` 依赖并全量回归，属于后续独立任务。
- **wheel 分发未做**：仓库含中文目录与域内私有依赖，整体打 wheel 不可行；跨机分发以 Docker 为第一载体。
- 镜像不含模型/DB/密钥；只读角色默认可用，写工具仍需宿主 Mandate。