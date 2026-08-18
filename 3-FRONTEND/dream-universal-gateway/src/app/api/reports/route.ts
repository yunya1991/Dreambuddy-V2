/**
 * 研报 API
 * GET /api/reports           - 获取研报列表
 * GET /api/reports?file=xxx  - 获取单个研报内容
 * GET /api/reports?chain_phase=A1&limit=10  - 过滤查询
 */
import { NextRequest, NextResponse } from 'next/server';
import { readFile, readdir } from 'fs/promises';
import { join } from 'path';

// 研报目录路径 — 直接指向 ~/.workbuddy/artifacts/trading/（sync_artifact.py的输出目录）
import { homedir } from 'os';
const ARTIFACTS_DIR = join(homedir(), '.workbuddy', 'artifacts', 'trading');
const INDEX_FILE = join(ARTIFACTS_DIR, 'index.json');

interface ReportMeta {
  file: string;
  title: string;
  date: string;
  type: string;
  chain_phase: string;
  tags: string;
  department: string;
  status: string;
  regime?: string;
  confidence?: number;
  direction?: string;
  position_modifier?: number;
  leverage_cap?: number;
}

interface ReportIndex {
  generated_at: string;
  artifacts: ReportMeta[];
}

// 链阶段颜色映射
const PHASE_COLORS: Record<string, string> = {
  A1: '#3b82f6', // 蓝色 - 侦察
  A2: '#8b5cf6', // 紫色 - 第一性原理
  A3: '#f59e0b', // 黄色 - 推演
  A4: '#06b6d4', // 青色 - 验证
  A5: '#22c55e', // 绿色 - 执行
  A6: '#ef4444', // 红色 - 情报
  A7: '#eab308', // 金色 - 实践论
  A8: '#ec4899', // 粉色 - 理论实践验证
};

// 只展示给用户前端的A系列阶段
const USER_FACING_PHASES = ['A1', 'A2', 'A3', 'A6'];

// GET /api/reports
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const file = searchParams.get('file');
  const chainPhase = searchParams.get('chain_phase');
  const phasesParam = searchParams.get('phases'); // 逗号分隔, 如 "A1,A2,A3,A6"
  const latest = parseInt(searchParams.get('latest') || '0', 10); // 按phase分组取最新N条
  const limit = parseInt(searchParams.get('limit') || '20', 10);
  const todayOnly = searchParams.get('today_only') === 'true';

  try {
    // 如果请求特定文件内容
    if (file) {
      return await getReportContent(file);
    }

    // 否则返回列表
    return await getReportList(chainPhase, phasesParam, limit, latest, todayOnly);
  } catch (error) {
    console.error('研报API失败:', error);
    return NextResponse.json(
      { success: false, error: '获取研报数据失败' },
      { status: 500 }
    );
  }
}

async function getReportList(
  chainPhase: string | null,
  phasesParam: string | null,
  limit: number,
  latest: number,
  todayOnly: boolean
) {
  // 确定过滤的phase列表：优先phases参数，否则chainPhase，否则默认USER_FACING_PHASES
  const filterPhases: string[] = (() => {
    if (phasesParam) return phasesParam.split(',').map(p => p.trim().toUpperCase());
    if (chainPhase) return [chainPhase.toUpperCase()];
    return USER_FACING_PHASES;
  })();

  try {
    const indexContent = await readFile(INDEX_FILE, 'utf-8');
    const parsed = JSON.parse(indexContent);

    // 兼容两种index.json格式: 纯数组[] 或 {generated_at, artifacts}
    let artifacts: ReportMeta[];
    if (Array.isArray(parsed)) {
      artifacts = parsed;
    } else if (parsed.artifacts && Array.isArray(parsed.artifacts)) {
      artifacts = parsed.artifacts;
    } else {
      artifacts = [];
    }

    if (filterPhases.length > 0) {
      artifacts = artifacts.filter((a) =>
        filterPhases.includes((a.chain_phase || '').toUpperCase())
      );
    }

    // 今日过滤
    if (todayOnly) {
      const todayStr = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
      artifacts = artifacts.filter((a) => {
        const artifactDate = a.date ? new Date(a.date).toISOString().slice(0, 10) : '';
        return artifactDate === todayStr;
      });
    }

    // 按日期降序排列
    artifacts.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

    // latest模式：按phase分组取每phase最新1条
    if (latest > 0) {
      const phaseMap = new Map<string, ReportMeta>();
      for (const a of artifacts) {
        const phase = a.chain_phase.toUpperCase();
        if (!phaseMap.has(phase)) {
          phaseMap.set(phase, a); // 已按日期降序，第一个就是最新
        }
      }
      artifacts = Array.from(phaseMap.values())
        .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
        .slice(0, latest);
    } else {
      // 普通limit
      artifacts = artifacts.slice(0, limit);
    }

    // 判断是否当日产物
    const todayStr = new Date().toISOString().slice(0, 10);

    // 附加颜色信息+新鲜度 — 统一chain_phase为大写以兼容不同格式
    const enriched = artifacts.map((a) => {
      const phaseKey = (a.chain_phase || '').toUpperCase();
      const artifactDate = a.date ? new Date(a.date).toISOString().slice(0, 10) : '';
      const isToday = artifactDate === todayStr;
      const relativeTime = getRelativeTime(a.date);

      return {
        ...a,
        chain_phase: phaseKey,
        phaseColor: PHASE_COLORS[phaseKey] || '#a1a1aa',
        isToday,
        relativeTime,
        freshness: isToday ? 'today' as const : 'stale' as const,
      };
    });

    return NextResponse.json({
      success: true,
      data: enriched,
      total: Array.isArray(parsed) ? parsed.length : (parsed.artifacts?.length || 0),
      filtered: enriched.length,
      phases: filterPhases,
    });
  } catch (error) {
    // 如果index.json不存在或读取失败，尝试扫描目录
    console.log('index.json读取失败，尝试扫描目录:', error);
    return await scanDirectoryForReports(limit, filterPhases);
  }
}

