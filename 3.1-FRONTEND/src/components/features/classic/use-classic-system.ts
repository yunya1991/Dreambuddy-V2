'use client';

import { useEffect, useCallback } from 'react';
import { useClassicStore } from '@/stores';

/**
 * 经典系统数据获取 Hook
 * 从 /api/classic/* 拉取真实流水线状态、审批流、Gate 阈值
 * 离线时自动降级为 offline 状态，不阻塞 UI
 */
export function useClassicSystem() {
  const {
    setPipelineState,
    setApprovalState,
    setGateThresholds,
  } = useClassicStore();

  const fetchPipelineState = useCallback(async () => {
    setPipelineState({ loading: true, error: undefined });
    try {
      const res = await fetch('/api/classic/pipeline-state', { method: 'GET' });
      const json = await res.json();
      if (json.ok && json.data) {
        setPipelineState({
          phase: json.data.phase,
          current: json.data.current,
          candidate: json.data.candidate,
          gatePassed: json.data.gate_result?.passed,
          approvalId: json.data.approval_id,
          loading: false,
          online: true,
        });
      } else {
        setPipelineState({ loading: false, online: false, error: json.error || 'unavailable' });
      }
    } catch (err) {
      setPipelineState({
        loading: false,
        online: false,
        error: err instanceof Error ? err.message : 'network_error',
      });
    }
  }, [setPipelineState]);

  const fetchApprovals = useCallback(async () => {
    setApprovalState({ loading: true, error: undefined });
    try {
      const res = await fetch('/api/classic/approvals', { method: 'GET' });
      const json = await res.json();
      if (json.ok && json.data) {
        setApprovalState({
          pending: json.data.pending || [],
          approvedCount: json.data.approved_count || 0,
          pendingCount: json.data.pending_count || 0,
          loading: false,
        });
      } else {
        setApprovalState({ loading: false, error: json.error || 'unavailable' });
      }
    } catch (err) {
      setApprovalState({
        loading: false,
        error: err instanceof Error ? err.message : 'network_error',
      });
    }
  }, [setApprovalState]);

  const fetchGateThresholds = useCallback(async () => {
    try {
      const res = await fetch('/api/classic/gate-thresholds', { method: 'GET' });
      const json = await res.json();
      if (json.ok && json.data) {
        setGateThresholds(json.data);
      }
    } catch {
      // silent fail — thresholds are optional
    }
  }, [setGateThresholds]);

  useEffect(() => {
    fetchPipelineState();
    fetchApprovals();
    fetchGateThresholds();
  }, [fetchPipelineState, fetchApprovals, fetchGateThresholds]);

  return {
    refresh: () => {
      fetchPipelineState();
      fetchApprovals();
      fetchGateThresholds();
    },
  };
}
