type ProfileId = "prod" | "ai_ex" | "fundamental" | "pilot";

type ProfileCfg = {
  backendPort: number;
  uiPort: number;
  backendLabel: string;
  frontendLabel: string;
  backendInstallProfileArg: "prod" | "explore" | "pilot" | "";
  backendLogDirRel: string;
  backendLogProfile: string;
  defaultProjectDir?: string;
};

const PROFILES: Record<ProfileId, ProfileCfg> = {
  prod: {
    backendPort: 8092,
    uiPort: 3001,
    backendLabel: "com.ft.ml_trade_service.prod",
    frontendLabel: "com.ft.dashboard.3001",
    backendInstallProfileArg: "prod",
    backendLogDirRel: "user_data_prod/logs",
    backendLogProfile: "prod",
    defaultProjectDir: "/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统",
  },
  ai_ex: {
    backendPort: 8093,
    uiPort: 3002,
    backendLabel: "com.ft.explore.ml_trade_service",
    frontendLabel: "com.ft.explore.dashboard.3002",
    backendInstallProfileArg: "explore",
    backendLogDirRel: "user_data/logs",
    backendLogProfile: "explore",
    defaultProjectDir: "/Users/zhangjiangtao/ft_userdata/Explore交易系统",
  },
  fundamental: {
    backendPort: 8095,
    uiPort: 3005,
    backendLabel: "com.ft.ml_trade_service.8095",
    frontendLabel: "com.ft.dashboard.3005",
    backendInstallProfileArg: "",
    backendLogDirRel: "user_data/logs",
    backendLogProfile: "p8095",
    defaultProjectDir: "/Users/zhangjiangtao/ft_userdata/基本面分析_fundamental",
  },
  pilot: {
    backendPort: 8094,
    uiPort: 3003,
    backendLabel: "com.ft.ml_trade_service.pilot",
    frontendLabel: "com.ft.dashboard.3003",
    backendInstallProfileArg: "pilot",
    backendLogDirRel: "user_data_pilot/logs",
    backendLogProfile: "pilot",
  },
};

const AGENT_PATH = "/chat?session=agent%3Amain%3Amain";

const OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat";

let activeProfile: ProfileId = "prod";
let BACKEND_PORT = 8092;
let UI_PORT = 3001;
let BACKEND_BASE = "http://127.0.0.1:8092";
let UI_BASE = "http://127.0.0.1:3001";
let FRONTEND_PORTS: number[] = [3001];

let HEALTH_URL = "";
let METRICS_URL = "";
let GUARD_EVAL_URL = "";
let BACKTEST_RUN_URL = "";
let BACKTEST_REPORT_LATEST_URL = "";
let INTEL_SNAPSHOT_URL = "";
let SAVE_GATE_POLICY_URL = "";
let DATA_QUALITY_URL = "";
let RISK_STACK_EVAL_URL = "";
let CORR_UPDATE_URL = "";
let STRATEGY_OPTIMIZE_URL = "";
let STRATEGY_BACKTEST_URL = "";
let STRATEGY_ROBUST_URL = "";
let QUANT_ADVANCE_URL = "";
let QUANT_ROLLBACK_URL = "";
let CHANGE_PKG_URL = "";
let JOINT_VALIDATE_URL = "";
let CONFLICT_RESOLVE_URL = "";
let DOC_SNIPPET_URL = "";

const loadProfile = (): ProfileId => {
  try {
    const raw = String(window.localStorage.getItem("agent_profile") || "").trim();
    if (raw === "explore") return "ai_ex";
    const v = raw as ProfileId;
    if (v === "prod" || v === "ai_ex" || v === "fundamental" || v === "pilot") return v;
    return "prod";
  } catch {
    return "prod";
  }
};

const setProfile = (p: ProfileId) => {
  activeProfile = p;
  try {
    window.localStorage.setItem("agent_profile", p);
  } catch {
    void 0;
  }
  const cfg = PROFILES[p] || PROFILES.prod;
  BACKEND_PORT = cfg.backendPort;
  UI_PORT = cfg.uiPort;
  BACKEND_BASE = `http://127.0.0.1:${BACKEND_PORT}`;
  UI_BASE = `http://127.0.0.1:${UI_PORT}`;
  FRONTEND_PORTS = [UI_PORT];
  HEALTH_URL = `${BACKEND_BASE}/health`;
  METRICS_URL = `${BACKEND_BASE}/metrics`;
  GUARD_EVAL_URL = `${BACKEND_BASE}/automation/serving/pipeline/guard/eval`;
  BACKTEST_RUN_URL = `${BACKEND_BASE}/automation/backtest/run`;
  BACKTEST_REPORT_LATEST_URL = `${BACKEND_BASE}/backtest/report/latest`;
  INTEL_SNAPSHOT_URL = `${BACKEND_BASE}/intelligence/snapshot`;
  SAVE_GATE_POLICY_URL = `${BACKEND_BASE}/macro/gate/policy`;
  DATA_QUALITY_URL = `${BACKEND_BASE}/data/quality/score`;
  RISK_STACK_EVAL_URL = `${BACKEND_BASE}/risk/stack/eval`;
  CORR_UPDATE_URL = `${BACKEND_BASE}/quant/correlation/update`;
  STRATEGY_OPTIMIZE_URL = `${BACKEND_BASE}/strategy/optimize`;
  STRATEGY_BACKTEST_URL = `${BACKEND_BASE}/strategy/backtest`;
  STRATEGY_ROBUST_URL = `${BACKEND_BASE}/strategy/robustness`;
  QUANT_ADVANCE_URL = `${BACKEND_BASE}/quant/rollout/advance`;
  QUANT_ROLLBACK_URL = `${BACKEND_BASE}/quant/rollback`;
  CHANGE_PKG_URL = `${BACKEND_BASE}/change/package/generate`;
  JOINT_VALIDATE_URL = `${BACKEND_BASE}/validation/joint/backtest`;
  CONFLICT_RESOLVE_URL = `${BACKEND_BASE}/validation/conflict/resolve`;
  DOC_SNIPPET_URL = `${BACKEND_BASE}/doc/snippet`;
};

setProfile(loadProfile());

