'use client';

import { useState, useEffect, useCallback } from 'react';
import { ChainRelatedArtifactsPanel } from './chain-related-artifacts';
import type { ChainPhaseArtifacts } from '@/lib/types';
import type { StrategySummary } from './types';

type LoopId = 'execution' | 'intelligence' | 'governance';
type PhaseStatus = 'done' | 'active' | 'idle';

interface PhaseState {
  id: string; name: string; status: PhaseStatus; loop: LoopId;
  x: number; y: number; w: number; h: number; href: string; isHub?: boolean;
  count: number; hasRecent: boolean;
}

interface RealPhase { count: number; latest: string }

interface Props {
  phases: Record<string, RealPhase>;
  activeLoop: LoopId;
  strategy: StrategySummary | null;
  orgData: any;
  phaseArtifacts: ChainPhaseArtifacts;
  focusPhase?: string;
  focusArtifactId?: string;
}

/* ──── Base layout ──── */
const BASE_LAYOUT = [
  { id: 'A1', name: '深度调研', loop: 'execution' as LoopId, x: 48, y: 100, w: 60, h: 32, href: '/org/trading/a_series/A1' },
  { id: 'A2', name: '第一性原理', loop: 'execution' as LoopId, x: 48, y: 146, w: 64, h: 32, href: '/org/trading/a_series/A2' },
  { id: 'A3', name: '矛盾推演', loop: 'execution' as LoopId, x: 48, y: 192, w: 60, h: 32, href: '/org/trading/a_series/A3' },
  { id: 'A4', name: '战术验证', loop: 'execution' as LoopId, x: 164, y: 146, w: 60, h: 40, href: '/org/trading/a_series/A4' },
  { id: 'A5', name: '战术执行', loop: 'execution' as LoopId, x: 262, y: 146, w: 60, h: 40, href: '/org/trading/a_series/A5' },
  { id: 'A9', name: '离场决策', loop: 'execution' as LoopId, x: 360, y: 146, w: 60, h: 40, href: '/org/trading/a_series/A9' },
  { id: 'A6', name: 'A6决策中枢', loop: 'intelligence' as LoopId, x: 262, y: 236, w: 76, h: 76, href: '/org/trading/risk_control/A6', isHub: true },
  { id: 'A0', name: '矛盾论', loop: 'governance' as LoopId, x: 468, y: 100, w: 60, h: 32, href: '/org/trading/a_series/A0' },
  { id: 'A7', name: '实践论门禁', loop: 'governance' as LoopId, x: 468, y: 160, w: 72, h: 32, href: '/org/governance/governance_ops/A7' },
  { id: 'A8', name: '自检验证', loop: 'governance' as LoopId, x: 468, y: 220, w: 60, h: 32, href: '/org/governance/governance_ops/A8' },
];

const LOOP: Record<LoopId, { ring: string; active: string; done: string; text: string }> = {
  execution:    { ring: '#378ADD', active: '#FAEEDA', done: '#EAF3DE', text: '#0C447C' },
  intelligence: { ring: '#BA7517', active: '#FAEEDA', done: '#EAF3DE', text: '#854F0B' },
  governance:   { ring: '#3C3489', active: '#EEEDFE', done: '#EAF3DE', text: '#3C3489' },
};
const DIMMED = { ring: '#D1D5DB', node: '#F3F4F6', stroke: '#D1D5DB', text: '#9CA3AF' };

