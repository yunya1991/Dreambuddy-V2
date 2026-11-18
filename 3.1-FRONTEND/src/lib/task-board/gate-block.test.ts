import { emptyTaskBoard, type GateKind, type TaskGate } from "@/types/task-board";
import { blockingGates, buildGatePendingPayload } from "./gate-block";

const ALL: GateKind[] = ["intent", "spec", "dispatch", "acceptance", "summary"];

function gate(kind: GateKind, status: TaskGate["status"]): TaskGate {
  return {
    gate_id: kind,
    kind,
    title: kind,
    status,
    required: true,
    evidence_ref: `${kind}:1`,
  };
}

function snapshot(gates: TaskGate[]) {
  return { ...emptyTaskBoard("task-1", "trace-1"), gates };
}

describe("gate-block", () => {
  it("waiting 与 rejected 都阻塞，approved 放行", () => {
    const gates = [
      gate("intent", "approved"),
      gate("spec", "waiting"),
      gate("acceptance", "rejected"),
      gate("summary", "approved"),
    ];
    const blocked = blockingGates(snapshot(gates)).map((item) => item.kind);
    expect(blocked).toEqual(["spec", "acceptance"]);
  });

  it("不可选门不阻塞", () => {
    const gates = [{ ...gate("summary", "waiting"), required: false }];
    expect(blockingGates(snapshot(gates))).toEqual([]);
  });

  it("409 载荷带任务、模式与待确认清单", () => {
    const payload = buildGatePendingPayload(
      snapshot(ALL.map((kind) => gate(kind, "waiting"))),
      "human",
    );
    expect(payload.error.code).toBe("GATE_PENDING");
    expect(payload.mode).toBe("human");
    expect(payload.pending_gates).toHaveLength(5);
    expect(payload.pending_gates[0].evidence_ref).toBe("intent:1");
  });
});
