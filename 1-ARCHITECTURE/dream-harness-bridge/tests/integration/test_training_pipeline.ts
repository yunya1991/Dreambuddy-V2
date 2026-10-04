/**
 * P0-5-S3: 训练数据管线集成测试
 *
 * 测试用例:
 * 1. TC-1: 难例 → request_label → pending.jsonl
 * 2. TC-2: 标注 → labeled.jsonl
 * 3. TC-3: 质量门禁（quality_gate.validate_dataset）
 * 4. TC-4: 模型注册 → registry.jsonl
 * 5. TC-5: 事件消费 → events.jsonl
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-5
 * 边界守护（HC-9 硬约束）:
 * - 测试全程不出现交易判断逻辑
 * - 测试样本不含 direction/action/reward 字段
 */

import { describe, it, expect, beforeAll, beforeEach, afterEach, afterAll } from "vitest";
import { ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import {
  readFileSync,
  unlinkSync,
  existsSync,
  mkdirSync,
  rmSync,
} from "node:fs";
import { startPythonIPCServer, stopPythonIPCServer } from "../../packages/bridge-core/src/python-ipc";
import { requestLabel } from "../../packages/bridge-core/src/label-requester";
import { publishModelUpdate, fetchTrainingDataset } from "../../packages/bridge-core/src/training-data-bridge";
import {
  consumeTrainingDatasetEvent,
  consumeModelUpdateEvent,
  getEventsDir,
  getEventsFile,
} from "../../packages/bridge-core/src/training-event-consumer";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

const QUALITY_GATE_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "quality_gate.py"
);

// 重定向 HOME 到项目内临时目录，避免沙盒阻止写入 ~/.workbuddy/
const FAKE_HOME = resolve(__dirname, "..", "..", ".test-tmp-home");
const TRAINING_DATASETS_DIR = resolve(FAKE_HOME, ".workbuddy", "training_datasets");
const PENDING_FILE = resolve(TRAINING_DATASETS_DIR, "pending.jsonl");
const LABELED_FILE = resolve(TRAINING_DATASETS_DIR, "labeled.jsonl");
const MODEL_REGISTRY_DIR = resolve(FAKE_HOME, ".workbuddy", "model_registry");
const REGISTRY_FILE = resolve(MODEL_REGISTRY_DIR, "registry.jsonl");

/**
 * 清理测试数据文件（每个测试前）
 */
function _cleanupTestFiles(): void {
  // EVENTS_FILE 在 HOME 重定向后由 getEventsFile() 动态返回
  const eventsFile = resolve(FAKE_HOME, ".workbuddy", "training_datasets", "events.jsonl");
  const files = [PENDING_FILE, LABELED_FILE, REGISTRY_FILE, eventsFile];
  for (const f of files) {
    try {
      if (existsSync(f)) unlinkSync(f);
    } catch {
      // ignore
    }
  }
}

/**
 * 读取 JSONL 文件并解析为行数组
 */
function _readJsonl(path: string): Record<string, unknown>[] {
  if (!existsSync(path)) return [];
  const content = readFileSync(path, "utf8");
  const lines = content.split("\n").filter((l) => l.trim());
  return lines.map((l) => JSON.parse(l));
}

/**
 * 调用 Python quality_gate.validate_dataset（通过 execSync 同步）
 */
function _callValidateDataset(dataset: unknown[]): {
  valid: boolean;
  quality_score: number;
  issues: string[];
} {
  const { execSync } = require("node:child_process");
  const qualityGateDir = resolve(QUALITY_GATE_PATH, "..");
  // 用 stdin 传 dataset，避免 shell 引号转义问题
  const script = [
    "import sys, json",
    `sys.path.insert(0, ${JSON.stringify(qualityGateDir)})`,
    "from quality_gate import validate_dataset",
    "dataset = json.loads(sys.stdin.read())",
    "result = validate_dataset(dataset)",
    "print(json.dumps(result))",
  ].join("; ");
  const output = execSync(`python3 -c "${script.replace(/"/g, '\\"')}"`, {
    input: JSON.stringify(dataset),
    encoding: "utf8",
  });
  return JSON.parse(output.trim());
}

