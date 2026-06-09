import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { BoardProposal, ApprovalGate, ExecutionReview, Distribution, Performance, MarketIntel, Decision } from "./types.js";

export class MetaStore {
  private readonly db: DatabaseSync;

  constructor(metaRoot: string) {
    fs.mkdirSync(metaRoot, { recursive: true });
    const dbPath = path.join(metaRoot, "artifact_hub.sqlite");
    this.db = new DatabaseSync(dbPath);
    this.bootstrap();
  }

  private bootstrap(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS events (
        trace_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        ts INTEGER NOT NULL,
        PRIMARY KEY (trace_id, event_id)
      );

      CREATE TABLE IF NOT EXISTS route_decisions (
        trace_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        intent_json TEXT NOT NULL,
        decision_json TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        department TEXT NOT NULL DEFAULT 'unknown',
        selected_route TEXT NOT NULL DEFAULT '',
        decision_level TEXT NOT NULL DEFAULT 'standard',
        PRIMARY KEY (trace_id, decision_id)
      );

      CREATE TABLE IF NOT EXISTS executions (
        execution_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        intent_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        workflow_type TEXT NOT NULL,
        department TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        finished_at INTEGER
      );

      CREATE TABLE IF NOT EXISTS audit_records (
        audit_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        department TEXT NOT NULL,
        decision_snapshot_json TEXT NOT NULL,
        execution_snapshot_json TEXT NOT NULL,
        events_json TEXT NOT NULL DEFAULT '[]',
        risk_flags_json TEXT,
        review_notes TEXT,
        created_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS board_proposals (
        proposal_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        department TEXT NOT NULL,
        decision_level TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        proposer_agent TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        resolved_at TEXT
      );

      CREATE TABLE IF NOT EXISTS approval_gates (
        gate_id TEXT PRIMARY KEY,
        proposal_id TEXT NOT NULL,
        required_approvers_json TEXT NOT NULL,
        received_approvals_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending',
        decided_at TEXT
      );


      CREATE TABLE IF NOT EXISTS distributions (
        distribution_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        channel TEXT NOT NULL,
        recipient TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        policy_version TEXT NOT NULL DEFAULT 'v0',
        sent_at TEXT,
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS performance_records (
        perf_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        workflow_type TEXT NOT NULL,
        department TEXT NOT NULL,
        total_trades INTEGER NOT NULL DEFAULT 0,
        win_rate REAL NOT NULL DEFAULT 0,
        pnl REAL NOT NULL DEFAULT 0,
        latency_ms INTEGER NOT NULL DEFAULT 0,
        recorded_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS market_intel (
        intel_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        department TEXT NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0,
        regime TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS execution_reviews (
        review_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        execution_id TEXT NOT NULL,
        reviewer_agent TEXT NOT NULL,
        verdict TEXT NOT NULL,
        findings TEXT NOT NULL,
        recommendations TEXT NOT NULL,
        reviewed_at TEXT NOT NULL
      );
    `);
  }

  addEvent(
    traceId: string,
    eventId: string,
    type: string,
    payload: unknown,
    ts = Date.now()
  ): void {
    const stmt = this.db.prepare(
      `INSERT INTO events(trace_id,event_id,type,payload_json,ts) VALUES(?,?,?,?,?)`
    );
    stmt.run(traceId, eventId, type, JSON.stringify(payload), ts);
  }

  listEvents(traceId: string): Array<{ type: string; payload: unknown; ts: number }> {
    const stmt = this.db.prepare(
      `SELECT type,payload_json,ts FROM events WHERE trace_id=? ORDER BY ts ASC`
    );
    return (stmt.all(traceId) as any[]).map((r) => ({
      type: r.type,
      payload: JSON.parse(r.payload_json),
      ts: r.ts,
    }));
  }

  addRouteDecision(
    traceId: string,
    decisionId: string,
    intent: unknown,
    decision: unknown,
    policyVersion = "v0",
    createdAt = Date.now(),
    department = "unknown",
    selectedRoute = "",
    decisionLevel = "standard"
  ): void {
    const stmt = this.db.prepare(
      `INSERT INTO route_decisions(trace_id,decision_id,intent_json,decision_json,policy_version,created_at,department,selected_route,decision_level) VALUES(?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(
      traceId,
      decisionId,
      JSON.stringify(intent),
      JSON.stringify(decision),
      policyVersion,
      createdAt,
      department,
      selectedRoute,
      decisionLevel
    );
  }

  getLatestRouteDecision(
    traceId: string
  ): { intent: unknown; decision: unknown; created_at: number } | null {
    const stmt = this.db.prepare(
      `SELECT intent_json,decision_json,created_at FROM route_decisions WHERE trace_id=? ORDER BY created_at DESC LIMIT 1`
    );
    const row = stmt.get(traceId) as any;
    if (!row) return null;
    return {
      intent: JSON.parse(row.intent_json),
      decision: JSON.parse(row.decision_json),
      created_at: row.created_at,
    };
  }

  addExecution(
    executionId: string,
    traceId: string,
    intentId: string,
    decisionId: string,
    workflowId: string,
    workflowType: string,
    department: string,
    status: string,
    startedAt = Date.now()
  ): void {
    const stmt = this.db.prepare(
      `INSERT INTO executions(execution_id,trace_id,intent_id,decision_id,workflow_id,workflow_type,department,status,started_at) VALUES(?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(executionId, traceId, intentId, decisionId, workflowId, workflowType, department, status, startedAt);
  }

  updateExecutionStatus(executionId: string, status: string, finishedAt = Date.now()): void {
    const stmt = this.db.prepare(
      `UPDATE executions SET status=?,finished_at=? WHERE execution_id=?`
    );
    stmt.run(status, finishedAt, executionId);
  }

  addAuditRecord(
    auditId: string,
    traceId: string,
    department: string,
    decisionSnapshot: unknown,
    executionSnapshot: unknown,
    events: unknown[] = [],
    riskFlags?: string[],
    reviewNotes?: string,
    createdAt = Date.now()
  ): void {
    const stmt = this.db.prepare(
      `INSERT INTO audit_records(audit_id,trace_id,department,decision_snapshot_json,execution_snapshot_json,events_json,risk_flags_json,review_notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(
      auditId,
      traceId,
      department,
      JSON.stringify(decisionSnapshot),
      JSON.stringify(executionSnapshot),
      JSON.stringify(events),
      riskFlags ? JSON.stringify(riskFlags) : null,
      reviewNotes ?? null,
      createdAt
    );
  }

  addBoardProposal(proposal: BoardProposal): void {
    const stmt = this.db.prepare(
      `INSERT INTO board_proposals(proposal_id,trace_id,department,decision_level,title,summary,proposer_agent,status,created_at,resolved_at) VALUES(?,?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(
      proposal.proposal_id,
      proposal.trace_id,
      proposal.department,
      proposal.decision_level,
      proposal.title,
      proposal.summary,
      proposal.proposer_agent,
      proposal.status,
      proposal.created_at,
      proposal.resolved_at ?? null
    );
  }

  addApprovalGate(gate: ApprovalGate): void {
    const stmt = this.db.prepare(
      `INSERT INTO approval_gates(gate_id,proposal_id,required_approvers_json,received_approvals_json,status,decided_at) VALUES(?,?,?,?,?,?)`
    );
    stmt.run(
      gate.gate_id,
      gate.proposal_id,
      JSON.stringify(gate.required_approvers),
      JSON.stringify(gate.received_approvals),
      gate.status,
      gate.decided_at ?? null
    );
  }

  addExecutionReview(review: ExecutionReview): void {
    const stmt = this.db.prepare(
      `INSERT INTO execution_reviews(review_id,trace_id,execution_id,reviewer_agent,verdict,findings,recommendations,reviewed_at) VALUES(?,?,?,?,?,?,?,?)`
    );
    stmt.run(
      review.review_id,
      review.trace_id,
      review.execution_id,
      review.reviewer_agent,
      review.verdict,
      review.findings,
      review.recommendations,
      review.reviewed_at
    );
  }

  listExecutionReviews(traceId?: string): ExecutionReview[] {
    const stmt = traceId
      ? this.db.prepare(`SELECT * FROM execution_reviews WHERE trace_id=? ORDER BY reviewed_at ASC`)
      : this.db.prepare(`SELECT * FROM execution_reviews ORDER BY reviewed_at ASC`);
    const rows = traceId ? (stmt.all(traceId) as any[]) : (stmt.all() as any[]);
    return rows.map((r) => ({
      review_id: r.review_id,
      trace_id: r.trace_id,
      execution_id: r.execution_id,
      reviewer_agent: r.reviewer_agent,
      verdict: r.verdict,
      findings: r.findings,
      recommendations: r.recommendations,
      reviewed_at: r.reviewed_at,
    }));
  }
  addDistribution(d: Distribution): void {
    const stmt = this.db.prepare(
      `INSERT INTO distributions(distribution_id,trace_id,artifact_id,channel,recipient,status,policy_version,sent_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(d.distribution_id, d.trace_id, d.artifact_id, d.channel, d.recipient, d.status, d.policy_version, d.sent_at ?? null, d.created_at);
  }

  listDistributions(traceId?: string): Distribution[] {
    const stmt = traceId
      ? this.db.prepare(`SELECT * FROM distributions WHERE trace_id=? ORDER BY created_at DESC`)
      : this.db.prepare(`SELECT * FROM distributions ORDER BY created_at DESC`);
    const rows = traceId ? (stmt.all(traceId) as any[]) : (stmt.all() as any[]);
    return rows.map((r) => ({ distribution_id: r.distribution_id, trace_id: r.trace_id, artifact_id: r.artifact_id, channel: r.channel, recipient: r.recipient, status: r.status, policy_version: r.policy_version, sent_at: r.sent_at ?? undefined, created_at: r.created_at }));
  }

  addPerformance(p: Performance): void {
    const stmt = this.db.prepare(
      `INSERT INTO performance_records(perf_id,trace_id,workflow_id,workflow_type,department,total_trades,win_rate,pnl,latency_ms,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(p.perf_id, p.trace_id, p.workflow_id, p.workflow_type, p.department, p.total_trades, p.win_rate, p.pnl, p.latency_ms, p.recorded_at);
  }

  listPerformance(workflowId?: string): Performance[] {
    const stmt = workflowId
      ? this.db.prepare(`SELECT * FROM performance_records WHERE workflow_id=? ORDER BY recorded_at DESC`)
      : this.db.prepare(`SELECT * FROM performance_records ORDER BY recorded_at DESC`);
    const rows = workflowId ? (stmt.all(workflowId) as any[]) : (stmt.all() as any[]);
    return rows.map((r) => ({ perf_id: r.perf_id, trace_id: r.trace_id, workflow_id: r.workflow_id, workflow_type: r.workflow_type, department: r.department, total_trades: r.total_trades, win_rate: r.win_rate, pnl: r.pnl, latency_ms: r.latency_ms, recorded_at: r.recorded_at }));
  }

  addMarketIntel(m: MarketIntel): void {
    const stmt = this.db.prepare(
      `INSERT INTO market_intel(intel_id,trace_id,department,symbol,direction,confidence,regime,source,summary,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)`
    );
    stmt.run(m.intel_id, m.trace_id, m.department, m.symbol, m.direction, m.confidence, m.regime, m.source, m.summary, m.created_at);
  }

  listMarketIntel(symbol?: string): MarketIntel[] {
    const stmt = symbol
      ? this.db.prepare(`SELECT * FROM market_intel WHERE symbol=? ORDER BY created_at DESC`)
      : this.db.prepare(`SELECT * FROM market_intel ORDER BY created_at DESC`);
    const rows = symbol ? (stmt.all(symbol) as any[]) : (stmt.all() as any[]);
    return rows.map((r) => ({ intel_id: r.intel_id, trace_id: r.trace_id, department: r.department, symbol: r.symbol, direction: r.direction, confidence: r.confidence, regime: r.regime, source: r.source, summary: r.summary, created_at: r.created_at }));
  }

  listRouteDecisions(limit = 50): Decision[] {
    const stmt = this.db.prepare(
      `SELECT * FROM route_decisions ORDER BY created_at DESC LIMIT ?`
    );
    const rows = stmt.all(limit) as any[];
    return rows.map((r) => {
      const intent = JSON.parse(r.intent_json);
      const plan = JSON.parse(r.decision_json);
      return {
        decision_id: r.decision_id,
        trace_id: r.trace_id,
        intent_id: "",
        department: intent?.domain ?? r.department ?? "unknown",
        policy_version: r.policy_version,
        selected_route: plan?.mode ?? r.selected_route ?? "",
        reason:
          typeof plan?.reason === "string"
            ? plan.reason
            : JSON.stringify(plan?.reason ?? {}),
        evidence_refs: [],
        decision_level: r.decision_level ?? "standard",
        created_at: new Date(r.created_at).toISOString(),
      };
    });
  }

  getApprovalSummary(): { total: number; pending: number; approved: number; rejected: number } {
    const stmt = this.db.prepare(
      `SELECT status, COUNT(1) as c FROM approval_gates GROUP BY status`
    );
    const rows = stmt.all() as any[];
    const summary = { total: 0, pending: 0, approved: 0, rejected: 0 };
    for (const r of rows) {
      const c = Number(r.c ?? 0);
      summary.total += c;
      if (r.status === "pending") summary.pending += c;
      else if (r.status === "approved") summary.approved += c;
      else if (r.status === "rejected") summary.rejected += c;
    }
    return summary;
  }

  // ============================================
  // Phase 2: Board Dashboard APIs
  // ============================================

  listBoardProposals(status?: string, limit = 50): BoardProposal[] {
    const sql = status
      ? `SELECT * FROM board_proposals WHERE status=? ORDER BY created_at DESC LIMIT ?`
      : `SELECT * FROM board_proposals ORDER BY created_at DESC LIMIT ?`;
    const rows = status ? (this.db.prepare(sql).all(status, limit) as any[]) : (this.db.prepare(sql).all(limit) as any[]);
    return rows.map((r) => ({
      proposal_id: r.proposal_id,
      trace_id: r.trace_id,
      department: r.department,
      decision_level: r.decision_level,
      title: r.title,
      summary: r.summary,
      proposer_agent: r.proposer_agent,
      status: r.status,
      created_at: r.created_at,
      resolved_at: r.resolved_at ?? undefined,
    }));
  }

  getBoardProposal(proposalId: string): BoardProposal | null {
    const stmt = this.db.prepare(`SELECT * FROM board_proposals WHERE proposal_id=?`);
    const r = stmt.get(proposalId) as any;
    if (!r) return null;
    return {
      proposal_id: r.proposal_id,
      trace_id: r.trace_id,
      department: r.department,
      decision_level: r.decision_level,
      title: r.title,
      summary: r.summary,
      proposer_agent: r.proposer_agent,
      status: r.status,
      created_at: r.created_at,
      resolved_at: r.resolved_at ?? undefined,
    };
  }

  getProposalGates(proposalId: string): ApprovalGate[] {
    const stmt = this.db.prepare(`SELECT * FROM approval_gates WHERE proposal_id=?`);
    const rows = stmt.all(proposalId) as any[];
    return rows.map((r) => ({
      gate_id: r.gate_id,
      proposal_id: r.proposal_id,
      required_approvers: JSON.parse(r.required_approvers_json),
      received_approvals: JSON.parse(r.received_approvals_json),
      status: r.status,
      decided_at: r.decided_at ?? undefined,
    }));
  }

  listAuditRecords(traceId?: string, limit = 50): Array<{
    audit_id: string;
    trace_id: string;
    department: string;
    risk_flags: string[];
    review_notes: string | null;
    created_at: string;
  }> {
    const sql = traceId
      ? `SELECT * FROM audit_records WHERE trace_id=? ORDER BY created_at DESC LIMIT ?`
      : `SELECT * FROM audit_records ORDER BY created_at DESC LIMIT ?`;
    const rows = traceId ? (this.db.prepare(sql).all(traceId, limit) as any[]) : (this.db.prepare(sql).all(limit) as any[]);
    return rows.map((r) => ({
      audit_id: r.audit_id,
      trace_id: r.trace_id,
      department: r.department,
      risk_flags: r.risk_flags_json ? JSON.parse(r.risk_flags_json) : [],
      review_notes: r.review_notes,
      created_at: new Date(r.created_at).toISOString(),
    }));
  }

  getBoardMetrics(): {
    total_traces: number;
    total_decisions: number;
    total_artifacts: number;
    pending_approvals: number;
    recent_performance: { avg_win_rate: number; total_pnl: number; trade_count: number };
    department_breakdown: Record<string, number>;
  } {
    const traceStmt = this.db.prepare(`SELECT COUNT(DISTINCT trace_id) as c FROM events`);
    const decisionStmt = this.db.prepare(`SELECT COUNT(*) as c FROM route_decisions`);
    const artifactCount = this.store?.getArtifactsIndex().length ?? 0;
    const approvalStmt = this.db.prepare(`SELECT COUNT(*) as c FROM approval_gates WHERE status='pending'`);
    const perfStmt = this.db.prepare(`SELECT AVG(win_rate) as avg_wr, SUM(pnl) as total_pnl, SUM(total_trades) as tc FROM performance_records`);
    const deptStmt = this.db.prepare(`SELECT department, COUNT(*) as c FROM route_decisions GROUP BY department`);

    const traces = (traceStmt.get() as any)?.c ?? 0;
    const decisions = (decisionStmt.get() as any)?.c ?? 0;
    const pending = (approvalStmt.get() as any)?.c ?? 0;
    const perf = perfStmt.get() as any;
    const deptRows = deptStmt.all() as any[];

    const department_breakdown: Record<string, number> = {};
    for (const r of deptRows) {
      department_breakdown[r.department] = r.c;
    }

    return {
      total_traces: traces,
      total_decisions: decisions,
      total_artifacts: artifactCount,
      pending_approvals: pending,
      recent_performance: {
        avg_win_rate: perf?.avg_wr ?? 0,
        total_pnl: perf?.total_pnl ?? 0,
        trade_count: perf?.tc ?? 0,
      },
      department_breakdown,
    };
  }

  // Reference to store for artifact count
  private store?: import("./artifact-store.js").ArtifactStore;
  setArtifactStore(store: import("./artifact-store.js").ArtifactStore): void {
    this.store = store;
  }
}
