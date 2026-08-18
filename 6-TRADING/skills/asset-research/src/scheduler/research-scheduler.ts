/**
 * 定时任务调度器
 * 定期自动执行资产调研
 */

import {
  V1MerrillClockEngine,
  V2MultiFactorEngine,
  V3ScenarioSimEngine,
  HistoryManager,
  AlertManager,
  ResearchResult,
  ScheduleConfig,
} from '../types';

export interface ScheduleJob {
  id: string;
  name: string;
  cronExpression: string;
  enabled: boolean;
  lastRun?: string;
  nextRun?: string;
  runCount: number;
  successCount: number;
}

export interface SchedulerOptions {
  storageDir?: string;
  onJobComplete?: (job: ScheduleJob, result: ResearchResult) => void;
  onJobError?: (job: ScheduleJob, error: Error) => void;
}

/**
 * 定时任务调度器
 */
export class ResearchScheduler {
  private jobs: Map<string, ScheduleJob> = new Map();
  private timers: Map<string, NodeJS.Timeout> = new Map();
  private orchestrator: AssetResearchOrchestratorInternal;
  private historyManager: HistoryManager;
  private alertManager: AlertManager | null = null;
  private options: SchedulerOptions;
  private isRunning: boolean = false;

  constructor(
    orchestrator: AssetResearchOrchestratorInternal,
    historyManager: HistoryManager,
    options?: SchedulerOptions
  ) {
    this.orchestrator = orchestrator;
    this.historyManager = historyManager;
    this.options = options || {};

    this.loadJobs();
  }

  /**
   * 设置告警管理器
   */
  setAlertManager(manager: AlertManager): void {
    this.alertManager = manager;
    this.alertManager.setHistoryManager(this.historyManager);
  }

  /**
   * 添加定时任务
   */
  addJob(config: ScheduleConfig): ScheduleJob {
    const job: ScheduleJob = {
      id: config.id || `job_${Date.now()}`,
      name: config.name,
      cronExpression: config.cronExpression,
      enabled: config.enabled ?? true,
      runCount: 0,
      successCount: 0,
    };

    this.jobs.set(job.id, job);
    this.saveJobs();

    if (job.enabled) {
      this.startJob(job);
    }

    console.log(`[Scheduler] 添加任务: ${job.name} (${job.cronExpression})`);
    return job;
  }

  /**
   * 移除定时任务
   */
  removeJob(jobId: string): boolean {
    const job = this.jobs.get(jobId);
    if (!job) return false;

    this.stopJob(jobId);
    this.jobs.delete(jobId);
    this.saveJobs();

    console.log(`[Scheduler] 移除任务: ${job.name}`);
    return true;
  }

  /**
   * 启用/禁用任务
   */
  setJobEnabled(jobId: string, enabled: boolean): boolean {
    const job = this.jobs.get(jobId);
    if (!job) return false;

    job.enabled = enabled;
    this.saveJobs();

    if (enabled) {
      this.startJob(job);
    } else {
      this.stopJob(jobId);
    }

    console.log(`[Scheduler] 任务 ${job.name} ${enabled ? '启用' : '禁用'}`);
    return true;
  }

  /**
   * 获取所有任务
   */
  getJobs(): ScheduleJob[] {
    return Array.from(this.jobs.values());
  }

  /**
   * 获取指定任务
   */
  getJob(jobId: string): ScheduleJob | undefined {
    return this.jobs.get(jobId);
  }

  /**
   * 手动触发任务
   */
  async triggerJob(jobId: string): Promise<ResearchResult | null> {
    const job = this.jobs.get(jobId);
    if (!job) {
      throw new Error(`任务不存在: ${jobId}`);
    }

    console.log(`[Scheduler] 手动触发任务: ${job.name}`);
    return this.runJob(job);
  }

  /**
   * 启动调度器
   */
  start(): void {
    if (this.isRunning) {
      console.log('[Scheduler] 调度器已在运行');
      return;
    }

    this.isRunning = true;
    console.log('[Scheduler] 调度器已启动');

    for (const job of this.jobs.values()) {
      if (job.enabled) {
        this.startJob(job);
      }
    }
  }

  /**
   * 停止调度器
   */
  stop(): void {
    if (!this.isRunning) {
      console.log('[Scheduler] 调度器已停止');
      return;
    }

    this.isRunning = false;

    for (const [jobId, timer] of this.timers) {
      clearTimeout(timer);
    }
    this.timers.clear();

    console.log('[Scheduler] 调度器已停止');
  }

  /**
   * 启动单个任务
   */
  private startJob(job: ScheduleJob): void {
    // 先停止已存在的定时器
    this.stopJob(job.id);

    // 计算下次执行时间
    const nextRun = this.calculateNextRun(job.cronExpression);
    job.nextRun = nextRun?.toISOString();

    // 设置定时器
    if (nextRun) {
      const delay = nextRun.getTime() - Date.now();
      const timer = setTimeout(() => {
        this.runJob(job).catch(err => {
          console.error(`[Scheduler] 任务执行失败: ${job.name}`, err);
        });
      }, Math.max(0, delay));

      this.timers.set(job.id, timer);
      console.log(`[Scheduler] 任务 ${job.name} 计划于 ${nextRun.toLocaleString('zh-CN')} 执行`);
    }
  }

