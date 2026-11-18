import { emptyTaskBoard, type GateKind, type TaskGate } from "@/types/task-board";
import { autoApproveGates, isAutoApprovable } from "./gate-auto";

const ALL: GateKind[] = ["intent", "spec", "dispatch", "acceptance", "summary"];

function snapshotWithGates() {
  const base = emptyTaskBoard("task-1", "trace-1");
  const gates: TaskGate[] = ALL.map((kind) => ({
    gate_id: kind,
    kind,
    title: kind,
    status: "waiting",
    required: true,
    evidence_ref: `${kind}:1`,
  }));
  return { ...base, gates };
}

describe("gate-auto", () => {
  it("验收门永不可自动确认", () => {
    expect(isAutoApprovable("acceptance")).toBe(false);
    expect(isAutoApprovable("intent")).toBe(true);
  });

  it("人工干预模式不产生自动确认", () => {
    expect(autoApproveGates(snapshotWithGates(), "human")).toEqual([]);
  });

  it("全权模式自动确认低/中风险，保留验收门", () => {
    const events = autoApproveGates(snapshotWithGates(), "autonomy", 123);
    const kinds = events.map((event) =>
      event.type === "gate.updated" ? event.payload.kind : null,
    );
    expect(kinds).toEqual(["intent", "spec", "dispatch", "summary"]);
    expect(kinds).not.toContain("acceptance");
    const first = events[0];
    expect(first.type).toBe("gate.updated");
    if (first.type === "gate.updated") {
      expect(first.payload.decided_by).toBe("mode:autonomy");
    }
  });
});
