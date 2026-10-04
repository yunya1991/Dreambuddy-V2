'use client';

// ============================================
// 治理面板 — 提案列表
// P0: 接入 boardApi.listProposals() 真实后端 + stage 由 status 派生
// P1: dataSource 角标 + 恢复投票列 (+N/-N) + 投票按钮交互
// ============================================

import { useEffect, useState } from 'react';
import { V3Card, V3Badge, V3StatusDot, V3Empty } from '@/components';
import { boardApi, deriveStageFromStatus, type Proposal } from '@/lib/v3/api/board';

const stageLabels: Record<string, string> = {
  draft: '草稿',
  gate: '门禁',
  approval: '审批',
  apply: '应用',
  audit: '审计',
};

// 后端 StrategyStatus → 前端 V3Badge variant 映射
const statusVariant: Record<string, 'default' | 'success' | 'warning' | 'danger'> = {
  DRAFT: 'default',
  APPROVED: 'success',
  APPLIED: 'success',
  PAUSED: 'warning',
  EXPIRED: 'default',
};

const statusLabel: Record<string, string> = {
  DRAFT: '草稿',
  APPROVED: '已批准',
  APPLIED: '执行中',
  PAUSED: '已暂停',
  EXPIRED: '已过期',
};

export function GovernanceScreen() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dataSource, setDataSource] = useState<'mock' | 'db' | null>(null);
  const [voteCounts, setVoteCounts] = useState<Record<string, { for: number; against: number }>>({});

  useEffect(() => {
    let active = true;
    boardApi
      .listProposals()
      .then((list) => {
        if (!active) return;
        setProposals(list);
        // 所有 proposal 同源 (DB 或 mock), 取首个 dataSource 即可
        setDataSource((list[0]?.dataSource as 'mock' | 'db' | undefined) ?? 'db');
        // 并发拉取每条提案的投票计数
        return Promise.all(
          list.map((p) =>
            boardApi.getProposalVotes(p.id).then((vs) => ({
              [p.id]: {
                for: vs.filter((v) => v.vote === 'FOR').length,
                against: vs.filter((v) => v.vote === 'AGAINST').length,
              },
            }))
          )
        );
      })
      .then((entries) => {
        if (!active || !entries) return;
        setVoteCounts(Object.assign({}, ...entries));
      })
      .catch((e: unknown) => {
        if (!active) return;
        setError(e instanceof Error ? e.message : '加载失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // 投票交互: 调用 vote → 刷新计数
  const handleVote = async (proposalId: string, vote: 'FOR' | 'AGAINST') => {
    try {
      await boardApi.vote(proposalId, vote);
      const vs = await boardApi.getProposalVotes(proposalId);
      setVoteCounts((prev) => ({
        ...prev,
        [proposalId]: {
          for: vs.filter((v) => v.vote === 'FOR').length,
          against: vs.filter((v) => v.vote === 'AGAINST').length,
        },
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '投票失败');
    }
  };

  // loading → 骨架屏 (animate-pulse)
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
          {Object.entries(stageLabels).map(([stage, label]) => (
            <div key={stage} className="flex items-center gap-1">
              <div className="w-8 h-8 rounded-full border-2 border-slate-700 flex items-center justify-center">
                <span className="text-[10px] text-slate-500">{label}</span>
              </div>
              {stage !== 'audit' && <span className="text-slate-700 mx-1">→</span>}
            </div>
          ))}
        </div>
        <V3Card title="提案列表">
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-16 animate-pulse rounded-lg bg-slate-800/50" />
            ))}
          </div>
        </V3Card>
      </div>
    );
  }

  // error → 红色横幅
  if (error) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
          {Object.entries(stageLabels).map(([stage, label]) => (
            <div key={stage} className="flex items-center gap-1">
              <div className="w-8 h-8 rounded-full border-2 border-slate-700 flex items-center justify-center">
                <span className="text-[10px] text-slate-500">{label}</span>
              </div>
              {stage !== 'audit' && <span className="text-slate-700 mx-1">→</span>}
            </div>
          ))}
        </div>
        <div className="p-3 rounded-lg bg-red-900/30 border border-red-700/50">
          <p className="text-sm text-red-300">{error}</p>
        </div>
      </div>
    );
  }

  // empty → V3Empty
  if (proposals.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
          {Object.entries(stageLabels).map(([stage, label]) => (
            <div key={stage} className="flex items-center gap-1">
              <div className="w-8 h-8 rounded-full border-2 border-slate-700 flex items-center justify-center">
                <span className="text-[10px] text-slate-500">{label}</span>
              </div>
              {stage !== 'audit' && <span className="text-slate-700 mx-1">→</span>}
            </div>
          ))}
        </div>
        <V3Empty title="暂无提案" description="当前没有待处理的治理提案" />
      </div>
    );
  }

  // 正常渲染: 提案列表 + 投票交互
  return (
    <div className="space-y-4">
      {/* 头部流程图: draft → gate → approval → apply → audit
          注: gate(门禁) 阶段无 StrategyStatus 对应, 仅作流程示意节点 */}
      <div className="flex items-center gap-2 p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
        {Object.entries(stageLabels).map(([stage, label]) => (
          <div key={stage} className="flex items-center gap-1">
            <div className="w-8 h-8 rounded-full border-2 border-slate-700 flex items-center justify-center">
              <span className="text-[10px] text-slate-500">{label}</span>
            </div>
            {stage !== 'audit' && <span className="text-slate-700 mx-1">→</span>}
          </div>
        ))}
      </div>

      <V3Card
        title="提案列表"
        actions={
          <span className="text-xs text-slate-500">
            {proposals.length} 个
            {dataSource === 'mock' && (
              <span className="ml-2 text-amber-500/70">（演示数据）</span>
            )}
          </span>
        }
      >
        <div className="space-y-2">
          {proposals.map((p) => {
            const stage = deriveStageFromStatus(p.status);
            const counts = voteCounts[p.id] ?? { for: 0, against: 0 };
            return (
              <div
                key={p.id}
                className="flex items-center justify-between p-3 rounded-lg bg-slate-900/50 border border-slate-700/30"
              >
                <div className="flex items-center gap-3">
                  <V3StatusDot
                    status={
                      p.status === 'APPLIED' ? 'success' :
                      p.status === 'APPROVED' ? 'success' :
                      p.status === 'PAUSED' ? 'warning' :
                      p.status === 'EXPIRED' ? 'idle' : 'idle'
                    }
                    size="sm"
                  />
                  <div>
                    <p className="text-sm text-slate-200">{p.title}</p>
                    <p className="text-[10px] text-slate-500">阶段: {stageLabels[stage]}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <V3Badge
                    variant={statusVariant[p.status] ?? 'default'}
                    label={statusLabel[p.status] ?? p.status}
                  />
                  {/* P1: 恢复投票列 (+N/-N 计数) */}
                  <span className="text-[10px] text-emerald-400">{`+${counts.for}`}</span>
                  <span className="text-[10px] text-red-400">{`-${counts.against}`}</span>
                  {/* P1: 投票按钮 */}
                  <button
                    onClick={() => handleVote(p.id, 'FOR')}
                    className="px-2 py-1 text-[10px] rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                  >
                    赞成
                  </button>
                  <button
                    onClick={() => handleVote(p.id, 'AGAINST')}
                    className="px-2 py-1 text-[10px] rounded bg-red-500/20 text-red-300 hover:bg-red-500/30"
                  >
                    反对
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </V3Card>
    </div>
  );
}