  /**
   * 停止单个任务
   */
  private stopJob(jobId: string): void {
    const timer = this.timers.get(jobId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(jobId);
    }
  }

  /**
   * 执行任务
   */
  private async runJob(job: ScheduleJob): Promise<ResearchResult | null> {
    job.lastRun = new Date().toISOString();
    job.runCount++;

    try {
      console.log(`[Scheduler] 执行任务: ${job.name}`);

      // 执行调研
      const result = await this.orchestrator.runMultiVersion();
      const latestResult = result.results[0];  // 使用最高置信度的结果

      // 保存到历史
      this.historyManager.addRecord(latestResult);

      // 检查并发送告警
      if (this.alertManager) {
        await this.alertManager.checkAndAlertCycleChange(latestResult);
      }

      job.successCount++;
      this.saveJobs();

      // 计算下次执行时间
      const nextRun = this.calculateNextRun(job.cronExpression);
      job.nextRun = nextRun?.toISOString();

      // 设置下次定时器
      if (job.enabled && nextRun) {
        const delay = nextRun.getTime() - Date.now();
        const timer = setTimeout(() => {
          this.runJob(job).catch(err => {
            console.error(`[Scheduler] 任务执行失败: ${job.name}`, err);
          });
        }, Math.max(0, delay));

        this.timers.set(job.id, timer);
      }

      // 回调
      this.options.onJobComplete?.(job, latestResult);

      console.log(`[Scheduler] 任务完成: ${job.name}，下次执行: ${job.nextRun}`);
      return latestResult;

    } catch (error) {
      console.error(`[Scheduler] 任务执行错误: ${job.name}`, error);
      this.options.onJobError?.(job, error as Error);

      // 仍然尝试设置下次执行
      const nextRun = this.calculateNextRun(job.cronExpression);
      job.nextRun = nextRun?.toISOString();
      this.saveJobs();

      return null;
    }
  }

  /**
   * 计算下次执行时间（简化版Cron解析）
   */
  private calculateNextRun(cronExpression: string): Date | null {
    // 简化实现：支持基本的时间间隔
    // 格式: "0 9 * * *" = 每天9点
    // 格式: "0 */6 * * *" = 每6小时
    // 格式: "*/30 * * * *" = 每30分钟

    const parts = cronExpression.split(' ');
    if (parts.length < 5) {
      // 默认：每天早上9点
      return this.getNextDaily9AM();
    }

    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

    const now = new Date();

    // 每天早上9点执行
    if (hour === '9' && minute === '0' && dayOfMonth === '*' && month === '*') {
      return this.getNextDaily9AM();
    }

    // 每小时执行
    if (minute === '0' && hour === '*') {
      const next = new Date(now);
      next.setHours(next.getHours() + 1, 0, 0, 0);
      return next;
    }

    // 每30分钟
    if (minute === '*/30') {
      const next = new Date(now);
      if (next.getMinutes() < 30) {
        next.setMinutes(30, 0, 0);
      } else {
        next.setHours(next.getHours() + 1, 0, 0, 0);
      }
      return next;
    }

    // 每6小时
    if (minute === '0' && hour === '*/6') {
      const next = new Date(now);
      const nextHour = Math.ceil(next.getHours() / 6) * 6;
      next.setHours(nextHour, 0, 0, 0);
      if (next <= now) {
        next.setHours(next.getHours() + 6);
      }
      return next;
    }

    // 默认：每天早上9点
    return this.getNextDaily9AM();
  }

  /**
   * 获取下一个早上9点
   */
  private getNextDaily9AM(): Date {
    const next = new Date();
    next.setHours(9, 0, 0, 0);

    if (next <= new Date()) {
      next.setDate(next.getDate() + 1);
    }

    return next;
  }

  /**
   * 保存任务配置
   */
  private saveJobs(): void {
    try {
      const jobs = Array.from(this.jobs.values());
      const { writeFileSync, mkdirSync, existsSync } = require('fs');
      const path = require('path');

      const dir = this.options.storageDir || path.join(process.cwd(), '.research-scheduler');
      if (!existsSync(dir)) {
        mkdirSync(dir, { recursive: true });
      }

      const file = path.join(dir, 'jobs.json');
      writeFileSync(file, JSON.stringify(jobs, null, 2));

    } catch (error) {
      console.error('[Scheduler] 保存任务配置失败:', error);
    }
  }

  /**
   * 加载任务配置
   */
  private loadJobs(): void {
    try {
      const { readFileSync, existsSync } = require('fs');
      const path = require('path');

      const dir = this.options.storageDir || path.join(process.cwd(), '.research-scheduler');
      const file = path.join(dir, 'jobs.json');

      if (existsSync(file)) {
        const data = readFileSync(file, 'utf-8');
        const jobs: ScheduleJob[] = JSON.parse(data);

        for (const job of jobs) {
          this.jobs.set(job.id, job);
        }

        console.log(`[Scheduler] 加载了 ${jobs.length} 个任务`);
      }

    } catch (error) {
      console.error('[Scheduler] 加载任务配置失败:', error);
    }
  }
}

/**
 * 内部编排器接口（简化版）
 */
interface AssetResearchOrchestratorInternal {
  runMultiVersion(): Promise<{
    results: ResearchResult[];
    bestVersion?: string;
    timestamp: string;
  }>;
}