// 相对时间计算
function getRelativeTime(dateStr: string): string {
  if (!dateStr) return '';
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin}分钟前`;
  if (diffHour < 24) return `${diffHour}小时前`;
  if (diffDay === 1) return '昨日';
  if (diffDay < 7) return `${diffDay}天前`;
  return date.toLocaleDateString('zh-CN');
}

async function scanDirectoryForReports(limit: number, filterPhases: string[] = USER_FACING_PHASES) {
  try {
    const files = await readdir(ARTIFACTS_DIR);
    const mdFiles = files.filter((f) => f.endsWith('.md')).sort().reverse();

    const todayStr = new Date().toISOString().slice(0, 10);

    const reports = mdFiles
      .map((file) => {
        // 从文件名解析信息
        const phaseMatch = file.match(/^(a\d+)_/i);
        const chainPhase = phaseMatch ? phaseMatch[1].toUpperCase() : 'UNKNOWN';
        const dateMatch = file.match(/(\d{8})/);
        const date = dateMatch
          ? `${dateMatch[1].slice(0, 4)}-${dateMatch[1].slice(4, 6)}-${dateMatch[1].slice(6, 8)}`
          : '';

        return {
          file,
          title: file.replace(/\.md$/, '').replace(/_/g, ' '),
          date,
          chain_phase: chainPhase,
          phaseColor: PHASE_COLORS[chainPhase] || '#a1a1aa',
          status: 'completed',
          isToday: date === todayStr,
          relativeTime: date ? getRelativeTime(date) : '',
          freshness: date === todayStr ? 'today' as const : 'stale' as const,
        };
      })
      .filter((r) => filterPhases.includes(r.chain_phase))
      .slice(0, limit);

    return NextResponse.json({
      success: true,
      data: reports,
      total: reports.length,
      filtered: reports.length,
      phases: filterPhases,
    });
  } catch {
    return NextResponse.json({
      success: true,
      data: [],
      total: 0,
      filtered: 0,
      phases: filterPhases,
    });
  }
}

async function getReportContent(filename: string) {
  // 安全检查：防止路径遍历
  const safeName = filename.replace(/[^a-zA-Z0-9_\-\.]/g, '');
  if (safeName !== filename) {
    return NextResponse.json(
      { success: false, error: '无效的文件名' },
      { status: 400 }
    );
  }

  const filePath = join(ARTIFACTS_DIR, safeName);

  try {
    const content = await readFile(filePath, 'utf-8');

    // 从index.json获取元数据
    let metadata: ReportMeta | null = null;
    try {
      const indexContent = await readFile(INDEX_FILE, 'utf-8');
      const index: ReportIndex = JSON.parse(indexContent);
      metadata = index.artifacts.find((a) => a.file === safeName) || null;
    } catch {}

    return NextResponse.json({
      success: true,
      data: {
        filename: safeName,
        content,
        metadata,
        phaseColor: PHASE_COLORS[metadata?.chain_phase || ''] || '#a1a1aa',
      },
    });
  } catch {
    return NextResponse.json(
      { success: false, error: `文件不存在: ${safeName}` },
      { status: 404 }
    );
  }
}
