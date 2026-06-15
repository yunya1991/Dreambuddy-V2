"use client";

// ============================================================
// NotebookPanel — 笔记本主面板
// 版本: v1.0 | 日期: 2026-06-15
// 整合 StepProgress + StepActionMenu + ActiveDZEChain + TaskCard
// 并与 API 路由同步
// ============================================================

import { useEffect, useState } from "react";
import StepProgress from "./StepProgress";
import StepActionMenu from "./StepActionMenu";
import TaskCard from "./TaskCard";
import ActiveDZEChain from "./ActiveDZEChain";
import { useNotebookStore } from "@/stores/notebook-store";
import type { NotebookTask, StepAction, NotebookState } from "@/lib/notebook/types";

interface Props {
  onNewTask?: (prompt: string) => void;
}

const TAB_COLORS: Record<string, { bg: string; color: string }> = {
  current: { bg: "#1a2a3a", color: "#00a0ff" },
  history: { bg: "#1a2a1a", color: "#00a060" },
};

export default function NotebookPanel({ onNewTask }: Props) {
  const { currentTaskId, tasks, startTask, applyStepAction, syncFromServer, init } = useNotebookStore();
  const [tab, setTab] = useState<"current" | "history">("current");
  const [busy, setBusy] = useState(false);
  const [serverState, setServerState] = useState<NotebookState | null>(null);

  // 首次加载: 从服务端拉取状态
  useEffect(() => {
    init();
    fetchServer();
  }, [init]);

  async function fetchServer() {
    try {
      const res = await fetch("/api/notebook/state");
      const data = await res.json();
      if (data.success && data.data) {
        setServerState(data.data);
        syncFromServer(data.data);
      }
    } catch {}
  }

  async function handleAction(action: StepAction, targetStep?: number, reason?: string) {
    if (!currentTaskId) return;
    setBusy(true);
    try {
      // 先本地更新
      applyStepAction(currentTaskId, action, targetStep, reason);

      // 再服务端同步
      const res = await fetch("/api/notebook/step", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId: currentTaskId, action, targetStep, reason }),
      });
      const data = await res.json();
      if (data.success && data.data?.state) {
        syncFromServer(data.data.state);
      }
    } catch (e) {
      console.warn("Notebook action sync failed:", e);
    } finally {
      setBusy(false);
    }
  }

  async function handleStartNewTask(title: string, prompt: string, intent: string = "triple_chain") {
    setBusy(true);
    try {
      const res = await fetch("/api/notebook", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          userInput: prompt,
          intent,
          sessionId: `sess_${Date.now()}`,
          entities: {},
          routing: null,
        }),
      });
      const data = await res.json();
      if (data.success) {
        syncFromServer(data.data.state);
      }
    } catch (e) {
      console.warn("Notebook start task failed:", e);
    } finally {
      setBusy(false);
    }
  }

  const currentTask: NotebookTask | null = tasks.find((t: NotebookTask) => t.id === currentTaskId) || null;
  const completedTasks = tasks.filter((t: NotebookTask) => t.phase === "done");
  const activeTasks = tasks.filter((t: NotebookTask) => t.phase === "active" && t.id !== currentTaskId);

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 600,
        backgroundColor: "#0a0a0a",
        color: "#ddd",
        fontFamily: "inherit",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid #1a1a1a",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#fff" }}>
            📒 笔记本
          </div>
          <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>
            {tasks.length} 个任务 · {completedTasks.length} 已完成
            {serverState && ` · 已同步`}
          </div>
        </div>
        <div
          style={{
            display: "flex",
            gap: 4,
            backgroundColor: "#0d0d0d",
            borderRadius: 6,
            padding: 3,
          }}
        >
          {(Object.keys(TAB_COLORS) as Array<"current" | "history">).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: "6px 12px",
                backgroundColor: tab === t ? TAB_COLORS[t].bg : "transparent",
                color: tab === t ? TAB_COLORS[t].color : "#666",
                border: "none",
                borderRadius: 4,
                fontSize: 12,
                fontWeight: tab === t ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {t === "current" ? "当前" : "历史"}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: 16 }}>
        {tab === "current" && (
          <>
            {/* 当前任务 或 空状态 */}
            {currentTask ? (
              <div>
                {/* Step Progress */}
                <div style={{ marginBottom: 16 }}>
                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      marginBottom: 4,
                      color: "#ccc",
                    }}
                  >
                    📊 7步进度
                  </div>
                  <StepProgress steps={currentTask.steps} />
                </div>

                {/* D-Z-E 链可视化 */}
                <div style={{ marginBottom: 16 }}>
                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      marginBottom: 8,
                      color: "#ccc",
                    }}
                  >
                    🔗 思维链
                  </div>
                  <ActiveDZEChain chain={currentTask.dzeChain} />
                </div>

                {/* 当前步骤的输入/输出 */}
                <ActiveStepContent task={currentTask} onUpdate={() => fetchServer()} />

                {/* 决策菜单 */}
                <StepActionMenu
                  taskId={currentTask.id}
                  onAction={handleAction}
                  totalSteps={currentTask.steps.length}
                  disabled={busy}
                />
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: 20 }}>
                <div style={{ fontSize: 13, color: "#888", marginBottom: 12 }}>
                  暂无活跃任务 · 在上方对话中提出需求会自动创建
                </div>
                <button
                  onClick={() =>
                    handleStartNewTask("黄金交易策略", "为我制定黄金交易策略", "triple_chain")
                  }
                  disabled={busy}
                  style={{
                    padding: "10px 18px",
                    backgroundColor: busy ? "#1a1a1a" : "#0066ff",
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: busy ? "not-allowed" : "pointer",
                  }}
                >
                  🚀 试试：制定黄金交易策略
                </button>
              </div>
            )}
          </>
        )}

        {tab === "history" && (
          <div>
            {tasks.length === 0 ? (
              <div style={{ fontSize: 12, color: "#666", textAlign: "center", padding: 20 }}>
                暂无历史任务
              </div>
            ) : (
              <>
                {completedTasks.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div
                      style={{
                        fontSize: 11,
                        color: "#008855",
                        marginBottom: 8,
                        fontWeight: 600,
                      }}
                    >
                      ✅ 已完成 ({completedTasks.length})
                    </div>
                    {completedTasks.slice(0, 5).map((t: NotebookTask) => (
                      <TaskCard key={t.id} task={t} />
                    ))}
                  </div>
                )}

                {activeTasks.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div
                      style={{
                        fontSize: 11,
                        color: "#0088ff",
                        marginBottom: 8,
                        fontWeight: 600,
                      }}
                    >
                      ▶ 其他活跃 ({activeTasks.length})
                    </div>
                    {activeTasks.slice(0, 5).map((t: NotebookTask) => (
                      <TaskCard key={t.id} task={t} />
                    ))}
                  </div>
                )}

                {/* 完整历史 (全部任务) */}
                <div
                  style={{
                    fontSize: 11,
                    color: "#888",
                    marginBottom: 8,
                    fontWeight: 600,
                  }}
                >
                  📋 全部任务 ({tasks.length})
                </div>
                {tasks.slice(0, 20).map((t) => (
                  <TaskCard key={t.id} task={t} isCurrent={t.id === currentTaskId} onClick={() => {
                    useNotebookStore.getState().currentTaskId = t.id;
                    // 触发刷新
                  }} />
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Bottom note */}
      <div
        style={{
          padding: 12,
          fontSize: 10,
          color: "#555",
          borderTop: "1px solid #1a1a1a",
          textAlign: "center",
        }}
      >
        Notebook v1.0 · 解决上下文压缩 & 工作漂移问题
      </div>
    </div>
  );
}

// 当前活跃步骤的内容展示组件
function ActiveStepContent({
  task,
}: {
  task: NotebookTask;
  onUpdate: () => void;
}) {
  const [output, setOutput] = useState("");

  const activeStep = task.steps.find((s) => s.status === "active");
  const lastCompleted = [...task.steps].reverse().find((s) => s.status === "done");

  useEffect(() => {
    if (activeStep) {
      setOutput(activeStep.output || defaultOutput(activeStep.number, task));
    } else {
      setOutput("");
    }
  }, [activeStep?.id, task.id]);

  if (!activeStep) {
    return (
      <div style={{ marginBottom: 16, padding: 12, backgroundColor: "#0d2d1a", border: "1px solid #006b3f", borderRadius: 6 }}>
        <div style={{ fontSize: 12, color: "#00a060", fontWeight: 600 }}>
          ✅ 全部步骤完成
        </div>
      </div>
    );
  }

  const stepColor = "#0088ff";

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          marginBottom: 8,
          color: stepColor,
        }}
      >
        {activeStep.icon} Step {activeStep.number} {activeStep.name} · 当前活跃
      </div>

      {/* 前一步的产出 */}
      {lastCompleted && lastCompleted.number < activeStep.number && lastCompleted.output && (
        <div
          style={{
            padding: 10,
            backgroundColor: "#0d1a0d",
            borderLeft: "3px solid #006b3f",
            borderRadius: 4,
            marginBottom: 10,
            fontSize: 11,
            color: "#88aa88",
            lineHeight: 1.5,
          }}
        >
          <div style={{ color: "#008855", fontWeight: 600, marginBottom: 4 }}>
            Step {lastCompleted.number} 产出:
          </div>
          <div style={{ whiteSpace: "pre-wrap" }}>{lastCompleted.output.slice(0, 500)}{lastCompleted.output.length > 500 ? "..." : ""}</div>
        </div>
      )}

      {/* 自动生成的当前步建议 */}
      <div
        style={{
          padding: 12,
          backgroundColor: "#0d1a2d",
          borderLeft: "3px solid #0066ff",
          borderRadius: 4,
          marginBottom: 10,
          fontSize: 11,
          color: "#aabbee",
          lineHeight: 1.6,
        }}
      >
        <div style={{ color: "#0088ff", fontWeight: 600, marginBottom: 6 }}>
          ✨ 本步建议产出
        </div>
        <div style={{ whiteSpace: "pre-wrap" }}>{output}</div>
      </div>

      <textarea
        value={output}
        onChange={(e) => setOutput(e.target.value)}
        placeholder="在下方编辑此步骤的产出内容..."
        style={{
          width: "100%",
          boxSizing: "border-box",
          minHeight: 60,
          padding: 10,
          backgroundColor: "#141414",
          border: "1px solid #222",
          borderRadius: 4,
          color: "#ccc",
          fontSize: 11,
          fontFamily: "inherit",
          resize: "vertical",
          lineHeight: 1.5,
        }}
      />
    </div>
  );
}

