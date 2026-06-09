import { getArtifactsIndex, getChainPhaseArtifacts } from '@/lib/content';
import { getOrgTreeWithStatus } from '@/lib/org-data';
import fs from 'fs';
import path from 'path';
import ChainMindmap from './ChainMindmap';
import type { ChainPosition, StrategySummary } from './types';
import { normalizeToChainPosition } from './types';

export default function ChainPage({
  searchParams,
}: {
  searchParams?: { phase?: string; artifact?: string };
}) {
  const artifacts = getArtifactsIndex();
  const orgData = getOrgTreeWithStatus();

  // Build per-phase summary from real artifacts
  const phases: Record<string, { count: number; latest: string }> = {};
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  for (const a of artifacts) {
    const p = a.chainPhase;
    if (!p) continue;
    if (!phases[p]) phases[p] = { count: 0, latest: '' };
    const isToday = (() => { try { return new Date(a.date) >= today; } catch { return false; } })();
    if (isToday) phases[p].count++;
    if (!phases[p].latest || a.date > phases[p].latest) phases[p].latest = a.date;
  }

  // Determine active loop from real data (count now represents today-only)
  let activeLoop: 'execution' | 'intelligence' | 'governance' = 'execution';
  const hasRecent = (p: string) => (phases[p]?.count ?? 0) > 0;

  if (hasRecent('A6')) activeLoop = 'intelligence';
  else if (hasRecent('A7') || hasRecent('A8')) activeLoop = 'governance';
  else if (hasRecent('A4') || hasRecent('A5') || hasRecent('A9')) activeLoop = 'execution';
  else if (hasRecent('A1') || hasRecent('A2') || hasRecent('A3')) activeLoop = 'execution';

  // Strategy summary: read latest A3/A4/A5/A9 artifacts
  const strategy = readLatestStrategy();

  return (
    <ChainMindmap
      phases={phases}
      activeLoop={activeLoop}
      strategy={strategy}
      orgData={orgData}
      phaseArtifacts={getChainPhaseArtifacts()}
      focusPhase={searchParams?.phase}
      focusArtifactId={searchParams?.artifact}
    />
  );
}

/* ──── Read latest position from logs or exit check ──── */
function readLatestPosition(): ChainPosition {
  try {
    const logsDir = path.join(process.cwd(), '..', 'logs');
    if (!fs.existsSync(logsDir)) {
      return { hasPosition: false, positions: { a4: { hasPosition: false }, a5: { hasPosition: false } }, orders: { a4: [], a5: [] } };
    }

    // Find latest position-related log
    const files = fs.readdirSync(logsDir)
      .filter((f) => f.startsWith('exit_check_') && f.endsWith('.json'))
      .sort()
      .reverse();

    if (files.length === 0) {
      return { hasPosition: false, positions: { a4: { hasPosition: false }, a5: { hasPosition: false } }, orders: { a4: [], a5: [] } };
    }

    // Try the 3 latest files
    for (const f of files.slice(0, 3)) {
      try {
        const content = JSON.parse(fs.readFileSync(path.join(logsDir, f), 'utf-8'));
        // Use normalizeToChainPosition for compatibility
        return normalizeToChainPosition(content);
      } catch {
        continue;
      }
    }

    return { hasPosition: false, positions: { a4: { hasPosition: false }, a5: { hasPosition: false } }, orders: { a4: [], a5: [] } };
  } catch (e) {
    console.error('[readLatestPosition] Error:', e);
    return { hasPosition: false, positions: { a4: { hasPosition: false }, a5: { hasPosition: false } }, orders: { a4: [], a5: [] } };
  }
}

