# research-reflect

反思进化组件（R4）：从 OKA 真实日记/决策生成候选、生成评审证据包、执行三模型评审，并扫描组件回放缺口。

- `status`：最近候选与门禁结果（只读）
- `propose`：生成交易候选（写 `<state_dir>/reverse/proposals`，不改交易配置）
- `gaps`：组件声明 vs 回放缺口（只读）
- `review`：评审证据包 + verdict（写 `<state_dir>/reverse/reviews`，不 promotion）

依赖本机 OKA：默认 `~/Documents/顺风车业务/okx-assistant`，可用 `OKA_HOME` 覆盖。

```bash
python3 skill/scripts/reflect.py status --json
# 历史回填日记集中在 2026-04~07，窗口需覆盖
python3 skill/scripts/reflect.py propose --window 400d --json
python3 skill/scripts/reflect.py gaps --llm --json
python3 skill/scripts/reflect.py review --opt-id <opt_id> --no-llm --json
```

写动作（`propose` / `review`）经 59 CLI 调用时需加 `--allow-write`。
