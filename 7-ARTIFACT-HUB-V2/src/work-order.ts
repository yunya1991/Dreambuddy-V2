import fs from "node:fs";
import path from "node:path";

export interface WorkOrder {
  trace_id: string;
  task_id: string;
  created_at: string;
  intent: unknown;
  routing_plan: unknown;
}

export interface WorkResult {
  trace_id: string;
  task_id: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  payload?: unknown;
}

export interface QueueStats {
  total_tasks: number;
  pending_tasks: number;
  processing_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  avg_latency_ms: number;
  queue_depth_by_department: Record<string, number>;
}

export interface QueueItem {
  task_id: string;
  trace_id: string;
  created_at: string;
  status: "pending" | "processing" | "completed" | "failed";
  department: string;
  workflow_type: string;
}

export class WorkOrderManager {
  private readonly seenResults = new Set<string>();
  private readonly tasks = new Map<string, WorkOrder>();

  constructor(private readonly artifactsRoot: string) {}

  ensureDirs(): void {
    fs.mkdirSync(path.join(this.artifactsRoot, "tasks"), { recursive: true });
    fs.mkdirSync(path.join(this.artifactsRoot, "results"), { recursive: true });
  }

  writeTask(order: WorkOrder): string {
    this.ensureDirs();
    const p = path.join(this.artifactsRoot, "tasks", `task_${order.task_id}.json`);
    fs.writeFileSync(p, JSON.stringify(order, null, 2));
    this.tasks.set(order.task_id, order);
    return p;
  }

  getTask(taskId: string): WorkOrder | null {
    return this.tasks.get(taskId) ?? null;
  }

  listTasks(): WorkOrder[] {
    return Array.from(this.tasks.values());
  }

  listQueueItems(): QueueItem[] {
    this.ensureDirs();
    const items: QueueItem[] = [];

    // Load pending tasks from tasks dir
    try {
      const taskDir = path.join(this.artifactsRoot, "tasks");
      const taskFiles = fs.readdirSync(taskDir).filter(f => f.startsWith("task_") && f.endsWith(".json"));
      for (const f of taskFiles) {
        try {
          const content = JSON.parse(fs.readFileSync(path.join(taskDir, f), "utf-8")) as WorkOrder;
          const plan = content.routing_plan as any;
          items.push({
            task_id: content.task_id,
            trace_id: content.trace_id,
            created_at: content.created_at,
            status: "pending",
            department: plan?.department ?? "unknown",
            workflow_type: plan?.mode ?? "unknown",
          });
        } catch { /* skip invalid files */ }
      }
    } catch { /* dir may not exist */ }

    // Load completed/failed from results
    try {
      const resultDir = path.join(this.artifactsRoot, "results");
      const resultFiles = fs.readdirSync(resultDir).filter(f => f.startsWith("result_") && f.endsWith(".json"));
      for (const f of resultFiles) {
        try {
          const content = JSON.parse(fs.readFileSync(path.join(resultDir, f), "utf-8")) as WorkResult;
          const task = this.tasks.get(content.task_id);
          const plan = task?.routing_plan as any;
          items.push({
            task_id: content.task_id,
            trace_id: content.trace_id,
            created_at: content.created_at ?? task?.created_at ?? new Date().toISOString(),
            status: content.status as QueueItem["status"],
            department: plan?.department ?? "unknown",
            workflow_type: plan?.mode ?? "unknown",
          });
        } catch { /* skip invalid files */ }
      }
    } catch { /* dir may not exist */ }

    return items;
  }

  getQueueStats(): QueueStats {
    const items = this.listQueueItems();
    const byStatus: Record<string, number> = {};
    const byDept: Record<string, number> = {};
    let totalLatency = 0;
    let latencyCount = 0;

    for (const item of items) {
      byStatus[item.status] = (byStatus[item.status] ?? 0) + 1;
      byDept[item.department] = (byDept[item.department] ?? 0) + 1;
    }

    // Calculate avg latency from completed tasks
    try {
      const resultDir = path.join(this.artifactsRoot, "results");
      const resultFiles = fs.readdirSync(resultDir).filter(f => f.startsWith("result_") && f.endsWith(".json"));
      for (const f of resultFiles) {
        try {
          const content = JSON.parse(fs.readFileSync(path.join(resultDir, f), "utf-8")) as WorkResult;
          if (content.created_at && content.updated_at) {
            totalLatency += new Date(content.updated_at).getTime() - new Date(content.created_at).getTime();
            latencyCount++;
          }
        } catch { /* skip */ }
      }
    } catch { /* dir may not exist */ }

    return {
      total_tasks: items.length,
      pending_tasks: byStatus.pending ?? 0,
      processing_tasks: byStatus.processing ?? 0,
      completed_tasks: byStatus.completed ?? 0,
      failed_tasks: byStatus.failed ?? 0,
      avg_latency_ms: latencyCount > 0 ? Math.round(totalLatency / latencyCount) : 0,
      queue_depth_by_department: byDept,
    };
  }

  pollResults(onResult: (r: WorkResult, filePath: string) => void, intervalMs = 1000): () => void {
    this.ensureDirs();
    const dir = path.join(this.artifactsRoot, "results");
    const timer = setInterval(() => {
      let files: string[] = [];
      try {
        files = fs.readdirSync(dir).filter((f) => f.startsWith("result_") && f.endsWith(".json"));
      } catch {
        return;
      }

      for (const f of files) {
        const fp = path.join(dir, f);
        if (this.seenResults.has(fp)) continue;
        try {
          const parsed = JSON.parse(fs.readFileSync(fp, "utf-8")) as WorkResult;
          if (!parsed?.trace_id || !parsed?.task_id) {
            this.seenResults.add(fp);
            continue;
          }
          this.seenResults.add(fp);
          onResult(parsed, fp);
        } catch {
          continue;
        }
      }
    }, intervalMs);

    return () => clearInterval(timer);
  }
}

