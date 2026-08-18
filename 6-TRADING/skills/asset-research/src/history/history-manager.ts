/**
 * 研究历史记录管理器
 * Research History Manager
 *
 * 功能：
 * 1. 保存每次调研结果到本地
 * 2. 查询历史记录
 * 3. 追踪周期变化
 * 4. 趋势分析
 */

import * as fs from 'fs';
import * as path from 'path';

export interface ResearchRecord {
  id: string;
  timestamp: string;
  version: string;
  engineName: string;
  region: string;
  cyclePhase: string;
  confidence: number;
  topSubCategories: string[];
  allocations: Record<string, number>;
  metadata?: any;
}

export interface CycleChangeEvent {
  fromPhase: string;
  toPhase: string;
  timestamp: string;
  daysBetween: number;
}

export interface TrendAnalysis {
  currentPhase: string;
  phaseDurationDays: number;
  lastPhaseChange?: CycleChangeEvent;
  phaseHistory: { phase: string; duration: number }[];
}

/**
 * 历史记录管理器
 */
export class ResearchHistoryManager {
  private storageDir: string;
  private records: ResearchRecord[] = [];

  constructor(storageDir?: string) {
    this.storageDir = storageDir || path.join(process.cwd(), '.asset-research-history');
    this.ensureStorageDir();
    this.loadRecords();
  }

  /**
   * 保存研究记录
   */
  saveRecord(result: any): string {
    const record: ResearchRecord = {
      id: this.generateId(),
      timestamp: result.timestamp || new Date().toISOString(),
      version: result.version,
      engineName: result.engineName,
      region: result.region,
      cyclePhase: result.cycle?.currentPhase || 'unknown',
      confidence: result.confidence || 0,
      topSubCategories: (result.topSubCategories || []).map((s: any) => s.name || s),
      allocations: this.extractAllocations(result),
      metadata: {
        indicatorCount: result.cycle?.indicators?.length || 0,
        dataSources: result.dataSources?.length || 0,
      },
    };

    this.records.push(record);
    this.persistRecord(record);

    return record.id;
  }

  /**
   * 获取历史记录
   */
  getRecords(options?: {
    limit?: number;
    version?: string;
    region?: string;
    startDate?: string;
    endDate?: string;
  }): ResearchRecord[] {
    let filtered = [...this.records];

    if (options?.version) {
      filtered = filtered.filter(r => r.version === options.version);
    }
    if (options?.region) {
      filtered = filtered.filter(r => r.region === options.region);
    }
    if (options?.startDate) {
      filtered = filtered.filter(r => r.timestamp >= options.startDate!);
    }
    if (options?.endDate) {
      filtered = filtered.filter(r => r.timestamp <= options.endDate!);
    }

    filtered.sort((a, b) => b.timestamp.localeCompare(a.timestamp));

    if (options?.limit) {
      filtered = filtered.slice(0, options.limit);
    }

    return filtered;
  }

  /**
   * 获取最近一条记录
   */
  getLatestRecord(version?: string): ResearchRecord | null {
    const records = this.getRecords({ limit: 1, version });
    return records.length > 0 ? records[0] : null;
  }

  /**
   * 分析周期变化趋势
   */
  analyzeCycleTrend(region?: string): TrendAnalysis {
    const records = this.getRecords({ region }).reverse(); // 按时间正序

    if (records.length === 0) {
      return {
        currentPhase: 'unknown',
        phaseDurationDays: 0,
        phaseHistory: [],
      };
    }

    const currentPhase = records[records.length - 1].cyclePhase;
    const phaseChanges = this.detectPhaseChanges(records);

    // 计算当前周期持续天数
    let currentPhaseStartIdx = records.length - 1;
    for (let i = records.length - 1; i >= 0; i--) {
      if (records[i].cyclePhase !== currentPhase) {
        currentPhaseStartIdx = i + 1;
        break;
      }
      currentPhaseStartIdx = i;
    }

    const startDate = new Date(records[currentPhaseStartIdx].timestamp);
    const endDate = new Date(records[records.length - 1].timestamp);
    const phaseDurationDays = Math.max(1, Math.round(
      (endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)
    ));

    // 构建周期历史
    const phaseHistory: { phase: string; duration: number }[] = [];
    if (phaseChanges.length > 0) {
      for (let i = 0; i < phaseChanges.length; i++) {
        const change = phaseChanges[i];
        phaseHistory.push({
          phase: change.fromPhase,
          duration: change.daysBetween,
        });
      }
    }

    return {
      currentPhase,
      phaseDurationDays,
      lastPhaseChange: phaseChanges.length > 0 ? phaseChanges[phaseChanges.length - 1] : undefined,
      phaseHistory,
    };
  }

