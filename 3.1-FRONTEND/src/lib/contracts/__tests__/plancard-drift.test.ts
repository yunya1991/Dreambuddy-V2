// ============================================
// PlanCard 契约漂移校验（SPEC-20261111-C §3.1 / G-C4）
// ============================================
// 事实源：52-lobehub协议集成/schemas/plancard.schema.json
// 镜像：src/types/plancard.ts（zod）
// 校验：必填字段集合、属性键集合、类型分类、枚举值、关键 pattern。
// 负样例：PLANCARD_SCHEMA_PATH 指向被篡改的副本时本套件必须失败（供 CI 阻断演示）。

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import type { z } from 'zod';
import { PLAN_TOOL_PATTERN, planCardSchema } from '@/types/plancard';

type JsonSchemaNode = {
  type?: string;
  enum?: unknown[];
  pattern?: string;
  required?: string[];
  properties?: Record<string, JsonSchemaNode>;
  items?: JsonSchemaNode;
};

const SCHEMA_CANDIDATES = [
  process.env.PLANCARD_SCHEMA_PATH,
  path.resolve(__dirname, '../../../../..', '52-lobehub协议集成/schemas/plancard.schema.json'),
  path.resolve(process.cwd(), '..', '52-lobehub协议集成/schemas/plancard.schema.json'),
].filter((p): p is string => Boolean(p));

const SCHEMA_PATH = SCHEMA_CANDIDATES.find((candidate) => existsSync(candidate));

const TYPE_MAP: Record<string, string> = {
  string: 'ZodString',
  integer: 'ZodNumber',
  number: 'ZodNumber',
  array: 'ZodArray',
  object: 'ZodObject',
  boolean: 'ZodBoolean',
};

function unwrap(schema: z.ZodTypeAny): z.ZodTypeAny {
  return schema._def.typeName === 'ZodOptional' ? unwrap((schema as z.ZodOptional<z.ZodTypeAny>).unwrap()) : schema;
}

function zodObjectSchema(schema: z.ZodTypeAny): z.ZodObject<z.ZodRawShape> {
  const inner = unwrap(schema);
  if (inner._def.typeName !== 'ZodObject') throw new Error(`期望 ZodObject，实际 ${inner._def.typeName}`);
  return inner as z.ZodObject<z.ZodRawShape>;
}

function zodRequiredKeys(schema: z.ZodObject<z.ZodRawShape>): string[] {
  return Object.entries(schema.shape)
    .filter(([, value]) => (value as z.ZodTypeAny)._def.typeName !== 'ZodOptional')
    .map(([key]) => key)
    .sort();
}

function compareNode(jsonNode: JsonSchemaNode, zodSchema: z.ZodTypeAny, location: string): void {
  const inner = unwrap(zodSchema);
  const typeName = inner._def.typeName;

  if (jsonNode.enum) {
    expect({ location, typeName }).toEqual({ location, typeName: 'ZodEnum' });
    const options = [...((inner as z.ZodEnum<[string, ...string[]]>).options as unknown as string[])].sort();
    expect({ location, options }).toEqual({ location, options: [...jsonNode.enum].sort() });
    return;
  }

  const expected = TYPE_MAP[jsonNode.type ?? ''];
  // args_hint 在 zod 侧是 record（任意键），与 JSON Schema 的 object 语义等价
  if (jsonNode.type === 'object' && typeName === 'ZodRecord') return;
  expect({ location, typeName }).toEqual({ location, typeName: expected });

  if (jsonNode.type === 'integer') {
    const checks = (inner as z.ZodNumber)._def.checks ?? [];
    expect({ location, int: checks.some((check) => check.kind === 'int') }).toEqual({ location, int: true });
  }

  if (jsonNode.type === 'object') {
    const objectSchema = zodObjectSchema(zodSchema);
    expect({ location, required: zodRequiredKeys(objectSchema) }).toEqual({
      location,
      required: [...(jsonNode.required ?? [])].sort(),
    });
    const jsonKeys = Object.keys(jsonNode.properties ?? {}).sort();
    const zodKeys = Object.keys(objectSchema.shape).sort();
    expect({ location, keys: zodKeys }).toEqual({ location, keys: jsonKeys });
    for (const key of jsonKeys) {
      compareNode(jsonNode.properties?.[key] ?? {}, objectSchema.shape[key] as z.ZodTypeAny, `${location}.${key}`);
    }
  }

  if (jsonNode.type === 'array' && jsonNode.items) {
    compareNode(jsonNode.items, (inner as z.ZodArray<z.ZodTypeAny>)._def.type, `${location}[]`);
  }
}

describe('PlanCard 契约漂移', () => {
  it('schema 文件可定位', () => {
    expect(SCHEMA_PATH).toBeTruthy();
  });

  it('根必填字段 / 属性键 / 类型与 zod 镜像一致', () => {
    const json = JSON.parse(readFileSync(SCHEMA_PATH as string, 'utf8')) as JsonSchemaNode;
    compareNode(json, planCardSchema, 'PlanCard');
  });

  it('工具命名 pattern 与契约一致', () => {
    const json = JSON.parse(readFileSync(SCHEMA_PATH as string, 'utf8')) as JsonSchemaNode;
    const contractPattern = json.properties?.plan_steps?.items?.properties?.tool?.pattern;
    expect(contractPattern).toBeTruthy();
    expect(PLAN_TOOL_PATTERN.source).toBe(contractPattern);
  });

  it('合法样例通过校验，缺必填字段被拒', () => {
    const valid = {
      id: 'pc-1',
      intent: '验证契约',
      plan_steps: [{ step: 1, action: '取数', tool: 'l0.data.mcp.query' }],
      validation: { evaluator_refs: ['45.eval@0.1.0'] },
    };
    expect(planCardSchema.safeParse(valid).success).toBe(true);

    const invalid = { ...valid, validation: undefined };
    expect(planCardSchema.safeParse(invalid).success).toBe(false);
  });
});