/* ──── Simulation steps ──── */
const SIM_STEPS = [
  { id: 'A0', delay: 600, label: 'A0 矛盾论启动', loop: 'governance' as LoopId },
  { id: 'A1', delay: 1200, label: 'A1 深度调研', loop: 'execution' as LoopId },
  { id: 'A2', delay: 1800, label: 'A2 第一性原理', loop: 'execution' as LoopId },
  { id: 'A3', delay: 2400, label: 'A3 矛盾推演', loop: 'execution' as LoopId },
  { id: 'A7', delay: 3000, label: 'A7 门禁', loop: 'governance' as LoopId },
  { id: 'A4', delay: 3600, label: 'A4 战术验证', loop: 'execution' as LoopId },
  { id: 'A5', delay: 4200, label: 'A5 战术执行', loop: 'execution' as LoopId },
  { id: 'A8', delay: 4800, label: 'A8 自检', loop: 'governance' as LoopId },
  { id: 'A6', delay: 5400, label: 'A6 情报监控', loop: 'intelligence' as LoopId },
  { id: 'A9', delay: 6600, label: 'A9 离场决策', loop: 'execution' as LoopId },
];

/* ──── Compute real status from phase data ──── */
function computeRealStatus(phaseId: string, data: Record<string, RealPhase> | undefined): PhaseStatus {
  if (!data || !data[phaseId]) return 'idle';
  const p = data[phaseId];
  if (p.count > 0) return 'active';
  return 'idle';
}