const healthBadge = document.querySelector<HTMLSpanElement>("#health-badge");
const healthTs = document.querySelector<HTMLSpanElement>("#health-ts");
const backendStatus = document.querySelector<HTMLSpanElement>("#backend-status");
const backendTs = document.querySelector<HTMLSpanElement>("#backend-ts");
const frontendStatus = document.querySelector<HTMLSpanElement>("#frontend-status");
const openBrowser = document.querySelector<HTMLButtonElement>("#open-browser");
const frame = document.querySelector<HTMLIFrameElement>("#agent-frame");
const mlSignals = document.querySelector<HTMLSpanElement>("#ml-signals");
const mlOrders = document.querySelector<HTMLSpanElement>("#ml-orders");
const mlGuardPass = document.querySelector<HTMLSpanElement>("#ml-guard-pass");
const openChat = document.querySelector<HTMLButtonElement>("#open-chat");
const openControl = document.querySelector<HTMLButtonElement>("#open-control");
const openMl = document.querySelector<HTMLButtonElement>("#open-ml");
const execToken = document.querySelector<HTMLInputElement>("#exec-token");
const approverA = document.querySelector<HTMLInputElement>("#approver-a");
const approverB = document.querySelector<HTMLInputElement>("#approver-b");
const rateLimitInput = document.querySelector<HTMLInputElement>("#rate-limit");
const rateUsed = document.querySelector<HTMLSpanElement>("#rate-used");
const btnRunBacktest = document.querySelector<HTMLButtonElement>("#btn-run-backtest");
const btnFetchReport = document.querySelector<HTMLButtonElement>("#btn-fetch-report");
const btnRefreshGuard = document.querySelector<HTMLButtonElement>("#btn-refresh-guard");
const btnFetchIntel = document.querySelector<HTMLButtonElement>("#btn-fetch-intel");
const btnStrategyOptimize = document.querySelector<HTMLButtonElement>("#btn-strategy-optimize");
const btnStrategyBacktest = document.querySelector<HTMLButtonElement>("#btn-strategy-backtest");
const btnStrategyRobust = document.querySelector<HTMLButtonElement>("#btn-strategy-robust");
const btnQuantAdvance = document.querySelector<HTMLButtonElement>("#btn-quant-advance");
const btnQuantRollback = document.querySelector<HTMLButtonElement>("#btn-quant-rollback");
const gateWeights = document.querySelector<HTMLInputElement>("#gate-weights");
const gateHalfLife = document.querySelector<HTMLInputElement>("#gate-half-life");
const btnSaveGate = document.querySelector<HTMLButtonElement>("#btn-save-gate");
const btnRefreshDq = document.querySelector<HTMLButtonElement>("#btn-refresh-dq");
const btnEvalRisk = document.querySelector<HTMLButtonElement>("#btn-eval-risk");
const btnUpdateCorr = document.querySelector<HTMLButtonElement>("#btn-update-corr");
const dqGrade = document.querySelector<HTMLSpanElement>("#dq-grade");
const riskPass = document.querySelector<HTMLSpanElement>("#risk-pass");
const btnExportChangePkg = document.querySelector<HTMLButtonElement>("#btn-export-change-pkg");
const btnJointValidate = document.querySelector<HTMLButtonElement>("#btn-joint-validate");
const btnConflictResolve = document.querySelector<HTMLButtonElement>("#btn-conflict-resolve");
const btConfig = document.querySelector<HTMLInputElement>("#bt-config");
const btTimerange = document.querySelector<HTMLInputElement>("#bt-timerange");
const btStrategy = document.querySelector<HTMLInputElement>("#bt-strategy");
const btTimeout = document.querySelector<HTMLInputElement>("#bt-timeout");
const btZip = document.querySelector<HTMLInputElement>("#bt-zip");
const btnViewAudit = document.querySelector<HTMLButtonElement>("#btn-view-audit");
const btnClearAudit = document.querySelector<HTMLButtonElement>("#btn-clear-audit");
const resultHint = document.querySelector<HTMLSpanElement>("#result-hint");
const resultBox = document.querySelector<HTMLPreElement>("#result-box");
const auditCount = document.querySelector<HTMLSpanElement>("#audit-count");
const auditBox = document.querySelector<HTMLPreElement>("#audit-box");
const sTitle = document.querySelector<HTMLInputElement>("#s-title");
const sSummary = document.querySelector<HTMLInputElement>("#s-summary");
const sDocSection = document.querySelector<HTMLInputElement>("#s-doc-section");
const sDocRule = document.querySelector<HTMLInputElement>("#s-doc-rule");
const sPairs = document.querySelector<HTMLInputElement>("#s-pairs");
const sRegime = document.querySelector<HTMLInputElement>("#s-regime");
const sRiskLevel = document.querySelector<HTMLSelectElement>("#s-risk-level");
const sActionPath1 = document.querySelector<HTMLInputElement>("#s-action-path1");
const sActionFrom1 = document.querySelector<HTMLInputElement>("#s-action-from1");
const sActionTo1 = document.querySelector<HTMLInputElement>("#s-action-to1");
const sActionPath2 = document.querySelector<HTMLInputElement>("#s-action-path2");
const sActionFrom2 = document.querySelector<HTMLInputElement>("#s-action-from2");
const sActionTo2 = document.querySelector<HTMLInputElement>("#s-action-to2");
const sApprovers = document.querySelector<HTMLInputElement>("#s-approvers");
const btnExportSuggestion = document.querySelector<HTMLButtonElement>("#btn-export-suggestion");
const llmModel = document.querySelector<HTMLInputElement>("#llm-model");
const llmInstruction = document.querySelector<HTMLInputElement>("#llm-instruction");
const llmStatus = document.querySelector<HTMLSpanElement>("#llm-status");
const btnLlmGenerate = document.querySelector<HTMLButtonElement>("#btn-llm-generate");
const btnLlmRunPlan = document.querySelector<HTMLButtonElement>("#btn-llm-runplan");

const profileSelect = document.querySelector<HTMLSelectElement>("#profile-select");
const projectDirInput = document.querySelector<HTMLInputElement>("#project-dir");
const profileBackendPortEl = document.querySelector<HTMLSpanElement>("#profile-backend-port");
const profileUiPortEl = document.querySelector<HTMLSpanElement>("#profile-ui-port");
const btnBackendInstall = document.querySelector<HTMLButtonElement>("#btn-backend-install");
const btnBackendStart = document.querySelector<HTMLButtonElement>("#btn-backend-start");
const btnBackendStop = document.querySelector<HTMLButtonElement>("#btn-backend-stop");
const btnBackendRestart = document.querySelector<HTMLButtonElement>("#btn-backend-restart");
const btnBackendStatus = document.querySelector<HTMLButtonElement>("#btn-backend-status");
const btnBackendLogs = document.querySelector<HTMLButtonElement>("#btn-backend-logs");
const btnNanoclawStartTop = document.querySelector<HTMLButtonElement>("#btn-nanoclaw-start-top");
const btnNanoclawStart = document.querySelector<HTMLButtonElement>("#btn-nanoclaw-start");
const btnFrontendInstall = document.querySelector<HTMLButtonElement>("#btn-frontend-install");
const btnFrontendStart = document.querySelector<HTMLButtonElement>("#btn-frontend-start");
const btnFrontendStop = document.querySelector<HTMLButtonElement>("#btn-frontend-stop");
const btnFrontendRestart = document.querySelector<HTMLButtonElement>("#btn-frontend-restart");
const btnFrontendStatus = document.querySelector<HTMLButtonElement>("#btn-frontend-status");
const btnFrontendLogs = document.querySelector<HTMLButtonElement>("#btn-frontend-logs");

