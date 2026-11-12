// design-tokens.test.ts - T-B1: scan all var(--color-*) refs, assert each is defined in globals.css
import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();
const SRC_DIR = path.join(ROOT, 'src');
const GLOBALS_CSS = path.join(ROOT, 'src', 'app', 'globals.css');

/** 从 globals.css 中提取所有已定义的 --color-xxx token */
function extractDefinedTokens(cssContent: string): Set<string> {
  const definePattern = /--color-([a-z0-9-]+)\s*:/g;
  const tokens = new Set<string>();
  let m: RegExpExecArray | null;
  while ((m = definePattern.exec(cssContent)) !== null) {
    tokens.add(`--color-${m[1]}`);
  }
  return tokens;
}

/** 递归列出 src 下所有 ts/tsx/css 文件 */
function listSourceFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.next' || entry.name.startsWith('.')) {
      continue;
    }
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...listSourceFiles(full));
    } else if (/\.(tsx?|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

/** 提取单文件中所有 var(--color-xxx) 引用 */
function extractVarRefs(content: string): string[] {
  const refPattern = /var\(\s*(--color-[a-z0-9-]+)\s*\)/g;
  const refs: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = refPattern.exec(content)) !== null) {
    refs.push(m[1]);
  }
  return refs;
}

describe('design-tokens', () => {
  let definedTokens: Set<string>;

  beforeAll(() => {
    const css = fs.readFileSync(GLOBALS_CSS, 'utf-8');
    definedTokens = extractDefinedTokens(css);
    expect(definedTokens.size).toBeGreaterThan(0);
  });

  it('globals.css self-references resolve', () => {
    const css = fs.readFileSync(GLOBALS_CSS, 'utf-8');
    const selfRefs = extractVarRefs(css);
    const undefinedInSelf = selfRefs.filter((t) => !definedTokens.has(t));
    expect(undefinedInSelf).toEqual([]);
  });

  it('all var(--color-*) refs in src/ have definitions', () => {
    const sourceFiles = listSourceFiles(SRC_DIR);
    const violations: Array<{ file: string; token: string }> = [];

    for (const file of sourceFiles) {
      const content = fs.readFileSync(file, 'utf-8');
      const refs = extractVarRefs(content);
      for (const token of refs) {
        if (!definedTokens.has(token)) {
          violations.push({ file: path.relative(ROOT, file), token });
        }
      }
    }

    expect(violations).toEqual([]);
  });

  it('critical pages use defined tokens', () => {
    const criticalPages = [
      'src/app/layout.tsx',
      'src/app/dashboard/layout.tsx',
      'src/app/chat/page.tsx',
    ];
    for (const rel of criticalPages) {
      const abs = path.resolve(process.cwd(), rel);
      if (!fs.existsSync(abs)) continue;
      const content = fs.readFileSync(abs, 'utf-8');
      const refs = extractVarRefs(content);
      for (const token of refs) {
        expect(definedTokens.has(token)).toBe(true);
      }
    }
  });
});