// 默认输出内容生成
function defaultOutput(stepNumber: number, task: NotebookTask): string {
  const intent = task.intent;
  const entity = task.entities.symbol || "标的";

  switch (stepNumber) {
    case 2:
      return `根据需求 "${task.title}"，建议通过 D-Z-E 三链展开：

📌 D 链 — 深度调研
  D1: ${entity} 宏观行情与资金流向分析
  D2: ${entity} 技术结构与关键位识别
  D3: ${entity} 多情景推演
  D4: 输出策略规格书

📌 Z 链 — 规划验证
  Z1: 参数扫描与回测
  Z2: 风险边界界定
  Z3: 具体路径
  Z4: 验收标准

📌 E 链 — 执行交付
  E1: 实际执行步骤
  E2: 监控与验证
  E3: 复盘总结

  ↓ 继续下一步，进入 D1 调研`;

    case 3:
      return `知识库检索建议：
  - 从 ${entity} 的历史数据中提取 1-3 篇最相关文档
  - 结合知识库中的策略模板与 ${entity} 最新行情
  - 补充回测结果，形成知识 + 数据双驱动`;

    case 4:
      return `方法论借鉴：
  - 参考 A 系列方法论（已集成到智能路由）
  - 基于 "调研 → 分析 → 推演 → 规格" 四步流程
  - 当前意图: ${intent}`;

    case 5:
      return `索引更新：
  - 策略文档保存到 0-NOTEBOOK/
  - 更新知识库索引
  - 记录关键指标与参数`;

    case 6:
      return `协作归档：
  - 策略规格已写入 Markdown
  - 飞书 Base / Wiki 同步建议
  - 供团队其他成员复用`;

    case 7:
      return `记忆蒸馏：
  - 本次任务的关键发现
  - 可复用的方法论片段
  - 未来改进建议`;

    default:
      return "";
  }
}