describe("P0-5: 训练数据管线集成测试", () => {
  let pyServer: ChildProcess | null = null;
  const originalHome = process.env.HOME;

  beforeAll(() => {
    // 重定向 HOME 到项目内临时目录（沙盒可写）
    process.env.HOME = FAKE_HOME;
    mkdirSync(FAKE_HOME, { recursive: true });
  });

  beforeEach(async () => {
    _cleanupTestFiles();
    // 确保目录存在
    mkdirSync(TRAINING_DATASETS_DIR, { recursive: true });
    mkdirSync(MODEL_REGISTRY_DIR, { recursive: true });
    mkdirSync(getEventsDir(), { recursive: true });

    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
      env: {
        ENABLE_ALGORITHM_LAYER: "1",
        HOME: FAKE_HOME,  // Python Path.home() 也指向临时目录
      },
    });
  });

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
    _cleanupTestFiles();
  });

  afterAll(() => {
    // 恢复原始 HOME
    if (originalHome !== undefined) {
      process.env.HOME = originalHome;
    } else {
      delete process.env.HOME;
    }
    // 清理临时目录
    try {
      rmSync(FAKE_HOME, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it("TC-1: 难例 → request_label → pending.jsonl", async () => {
    // 难例: confidence < 0.55（ACTIVE_LEARNING_DIFFICULTY_THRESHOLD）
    const result = await requestLabel(pyServer!, {
      user_message: "BTC 行情研判",
      intent_type: "UNCERTAIN",
      confidence: 0.32,
      tier: "T1",
    });

    expect(result.degraded).toBe(false);
    expect(result.status).toBe("ok");
    expect(result.sample_id).toBeTruthy();

    // 验证 pending.jsonl 有记录
    const pending = _readJsonl(PENDING_FILE);
    expect(pending.length).toBe(1);
    expect(pending[0].id).toBe(result.sample_id);
    expect(pending[0].user_message).toBe("BTC 行情研判");

    // HC-9 验证：样本不含交易决策字段
    expect(pending[0]).not.toHaveProperty("direction");
    expect(pending[0]).not.toHaveProperty("action");
    expect(pending[0]).not.toHaveProperty("reward");
  }, 15000);

  it("TC-2: 标注 → labeled.jsonl", async () => {
    // 附带 label 直接写入 labeled.jsonl
    const result = await requestLabel(pyServer!, {
      algorithm_result: {
        user_message: "ETH 趋势跟踪",
        intent_type: "TREND_FOLLOWING",
        confidence: 0.72,
        tier: "T1",
      },
      label: "TREND_FOLLOWING",
      label_source: "shadow_review",
    });

    expect(result.degraded).toBe(false);
    expect(result.status).toBe("ok");

    // 验证 labeled.jsonl 有记录
    const labeled = _readJsonl(LABELED_FILE);
    expect(labeled.length).toBe(1);
    expect(labeled[0].label).toBe("TREND_FOLLOWING");
    expect(labeled[0].label_source).toBe("shadow_review");
    expect(labeled[0].algorithm_result).toBeTruthy();

    // HC-9 验证
    expect(labeled[0]).not.toHaveProperty("direction");
    expect(labeled[0]).not.toHaveProperty("action");
  }, 15000);

  it("TC-3: 质量门禁（quality_gate.validate_dataset）", () => {
    // 构造 12 条合法样本（> _MIN_DATASET_SIZE=10）
    // 标签分布: 6 条 TREND_FOLLOWING + 6 条 BREAKOUT（1:1 平衡）
    const dataset: Record<string, unknown>[] = [];
    for (let i = 0; i < 6; i++) {
      dataset.push({
        id: `sample-tf-${i}`,
        user_message: `trend query #${i}`,
        algorithm_result: { intent_type: "TREND_FOLLOWING", confidence: 0.7 },
        label: "TREND_FOLLOWING",
        label_source: "shadow_review",
      });
    }
    for (let i = 0; i < 6; i++) {
      dataset.push({
        id: `sample-bo-${i}`,
        user_message: `breakout query #${i}`,
        algorithm_result: { intent_type: "BREAKOUT", confidence: 0.65 },
        label: "BREAKOUT",
        label_source: "shadow_review",
      });
    }

    // 调用 Python quality_gate
    const result = _callValidateDataset(dataset);

    expect(result.valid).toBe(true);
    expect(result.quality_score).toBeGreaterThan(0.8);
    expect(result.issues.length).toBe(0);
  });

  it("TC-4: 模型注册 → registry.jsonl", async () => {
    const result = await publishModelUpdate(pyServer!, {
      model_id: "intent_classifier_v1",
      version: "1.0.0",
      metrics: { accuracy: 0.85, f1: 0.82 },
      dataset_size: 1200,
      training_params: { epochs: 10, lr: 1e-4 },
      rollout_strategy: "canary_10pct",
    });

    expect(result.degraded).toBe(false);
    expect(result.registered).toBe(true);

    // 验证 registry.jsonl 有记录
    const registry = _readJsonl(REGISTRY_FILE);
    expect(registry.length).toBe(1);
    expect(registry[0].model_id).toBe("intent_classifier_v1");
    expect(registry[0].version).toBe("1.0.0");
    expect(registry[0].metrics).toEqual({ accuracy: 0.85, f1: 0.82 });
    expect(registry[0].dataset_size).toBe(1200);
    expect(registry[0].record_id).toBeTruthy();

    // HC-9 验证
    expect(registry[0]).not.toHaveProperty("direction");
    expect(registry[0]).not.toHaveProperty("action");
    expect(registry[0]).not.toHaveProperty("reward");
  }, 15000);

  it("TC-5: 事件消费 → events.jsonl", () => {
    // TC-5a: 消费 training.dataset 事件
    const datasetResult = consumeTrainingDatasetEvent({
      sample_count: 1200,
      label_distribution: { TREND_FOLLOWING: 600, BREAKOUT: 600 },
      generated_at: new Date().toISOString(),
    });

    expect(datasetResult.degraded).toBe(false);
    expect(datasetResult.written).toBe(true);
    expect(datasetResult.event_type).toBe("training.dataset");

    // TC-5b: 消费 model.update 事件
    const modelResult = consumeModelUpdateEvent({
      model_id: "intent_classifier_v1",
      version: "1.0.0",
      rollout_strategy: "canary_10pct",
    });

    expect(modelResult.degraded).toBe(false);
    expect(modelResult.written).toBe(true);
    expect(modelResult.event_type).toBe("model.update");

    // 验证 events.jsonl 有两条记录
    const events = _readJsonl(getEventsFile());
    expect(events.length).toBe(2);
    expect(events[0].event_type).toBe("training.dataset");
    expect(events[1].event_type).toBe("model.update");
    expect(events[0].payload.sample_count).toBe(1200);
    expect(events[1].payload.model_id).toBe("intent_classifier_v1");

    // HC-9 验证
    expect(events[0]).not.toHaveProperty("direction");
    expect(events[0]).not.toHaveProperty("action");
    expect(events[1]).not.toHaveProperty("reward");
  });

  it("TC-6: FAIL-OPEN — fetch_training_dataset 在无标注文件时返回空数组", async () => {
    // pending.jsonl 和 labeled.jsonl 都不存在（已被 _cleanupTestFiles 清理）
    const result = await fetchTrainingDataset(pyServer!, { limit: 50 });

    expect(result.degraded).toBe(false);
    expect(result.count).toBe(0);
    expect(Array.isArray(result.dataset)).toBe(true);
    expect(result.dataset.length).toBe(0);
  }, 15000);
});