let activeAgentUrl = `http://127.0.0.1:${FRONTEND_PORTS[0]}${AGENT_PATH}`;
let rateCount = 0;
let rateStartMs = Date.now();
const localAudit: Array<Record<string, unknown>> = [];

type LlmPlanTask = { type: string; params?: Record<string, unknown> };
let lastLlmPlan: LlmPlanTask[] = [];

const setHealthBadge = (ok: boolean) => {
  if (!healthBadge) return;
  healthBadge.textContent = ok ? "在线" : "离线";
  healthBadge.classList.toggle("badge-ok", ok);
  healthBadge.classList.toggle("badge-warn", !ok);
};

const fmtTs = (ts: number) => {
  if (!ts) return "--";
  const d = new Date(ts);
  return d.toLocaleString();
};

const checkHealth = async (): Promise<boolean> => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 2000);
  try {
    const resp = await fetch(HEALTH_URL, { signal: controller.signal });
    const data = (await resp.json()) as { ok?: boolean; ts?: number };
    const ok = Boolean(data?.ok);
    setHealthBadge(ok);
    if (backendStatus) backendStatus.textContent = ok ? "已连接" : "离线";
    if (backendTs) backendTs.textContent = fmtTs(Number(data?.ts ?? 0));
    if (healthTs) healthTs.textContent = `health: ${fmtTs(Number(data?.ts ?? 0))}`;
    return ok;
  } catch {
    setHealthBadge(false);
    if (backendStatus) backendStatus.textContent = "离线";
    if (backendTs) backendTs.textContent = "--";
    if (healthTs) healthTs.textContent = "health: --";
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const checkFrontendHealth = async () => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 2000);
  try {
    const resp = await fetch(`${UI_BASE}/api/health`, { signal: controller.signal });
    const data = (await resp.json()) as { ok?: boolean };
    const ok = Boolean(data?.ok);
    if (frontendStatus) frontendStatus.textContent = ok ? `已连接 ${UI_BASE}` : "离线";
    return ok;
  } catch {
    if (frontendStatus) frontendStatus.textContent = "离线";
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const waitForOk = async (probe: () => Promise<boolean>, timeoutMs: number, intervalMs: number): Promise<boolean> => {
  const deadline = Date.now() + Math.max(0, timeoutMs);
  let last = false;
  while (Date.now() < deadline) {
    try {
      last = await probe();
      if (last) return true;
    } catch {
      last = false;
    }
    await new Promise((r) => window.setTimeout(r, Math.max(200, intervalMs)));
  }
  return last;
};

const canExecute = (): boolean => {
  const tokenOk = Boolean(execToken?.value?.trim());
  const aOk = Boolean(approverA?.checked);
  const bOk = Boolean(approverB?.checked);
  const limit = Math.max(0, parseInt(rateLimitInput?.value || "0", 10) || 0);
  const now = Date.now();
  if (now - rateStartMs >= 60_000) {
    rateStartMs = now;
    rateCount = 0;
  }
  const allow = tokenOk && aOk && bOk && (limit <= 0 || rateCount < limit);
  if (rateUsed) rateUsed.textContent = String(rateCount);
  return allow;
};

const canGenerate = (): boolean => {
  const limit = Math.max(0, parseInt(rateLimitInput?.value || "0", 10) || 0);
  const now = Date.now();
  if (now - rateStartMs >= 60_000) {
    rateStartMs = now;
    rateCount = 0;
  }
  const allow = limit <= 0 || rateCount < limit;
  if (rateUsed) rateUsed.textContent = String(rateCount);
  return allow;
};

const bumpRate = () => {
  rateCount += 1;
  if (rateUsed) rateUsed.textContent = String(rateCount);
};

const setResult = (hint: string, data: unknown) => {
  if (resultHint) resultHint.textContent = hint;
  if (resultBox) resultBox.textContent = typeof data === "string" ? data : JSON.stringify(data ?? "-", null, 2);
};

const pushAudit = (entry: Record<string, unknown>) => {
  localAudit.push({ ts: Date.now(), ...entry });
  if (auditCount) auditCount.textContent = String(localAudit.length);
  if (auditBox) auditBox.textContent = JSON.stringify(localAudit, null, 2);
};

const getProjectDirKey = (p: ProfileId) => `agent_project_dir_${p}`;

const ensureDefaultProjectDir = () => {
  const cfg = PROFILES[activeProfile] || PROFILES.prod;
  const def = String(cfg.defaultProjectDir || "").trim();
  if (!def) return;
  const inputEmpty = !String(projectDirInput?.value || "").trim();
  try {
    const existing = String(window.localStorage.getItem(getProjectDirKey(activeProfile)) || "").trim();
    if (existing) {
      if (projectDirInput && inputEmpty) projectDirInput.value = existing;
      return;
    }
    window.localStorage.setItem(getProjectDirKey(activeProfile), def);
  } catch {
    void 0;
  }
  if (projectDirInput && inputEmpty) projectDirInput.value = def;
};

const getProjectDir = (): string => {
  const fromInput = String(projectDirInput?.value ?? "").trim();
  if (fromInput) return fromInput;
  try {
    return String(window.localStorage.getItem(getProjectDirKey(activeProfile)) || "").trim();
  } catch {
    return "";
  }
};

const setProjectDir = (v: string) => {
  const s = String(v || "").trim();
  if (projectDirInput) projectDirInput.value = s;
  try {
    window.localStorage.setItem(getProjectDirKey(activeProfile), s);
  } catch {
    void 0;
  }
};

type TauriInvoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
let _tauriInvoke: Promise<TauriInvoke | null> | null = null;

const getTauriInvoke = async (): Promise<TauriInvoke | null> => {
  if (_tauriInvoke) return _tauriInvoke;
  _tauriInvoke = (async () => {
    try {
      const mod = await import("@tauri-apps/api/core");
      const inv = (mod as any)?.invoke;
      if (typeof inv !== "function") return null;
      return inv as TauriInvoke;
    } catch {
      return null;
    }
  })();
  return _tauriInvoke;
};

const runLaunchdScript = async (scriptRel: string, args: string[]) => {
  const inv = await getTauriInvoke();
  if (!inv) throw new Error("tauri_not_available");
  const projectDir = getProjectDir();
  if (!projectDir) throw new Error("missing_project_dir");
  return await inv("run_launchd_script", { projectDir, scriptRel, args });
};

const launchctlPrint = async (label: string) => {
  const inv = await getTauriInvoke();
  if (!inv) throw new Error("tauri_not_available");
  return await inv("launchctl_print", { label });
};

const launchctlKickstart = async (label: string) => {
  const inv = await getTauriInvoke();
  if (!inv) throw new Error("tauri_not_available");
  return await inv("launchctl_kickstart", { label });
};

const launchctlBootoutByLabel = async (label: string) => {
  const inv = await getTauriInvoke();
  if (!inv) throw new Error("tauri_not_available");
  return await inv("launchctl_bootout_by_label", { label });
};

const readTextTail = async (path: string, maxLines: number = 200, maxBytes: number = 250000) => {
  const inv = await getTauriInvoke();
  if (!inv) throw new Error("tauri_not_available");
  return await inv<string>("read_text_tail", { path, maxLines, maxBytes });
};

const backendLabel = () => (PROFILES[activeProfile] || PROFILES.prod).backendLabel;
const frontendLabel = () => (PROFILES[activeProfile] || PROFILES.prod).frontendLabel;
const nanoclawLabel = () => "com.nanoclaw";

const backendLogPaths = () => {
  const projectDir = getProjectDir();
  const cfg = PROFILES[activeProfile] || PROFILES.prod;
  const base = projectDir ? `${projectDir.replace(/\/+$/, "")}/${cfg.backendLogDirRel}` : "";
  return {
    out: base ? `${base}/ml_trade_service_${cfg.backendLogProfile}_${BACKEND_PORT}.out.log` : "",
    err: base ? `${base}/ml_trade_service_${cfg.backendLogProfile}_${BACKEND_PORT}.err.log` : "",
  };
};

const frontendLogPaths = () => {
  const projectDir = getProjectDir();
  const base = projectDir ? `${projectDir.replace(/\/+$/, "")}/user_data/logs` : "";
  return {
    out: base ? `${base}/dashboard_${UI_PORT}.out.log` : "",
    err: base ? `${base}/dashboard_${UI_PORT}.err.log` : "",
  };
};

const setLlmStatus = (s: string) => {
  if (llmStatus) llmStatus.textContent = s;
};

const jsonParseLoose = (text: string): unknown => {
  const t = String(text || "").trim();
  if (!t) throw new Error("empty_llm_response");
  try {
    return JSON.parse(t);
  } catch {
    const s = t.indexOf("{");
    const e = t.lastIndexOf("}");
    if (s >= 0 && e > s) {
      const mid = t.slice(s, e + 1);
      return JSON.parse(mid);
    }
    throw new Error("invalid_json");
  }
};

const fetchJsonWithTimeout = async (url: string, timeoutMs: number, init?: RequestInit) => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    return await resp.json();
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const fetchDocSnippet = async (doc: string, section: string) => {
  const params = new URLSearchParams();
  params.set("doc", doc);
  params.set("section", section);
  const data = (await fetchJsonWithTimeout(`${DOC_SNIPPET_URL}?${params.toString()}`, 20_000)) as any;
  if (!data?.ok) throw new Error(String(data?.error || "doc_snippet_failed"));
  return data as { ok: true; doc_path: string; section: string; title?: string; text: string };
};

const ollamaChat = async (model: string, messages: Array<{ role: "system" | "user" | "assistant"; content: string }>) => {
  const payload = {
    model: model || "qwen2.5:7b-instruct",
    stream: false,
    messages,
    options: { temperature: 0.2 },
  };
  const data = (await fetchJsonWithTimeout(OLLAMA_CHAT_URL, 90_000, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })) as any;
  if (data?.error) throw new Error(String(data.error));
  const content = String(data?.message?.content ?? "");
  if (!content.trim()) throw new Error("ollama_empty_content");
  return content;
};

