// 卡片配置服务端存储客户端（SPEC-54 R3b）
// 职责：把参数/自定义序列落 `19-数据访问层/data/visual_cards.db`；
// user_id 由路由从 session 注入，本模块只做数据搬运，不做鉴权判断。

import { execFile } from 'child_process';
import { promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

export interface CardConfigItem {
  tab_id: string;
  panel_key: string;
  capability_id: string;
  args: Record<string, unknown>;
  data_provenance: string;
  updated_at: number;
}

export interface CardPanelInput {
  panel_key: string;
  capability_id: string;
  args: Record<string, unknown>;
  data_provenance?: string;
}

export interface CardsConfigResponse {
  ok: boolean;
  code: string;
  items?: CardConfigItem[];
  count?: number;
  tab_id?: string;
  reason?: string;
}

interface RunOptions {
  op: 'get' | 'put';
  userId: string;
  tabId?: string;
  panels?: CardPanelInput[];
}

async function run(options: RunOptions): Promise<CardsConfigResponse> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'cards_config.py');
  const pythonBin = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
  const base = [scriptPath, '--op', options.op, '--user', options.userId];

  let tmpDir: string | null = null;
  try {
    if (options.op === 'get') {
      if (options.tabId) base.push('--tab', options.tabId);
    } else {
      // args 可能含 custom_series（≤5000 点），走临时文件避免命令行长度限制
      tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'cards-config-'));
      const file = path.join(tmpDir, 'payload.json');
      await fs.writeFile(
        file,
        JSON.stringify({
          user: options.userId,
          tab: options.tabId,
          panels: options.panels ?? [],
        }),
        'utf8',
      );
      base.push('--payload-file', file);
    }
    const { stdout } = await execFileAsync(pythonBin, base, {
      maxBuffer: 8 * 1024 * 1024,
      timeout: 15000,
    });
    const lines = stdout.trim().split('\n').filter((line) => line.trim().startsWith('{'));
    return JSON.parse(lines[lines.length - 1] || '{"ok":false,"code":"error"}');
  } finally {
    if (tmpDir) await fs.rm(tmpDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

export function readCardsConfig(userId: string, tabId?: string): Promise<CardsConfigResponse> {
  return run({ op: 'get', userId, tabId });
}

export function writeCardsConfig(
  userId: string,
  tabId: string,
  panels: CardPanelInput[],
): Promise<CardsConfigResponse> {
  return run({ op: 'put', userId, tabId, panels });
}
