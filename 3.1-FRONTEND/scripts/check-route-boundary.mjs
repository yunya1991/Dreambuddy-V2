#!/usr/bin/env node
// ============================================
// route.ts 边界门禁（SPEC-20261111-C §3.8）
// ============================================
// 规则：扫描 src/app/api/**/route.ts 中 fs / child_process 的使用点，对照基线：
//   1) 总量不得增加；
//   2) 单个文件不得超过其基线计数；
//   3) 基线中不存在的文件一旦使用 fs/child_process 即失败（新增必须显式评审）。
// 只允许下降。违规输出 文件:行号，退出码 1。
//
// 用法：
//   node scripts/check-route-boundary.mjs
//   node scripts/check-route-boundary.mjs --update-baseline   # 仅在评审通过后手工下调/登记
//   node scripts/check-route-boundary.mjs --json

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const API_DIR = path.join(ROOT, 'src', 'app', 'api');
const BASELINE_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), 'route-boundary-baseline.json');

const CAPABILITIES = {
  fs: [
    // import/require 来源
    /(?:from|require\s*\()\s*['"](?:node:)?fs(?:\/promises)?['"]/,
    // 常见直接调用（排除 obj.readFile 之类的方法调用）
    /(?<![.\w])(?:readFile|readFileSync|writeFile|writeFileSync|appendFile|appendFileSync|unlink|unlinkSync|mkdir|mkdirSync|readdir|readdirSync|rm|rmSync|statSync|existsSync|createReadStream|createWriteStream)\s*\(/,
  ],
  child_process: [
    /(?:from|require\s*\()\s*['"](?:node:)?child_process['"]/,
    /(?<![.\w])(?:spawn|spawnSync|exec|execSync|execFile|execFileSync|fork)\s*\(/,
  ],
};

function walkRouteFiles(dir) {
  if (!existsSync(dir)) return [];
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      out.push(...walkRouteFiles(full));
    } else if (entry === 'route.ts') {
      out.push(full);
    }
  }
  return out.sort();
}

function scanFile(file) {
  const text = readFileSync(file, 'utf8');
  const lines = text.split(/\r?\n/);
  const hits = { fs: [], child_process: [] };
  lines.forEach((line, index) => {
    for (const [capability, patterns] of Object.entries(CAPABILITIES)) {
      if (patterns.some((re) => re.test(line))) {
        hits[capability].push({ line: index + 1, text: line.trim() });
      }
    }
  });
  return hits;
}

function toRelative(file) {
  return path.relative(ROOT, file).split(path.sep).join('/');
}

function buildSnapshot() {
  const files = {};
  const totals = { fs: 0, child_process: 0 };
  for (const file of walkRouteFiles(API_DIR)) {
    const hits = scanFile(file);
    const counts = { fs: hits.fs.length, child_process: hits.child_process.length };
    if (counts.fs || counts.child_process) {
      files[toRelative(file)] = { ...counts, occurrences: hits };
      totals.fs += counts.fs;
      totals.child_process += counts.child_process;
    }
  }
  return { totals, files };
}

function loadBaseline() {
  if (!existsSync(BASELINE_PATH)) return null;
  return JSON.parse(readFileSync(BASELINE_PATH, 'utf8'));
}

function writeBaseline(snapshot) {
  const payload = {
    generated_at: new Date().toISOString(),
    note: '只允许下降。新增 fs/child_process 使用必须先评审，再运行 node scripts/check-route-boundary.mjs --update-baseline 登记。',
    totals: snapshot.totals,
    files: Object.fromEntries(
      Object.entries(snapshot.files).map(([file, value]) => [
        file,
        { fs: value.fs, child_process: value.child_process },
      ]),
    ),
  };
  writeFileSync(BASELINE_PATH, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function main() {
  const args = process.argv.slice(2);
  const snapshot = buildSnapshot();

  if (args.includes('--update-baseline')) {
    writeBaseline(snapshot);
    console.log(`[check:boundary] 基线已更新：fs=${snapshot.totals.fs} child_process=${snapshot.totals.child_process}`);
    process.exit(0);
  }

  const baseline = loadBaseline();
  if (!baseline) {
    console.error('[check:boundary] 缺少基线文件 scripts/route-boundary-baseline.json');
    console.error('                先评审现状后运行：node scripts/check-route-boundary.mjs --update-baseline');
    process.exit(1);
  }

  const violations = [];

  for (const [capability, total] of Object.entries(snapshot.totals)) {
    const allowed = baseline.totals?.[capability] ?? 0;
    if (total > allowed) {
      violations.push(`总量 ${capability} 增加：${allowed} → ${total}`);
    }
  }

  for (const [file, value] of Object.entries(snapshot.files)) {
    const allowed = baseline.files?.[file];
    if (!allowed) {
      for (const capability of Object.keys(CAPABILITIES)) {
        for (const hit of value.occurrences[capability]) {
          violations.push(`新增使用（未在基线白名单）：${file}:${hit.line} [${capability}] ${hit.text}`);
        }
      }
      continue;
    }
    for (const capability of Object.keys(CAPABILITIES)) {
      if (value[capability] > (allowed[capability] ?? 0)) {
        const extra = value.occurrences[capability].slice(allowed[capability] ?? 0);
        for (const hit of extra) {
          violations.push(`单文件 ${capability} 增加：${file}:${hit.line}（基线 ${allowed[capability] ?? 0}，当前 ${value[capability]}）${hit.text}`);
        }
      }
    }
  }

  const summary = {
    routes: walkRouteFiles(API_DIR).length,
    current: snapshot.totals,
    baseline: baseline.totals,
    violations,
  };

  if (args.includes('--json')) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    console.log(
      `[check:boundary] route 文件 ${summary.routes} 个；当前 fs=${snapshot.totals.fs} child_process=${snapshot.totals.child_process}；` +
        `基线 fs=${baseline.totals?.fs ?? 0} child_process=${baseline.totals?.child_process ?? 0}`,
    );
    const decreased = Object.entries(snapshot.totals).some(
      ([capability, total]) => total < (baseline.totals?.[capability] ?? 0),
    );
    if (decreased && violations.length === 0) {
      console.log('[check:boundary] 提示：使用量低于基线，可在评审后运行 --update-baseline 下调。');
    }
  }

  if (violations.length > 0) {
    console.error(`[check:boundary] 失败：${violations.length} 处违规`);
    for (const item of violations) console.error(`  - ${item}`);
    process.exit(1);
  }

  if (!args.includes('--json')) console.log('[check:boundary] OK');
  process.exit(0);
}

main();