  /**
   * 检测周期变化
   */
  private detectPhaseChanges(records: ResearchRecord[]): CycleChangeEvent[] {
    const changes: CycleChangeEvent[] = [];

    for (let i = 1; i < records.length; i++) {
      const prev = records[i - 1];
      const curr = records[i];

      if (prev.cyclePhase !== curr.cyclePhase) {
        const prevDate = new Date(prev.timestamp);
        const currDate = new Date(curr.timestamp);
        const daysBetween = Math.round(
          (currDate.getTime() - prevDate.getTime()) / (1000 * 60 * 60 * 24)
        );

        changes.push({
          fromPhase: prev.cyclePhase,
          toPhase: curr.cyclePhase,
          timestamp: curr.timestamp,
          daysBetween,
        });
      }
    }

    return changes;
  }

  /**
   * 提取大类权重
   */
  private extractAllocations(result: any): Record<string, number> {
    const allocations: Record<string, number> = {};
    if (result.assetAllocation) {
      for (const alloc of result.assetAllocation) {
        allocations[alloc.category] = alloc.weight;
      }
    }
    return allocations;
  }

  /**
   * 确保存储目录存在
   */
  private ensureStorageDir(): void {
    try {
      if (!fs.existsSync(this.storageDir)) {
        fs.mkdirSync(this.storageDir, { recursive: true });
      }
    } catch (e) {
      // 忽略错误
    }
  }

  /**
   * 持久化单条记录
   */
  private persistRecord(record: ResearchRecord): void {
    try {
      const filePath = path.join(this.storageDir, record.id + '.json');
      fs.writeFileSync(filePath, JSON.stringify(record, null, 2));
    } catch (e) {
      console.warn('保存研究记录失败:', e);
    }
  }

  /**
   * 加载所有记录
   */
  private loadRecords(): void {
    try {
      if (!fs.existsSync(this.storageDir)) return;

      const files = fs.readdirSync(this.storageDir)
        .filter(f => f.endsWith('.json'))
        .sort();

      for (const file of files) {
        try {
          const filePath = path.join(this.storageDir, file);
          const content = fs.readFileSync(filePath, 'utf-8');
          const record = JSON.parse(content);
          this.records.push(record);
        } catch (e) {
          // 忽略损坏的文件
        }
      }
    } catch (e) {
      console.warn('加载历史记录失败:', e);
    }
  }

  /**
   * 生成ID
   */
  private generateId(): string {
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
    const timeStr = now.toISOString().slice(11, 19).replace(/:/g, '');
    const random = Math.random().toString(36).slice(2, 6);
    return 'research_' + dateStr + '_' + timeStr + '_' + random;
  }

  /**
   * 清除所有历史记录
   */
  clearAll(): void {
    try {
      if (fs.existsSync(this.storageDir)) {
        const files = fs.readdirSync(this.storageDir).filter(f => f.endsWith('.json'));
        for (const file of files) {
          fs.unlinkSync(path.join(this.storageDir, file));
        }
      }
      this.records = [];
    } catch (e) {
      console.warn('清除历史记录失败:', e);
    }
  }

  /**
   * 获取记录总数
   */
  getRecordCount(): number {
    return this.records.length;
  }
}
