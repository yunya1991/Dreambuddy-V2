/**
 * DSH 能力名契约回归测试（SPEC FRONTEND_INDUSTRIALIZATION_GOAL_SPEC HC-11）
 *
 * 背景：跨语言契约最易错点。前端曾调用 `orchestrator.status`（点号）、
 * `index_query`、`research` 等 DSH 不存在的能力名，云端只会返回 not_found，
 * 且单测覆盖不到。本测试以 dsh_frontend_bridge.HANDLER_TO_SHELL_ID 为唯一事实源，
 * 静态校验前端所有字面量能力名。
 */
import fs from 'fs';
import path from 'path';

const REPO_ROOT = path.resolve(process.cwd(), '..');
const BRIDGE_PATH = path.join(
  REPO_ROOT,
  '34-前端应用训练系统',
  'core',
  'dsh_frontend_bridge.py',
);
const SRC_ROOT = path.join(process.cwd(), 'src');

function readRegisteredHandlers(): Set<string> {
  const source = fs.readFileSync(BRIDGE_PATH, 'utf-8');
  const marker = 'HANDLER_TO_SHELL_ID: Dict[str, str] = {';
  const start = source.indexOf(marker);
  if (start < 0) throw new Error('未找到 HANDLER_TO_SHELL_ID 定义');
  const body = source.slice(start + marker.length).split('\n}')[0];
  const names = new Set<string>();
  for (const match of body.matchAll(/^\s{4}"([A-Za-z0-9_.]+)"\s*:/gm)) {
    names.add(match[1]);
  }
  return names;
}

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.(ts|tsx)$/.test(entry.name)) return [];
    return [full];
  });
}

function collectCalledHandlers(file: string): string[] {
  const source = fs.readFileSync(file, 'utf-8');
  const pattern = /callDsh(?:Handler|Http)\s*(?:<[^>]*>)?\s*\(\s*['"]([^'"]+)['"]/g;
  return [...source.matchAll(pattern)].map((match) => match[1]);
}

describe('DSH 能力名契约', () => {
  it('前端字面量能力名必须全部登记在 HANDLER_TO_SHELL_ID', () => {
    const registered = readRegisteredHandlers();
    expect(registered.size).toBeGreaterThan(0);

    const violations: string[] = [];
    for (const file of walk(SRC_ROOT)) {
      for (const handler of collectCalledHandlers(file)) {
        if (!registered.has(handler)) {
          violations.push(`${path.relative(SRC_ROOT, file)} -> ${handler}`);
        }
      }
    }

    expect(violations).toEqual([]);
  });
});
