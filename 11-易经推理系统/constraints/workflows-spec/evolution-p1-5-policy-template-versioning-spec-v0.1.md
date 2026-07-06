# Evolution P1.5 Policy Template Versioning Spec v0.1

## 1. 目标

在 P1 的 `stage_policy` 基础上引入模板版本化能力，统一策略发布、调用和回归验证。

核心能力：

- `policy_version`：策略版本标识
- 模板库：`artifacts/evolution/policy/templates/*.json`
- 回归矩阵：`artifacts/evolution/policy/regression-matrix-p1-5-v1.json`

## 2. 模板契约

模板文件结构：

```json
{
  "policy_version": "p1.default.v1",
  "stage_policy": {
    "scenario": {
      "allow_warnings": true
    }
  }
}
```

约束：

- `policy_version` 必填且与文件名一致（不含 `.json`）。
- `stage_policy` 为 `stage -> policy` 映射。
- 任一阶段未显式声明字段时，继承脚本默认策略。

## 3. 脚本接口

`scripts/ci/evolution_decision_gate.py` 新增：

- `--policy-version`：策略版本号
- `--policy-library-dir`：模板库目录（默认 `artifacts/evolution/policy/templates`）

行为：

- 仅传 `--policy-version`：从模板库加载 `<policy-version>.json`
- 传 `--stage-policy-json`：直接使用指定策略文件
- 两者并传：校验 `policy_version` 一致，否则报错 `policy_version mismatch`

输出新增字段：

- `policy_version`
- `policy_source`

## 4. 工作流接口

`.github/workflows/evolution-decision-gate.yml` 新增输入：

- `policy_version`
- `policy_library_dir`
- `run_regression_matrix`
- `regression_matrix_json`

## 5. 回归矩阵

矩阵脚本：`scripts/ci/evolution_policy_regression_matrix.py`

执行逻辑：

- 读取矩阵用例
- 按用例运行 Decision Gate
- 对比 `expected_decision` 与实际决策
- 输出总结到 `regression-matrix-summary-*.json`

## 6. 发布基线

P1.5 基线模板：

- `p1.default.v1`
- `p1.relaxed-scenario.v1`

默认策略保持 fail-closed，不因版本化而放松门禁。