const truncateText = (v: unknown, maxChars: number) => {
  const s = typeof v === "string" ? v : JSON.stringify(v ?? "-", null, 2);
  if (s.length <= maxChars) return s;
  return `${s.slice(0, Math.max(0, maxChars - 20))}\n...<truncated ${s.length - maxChars} chars>`;
};

const applySuggestionToForm = (s: Record<string, any>) => {
  if (sTitle) sTitle.value = String(s?.title ?? "");
  if (sSummary) sSummary.value = String(s?.summary ?? "");
  if (sDocSection) sDocSection.value = String(s?.doc?.section ?? "");
  if (sDocRule) sDocRule.value = String(s?.doc?.rule ?? "");
  if (sPairs) sPairs.value = String(s?.pairs ?? "");
  if (sRegime) sRegime.value = String(s?.market_regime ?? "");
  if (sRiskLevel) sRiskLevel.value = String(s?.risk?.level ?? "low");
  const approvers = Array.isArray(s?.review?.approvers) ? s.review.approvers : [];
  if (sApprovers) sApprovers.value = approvers.map((x: any) => String(x || "").trim()).filter(Boolean).join(",");
  const actions = Array.isArray(s?.proposed_actions) ? s.proposed_actions : [];
  const a1 = actions[0] || {};
  const a2 = actions[1] || {};
  if (sActionPath1) sActionPath1.value = String(a1?.path ?? "");
  if (sActionFrom1) sActionFrom1.value = String(a1?.from ?? "");
  if (sActionTo1) sActionTo1.value = String(a1?.to ?? "");
  if (sActionPath2) sActionPath2.value = String(a2?.path ?? "");
  if (sActionFrom2) sActionFrom2.value = String(a2?.from ?? "");
  if (sActionTo2) sActionTo2.value = String(a2?.to ?? "");
};

const ensureDocRef = (suggestion: Record<string, any>, docRef: { doc_path: string; section: string; rule: string }) => {
  const s = suggestion || {};
  const refs = Array.isArray(s.doc_refs) ? s.doc_refs : [];
  const found = refs.some((r: any) => String(r?.doc_path || "") === docRef.doc_path && String(r?.section || "") === docRef.section);
  if (!found) refs.unshift({ doc_path: docRef.doc_path, section: docRef.section, rule: docRef.rule });
  s.doc_refs = refs;
};

