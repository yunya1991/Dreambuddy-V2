/**
 * T4 注册器单测：显式 manifest 才注册，字段不全一律跳过（不猜测映射）。
 */

import fs from "fs";
import os from "os";
import path from "path";
import type { CapabilityDomain } from "./capability-domain";
import {
  ensureDomainsRegistered,
  loadDomainManifests,
  parseDomainManifest,
  registerDomainsFromDir,
} from "./capability-domain-registrar";

const COMPLETE = `---
name: market-evidence
description: 行情与指标取证
version: 1.2.0
acceptance: 每个数值必须可回溯
capabilities: [market.price, market.series]
evidence_types:
  - tool_result
  - quote_snapshot
---
# body
`;

const COMPLETE_MACRO = `---
name: macro-evidence
description: 宏观数据取证
version: 1.0.0
acceptance: 口径与统计区间明确
capabilities: [data.macro_snapshot]
evidence_types: [tool_result]
---
# body
`;

const INCOMPLETE = `---
name: legacy-skill
description: 缺少能力清单与验收口径
version: 1.0.0
---
# body
`;

function writeSkill(dir: string, name: string, content: string): string {
  const skillDir = path.join(dir, name);
  fs.mkdirSync(skillDir, { recursive: true });
  fs.writeFileSync(path.join(skillDir, "SKILL.md"), content, "utf-8");
  return skillDir;
}

let tmpRoot = "";

beforeEach(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "domain-registrar-"));
});

afterEach(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

describe("parseDomainManifest", () => {
  it("完整 manifest 解析出全部字段", () => {
    const parsed = parseDomainManifest(COMPLETE);
    expect(parsed.errors).toHaveLength(0);
    expect(parsed.domainId).toBe("domain:market_evidence");
    expect(parsed.domain?.capabilities).toEqual(["market.price", "market.series"]);
    expect(parsed.domain?.evidence_types).toEqual([
      "tool_result",
      "quote_snapshot",
    ]);
    expect(parsed.domain?.acceptance).toBe("每个数值必须可回溯");
    expect(parsed.domain?.version).toBe("1.2.0");
  });

  it("缺 capabilities / evidence_types / acceptance 时只报错，不产出一半字段的域", () => {
    const parsed = parseDomainManifest(INCOMPLETE);
    expect(parsed.domain).toBeUndefined();
    expect(parsed.errors).toEqual(
      expect.arrayContaining([
        "missing:acceptance",
        "missing:capabilities",
        "missing:evidence_types",
        "capabilities_empty",
        "evidence_types_empty",
      ]),
    );
  });
});

describe("registerDomainsFromDir", () => {
  it("只注册字段齐全的 skill，缺失的进入 skipped", () => {
    writeSkill(tmpRoot, "market-evidence", COMPLETE);
    writeSkill(tmpRoot, "legacy-skill", INCOMPLETE);
    const target: Record<string, CapabilityDomain> = {};

    const result = registerDomainsFromDir(tmpRoot, target);

    expect(result.registered).toEqual(["domain:market_evidence"]);
    expect(result.skipped).toHaveLength(1);
    expect(result.skipped[0].path).toContain("legacy-skill");
    expect(Object.keys(target)).toEqual(["domain:market_evidence"]);
    expect(target["domain:market_evidence"].capabilities).toContain("market.price");
  });

  it("同名域不覆盖，记入 duplicates", () => {
    writeSkill(tmpRoot, "market-evidence", COMPLETE);
    const target: Record<string, CapabilityDomain> = {
      "domain:market_evidence": {
        name: "existing",
        description: "已注册",
        capabilities: ["market.price"],
        acceptance: "既有口径",
        evidence_types: ["tool_result"],
        version: "0.0.1",
      },
    };

    const result = registerDomainsFromDir(tmpRoot, target);

    expect(result.registered).toHaveLength(0);
    expect(result.duplicates).toEqual(["domain:market_evidence"]);
    expect(target["domain:market_evidence"].name).toBe("existing");
  });

  it("目录不存在时返回空结果，不抛异常", () => {
    const result = registerDomainsFromDir(path.join(tmpRoot, "missing"), {});
    expect(result).toEqual({ registered: [], skipped: [], duplicates: [] });
    expect(loadDomainManifests(path.join(tmpRoot, "missing"))).toEqual({
      loaded: [],
      skipped: [],
    });
  });
});

describe("ensureDomainsRegistered", () => {
  it("首次扫描即注册，重复调用走进程缓存，force 才重扫", () => {
    writeSkill(tmpRoot, "market-evidence", COMPLETE);
    const target: Record<string, CapabilityDomain> = {};

    const first = ensureDomainsRegistered({ dirs: [tmpRoot], target });
    expect(first[0].registered).toEqual(["domain:market_evidence"]);

    writeSkill(tmpRoot, "macro-evidence", COMPLETE_MACRO);
    const cached = ensureDomainsRegistered({ dirs: [tmpRoot], target });
    expect(cached[0].registered).toEqual([]);
    expect(target["domain:macro_evidence"]).toBeUndefined();

    const forced = ensureDomainsRegistered({
      dirs: [tmpRoot],
      target,
      force: true,
    });
    expect(forced[0].registered).toEqual(["domain:macro_evidence"]);
    expect(target["domain:macro_evidence"].capabilities).toEqual([
      "data.macro_snapshot",
    ]);
  });
});
