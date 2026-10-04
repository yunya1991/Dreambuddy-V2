"use client";

import { useCallback, useState } from "react";
import {
  StrategyLibraryAPI,
  PipelineAPI,
  SandboxAPI,
  SignalsAPI,
  ApprovalsAPI,
  ExitAPI,
  SystemHealthAPI,
  AutomationAPI,
  ArenaAPI,
  UniverseAPI,
  MacroAPI,
  EvaluationAPI,
  TrackerAPI,
  type StrategyInfo,
  type SignalInfo,
  type ApprovalInfo,
  type AutomationCard,
  type SettlementRecord,
  type BacktestResultItem,
  type SandboxState,
  type ServingPipelineState,
} from "@/lib/classic-system-api";

/**
 * 经典交易体系数据 Hook
 *
 * 封装 dashboard/page.tsx 中经典系统的数据加载逻辑，
 * 供 /dashboard/classic 路由复用。
 */
export function useClassicSystemData() {
  const [classicHealth, setClassicHealth] = useState<{ ok: boolean; error?: string }>({ ok: false });
  const [strategyList, setStrategyList] = useState<StrategyInfo[]>([]);
  const [signalList, setSignalList] = useState<SignalInfo[]>([]);
  const [approvalList, setApprovalList] = useState<ApprovalInfo[]>([]);
  const [automationCards, setAutomationCards] = useState<AutomationCard[]>([]);
  const [exitStats, setExitStats] = useState<{ ok: boolean; open_positions: Record<string, any>; exit_owner_state: { weights: Record<string, number> } }>({ ok: false, open_positions: {}, exit_owner_state: { weights: {} } });
  const [arenaState, setArenaState] = useState<{ ok: boolean; enabled?: boolean; pool_u?: number; models?: Record<string, any> }>({ ok: false });
  const [universeState, setUniverseState] = useState<{ ok: boolean; core?: string[]; watchlist?: string[]; shadow?: string[]; last_update?: number }>({ ok: false });
  const [macroState, setMacroState] = useState<{ ok: boolean; gate_std1h?: Record<string, any>; btc?: Record<string, any>; eth?: Record<string, any>; macro_btceth_shape?: Record<string, any>; macro_tri_layer?: Record<string, any> }>({ ok: false });
  const [evaluationState, setEvaluationState] = useState<{ ok: boolean; orders?: { total: number; window: number }; acceptance?: Record<string, any>; online?: Record<string, any>; profit_window?: Record<string, any> }>({ ok: false });
  const [settlements, setSettlements] = useState<SettlementRecord[]>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResultItem[]>([]);
  const [sandboxState, setSandboxState] = useState<SandboxState>({ running: 0, queued: 0, max_slots: 3 });
  const [pipelineState, setPipelineState] = useState<ServingPipelineState>({});
  const [gateCheck, setGateCheck] = useState<{ ok: boolean; passed?: boolean; checks?: Record<string, boolean>; thresholds?: Record<string, number>; metrics?: Record<string, number> }>({ ok: false });
  const [isLoadingClassicData, setIsLoadingClassicData] = useState(false);

  const loadClassicSystemData = useCallback(async () => {
    setIsLoadingClassicData(true);
    try {
      const health = await SystemHealthAPI.healthCheck();
      setClassicHealth(health);

      const [strategies, signals, approvals, autoCards, exitData, arena, universe, macro, evaluation, tracker, backtestRes, sandboxRes, pipelineRes, gateCheckRes] = await Promise.all([
        StrategyLibraryAPI.listStrategies(),
        SignalsAPI.getRecentSignals(20),
        ApprovalsAPI.getPendingApprovals(),
        AutomationAPI.getAutomationStatus(),
        ExitAPI.getExitStatus(),
        ArenaAPI.getState(),
        UniverseAPI.getStatus(),
        MacroAPI.getOverview(),
        EvaluationAPI.getAcceptanceStatus(),
        TrackerAPI.getStats(),
        SandboxAPI.getBacktestResults(20),
        SandboxAPI.getSandboxState(),
        PipelineAPI.getServingPipelineState(),
        PipelineAPI.getGateCheck(),
      ]);

      if (strategies.ok && strategies.strategies) setStrategyList(strategies.strategies);
      if (signals.ok && signals.signals) setSignalList(signals.signals);
      if (approvals.ok && approvals.approvals) setApprovalList(approvals.approvals);
      if (autoCards.ok && autoCards.cards) setAutomationCards(autoCards.cards);
      if (exitData.ok) setExitStats(exitData);
      if (arena.ok) setArenaState(arena);
      if (universe.ok) setUniverseState(universe);
      if (macro.ok) setMacroState(macro);
      if (evaluation.ok) setEvaluationState(evaluation);
      if (tracker.ok && tracker.ab_settlements) setSettlements(tracker.ab_settlements);
      if (backtestRes.ok && backtestRes.results) setBacktestResults(backtestRes.results);
      if (sandboxRes.ok && sandboxRes.state) setSandboxState(sandboxRes.state);
      if (pipelineRes.ok && pipelineRes.serving_pipeline) setPipelineState(pipelineRes.serving_pipeline);
      if (gateCheckRes.ok) setGateCheck(gateCheckRes);
    } catch (error) {
      console.error("[Classic System] Load data failed:", error);
    } finally {
      setIsLoadingClassicData(false);
    }
  }, []);

  return {
    classicHealth,
    strategyList,
    signalList,
    approvalList,
    automationCards,
    exitStats,
    arenaState,
    universeState,
    macroState,
    evaluationState,
    settlements,
    backtestResults,
    sandboxState,
    pipelineState,
    gateCheck,
    isLoadingClassicData,
    loadClassicSystemData,
  };
}

export type ClassicSystemData = ReturnType<typeof useClassicSystemData>;