const filterPlan = (tasks: unknown): LlmPlanTask[] => {
  const allow = new Set([
    "report_latest",
    "intel_snapshot",
    "guard_eval",
    "strategy_optimize",
    "strategy_backtest",
    "strategy_robustness",
  ]);
  const arr = Array.isArray(tasks) ? tasks : [];
  return arr
    .map((x: any) => ({ type: String(x?.type ?? ""), params: typeof x?.params === "object" ? x.params : undefined }))
    .filter((x: any) => allow.has(x.type));
};

const runPlanTask = async (t: LlmPlanTask) => {
  if (!t?.type) return { ok: false, error: "empty_task" };
  const p = (t.params || {}) as any;
  if (t.type === "report_latest") {
    const params = new URLSearchParams();
    if (p?.strategy) params.set("strategy", String(p.strategy));
    const data = await fetchJsonWithTimeout(`${BACKTEST_REPORT_LATEST_URL}?${params.toString()}`, 20_000);
    return { ok: true, data };
  }
  if (t.type === "intel_snapshot") {
    const params = new URLSearchParams();
    params.set("coin", String(p?.coin || "BTC"));
    const data = await fetchJsonWithTimeout(`${INTEL_SNAPSHOT_URL}?${params.toString()}`, 20_000);
    return { ok: true, data };
  }
  if (t.type === "guard_eval") {
    const data = await fetchJsonWithTimeout(GUARD_EVAL_URL, 20_000);
    return { ok: true, data };
  }
  if (t.type === "strategy_optimize") {
    const data = await fetchJsonWithTimeout(STRATEGY_OPTIMIZE_URL, 120_000, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p || {}),
    });
    return { ok: true, data };
  }
  if (t.type === "strategy_backtest") {
    const data = await fetchJsonWithTimeout(STRATEGY_BACKTEST_URL, 120_000, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p || {}),
    });
    return { ok: true, data };
  }
  if (t.type === "strategy_robustness") {
    const data = await fetchJsonWithTimeout(STRATEGY_ROBUST_URL, 120_000, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p || {}),
    });
    return { ok: true, data };
  }
  return { ok: false, error: "unsupported_task" };
};

const tryPostAudit = async (entry: Record<string, unknown>) => {
  try {
    await fetch(`${BACKEND_BASE}/agent/audit/actions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
  } catch {
  }
};

const trySendPush = async (message: string) => {
  try {
    await fetch(`${BACKEND_BASE}/agent/push/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: "im", message, severity: "info" }),
    });
  } catch {
  }
};

const checkMetrics = async () => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 2000);
  try {
    const resp = await fetch(METRICS_URL, { signal: controller.signal });
    const data = (await resp.json()) as { signals?: number; orders?: number };
    if (mlSignals) mlSignals.textContent = String(Number(data?.signals ?? 0));
    if (mlOrders) mlOrders.textContent = String(Number(data?.orders ?? 0));
  } catch {
    if (mlSignals) mlSignals.textContent = "--";
    if (mlOrders) mlOrders.textContent = "--";
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const checkGuardEval = async () => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 2000);
  try {
    const resp = await fetch(GUARD_EVAL_URL, { signal: controller.signal });
    const data = await resp.json();
    const pass = Boolean((data as { pass?: boolean }).pass);
    if (mlGuardPass) mlGuardPass.textContent = pass ? "PASS" : "FAIL";
  } catch {
    if (mlGuardPass) mlGuardPass.textContent = "--";
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const probeAgent = async (url: string) => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 1500);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    return resp.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const resolveAgentUrl = async () => {
  for (const port of FRONTEND_PORTS) {
    const url = `http://127.0.0.1:${port}${AGENT_PATH}`;
    if (await probeAgent(url)) {
      return url;
    }
  }
  return `http://127.0.0.1:${FRONTEND_PORTS[0]}${AGENT_PATH}`;
};