/* ──── Read latest strategy summary from artifacts ──── */
function readLatestStrategy(): StrategySummary {
  const result: StrategySummary = { lastUpdated: new Date().toISOString() };

  try {
    const logsDir = path.join(process.cwd(), '..', 'logs');
    const contentDir = path.join(process.cwd(), '..', 'web', 'content');

    // === A9: 离场决策 from latest log ===
    try {
      const logFiles = fs.readdirSync(logsDir)
        .filter((f) => f.startsWith('exit_check_') && f.endsWith('.json'))
        .sort()
        .reverse();

      for (const f of logFiles.slice(0, 3)) {
        try {
          const log = JSON.parse(fs.readFileSync(path.join(logsDir, f), 'utf-8'));
          const esr = log.exit_skill_result || {};
          result.a9 = {
            riskLevel: esr.risk_level as any || 'low',
            decision: log.final_decision || 'HOLD',
            reason: log.decision_reason || '',
            timestamp: log.timestamp,
            l0Status: esr.risk_level === 'critical' ? 'fail' : 'pass',
            l1Status: esr.risk_level === 'high' ? 'warning' : esr.risk_level === 'critical' ? 'fail' : 'pass',
            l2Status: esr.risk_level === 'medium' ? 'warning' : 'pass',
          };
          break;
        } catch { continue; }
      }
    } catch { /* logs not available */ }

    // === A3: 战略指令 from latest artifact ===
    try {
      const a3Files = fs.readdirSync(path.join(contentDir, 'reports', 'trading'))
        .filter((f) => f.startsWith('a3_') && f.endsWith('.md'))
        .sort()
        .reverse();

      for (const f of a3Files.slice(0, 5)) {
        try {
          const content = fs.readFileSync(path.join(contentDir, 'reports', 'trading', f), 'utf-8');
          // Extract key info from markdown
          const regimeMatch = content.match(/情景[：:]\s*([^\n]+)/);
          const confidenceMatch = content.match(/置信度[：:]\s*([\d.]+)%/);
          const directionMatch = content.match(/执行策略[：:]\s*([^\n]+)/);
          const scenarioMatch = content.match(/主导情景[：:]\s*([^\n]+)/);

          if (regimeMatch || confidenceMatch) {
            result.a3 = {
              regime: regimeMatch ? regimeMatch[1].trim() : '待评估',
              confidence: confidenceMatch ? parseFloat(confidenceMatch[1]) : undefined,
              direction: directionMatch ? directionMatch[1].trim() : undefined,
              scenario: scenarioMatch ? scenarioMatch[1].trim() : undefined,
              timestamp: content.match(/时间[：:]\s*([^\n]+)/)?.[1] || '',
              source: f,
            };
            break;
          }
        } catch { continue; }
      }
    } catch { /* content not available */ }

    // === A4: 战术验证 from latest artifact ===
    try {
      const a4Files = fs.readdirSync(path.join(contentDir, 'reports', 'trading'))
        .filter((f) => f.startsWith('a4_') && f.endsWith('.md'))
        .sort()
        .reverse();

      for (const f of a4Files.slice(0, 5)) {
        try {
          const content = fs.readFileSync(path.join(contentDir, 'reports', 'trading', f), 'utf-8');
          // Extract validation info
          const statusMatch = content.match(/验证结果[：:]\s*([^\n]+)/);
          const methodMatch = content.match(/验证方法[：:]\s*([^\n]+)/);
          const signalMatch = content.match(/Regime[：:]\s*([^\n]+)/);
          const confMatch = content.match(/置信度[：:]\s*([\d.]+)%/);

          if (statusMatch || signalMatch) {
            result.a4 = {
              signal: signalMatch ? signalMatch[1].trim() : undefined,
              validationStatus: statusMatch?.includes('通过') || statusMatch?.includes('✅') ? 'pass' :
                               statusMatch?.includes('失败') || statusMatch?.includes('❌') ? 'fail' : 'pending',
              validationMethod: methodMatch ? methodMatch[1].trim() : undefined,
              confidence: confMatch ? parseFloat(confMatch[1]) : undefined,
              timestamp: content.match(/执行时间[：:]\s*([^\n]+)/)?.[1] || '',
              source: f,
            };
            break;
          }
        } catch { continue; }
      }
    } catch { /* content not available */ }

    // === A5: 战术执行 from latest artifact ===
    try {
      const a5Files = fs.readdirSync(path.join(contentDir, 'reports', 'trading'))
        .filter((f) => f.startsWith('a5_') && f.endsWith('.md'))
        .sort()
        .reverse();

      for (const f of a5Files.slice(0, 5)) {
        try {
          const content = fs.readFileSync(path.join(contentDir, 'reports', 'trading', f), 'utf-8');
          // Extract execution info
          const actionMatch = content.match(/执行动作[：:]\s*([^\n]+)/);
          const siMatch = content.match(/SI[：:]\s*([+\-]?[\d.]+)/);
          const edgeMatch = content.match(/Edge[：:]\s*([+\-]?[\d.]+)/);
          const fitMatch = content.match(/Regime Fit[：:]\s*([\d.]+)%/);

          if (actionMatch || siMatch) {
            result.a5 = {
              action: actionMatch ? actionMatch[1].trim() : undefined,
              si: siMatch ? parseFloat(siMatch[1]) : undefined,
              edge: edgeMatch ? parseFloat(edgeMatch[1]) : undefined,
              regimeFit: fitMatch ? parseFloat(fitMatch[1]) : undefined,
              timestamp: content.match(/执行时间[：:]\s*([^\n]+)/)?.[1] || '',
              source: f,
            };
            break;
          }
        } catch { continue; }
      }
    } catch { /* content not available */ }

  } catch (e) {
    console.error('[readLatestStrategy] Error:', e);
  }

  return result;
}
