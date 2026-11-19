import { promises as fs } from "fs";
import os from "os";
import path from "path";

import {
  appendGateFlowEvent,
  buildGateFlowRejectionRecord,
} from "../gateflow-event-export";

describe("gateflow-event-export", () => {
  it("maps high-risk rejection without rewind to T3 signal", () => {
    const record = buildGateFlowRejectionRecord({
      taskId: "TK-1",
      traceId: "rp-1",
      gateId: "G2",
      gateKind: "acceptance",
      comment: "回测未达标",
      rewindTo: "none",
      highRisk: true,
      at: 1000,
    });

    expect(record.type).toBe("node.rejected");
    expect(record.run_id).toBe("TK-1:gate");
    expect(record.detail.high_risk).toBe(true);
    expect(record.detail.risk_level).toBe("critical");
    expect(record.detail.reversible).toBe(false);
    expect(record.detail.uncertainty_score).toBe(0.7);
    expect(record.detail.evidence_refs).toEqual([]);
  });

  it("maps normal rejection with rewind target", () => {
    const record = buildGateFlowRejectionRecord({
      taskId: "TK-2",
      gateId: "G1",
      gateKind: "spec",
      comment: "补充证据",
      rewindTo: "spec",
      evidenceRef: "EV-1",
      at: 2000,
    });

    expect(record.detail.risk_level).toBe("low");
    expect(record.detail.reversible).toBe(true);
    expect(record.detail.rewind_to).toBe("spec");
    expect(record.detail.evidence_refs).toEqual(["EV-1"]);
    expect(record.detail.uncertainty_score).toBe(0.5);
  });

  it("appends JSONL to the configured directory", async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "gateflow-export-"));
    const record = buildGateFlowRejectionRecord({
      taskId: "TK-3",
      gateId: "G3",
      gateKind: "dispatch",
      at: 3000,
    });

    const ok = await appendGateFlowEvent(record, { dir });
    expect(ok).toBe(true);

    const files = await fs.readdir(dir);
    expect(files).toHaveLength(1);
    const text = await fs.readFile(path.join(dir, files[0]), "utf8");
    const parsed = JSON.parse(text.trim());
    expect(parsed.task_id).toBe("TK-3");
    expect(parsed.type).toBe("node.rejected");
  });
});