export default function ChainMindmap({
  phases: realPhases,
  activeLoop: initialLoop,
  strategy,
  phaseArtifacts,
  focusPhase,
  focusArtifactId,
}: Props) {
  const [simIdx, setSimIdx] = useState(-1);
  const [simRunning, setSimRunning] = useState(false);
  const [mode, setMode] = useState<'live' | 'sim'>('live');

  /* ──── Build phase states: real or sim ──── */
  const getPhaseStates = (): PhaseState[] => {
    return BASE_LAYOUT.map(b => {
      if (mode === 'sim') {
        const simData = SIM_STEPS.find((s, i) => i <= simIdx && s.id === b.id);
        return { ...b, status: simData ? (simIdx >= 0 && SIM_STEPS[simIdx]?.id === b.id ? 'active' : 'done') : 'idle', count: 0, hasRecent: !!simData };
      }
      // Real data mode
      const status = computeRealStatus(b.id, realPhases);
      const count = realPhases?.[b.id]?.count ?? 0;
      return { ...b, status, count, hasRecent: count > 0 };
    });
  };

  const [phaseStates, setPhaseStates] = useState<PhaseState[]>(getPhaseStates);
  const [activeLoop, setActiveLoop] = useState<LoopId>(initialLoop);

  // Refresh real data periodically
  useEffect(() => {
    if (mode === 'sim') return;
    setPhaseStates(getPhaseStates());
    setActiveLoop(initialLoop);
    const iv = setInterval(() => {
      // In a real app this would re-fetch; here we use the initial server data
      setPhaseStates(prev => prev.map(p => ({
        ...p,
        status: computeRealStatus(p.id, realPhases),
        count: realPhases?.[p.id]?.count ?? 0,
        hasRecent: (realPhases?.[p.id]?.count ?? 0) > 0,
      })));
    }, 30000);
    return () => clearInterval(iv);
  }, [mode, initialLoop]);

  /* ──── Simulation control ──── */
  const startSim = useCallback(() => {
    setMode('sim');
    setSimIdx(-1);
    setSimRunning(true);
  }, []);

  const stopSim = useCallback(() => {
    setSimRunning(false);
    setMode('live');
    setSimIdx(-1);
  }, []);

  useEffect(() => {
    if (!simRunning || mode !== 'sim') return;
    const nextIdx = simIdx + 1;
    if (nextIdx >= SIM_STEPS.length) { setSimRunning(false); return; }
    const step = SIM_STEPS[nextIdx];
    const timer = setTimeout(() => {
      setSimIdx(nextIdx);
      setActiveLoop(step.loop);
      setPhaseStates(prev => {
        const updated = prev.map(p => ({ ...p }));
        // Mark current as active, previous as done
        updated.forEach(p => {
          if (p.id === step.id) p.status = 'active';
          else if (simIdx >= 0 && p.id === SIM_STEPS[simIdx].id) p.status = 'done';
        });
        return updated;
      });
    }, step.delay - (simIdx >= 0 ? SIM_STEPS[simIdx].delay : 0));
    return () => clearTimeout(timer);
  }, [simIdx, simRunning, mode]);

  /* ──── Status text ──── */
  const hasA9Decision = !!(strategy?.a9);
  const statusText = mode === 'sim'
    ? (simIdx >= 0 ? SIM_STEPS[simIdx]?.label || '' : '初始化模拟...')
    : (strategy?.a3?.regime
      ? `战略: ${strategy.a3.regime} | 置信度: ${strategy.a3.confidence || '--'}%`
      : '战略待生成');

  /* ──── Node style ──── */
  const nodeStyle = (p: PhaseState) => {
    const isActive = p.status === 'active';
    const isDone = p.status === 'done';
    const loopActive = p.loop === activeLoop;
    if (isActive) return { bg: LOOP[p.loop].active, stroke: LOOP[p.loop].ring, text: LOOP[p.loop].text, alpha: 1, border: 3 };
    if (isDone) return { bg: '#EAF3DE', stroke: '#639922', text: '#3B6D11', alpha: 0.85, border: 2 };
    if (!loopActive) return { bg: DIMMED.node, stroke: DIMMED.stroke, text: DIMMED.text, alpha: 0.25, border: 1 };
    return { bg: LOOP[p.loop].active + '30', stroke: LOOP[p.loop].ring, text: LOOP[p.loop].text, alpha: 0.45, border: 1.5 };
  };

  const ringS = (loop: LoopId) => {
    const isActive = loop === activeLoop;
    return { color: isActive ? LOOP[loop].ring : DIMMED.ring, alpha: isActive ? 0.9 : 0.2 };
  };

  const hasAny = (loop: LoopId) => phaseStates.some(p => p.loop === loop && p.status !== 'idle');
  const phases = phaseStates;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">
            A系列 三环驾驶舱
            <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded" style={{
              background: mode === 'live' ? (strategy?.a3 ? '#EEEDFE' : '#F3F4F6') : '#FAEEDA',
              color: mode === 'live' ? (strategy?.a3 ? '#3C3489' : '#6B7280') : '#854F0B'
            }}>
              {mode === 'live' ? (strategy?.a3 ? '战略就绪' : '待机中') : '模拟中'}
            </span>
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">{statusText}</p>
        </div>
        <div className="flex gap-2 items-center">
          {mode === 'live' ? (
            <button onClick={startSim} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500 text-white hover:bg-amber-600">模拟演示</button>
          ) : (
            <button onClick={stopSim} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-200 text-gray-600 hover:bg-gray-300">返回实盘</button>
          )}
          <div className="flex gap-3 text-xs items-center ml-4">
            {(['execution', 'intelligence', 'governance'] as LoopId[]).map(id => (
              <span key={id} className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-full" style={{ background: LOOP[id].ring, opacity: hasAny(id) ? 1 : 0.3 }}/>
                <span style={{ color: hasAny(id) ? LOOP[id].ring : '#9CA3AF', fontWeight: hasAny(id) ? 500 : 400 }}>
                  {id === 'execution' ? '执行' : id === 'intelligence' ? '情报' : '治理'}
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Status legend */}
      <div className="flex gap-4 text-xs">
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded" style={{background:'#639922'}}/>已完成</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded" style={{background:LOOP.execution.active}}/>执行中</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded" style={{background:DIMMED.node, border:'1px solid '+DIMMED.stroke}}/>待触发</span>
        <span className="text-gray-400 ml-auto">每30秒自动刷新</span>
      </div>

      {/* SVG Mindmap */}
      <div className="rounded-xl border border-gray-200 bg-white p-3 overflow-x-auto">
        <svg viewBox="0 0 620 340" width="100%" style={{ minWidth: '620px' }}>
          <defs>
            <marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1.5" strokeLinecap="round"/>
            </marker>
            <marker id="ad" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1" strokeLinecap="round"/>
            </marker>
          </defs>

          {/* Rings */}
          <Ellipse cx={190} cy={170} rx={178} ry={98} color={ringS('execution').color} alpha={ringS('execution').alpha} />
          <text x={190} y={52} textAnchor="middle" fontFamily="sans-serif" fontSize="12" fontWeight="500" fill={ringS('execution').color} opacity={ringS('execution').alpha}>执行环</text>
          <Ellipse cx={298} cy={274} rx={72} ry={56} color={ringS('intelligence').color} alpha={ringS('intelligence').alpha} />
          <text x={298} y={200} textAnchor="middle" fontFamily="sans-serif" fontSize="12" fontWeight="500" fill={ringS('intelligence').color} opacity={ringS('intelligence').alpha}>情报环</text>
          <Ellipse cx={504} cy={160} rx={58} ry={92} color={ringS('governance').color} alpha={ringS('governance').alpha} />
          <text x={504} y={48} textAnchor="middle" fontFamily="sans-serif" fontSize="12" fontWeight="500" fill={ringS('governance').color} opacity={ringS('governance').alpha}>治理环</text>

          {/* Execution arrows */}
          <Arr f={{x:108,y:116}} t={{x:108,y:146}} c={ringS('execution').color} a={hasAny('execution') ? ringS('execution').alpha : 0.15}/>
          <Arr f={{x:112,y:178}} t={{x:112,y:192}} c={ringS('execution').color} a={hasAny('execution') ? ringS('execution').alpha : 0.15}/>
          <Arr f={{x:108,y:208}} t={{x:164,y:166}} c={ringS('execution').color} a={hasAny('execution') ? ringS('execution').alpha : 0.15} d/>
          <Arr f={{x:224,y:166}} t={{x:262,y:166}} c={ringS('execution').color} a={hasAny('execution') ? ringS('execution').alpha : 0.15}/>
          <Arr f={{x:322,y:166}} t={{x:360,y:166}} c={ringS('execution').color} a={hasAny('execution') ? ringS('execution').alpha : 0.15}/>
          <Arr f={{x:194,y:146}} t={{x:300,y:274}} c="#639922" a={hasAny('execution') ? 0.8 : 0.1} d tx="PASS"/>
          <Arr f={{x:164,y:186}} t={{x:164,y:240}} c="#E24B4A" a={hasAny('execution') ? 0.5 : 0.08} d tx="FAIL"/>
          <Arr f={{x:164,y:240}} t={{x:78,y:224}} c="#E24B4A" a={hasAny('execution') ? 0.5 : 0.08} d/>

          {/* A6 radiation (only when intelligence active) */}
          {hasAny('intelligence') && (
            <>
              <Arr f={{x:290,y:274}} t={{x:222,y:186}} c={LOOP.intelligence.ring} a={phases.find(p=>p.id==='A6')?.status==='active'?1:0.5} d tx="L1.5→A2"/>
              <Arr f={{x:250,y:300}} t={{x:160,y:280}} c={LOOP.intelligence.ring} a={phases.find(p=>p.id==='A6')?.status==='active'?0.9:0.4} d tx="L3→A1"/>
              <Arr f={{x:300,y:274}} t={{x:360,y:186}} c="#E24B4A" a={phases.find(p=>p.id==='A6')?.status==='active'?1:0.4} d tx="L0→A9"/>
              <Arr f={{x:312,y:240}} t={{x:370,y:240}} c={LOOP.intelligence.ring} a={phases.find(p=>p.id==='A6')?.status==='active'?0.8:0.3} d tx="L1→A4/A5"/>
            </>
          )}

          {/* Governance arrows */}
          <Arr f={{x:504,y:132}} t={{x:504,y:160}} c={ringS('governance').color} a={hasAny('governance') ? ringS('governance').alpha : 0.15}/>
          <Arr f={{x:504,y:192}} t={{x:504,y:220}} c={ringS('governance').color} a={hasAny('governance') ? ringS('governance').alpha : 0.15}/>
          <Arr f={{x:504,y:252}} t={{x:540,y:260}} c="#7F77DD" a={hasAny('governance') ? 0.7 : 0.08} d/>
          <path d="M540 260 Q560 260 560 100 Q560 60 528 80" fill="none" stroke="#7F77DD" strokeWidth="1" opacity={hasAny('governance') ? 0.7 : 0.08} strokeDasharray="4 3" markerEnd="url(#ad)"/>
          <Arr f={{x:468,y:176}} t={{x:322,y:146}} c="#7F77DD" a={hasAny('governance') ? 0.6 : 0.08} d tx="门禁"/>

          {/* Level badges (A6 active) in live mode or when A6 has products */}
          {phases.find(p=>p.id==='A6')?.status!=='idle' && (
            <g transform="translate(420, 210)">
              {[
                ['L0致命→A9', '#FCEBEB', '#E24B4A'],
                ['L1风险→A4A5', '#FAEEDA', '#BA7517'],
                ['L1.5变→A2', '#EEEDFE', '#534AB7'],
                ['L3背离→A1', '#E6F1FB', '#378ADD'],
              ].map(([t, bg, fg], i) => (
                <g key={t}><rect x="0" y={i*17} width="82" height="14" rx="4" fill={bg}/><text x="41" y={i*17+10} textAnchor="middle" fontFamily="sans-serif" fontSize="8" fill={fg}>{t}</text></g>
              ))}
            </g>
          )}

          {/* NODES */}
          {phases.map(n => {
            const s = nodeStyle(n);
            if (n.isHub) {
              const cx = n.x + n.w/2, cy = n.y + n.h/2, r = 38;
              return (
                <a key={n.id} href={n.href} style={{cursor:'pointer'}}>
                  <g opacity={s.alpha}>
                    <circle cx={cx} cy={cy} r={r} fill={s.bg} stroke={s.stroke} strokeWidth={s.border}/>
                    <text x={cx} y={cy-8} textAnchor="middle" fontFamily="sans-serif" fontSize="14" fontWeight="500" fill={s.text}>A6</text>
                    <text x={cx} y={cy+8} textAnchor="middle" fontFamily="sans-serif" fontSize="10" fill={s.text}>决策中枢</text>
                    {n.status==='active' && <text x={cx} y={cy+22} textAnchor="middle" fontFamily="sans-serif" fontSize="8" fill={LOOP.intelligence.ring}>5级放射中</text>}
                    {n.count>0 && n.status!=='active' && <text x={cx} y={cy+22} textAnchor="middle" fontFamily="sans-serif" fontSize="8" fill={LOOP.intelligence.ring}>{n.count}产物</text>}
                  </g>
                </a>
              );
            }
            return (
              <a key={n.id} href={n.href} style={{cursor:'pointer'}}>
                <g opacity={s.alpha}>
                  <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="7" fill={s.bg} stroke={s.stroke} strokeWidth={s.border}/>
                  <text x={n.x+n.w/2} y={n.y+n.h/2-3} textAnchor="middle" dominantBaseline="central" fontFamily="sans-serif" fontSize="10" fontWeight="500" fill={s.text}>{n.name}</text>
                  <text x={n.x+n.w/2} y={n.y+n.h/2+12} textAnchor="middle" fontFamily="sans-serif" fontSize="8" fill={s.text} opacity="0.8">
                    {n.id}{n.status==='active'?' ⚡':n.status==='done'?' ✓':''}{n.count>0?` ${n.count}`:''}
                  </text>
                </g>
              </a>
            );
          })}
        </svg>
      </div>

      {/* Strategy Summary Panels */}
      <ChainRelatedArtifactsPanel
        phaseArtifacts={phaseArtifacts}
        focusPhase={focusPhase}
        focusArtifactId={focusArtifactId}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* A3: 战略指令 */}
        <Panel
          title="📋 今日战略指令"
          badge={strategy?.a3 ? `${strategy.a3.confidence || '--'}%` : '待生成'}
          badgeColor={strategy?.a3 ? 'blue' : undefined}
        >
          {strategy?.a3 ? (
            <div className="space-y-2">
              <Grid items={[
                { label: 'Regime', val: strategy.a3.regime || '--' },
                { label: '情景', val: strategy.a3.scenario || '--' },
              ]} />
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">方向</span>
                <span className="text-xs font-medium px-2 py-0.5 rounded bg-blue-50 text-blue-600">
                  {strategy.a3.direction || '待定'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">置信度</span>
                <span className="text-xs font-medium">
                  <span className={`${(strategy.a3.confidence || 0) >= 70 ? 'text-green-600' : (strategy.a3.confidence || 0) >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
                    {strategy.a3.confidence || '--'}%
                  </span>
                </span>
              </div>
              {strategy.a3.source && (
                <div className="text-[10px] text-gray-400 mt-1 truncate">
                  来源: {strategy.a3.source}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-gray-400 py-4 text-center">等待 A3 战略推演生成</div>
          )}
        </Panel>

        {/* A9: 离场决策 */}
        <Panel
          title="🛡️ 离场决策状态"
          badge={strategy?.a9?.decision || 'HOLD'}
          badgeColor={strategy?.a9?.riskLevel === 'low' ? 'green' : strategy?.a9?.riskLevel === 'medium' ? 'amber' : 'red'}
        >
          {strategy?.a9 ? (
            <div className="space-y-2">
              <div className="grid grid-cols-3 gap-2 text-center">
                <RiskBadge label="L0" status={strategy.a9.l0Status} detail="浮亏<3%"/>
                <RiskBadge label="L1" status={strategy.a9.l1Status} detail="风险<70"/>
                <RiskBadge label="L2" status={strategy.a9.l2Status} detail="正常"/>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">最新决策</span>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                  strategy.a9.decision === 'HOLD' ? 'bg-green-50 text-green-600' :
                  strategy.a9.decision === 'EXIT' ? 'bg-red-50 text-red-600' :
                  'bg-amber-50 text-amber-600'
                }`}>
                  {strategy.a9.decision || 'HOLD'}
                </span>
              </div>
              {strategy.a9.reason && (
                <div className="text-[10px] text-gray-400 mt-1">
                  原因: {strategy.a9.reason}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-gray-400 py-4 text-center">等待 A9 离场决策</div>
          )}
        </Panel>

        {/* A4: 战术验证 */}
        <Panel
          title="🔬 战术验证摘要"
          badge={strategy?.a4?.validationStatus === 'pass' ? '通过' : strategy?.a4?.validationStatus === 'fail' ? '失败' : '待验证'}
          badgeColor={strategy?.a4?.validationStatus === 'pass' ? 'green' : strategy?.a4?.validationStatus === 'fail' ? 'red' : undefined}
        >
          {strategy?.a4 ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">验证信号</span>
                <span className="text-xs font-medium px-2 py-0.5 rounded bg-purple-50 text-purple-600">
                  {strategy.a4.signal || '--'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">置信度</span>
                <span className="text-xs font-medium">
                  {strategy.a4.confidence ? `${strategy.a4.confidence}%` : '--'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">验证方法</span>
                <span className="text-[10px] text-gray-600 truncate max-w-[60%]">
                  {strategy.a4.validationMethod || '--'}
                </span>
              </div>
              {strategy.a4.source && (
                <div className="text-[10px] text-gray-400 mt-1 truncate">
                  来源: {strategy.a4.source}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-gray-400 py-4 text-center">等待 A4 战术验证</div>
          )}
        </Panel>

        {/* A5: 战术执行 */}
        <Panel
          title="⚡ 战术执行状态"
          badge={strategy?.a5?.action || '待执行'}
          badgeColor={strategy?.a5 ? 'green' : undefined}
        >
          {strategy?.a5 ? (
            <div className="space-y-2">
              <Grid items={[
                { label: 'SI', val: strategy.a5.si !== undefined ? String(strategy.a5.si) : '--' },
                { label: 'Edge', val: strategy.a5.edge !== undefined ? String(strategy.a5.edge) : '--' },
              ]} />
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">Regime Fit</span>
                <span className="text-xs font-medium">
                  {strategy.a5.regimeFit ? `${strategy.a5.regimeFit}%` : '--'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">执行动作</span>
                <span className="text-xs font-medium px-2 py-0.5 rounded bg-emerald-50 text-emerald-600">
                  {strategy.a5.action || '--'}
                </span>
              </div>
              {strategy.a5.source && (
                <div className="text-[10px] text-gray-400 mt-1 truncate">
                  来源: {strategy.a5.source}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-gray-400 py-4 text-center">等待 A5 战术执行</div>
          )}
        </Panel>
      </div>
    </div>
  );
}

/* ──── SVG Helpers ──── */
function Ellipse({ cx, cy, rx, ry, color, alpha }: { cx: number; cy: number; rx: number; ry: number; color: string; alpha: number }) {
  return <>
    <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke={color} strokeWidth="2.5" strokeDasharray="8 3" opacity={alpha * 0.9}/>
    <ellipse cx={cx} cy={cy} rx={rx + 10} ry={ry + 8} fill="none" stroke={color} strokeWidth="4" strokeDasharray="14 5" opacity={alpha * 0.2}/>
  </>;
}

function Arr({ f: {x: x1, y: y1}, t: {x: x2, y: y2}, c, a, d, tx }: any) {
  return (
    <g opacity={a}>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={c} strokeWidth={d ? 1 : 1.5} strokeDasharray={d ? '5 3' : undefined} markerEnd={d ? 'url(#ad)' : 'url(#a)'}/>
      {tx && <text x={(x1+x2)/2 + 8} y={(y1+y2)/2 - 5} textAnchor="start" fontFamily="sans-serif" fontSize="8" fill={c}>{tx}</text>}
    </g>
  );
}

/* ──── UI Components ──── */
function Panel({ title, badge, badgeColor, children }: { title: string; badge: string; badgeColor?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        <span className={`text-xs px-2 py-0.5 rounded border ${
          badgeColor === 'green' ? 'bg-green-50 text-green-600 border-green-200' :
          badgeColor === 'amber' ? 'bg-amber-50 text-amber-600 border-amber-200' :
          badgeColor === 'red' ? 'bg-red-50 text-red-600 border-red-200' :
          badgeColor === 'blue' ? 'bg-blue-50 text-blue-600 border-blue-200' :
          'bg-gray-50 text-gray-500 border-gray-200'
        }`}>{badge}</span>
      </div>
      {children}
    </div>
  );
}

function RiskBadge({ label, status, detail }: { label: string; status?: string; detail: string }) {
  const isPass = status === 'pass';
  const isFail = status === 'fail';
  return (
    <div className="bg-gray-50 rounded-lg p-2 text-center">
      <div className="text-[10px] text-gray-400">{detail}</div>
      <div className={`text-sm font-semibold ${isPass ? 'text-green-600' : isFail ? 'text-red-600' : 'text-amber-600'}`}>
        {label} {isPass ? '✅' : isFail ? '❌' : '⚠️'}
      </div>
    </div>
  );
}

/* ──── Grid component ──── */
function Grid({ items }: { items: { label: string; val: string; red?: boolean }[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 text-center">
      {items.map(it => (
        <div key={it.label} className="bg-gray-50 rounded-lg p-2">
          <div className="text-[10px] text-gray-400">{it.label}</div>
          <div className={`text-sm font-semibold ${it.red ? 'text-red-600' : ''}`}>{it.val}</div>
        </div>
      ))}
    </div>
  );
}
