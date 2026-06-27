/**
 * 增强功能测试
 * 包含回测、告警、导出、调度功能的测试
 */

import {
  V1MerrillClockEngine,
  ResearchResult,
  CyclePhase,
  HistoricalPeriod,
} from '../src/index';

// 测试辅助函数
function asyncTest(name: string, fn: () => Promise<void>): void {
  Promise.resolve()
    .then(() => fn())
    .then(() => {
      console.log('  ✅ ' + name);
    })
    .catch((err) => {
      console.error('  ❌ ' + name);
      console.error('    ', err.message);
    });
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

// ==================== 回测引擎测试 ====================

async function testBacktestEngine(): Promise<void> {
  console.log('\n--- 回测引擎测试 ---');

  await asyncTest('创建回测引擎实例', async () => {
    const { BacktestEngine } = await import('../src/index');
    const engine = new BacktestEngine({ initialCapital: 100000 });
    assert(engine !== null, '回测引擎应能正常创建');
  });

  await asyncTest('回测引擎初始化', async () => {
    const { BacktestEngine } = await import('../src/index');
    const engine = new BacktestEngine({
      initialCapital: 100000,
      commission: 0.001,
      slippage: 0.0005,
    });
    assert(engine !== null, '带配置的引擎应能正常创建');
  });
}

// ==================== 告警管理器测试 ====================

async function testAlertManager(): Promise<void> {
  console.log('\n--- 告警管理器测试 ---');

  await asyncTest('创建告警管理器', async () => {
    const { AlertManager } = await import('../src/index');
    const manager = new AlertManager({ enabled: false });
    assert(manager !== null, '告警管理器应能正常创建');
  });

  await asyncTest('创建带飞书Webhook的告警管理器', async () => {
    const { AlertManager } = await import('../src/index');
    const manager = new AlertManager({
      enabled: true,
      channels: ['lark'],
      larkWebhookUrl: 'https://open.feishu.cn/open-apis/bot/v2/hook/test',
      cooldownMinutes: 60,
    });
    assert(manager !== null, '带配置的告警管理器应能正常创建');
  });
}

// ==================== 报告导出测试 ====================

async function testReportExporter(): Promise<void> {
  console.log('\n--- 报告导出测试 ---');

  await asyncTest('导出HTML格式', async () => {
    const { ReportExporter, V1MerrillClockEngine } = await import('../src/index');

    const engine = new V1MerrillClockEngine();
    const result = await engine.run();

    const html = ReportExporter.export(result, { format: 'html' });
    assert(html.includes('<!DOCTYPE html>'), 'HTML导出应包含DOCTYPE声明');
    assert(html.includes('资产调研报告'), 'HTML应包含报告标题');
  });

  await asyncTest('导出JSON格式', async () => {
    const { ReportExporter, V1MerrillClockEngine } = await import('../src/index');

    const engine = new V1MerrillClockEngine();
    const result = await engine.run();

    const json = ReportExporter.export(result, { format: 'json' });
    const parsed = JSON.parse(json);
    assert(parsed.metadata !== undefined, 'JSON应包含metadata');
    assert(parsed.cycle !== undefined, 'JSON应包含cycle');
  });

  await asyncTest('导出CSV格式', async () => {
    const { ReportExporter, V1MerrillClockEngine } = await import('../src/index');

    const engine = new V1MerrillClockEngine();
    const result = await engine.run();

    const csv = ReportExporter.export(result, { format: 'csv' });
    assert(csv.includes('排名'), 'CSV应包含表头');
    assert(csv.includes('子类'), 'CSV应包含子类列');
  });
}

// ==================== 调度器测试 ====================

async function testScheduler(): Promise<void> {
  console.log('\n--- 调度器测试 ---');

  await asyncTest('创建调度器', async () => {
    const { ResearchScheduler, V1MerrillClockEngine, ResearchHistoryManager } = await import('../src/index');

    const orchestrator = {
      async runMultiVersion() {
        const engine = new V1MerrillClockEngine();
        return { results: [await engine.run()], timestamp: new Date().toISOString() };
      }
    };

    const historyManager = new ResearchHistoryManager();
    const scheduler = new ResearchScheduler(
      orchestrator as any,
      historyManager
    );

    assert(scheduler !== null, '调度器应能正常创建');
  });

  await asyncTest('添加定时任务', async () => {
    const { ResearchScheduler, V1MerrillClockEngine, ResearchHistoryManager } = await import('../src/index');

    const orchestrator = {
      async runMultiVersion() {
        const engine = new V1MerrillClockEngine();
        return { results: [await engine.run()], timestamp: new Date().toISOString() };
      }
    };

    const historyManager = new ResearchHistoryManager();
    const scheduler = new ResearchScheduler(
      orchestrator as any,
      historyManager
    );

    const job = scheduler.addJob({
      name: '每日调研',
      cronExpression: '0 9 * * *',
    });

    assert(job.id !== undefined, '任务应有ID');
    assert(job.name === '每日调研', '任务名称应正确');
  });
}

// ==================== 历史记录测试 ====================

async function testHistoryManager(): Promise<void> {
  console.log('\n--- 历史记录测试 ---');

  await asyncTest('创建历史管理器', async () => {
    const { ResearchHistoryManager } = await import('../src/index');
    const manager = new ResearchHistoryManager();
    assert(manager !== null, '历史管理器应能正常创建');
  });

  await asyncTest('保存研究记录', async () => {
    const { ResearchHistoryManager, V1MerrillClockEngine } = await import('../src/index');

    const manager = new ResearchHistoryManager();
    const engine = new V1MerrillClockEngine();
    const result = await engine.run();

    const id = manager.saveRecord(result);
    assert(id !== undefined, '应有记录ID');
    console.log('    保存记录ID:', id);
  });
}

// ==================== 主测试函数 ====================

async function runAllTests(): Promise<void> {
  console.log('='.repeat(60));
  console.log('资产调研引擎 - 增强功能测试');
  console.log('='.repeat(60));

  const startTime = Date.now();

  await testBacktestEngine();
  await testAlertManager();
  await testReportExporter();
  await testScheduler();
  await testHistoryManager();

  const elapsed = Date.now() - startTime;

  console.log('\n' + '='.repeat(60));
  console.log('测试完成，耗时:', elapsed + 'ms');
  console.log('='.repeat(60));
}

// 运行测试
runAllTests().catch(console.error);
