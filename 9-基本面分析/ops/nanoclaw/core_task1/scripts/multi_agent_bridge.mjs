import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function nowTag() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}_${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}`;
}

function parseArgs(argv) {
  const args = { asset: 'BTC', debate: false, outDir: '', multiAgentRepo: '', writeMd: true };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--asset' && argv[i + 1]) {
      args.asset = String(argv[i + 1]).trim();
      i += 1;
      continue;
    }
    if (a === '--debate') {
      args.debate = true;
      continue;
    }
    if (a === '--no-md') {
      args.writeMd = false;
      continue;
    }
    if (a === '--out' && argv[i + 1]) {
      args.outDir = String(argv[i + 1]).trim();
      i += 1;
      continue;
    }
    if (a === '--multi-agent-repo' && argv[i + 1]) {
      args.multiAgentRepo = String(argv[i + 1]).trim();
      i += 1;
      continue;
    }
  }
  return args;
}

async function readJson(p) {
  const txt = await fs.readFile(p, 'utf-8');
  return JSON.parse(txt);
}

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function pickLatestByPrefix(dir, prefix, suffix) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files = entries
    .filter((e) => e.isFile())
    .map((e) => e.name)
    .filter((n) => n.startsWith(prefix) && n.endsWith(suffix))
    .map((n) => path.join(dir, n));
  if (files.length === 0) return null;
  const stats = await Promise.all(files.map(async (p) => ({ p, s: await fs.stat(p) })));
  stats.sort((a, b) => b.s.mtimeMs - a.s.mtimeMs);
  return stats[0].p;
}

function clamp01(x) {
  if (typeof x !== 'number' || !Number.isFinite(x)) return null;
  return Math.max(0, Math.min(1, x));
}

function toNum(x) {
  if (x === null || x === undefined) return null;
  const n = Number(x);
  if (!Number.isFinite(n)) return null;
  return n;
}

function fearGreedClass(v) {
  if (v <= 20) return 'extreme_fear';
  if (v <= 40) return 'fear';
  if (v <= 60) return 'neutral';
  if (v <= 80) return 'greed';
  return 'extreme_greed';
}

function narrativePhaseFromLifecycle(x) {
  const s = String(x || '').trim().toLowerCase();
  if (s === 'emerging' || s === 'early') return 'early';
  if (s === 'growing') return 'growing';
  if (s === 'mature' || s === 'peak') return 'peak';
  if (s === 'declining' || s === 'cooling') return 'declining';
  return 'early';
}

function signalFromSignedScore(x, deadzone = 0.15) {
  const v = toNum(x);
  if (v === null) return 'neutral';
  if (v > deadzone) return 'bullish';
  if (v < -deadzone) return 'bearish';
  return 'neutral';
}

function scoreToUnit(v, maxAbs) {
  const x = toNum(v);
  if (x === null) return null;
  return Math.max(-1, Math.min(1, x / maxAbs));
}

function extractSnapshotValue(snapshot, bindBase) {
  const items = Array.isArray(snapshot?.items) ? snapshot.items : [];
  const it = items.find((x) => x && typeof x === 'object' && x.bindBase === bindBase);
  if (!it) return { value: null, quality: null, source: null, generated_at: null };
  return {
    value: it.value ?? null,
    quality: it.quality?.status ?? null,
    source: it.source ?? null,
    generated_at: it.generated_at ?? null,
  };
}

function extractSnapshotValueAny(snapshot, bindBases) {
  const arr = Array.isArray(bindBases) ? bindBases : [];
  for (const b of arr) {
    const got = extractSnapshotValue(snapshot, b);
    if (got && got.value !== null && got.value !== undefined) return got;
  }
  return { value: null, quality: null, source: null, generated_at: null };
}

function buildSentimentFromNarrativeRegistry(nar) {
  const contract = (nar && typeof nar === 'object') ? (nar.contract || {}) : {};
  const ext = (nar && typeof nar === 'object') ? (nar.extended_sentiment || {}) : {};
  const fg = toNum(ext?.fear_greed_index?.value);
  const fgValue = fg !== null ? fg : toNum((contract?.scores?.narrative_stress?.fear_greed_index) ?? null);
  const fearGreedIndex = fgValue !== null ? Math.round(fgValue * 100) / 100 : 50;
  const overallSentiment = toNum(nar?.overall_sentiment);
  const s = overallSentiment !== null ? Math.max(-1, Math.min(1, overallSentiment)) : 0;
  const socialHeat = toNum(nar?.overall_heat);
  const socialVolume = socialHeat !== null ? Math.round(socialHeat * 1000) : 0;
  const sig = s;
  return {
    agent: 'sentiment-analyst',
    timestamp: new Date().toISOString(),
    fearGreedIndex,
    fearGreedClassification: fearGreedClass(fearGreedIndex),
    socialSentiment: sig,
    bullishTweetRatio: (sig + 1) / 2,
    socialVolume,
    socialVolumeChange24h: 0,
    newsSentiment: sig,
    newsVolume: 0,
    positiveNewsRatio: (sig + 1) / 2,
    isExtremeFear: fearGreedIndex <= 20,
    isExtremeGreed: fearGreedIndex >= 80,
    sentimentDivergence: false,
    sentimentSignal: sig,
    confidence: 0.55,
  };
}

function buildNarrativeFromRegistry(nar) {
  const topName = String(nar?.top_narrative || (nar?.narratives?.[0]?.narrative_name) || 'unknown');
  const top = Array.isArray(nar?.narratives) ? nar.narratives.find((x) => x?.narrative_name === topName) : null;
  const strength0 = toNum(nar?.overall_heat);
  const strength = strength0 !== null ? Math.round(Math.max(0, Math.min(100, strength0 * 100))) : 0;
  const sentiment0 = toNum(nar?.overall_sentiment);
  const conviction = clamp01(toNum(top?.confidence) ?? 0.45) ?? 0.45;
  const phase = narrativePhaseFromLifecycle(top?.lifecycle_stage || top?.status);
  const eventCount = toNum(top?.event_count);
  return {
    agent: 'narrative-analyst',
    timestamp: new Date().toISOString(),
    narrativeName: topName,
    narrativeStrength: strength,
    narrativePhase: phase,
    discussionVolume: eventCount !== null ? Math.max(0, Math.round(eventCount * 5)) : 0,
    discussionGrowth1h: 0,
    discussionGrowth24h: 0,
    sectorRotation: null,
    relatedTokens: Array.isArray(top?.related_tokens)
      ? top.related_tokens.map((t) => ({
          symbol: String(t?.symbol || '').toUpperCase(),
          priceChange24h: toNum(t?.price_change_24h) ?? 0,
          volumeChange: toNum(t?.volume_change) ?? 0,
        })).filter((x) => x.symbol)
      : [],
    narrativeSignal: signalFromSignedScore(sentiment0 ?? 0),
    conviction,
  };
}

function buildFlowFromRegime(flowRegime) {
  const bias = String(flowRegime?.regime_output?.bias || flowRegime?.bias || 'neutral').toLowerCase();
  let flowSignal = scoreToUnit(toNum(flowRegime?.composite) ?? null, 1.0);
  if (flowSignal === null) {
    if (bias.includes('long') || bias === 'bullish') flowSignal = 0.5;
    else if (bias.includes('short') || bias === 'bearish') flowSignal = -0.5;
    else flowSignal = 0;
  }
  const coverage = toNum(flowRegime?.diagnostics?.data_quality?.coverage) ?? toNum(flowRegime?.quality?.coverage) ?? null;
  const confidence = clamp01(toNum(flowRegime?.confidence) ?? (coverage !== null ? coverage : 0.1)) ?? 0.1;
  return {
    agent: 'flow-analyzer',
    timestamp: String(flowRegime?.timestamp || new Date().toISOString()),
    exchangeNetflow: 0,
    exchangeNetflowSignal: flowSignal > 0.15 ? 'bullish' : flowSignal < -0.15 ? 'bearish' : 'neutral',
    smartMoneyInflow: 0,
    smartMoneyAddresses: [],
    smartMoneySignal: 'neutral',
    stablecoinMinting: 0,
    stablecoinExchangeReserves: 0,
    flowSignal,
    confidence,
  };
}

export function buildFundamentalPlaceholder({ asset, narrativeRegistry, flowRegime, macroPressure = null, macroPressureQuality = null }) {
  const covFlow = toNum(flowRegime?.diagnostics?.data_quality?.coverage) ?? toNum(flowRegime?.quality?.coverage) ?? 0;
  const covNar = toNum(narrativeRegistry?.contract?.quality?.coverage) ?? 0;
  const macro = toNum(macroPressure) ?? 0;
  const macroQ = String(macroPressureQuality || '').trim().toLowerCase();
  const sourceCoverage = clamp01(Math.max(covFlow, covNar, 0.0)) ?? 0.0;
  const conviction = clamp01(Math.max(covFlow, covNar, 0.25)) ?? 0.25;
  const flowBias = toNum(flowRegime?.composite) ?? 0;
  let sig = 'neutral';
  if (sourceCoverage >= 0.55 && (macroQ === 'ok' || macroQ === 'stale')) {
    if (macro >= 0.70) sig = 'bearish';
    else if (flowBias >= 0.20 && macro <= 0.35) sig = 'bullish';
    else sig = 'neutral';
  } else {
    sig = 'neutral';
  }
  return {
    agent: 'fundamental-analyst',
    timestamp: new Date().toISOString(),
    macroEnvironment: { gdpGrowth: 0, inflationRate: 0, interestRate: 0, unemploymentRate: 0 },
    industryMetrics: { sectorGrowth: 0, marketSize: 0, competitiveIntensity: 50 },
    projectMetrics: { revenue: 0, revenueGrowth: 0, users: 0, userGrowth: 0 },
    valuation: { marketCap: 0, psRatio: 0, industryAvgPS: 0, valuationGap: 0 },
    valuationState: 'FAIR',
    macroPressure: macro,
    sourceCoverage,
    fundamentalSignal: sig,
    conviction,
  };
}

function candlesFromDailyPrices(dailyPrices) {
  if (!dailyPrices || typeof dailyPrices !== 'object') return [];
  const dates = Object.keys(dailyPrices).sort();
  return dates
    .map((d) => ({ date: d, row: dailyPrices[d] }))
    .map(({ date, row }) => {
      const r = row && typeof row === 'object' ? row : {};
      const ts = new Date(`${date}T00:00:00.000Z`).toISOString();
      return {
        timestamp: ts,
        open: toNum(r.open) ?? toNum(r.close) ?? 0,
        high: toNum(r.high) ?? toNum(r.close) ?? 0,
        low: toNum(r.low) ?? toNum(r.close) ?? 0,
        close: toNum(r.close) ?? 0,
        volume: toNum(r.volume) ?? 0,
      };
    })
    .filter((c) => Number.isFinite(c.close) && c.close > 0);
}

async function main() {
  const args = parseArgs(process.argv);
  const coreDir = path.resolve(__dirname, '..');
  const outputsDir = path.resolve(coreDir, 'outputs');
  const flowOutputsDir = path.resolve(coreDir, 'flow', 'outputs');
  const narrativeOutputsDir = path.resolve(coreDir, 'narrative', 'narrative', 'outputs');
  const historicalDir = path.resolve(coreDir, 'historical_data');

  const outRoot = args.outDir ? path.resolve(args.outDir) : path.join(outputsDir, 'multi_agent');
  await fs.mkdir(outRoot, { recursive: true });

  const flowRegimePath = await pickLatestByPrefix(flowOutputsDir, 'flow_regime_', '.json');
  const narrativeRegistryPath = await pickLatestByPrefix(narrativeOutputsDir, 'narrative_registry_', '.json');
  const skillSnapshotPath = path.resolve(flowOutputsDir, 'web3_skill_snapshot_latest.json');
  const pricesPath = path.resolve(historicalDir, 'btc_daily_prices.json');

  if (!flowRegimePath) {
    throw new Error(`flow_regime_not_found in ${flowOutputsDir}`);
  }
  if (!narrativeRegistryPath) {
    throw new Error(`narrative_registry_not_found in ${narrativeOutputsDir}`);
  }

  const flowRegime = await readJson(flowRegimePath);
  const narrativeRegistry = await readJson(narrativeRegistryPath);
  const skillSnapshot = (await exists(skillSnapshotPath)) ? await readJson(skillSnapshotPath) : null;
  const dailyPrices = (await exists(pricesPath)) ? await readJson(pricesPath) : null;

  const multiAgentRepo = (
    args.multiAgentRepo
      || process.env.MULTI_AGENT_REPO
      || '/Users/zhangjiangtao/ft_userdata/多Agent交易系统_multi_agent'
  );
  const distRoot = path.resolve(multiAgentRepo, 'dist', 'src');

  const { TechnicalAnalyst } = await import(pathToFileURL(path.join(distRoot, 'agents', 'technical-analyst.js')).href);
  const { generateFundamentalOverview } = await import(pathToFileURL(path.join(distRoot, 'orchestrator', 'fundamental-orchestrator.js')).href);
  const { generateInvestmentDecision } = await import(pathToFileURL(path.join(distRoot, 'orchestrator', 'decision-orchestrator.js')).href);

  const asset = String(args.asset || 'BTC').trim().toUpperCase();
  const tag = nowTag();

  const flow = buildFlowFromRegime(flowRegime);
  const sentiment = buildSentimentFromNarrativeRegistry(narrativeRegistry);
  const narrative = buildNarrativeFromRegistry(narrativeRegistry);
  const macroPressureSnap = extractSnapshotValueAny(
    skillSnapshot,
    ['macro_event_pressure_score__btc__macro__na', 'macro_event_pressure_score__all__all__na']
  );
  const fundamental = buildFundamentalPlaceholder({
    asset,
    narrativeRegistry,
    flowRegime,
    macroPressure: macroPressureSnap.value,
    macroPressureQuality: macroPressureSnap.quality,
  });

  let technical = {
    agent: 'technical-analyst',
    timestamp: new Date().toISOString(),
    trend: 'sideways',
    trendStrength: 0,
    maAlignment: 'neutral',
    ma: { ma7: 0, ma25: 0, ma99: 0, priceVsMa7: 0, priceVsMa25: 0, priceVsMa99: 0 },
    rsi: 50,
    rsiSignal: 'neutral',
    macd: { value: 0, signal: 0, histogram: 0, crossover: 'none' },
    atr: 0,
    atrPercentile: 0,
    supportLevels: [],
    resistanceLevels: [],
    nearestSupport: 0,
    nearestResistance: 0,
    patterns: [],
    technicalSignal: 'neutral',
    conviction: 0.1,
  };

  const candles = candlesFromDailyPrices(dailyPrices);
  if (candles.length >= 120) {
    const ta = new TechnicalAnalyst();
    technical = await ta.analyze({
      symbol: `${asset}USDT`,
      timeframe: '1d',
      candles,
    });
  }

  const modulesForOverview = {
    flows: {
      exchangeNetflow: flow.exchangeNetflow,
      flowSignal: flow.flowSignal,
      confidence: flow.confidence,
    },
    narrative: {
      narrativeName: narrative.narrativeName,
      narrativeStrength: narrative.narrativeStrength,
      narrativeSignal: narrative.narrativeSignal,
    },
    sentiment: {
      fearGreedIndex: sentiment.fearGreedIndex,
      socialSentiment: sentiment.socialSentiment,
      sentimentSignal: sentiment.sentimentSignal,
    },
    fundamental: {
      projectMetrics: fundamental.projectMetrics,
      valuation: fundamental.valuation,
      valuationState: fundamental.valuationState,
      macroPressure: fundamental.macroPressure,
      sourceCoverage: fundamental.sourceCoverage,
      fundamentalSignal: fundamental.fundamentalSignal,
    },
    technical: {
      trend: technical.trend,
      rsi: technical.rsi,
      macd: technical.macd,
      technicalSignal: technical.technicalSignal,
    },
  };

  const inputs = {
    asset,
    sources: {
      flow_regime: flowRegimePath,
      narrative_registry: narrativeRegistryPath,
      web3_skill_snapshot: (skillSnapshot ? skillSnapshotPath : null),
      btc_daily_prices: (dailyPrices ? pricesPath : null),
    },
    snapshot: {
      funding_rate_bps: extractSnapshotValue(skillSnapshot, 'funding_rate_bps__btc__binance__na'),
      oi_usd: extractSnapshotValue(skillSnapshot, 'oi_usd__btc__coinglass__na'),
      social_heat: extractSnapshotValue(skillSnapshot, 'social_heat_event_score__btc__all__na'),
      macro_pressure: macroPressureSnap,
    },
  };

  const overview = await generateFundamentalOverview({
    asset,
    modules: {
      flow: modulesForOverview.flows,
      sentiment: modulesForOverview.sentiment,
      narrative: modulesForOverview.narrative,
      fundamental: modulesForOverview.fundamental,
      technical: modulesForOverview.technical,
    },
    freshness: {
      flow: 1,
      sentiment: 1,
      narrative: 1,
      fundamental: 24,
      technical: 24,
    },
    quality: {
      flow: clamp01(toNum(flowRegime?.diagnostics?.data_quality?.coverage) ?? toNum(flowRegime?.quality?.coverage) ?? 0) ?? 0,
      narrative: clamp01(toNum(narrativeRegistry?.contract?.quality?.coverage) ?? 0.4) ?? 0.4,
      sentiment: 0.6,
      fundamental: clamp01(toNum(fundamental?.conviction) ?? 0.25) ?? 0.25,
      technical: candles.length >= 120 ? 0.7 : 0.2,
    },
    backfilledFields: {},
    suspectFields: {},
  });

  const signals = {
    timestamp: new Date().toISOString(),
    asset: `${asset}-USD`,
    fundamental,
    technical,
    sentiment,
    narrative,
    flow,
  };

  const historicalPrices = candles.map((c) => c.close).slice(-200);
  const orchestration = await generateInvestmentDecision(
    signals,
    undefined,
    historicalPrices.length >= 50 ? historicalPrices : undefined,
    undefined,
    {
      debate: { enabled: true, autoDebate: args.debate, minDisagreement: 0.5 },
      risk: { autoVeto: false, varLookbackDays: 30, stressTestEnabled: true },
      principlesAudit: { enabled: false, strictMode: false, autoRejectOnCritical: false },
      decision: { autoAdjustPosition: true, minVoteThreshold: 0.6 },
      execution: { enabled: false },
    }
  );

  const outSignalsPath = path.join(outRoot, `multi_agent_signals_${asset}_${tag}.json`);
  const outOverviewPath = path.join(outRoot, `multi_agent_fundamental_overview_${asset}_${tag}.json`);
  const outMeetingPath = path.join(outRoot, `multi_agent_meeting_${asset}_${tag}.json`);
  const outMetaPath = path.join(outRoot, `multi_agent_meta_${asset}_${tag}.json`);
  const outMdPath = path.join(outRoot, `multi_agent_summary_${asset}_${tag}.md`);

  await fs.writeFile(outSignalsPath, JSON.stringify({ ok: true, inputs, signals }, null, 2), 'utf-8');
  await fs.writeFile(outOverviewPath, JSON.stringify({ ok: true, inputs, overview }, null, 2), 'utf-8');
  await fs.writeFile(outMeetingPath, JSON.stringify({ ok: true, inputs, result: orchestration }, null, 2), 'utf-8');
  await fs.writeFile(outMetaPath, JSON.stringify({ ok: true, asset, tag, paths: { signals: outSignalsPath, overview: outOverviewPath, meeting: outMeetingPath }, generated_at: new Date().toISOString(), multi_agent_repo: multiAgentRepo }, null, 2), 'utf-8');

  if (args.writeMd) {
    const decision = orchestration?.decision || {};
    const action = decision?.action || decision?.decision?.action || 'UNKNOWN';
    const positionSize = decision?.positionSize ?? decision?.decision?.positionSize;
    const summaryLines = [
      `# Multi-Agent Overlay (${asset})`,
      ``,
      `- generated_at: ${new Date().toISOString()}`,
      `- asset: ${asset}`,
      `- debate: ${args.debate ? 'auto' : 'simplified'}`,
      `- decision_action: ${String(action)}`,
      `- position_size: ${positionSize === undefined ? '' : String(positionSize)}`,
      ``,
      `## Sources`,
      `- flow_regime: ${flowRegimePath}`,
      `- narrative_registry: ${narrativeRegistryPath}`,
      `- web3_skill_snapshot: ${skillSnapshot ? skillSnapshotPath : ''}`,
      `- btc_daily_prices: ${dailyPrices ? pricesPath : ''}`,
      ``,
      `## Outputs`,
      `- signals: ${outSignalsPath}`,
      `- fundamental_overview: ${outOverviewPath}`,
      `- meeting: ${outMeetingPath}`,
      `- meta: ${outMetaPath}`,
    ];
    await fs.writeFile(outMdPath, summaryLines.join('\n'), 'utf-8');
  }

  process.stdout.write(JSON.stringify({ ok: true, asset, tag, outDir: outRoot, outputs: { signals: outSignalsPath, overview: outOverviewPath, meeting: outMeetingPath, meta: outMetaPath, md: (args.writeMd ? outMdPath : null) } }, null, 2));
}

if (process.env.MULTI_AGENT_BRIDGE_NO_MAIN !== '1') {
  main().catch((e) => {
    process.stderr.write(String(e?.stack || e?.message || e) + '\n');
    process.exit(1);
  });
}