window.addEventListener("DOMContentLoaded", () => {
  const renderProfile = () => {
    ensureDefaultProjectDir();
    if (profileSelect) profileSelect.value = activeProfile;
    if (profileBackendPortEl) profileBackendPortEl.textContent = String(BACKEND_PORT);
    if (profileUiPortEl) profileUiPortEl.textContent = String(UI_PORT);
    try {
      const v = String(window.localStorage.getItem(getProjectDirKey(activeProfile)) || "").trim();
      if (projectDirInput && !String(projectDirInput.value || "").trim()) projectDirInput.value = v;
    } catch {
      void 0;
    }
  };

  renderProfile();

  if (profileSelect) {
    profileSelect.addEventListener("change", async () => {
      const v = String(profileSelect.value || "").trim() as ProfileId;
      if (v === "prod" || v === "ai_ex" || v === "fundamental" || v === "pilot") {
        setProfile(v);
        if (projectDirInput) projectDirInput.value = "";
        ensureDefaultProjectDir();
        renderProfile();
        if (frame) {
          try {
            const url = await resolveAgentUrl();
            activeAgentUrl = url;
            frame.src = url;
            if (frontendStatus) frontendStatus.textContent = `已连接 ${url}`;
          } catch {
            void 0;
          }
        }
        try {
          await checkHealth();
        } catch {
          void 0;
        }
      }
    });
  }

  if (projectDirInput) {
    projectDirInput.addEventListener("change", () => setProjectDir(projectDirInput.value));
    projectDirInput.addEventListener("blur", () => setProjectDir(projectDirInput.value));
    projectDirInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") setProjectDir(projectDirInput.value);
    });
  }

  (async () => {
    ensureDefaultProjectDir();
    if (getProjectDir()) return;
    const inv = await getTauriInvoke();
    if (!inv) return;
    try {
      const guess = await inv<string | null>("guess_project_dir", {});
      if (guess && String(guess).trim()) setProjectDir(String(guess).trim());
    } catch {
      void 0;
    }
  })();

  if (frame) {
    resolveAgentUrl().then((url) => {
      activeAgentUrl = url;
      frame.src = url;
      if (frontendStatus) frontendStatus.textContent = `已连接 ${url}`;
    });
    frame.addEventListener("load", () => {
      if (frontendStatus && activeAgentUrl) frontendStatus.textContent = `已加载 ${activeAgentUrl}`;
    });
  }

  if (openBrowser) {
    openBrowser.addEventListener("click", () => {
      window.open(activeAgentUrl, "_blank");
    });
  }
  if (openChat) {
    openChat.addEventListener("click", () => {
      const targetUrl = activeAgentUrl || `http://127.0.0.1:${FRONTEND_PORTS[0]}${AGENT_PATH}`;
      window.open(targetUrl, "_blank");
    });
  }
  if (openControl) {
    openControl.addEventListener("click", () => {
      window.open(`${UI_BASE}/`, "_blank");
    });
  }
  if (openMl) {
    openMl.addEventListener("click", () => {
      window.open(`${UI_BASE}/ml`, "_blank");
    });
  }

  const runOp = async (name: string, op: () => Promise<unknown>) => {
    try {
      setResult(`${name}.running`, { ok: true, profile: activeProfile, backend_port: BACKEND_PORT, ui_port: UI_PORT });
      const data = await op();
      setResult(name, data);
    } catch (e) {
      setResult(`${name}.error`, String((e as any)?.message ?? e));
    }
  };

  if (btnBackendInstall) {
    btnBackendInstall.addEventListener("click", () =>
      runOp("backend.install", () => {
        const cfg = PROFILES[activeProfile] || PROFILES.prod;
        return runLaunchdScript("ops/launchd/install_8092.sh", [String(BACKEND_PORT), cfg.backendInstallProfileArg]);
      }),
    );
  }
  if (btnBackendStart) {
    btnBackendStart.addEventListener("click", () =>
      runOp("backend.start", async () => {
        const r = await launchctlKickstart(backendLabel());
        const ok = await waitForOk(checkHealth, 15_000, 1000);
        await checkFrontendHealth();
        return { kickstart: r, health_ok: ok };
      }),
    );
  }
  if (btnBackendStop) {
    btnBackendStop.addEventListener("click", () =>
      runOp("backend.stop", async () => {
        const r = await launchctlBootoutByLabel(backendLabel());
        await waitForOk(async () => !(await checkHealth()), 15_000, 1000);
        await checkFrontendHealth();
        return { bootout: r };
      }),
    );
  }
  if (btnBackendRestart) {
    btnBackendRestart.addEventListener("click", () =>
      runOp("backend.restart", async () => {
        const r = await launchctlKickstart(backendLabel());
        const ok = await waitForOk(checkHealth, 15_000, 1000);
        await checkFrontendHealth();
        return { kickstart: r, health_ok: ok };
      }),
    );
  }
  if (btnBackendStatus) {
    btnBackendStatus.addEventListener("click", () => runOp("backend.status", () => launchctlPrint(backendLabel())));
  }
  if (btnBackendLogs) {
    btnBackendLogs.addEventListener("click", () =>
      runOp("backend.logs", async () => {
        const p = backendLogPaths();
        const out = p.out ? await readTextTail(p.out, 200, 250000) : "";
        const err = p.err ? await readTextTail(p.err, 200, 250000) : "";
        return { out_path: p.out, err_path: p.err, out, err };
      }),
    );
  }
  const onNanoclawStart = () =>
    runOp("nanoclaw.start", async () => {
      const r = await launchctlKickstart(nanoclawLabel());
      const backendOk = await waitForOk(checkHealth, 15_000, 1000);
      const frontendOk = await waitForOk(checkFrontendHealth, 15_000, 1000);
      return { kickstart: r, backend_ok: backendOk, frontend_ok: frontendOk };
    });
  if (btnNanoclawStartTop) {
    btnNanoclawStartTop.addEventListener("click", onNanoclawStart);
  }
  if (btnNanoclawStart) {
    btnNanoclawStart.addEventListener("click", onNanoclawStart);
  }

  if (btnFrontendInstall) {
    btnFrontendInstall.addEventListener("click", () =>
      runOp("frontend.install", () => runLaunchdScript("ops/launchd/install_dashboard.sh", [String(UI_PORT), String(BACKEND_PORT)])),
    );
  }
  if (btnFrontendStart) {
    btnFrontendStart.addEventListener("click", () =>
      runOp("frontend.start", async () => {
        const r = await launchctlKickstart(frontendLabel());
        const ok = await waitForOk(checkFrontendHealth, 15_000, 1000);
        return { kickstart: r, health_ok: ok };
      }),
    );
  }
  if (btnFrontendStop) {
    btnFrontendStop.addEventListener("click", () =>
      runOp("frontend.stop", async () => {
        const r = await launchctlBootoutByLabel(frontendLabel());
        await waitForOk(async () => !(await checkFrontendHealth()), 15_000, 1000);
        return { bootout: r };
      }),
    );
  }
  if (btnFrontendRestart) {
    btnFrontendRestart.addEventListener("click", () =>
      runOp("frontend.restart", async () => {
        const r = await launchctlKickstart(frontendLabel());
        const ok = await waitForOk(checkFrontendHealth, 15_000, 1000);
        return { kickstart: r, health_ok: ok };
      }),
    );
  }
  if (btnFrontendStatus) {
    btnFrontendStatus.addEventListener("click", () => runOp("frontend.status", () => launchctlPrint(frontendLabel())));
  }
  if (btnFrontendLogs) {
    btnFrontendLogs.addEventListener("click", () =>
      runOp("frontend.logs", async () => {
        const p = frontendLogPaths();
        const out = p.out ? await readTextTail(p.out, 200, 250000) : "";
        const err = p.err ? await readTextTail(p.err, 200, 250000) : "";
        return { out_path: p.out, err_path: p.err, out, err };
      }),
    );
  }
  if (btnRunBacktest) {
    btnRunBacktest.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload: Record<string, unknown> = {
        config: btConfig?.value?.trim() || undefined,
        timerange: btTimerange?.value?.trim() || undefined,
        strategy: btStrategy?.value?.trim() || undefined,
        timeout_sec: btTimeout?.value ? parseInt(btTimeout.value, 10) || 0 : undefined,
      };
      try {
        const resp = await fetch(BACKTEST_RUN_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-EXEC-TOKEN": execToken?.value || "" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        setResult("backtest_run", data);
        pushAudit({ action: "backtest_run", payload, response: data });
        tryPostAudit({ action: "backtest_run", payload, response: data });
        trySendPush("已执行回测");
        bumpRate();
        if ((data as any)?.result_zip && btZip) btZip.value = String((data as any).result_zip);
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnFetchReport) {
    btnFetchReport.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const params = new URLSearchParams();
      if (btStrategy?.value?.trim()) params.set("strategy", btStrategy.value.trim());
      try {
        const resp = await fetch(`${BACKTEST_REPORT_LATEST_URL}?${params.toString()}`);
        const data = await resp.json();
        setResult("report_latest", data);
        pushAudit({ action: "report_latest", response: data });
        tryPostAudit({ action: "report_latest", response: data });
        trySendPush("已拉取最新报告");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnRefreshGuard) {
    btnRefreshGuard.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      try {
        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), 2000);
        const resp = await fetch(GUARD_EVAL_URL, { signal: controller.signal });
        const data = await resp.json();
        setResult("guard_eval", data);
        window.clearTimeout(timeoutId);
        pushAudit({ action: "guard_eval_refresh" });
        tryPostAudit({ action: "guard_eval_refresh" });
        trySendPush("已刷新门禁评估");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnViewAudit) {
    btnViewAudit.addEventListener("click", () => {
      setResult("audit", localAudit);
    });
  }
  if (btnClearAudit) {
    btnClearAudit.addEventListener("click", () => {
      localAudit.splice(0, localAudit.length);
      if (auditCount) auditCount.textContent = "0";
      if (auditBox) auditBox.textContent = "-";
      setResult("audit", "-");
    });
  }
  if (btnExportSuggestion) {
    btnExportSuggestion.addEventListener("click", () => {
      const docRefs = [{ doc_path: "交易Ai Agent 技术文档.md", section: sDocSection?.value || "", rule: sDocRule?.value || "" }];
      const evidence: Array<Record<string, unknown>> = [];
      const actions: Array<Record<string, unknown>> = [];
      if (sActionPath1?.value) actions.push({ path: sActionPath1.value, from: sActionFrom1?.value || "", to: sActionTo1?.value || "" });
      if (sActionPath2?.value) actions.push({ path: sActionPath2.value, from: sActionFrom2?.value || "", to: sActionTo2?.value || "" });
      const suggestion = {
        title: sTitle?.value || "",
        summary: sSummary?.value || "",
        doc: { section: sDocSection?.value || "", rule: sDocRule?.value || "" },
        pairs: sPairs?.value || "",
        market_regime: sRegime?.value || "",
        risk: { level: sRiskLevel?.value || "low" },
        review: { approvers: (sApprovers?.value || "").split(",").map((x) => x.trim()).filter(Boolean) },
        doc_refs: docRefs,
        evidence,
        proposed_actions: actions,
      };
      const text = JSON.stringify(suggestion, null, 2);
      setResult("suggestion_export", text);
    });
  }

  if (btnLlmGenerate) {
    btnLlmGenerate.addEventListener("click", async () => {
      if (!canGenerate()) {
        setResult("denied", "动作锁定：限流已达上限");
        return;
      }
      setLlmStatus("running");
      try {
        const strategy = btStrategy?.value?.trim() || "";
        const timerange = btTimerange?.value?.trim() || "";
        const docSection = (sDocSection?.value || "").trim() || "11.y.0.2";
        const metrics = await fetchJsonWithTimeout(METRICS_URL, 8000);
        let docSnippet: any = undefined;
        try {
          docSnippet = await fetchDocSnippet("技术文档.md", docSection);
        } catch {
        }
        let report: unknown = undefined;
        let intel: unknown = undefined;
        if (canExecute()) {
          try {
            const reportParams = new URLSearchParams();
            if (strategy) reportParams.set("strategy", strategy);
            report = await fetchJsonWithTimeout(`${BACKTEST_REPORT_LATEST_URL}?${reportParams.toString()}`, 20_000);
          } catch {
          }
          try {
            const intelParams = new URLSearchParams();
            intelParams.set("coin", "BTC");
            intel = await fetchJsonWithTimeout(`${INTEL_SNAPSHOT_URL}?${intelParams.toString()}`, 20_000);
          } catch {
          }
        }

        const instruction = (llmInstruction?.value || "").trim() || "基于给定指标与回测报告，生成建议单草案与下一步沙箱计划";
        const modelName = (llmModel?.value || "qwen2.5:7b-instruct").trim() || "qwen2.5:7b-instruct";
        const sys = [
          "你是交易系统的本地大模型驱动模块。",
          "只输出严格 JSON，不要输出任何解释性文本。",
          "JSON 顶层包含 suggestion 与 recommended_tasks。",
          "suggestion 字段结构：{title,summary,doc:{section,rule},pairs,market_regime,risk:{level},review:{approvers},doc_refs,evidence,proposed_actions}。",
          "doc_refs 必须至少包含一条来自技术文档的引用。",
          "recommended_tasks 只能使用以下 type：report_latest,intel_snapshot,guard_eval,strategy_optimize,strategy_backtest,strategy_robustness。",
          "proposed_actions 只能给出配置建议的 path/from/to，不要包含密钥、token 或任何生产写入指令。",
        ].join("\n");

        const user = [
          `instruction: ${instruction}`,
          `strategy: ${strategy || "-"}`,
          `timerange: ${timerange || "-"}`,
          `doc_ref_required: 技术文档.md#${docSection}`,
          `doc_snippet: ${truncateText(docSnippet?.text || "-", 8000)}`,
          `metrics: ${truncateText(metrics, 4000)}`,
          `report_latest: ${truncateText(report, 8000)}`,
          `intel_snapshot: ${truncateText(intel, 4000)}`,
        ].join("\n\n");

        const content = await ollamaChat(modelName, [
          { role: "system", content: sys },
          { role: "user", content: user },
        ]);

        const parsed = jsonParseLoose(content) as any;
        const suggestion = (parsed?.suggestion && typeof parsed.suggestion === "object") ? parsed.suggestion : parsed;
        const tasks = filterPlan(parsed?.recommended_tasks);
        lastLlmPlan = tasks;

        const ruleTitle = String(docSnippet?.title || "加仓（Addon）模块").trim() || "加仓（Addon）模块";
        if (suggestion && typeof suggestion === "object") {
          suggestion.doc = suggestion.doc && typeof suggestion.doc === "object" ? suggestion.doc : {};
          if (!String(suggestion.doc.section || "").trim()) suggestion.doc.section = docSection;
          if (!String(suggestion.doc.rule || "").trim()) suggestion.doc.rule = ruleTitle;
          ensureDocRef(suggestion, { doc_path: "技术文档.md", section: docSection, rule: ruleTitle });
        }

        applySuggestionToForm(suggestion || {});
        setResult("llm_suggestion", { suggestion, recommended_tasks: tasks, raw: truncateText(content, 3000) });
        pushAudit({ action: "llm_generate", model: modelName, instruction, recommended_tasks: tasks });
        tryPostAudit({ action: "llm_generate", model: modelName, instruction, recommended_tasks: tasks });
        trySendPush("已生成建议单草案");
        bumpRate();
        setLlmStatus(tasks.length ? `ok plan=${tasks.length}` : "ok");
      } catch (e) {
        setLlmStatus("error");
        setResult("llm_error", String(e));
      }
    });
  }

  if (btnLlmRunPlan) {
    btnLlmRunPlan.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      if (!lastLlmPlan.length) {
        setResult("llm_plan", "no_plan");
        return;
      }
      setLlmStatus("running_plan");
      const results: Array<Record<string, unknown>> = [];
      for (const t of lastLlmPlan) {
        try {
          const out = await runPlanTask(t);
          results.push({ task: t, out });
          pushAudit({ action: "llm_plan_task", task: t, out });
          tryPostAudit({ action: "llm_plan_task", task: t, out });
          bumpRate();
        } catch (e) {
          results.push({ task: t, error: String(e) });
        }
      }
      setResult("llm_plan_results", results);
      setLlmStatus("ok");
      trySendPush("已执行推荐任务");
    });
  }
  if (btnFetchIntel) {
    btnFetchIntel.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const params = new URLSearchParams();
      params.set("coin", "BTC");
      try {
        const resp = await fetch(`${INTEL_SNAPSHOT_URL}?${params.toString()}`);
        const data = await resp.json();
        setResult("intel_snapshot", data);
        pushAudit({ action: "intel_snapshot", response: data });
        tryPostAudit({ action: "intel_snapshot", response: data });
        trySendPush("已获取数据快照");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnStrategyOptimize) {
    btnStrategyOptimize.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = { family: btStrategy?.value || undefined, params: {} };
      try {
        const resp = await fetch(STRATEGY_OPTIMIZE_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("strategy_optimize", data);
        pushAudit({ action: "strategy_optimize", payload, response: data });
        tryPostAudit({ action: "strategy_optimize", payload, response: data });
        trySendPush("已触发策略优化");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnStrategyBacktest) {
    btnStrategyBacktest.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = {
        config: btConfig?.value || undefined,
        timerange: btTimerange?.value || undefined,
        strategy: btStrategy?.value || undefined,
        timeout_sec: btTimeout?.value ? parseInt(btTimeout.value, 10) || 0 : undefined,
      };
      try {
        const resp = await fetch(STRATEGY_BACKTEST_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("strategy_backtest", data);
        pushAudit({ action: "strategy_backtest", payload, response: data });
        tryPostAudit({ action: "strategy_backtest", payload, response: data });
        trySendPush("已触发策略回测");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnStrategyRobust) {
    btnStrategyRobust.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = { zip: btZip?.value || undefined, strategy: btStrategy?.value || undefined };
      try {
        const resp = await fetch(STRATEGY_ROBUST_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("strategy_robustness", data);
        pushAudit({ action: "strategy_robustness", payload, response: data });
        tryPostAudit({ action: "strategy_robustness", payload, response: data });
        trySendPush("已触发稳健性评估");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnQuantAdvance) {
    btnQuantAdvance.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = { package: "latest" };
      try {
        const resp = await fetch(QUANT_ADVANCE_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("quant_advance", data);
        pushAudit({ action: "quant_advance", payload, response: data });
        tryPostAudit({ action: "quant_advance", payload, response: data });
        trySendPush("已执行版本切换");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnQuantRollback) {
    btnQuantRollback.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = { package: "latest" };
      try {
        const resp = await fetch(QUANT_ROLLBACK_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("quant_rollback", data);
        pushAudit({ action: "quant_rollback", payload, response: data });
        tryPostAudit({ action: "quant_rollback", payload, response: data });
        trySendPush("已执行版本回滚");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnSaveGate) {
    btnSaveGate.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = {
        weights: gateWeights?.value ? JSON.parse(gateWeights.value) : undefined,
        half_life_seconds: gateHalfLife?.value ? parseInt(gateHalfLife.value, 10) : undefined,
      };
      try {
        const resp = await fetch(SAVE_GATE_POLICY_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("save_gate_policy", data);
        pushAudit({ action: "save_gate_policy", payload, response: data });
        tryPostAudit({ action: "save_gate_policy", payload, response: data });
        trySendPush("已保存门控策略");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnRefreshDq) {
    btnRefreshDq.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      try {
        const resp = await fetch(DATA_QUALITY_URL);
        const data = await resp.json();
        setResult("data_quality", data);
        if (dqGrade) dqGrade.textContent = String((data as any)?.grade || "--");
        pushAudit({ action: "data_quality_refresh", response: data });
        tryPostAudit({ action: "data_quality_refresh", response: data });
        trySendPush("已刷新数据质量");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnEvalRisk) {
    btnEvalRisk.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      try {
        const resp = await fetch(RISK_STACK_EVAL_URL);
        const data = await resp.json();
        setResult("risk_stack_eval", data);
        if (riskPass) riskPass.textContent = String((data as any)?.pass ? "PASS" : "FAIL");
        pushAudit({ action: "risk_stack_eval", response: data });
        tryPostAudit({ action: "risk_stack_eval", response: data });
        trySendPush("已评估风险");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnUpdateCorr) {
    btnUpdateCorr.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      try {
        const resp = await fetch(CORR_UPDATE_URL, { method: "POST" });
        const data = await resp.json();
        setResult("correlation_update", data);
        pushAudit({ action: "correlation_update", response: data });
        tryPostAudit({ action: "correlation_update", response: data });
        trySendPush("已更新相关性");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnExportChangePkg) {
    btnExportChangePkg.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      try {
        const resp = await fetch(CHANGE_PKG_URL, { method: "POST" });
        const data = await resp.json();
        setResult("change_pkg_generate", data);
        pushAudit({ action: "change_pkg_generate", response: data });
        tryPostAudit({ action: "change_pkg_generate", response: data });
        trySendPush("已生成变更包");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnJointValidate) {
    btnJointValidate.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = { package: "latest" };
      try {
        const resp = await fetch(JOINT_VALIDATE_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("joint_validate", data);
        pushAudit({ action: "joint_validate", payload, response: data });
        tryPostAudit({ action: "joint_validate", payload, response: data });
        trySendPush("已触发联合验证");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }
  if (btnConflictResolve) {
    btnConflictResolve.addEventListener("click", async () => {
      if (!canExecute()) {
        setResult("denied", "动作锁定：令牌或审批未满足或限流已达上限");
        return;
      }
      const payload = { package: "latest" };
      try {
        const resp = await fetch(CONFLICT_RESOLVE_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setResult("conflict_resolve", data);
        pushAudit({ action: "conflict_resolve", payload, response: data });
        tryPostAudit({ action: "conflict_resolve", payload, response: data });
        trySendPush("已解决冲突");
        bumpRate();
      } catch (e) {
        setResult("error", String(e));
      }
    });
  }

  checkHealth();
  checkMetrics();
  checkGuardEval();
  setInterval(checkHealth, 15_000);
  setInterval(checkMetrics, 15_000);
  setInterval(checkGuardEval, 15_000);
});
