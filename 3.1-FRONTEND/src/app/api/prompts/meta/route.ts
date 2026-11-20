import { NextResponse } from 'next/server';
import { getSkillPromptMeta } from '@/lib/orchestration/node-prompts';
import promptRegistry from '@/lib/orchestration/prompt-registry.generated.json';

export const dynamic = 'force-dynamic';

/**
 * L2 提示词运行时元数据出口（SPEC-57 P6）。
 * 七字段只从注册表快照读取，便于线上核对「宪法 + 提示词」是否同版本协同。
 */
export async function GET() {
  const meta = getSkillPromptMeta();
  return NextResponse.json(
    {
      ok: true,
      prompt_meta: meta,
      constitution_version: meta.constitution_version,
      persona: promptRegistry.persona,
      snapshot: {
        generated_by: promptRegistry.generated_by,
        schema_version: promptRegistry.schema_version,
        notice: promptRegistry._notice,
      },
    },
    { headers: { 'X-L2-Prompt-Version': `${meta.prompt_id}@${meta.prompt_version}` } },
  );
}
