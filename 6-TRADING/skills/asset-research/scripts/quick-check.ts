/**
 * 快速调研脚本（事件驱动）
 * 用于重大数据发布、黑天鹅事件等情况下的快速周期验证
 * 只运行V1版本，快速输出结果
 */

import { V1MerrillClockEngine, MacroIndicator } from '../src';
import { StandardOutputManager } from '../src/output/standard-output';
import * as fs from 'fs';
import * as path from 'path';

const BASE_DIR = path.join(__dirname, '..');
const OUTPUT_DIR = path.join(BASE_DIR, 'output');

interface QuickCheckOptions {
  reason?: string;              // 触发原因
  customIndicators?: MacroIndicator[];  // 自定义指标
  updateLatest?: boolean;       // 是否更新latest.json
  alertOnChange?: boolean;      // 周期变化时是否告警
}

async function runQuickCheck(options: QuickCheckOptions = {}) {
  console.log('='.repeat(60));
  console.log('快速资产调研');
  console.log('执行时间:', new Date().toLocaleString('zh-CN'));
  if (options.reason) {
    console.log('触发原因:', options.reason);
  }
  console.log('='.repeat(60));
  console.log('');

  const startTime = Date.now();

  try {
    const engine = new V1MerrillClockEngine();

    console.log('运行V1美林时钟快速调研...');
    const result = await engine.run({
      customIndicators: options.customIndicators,
    });

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`✅ 快速调研完成，耗时 ${elapsed} 秒`);
    console.log('');

    // 读取上次结果（用于检测变化）
    const lastPath = path.join(OUTPUT_DIR, 'latest.json');
    const lastResult = StandardOutputManager.readFromFile(lastPath);
    const lastPhase = lastResult?.cycle.currentPhase;

    // 检查周期是否变化
    const phaseChanged = lastPhase && lastPhase !== result.cycle.currentPhase;

    if (phaseChanged) {
      console.log('⚠️  周期发生变化！');
      console.log(`   旧周期: ${lastPhase}`);
      console.log(`   新周期: ${result.cycle.currentPhase}`);
      console.log('');
    } else {
      console.log(`周期未变: ${result.cycle.currentPhase}`);
      console.log('');
    }

    // 输出核心结论
    console.log('📊 核心结论：');
    console.log(`   当前周期: ${result.cycle.currentPhase}`);
    console.log(`   置信度: ${(result.confidence * 100).toFixed(0)}%`);
    console.log(`   Top 3: ${result.topSubCategories.slice(0, 3).map(s => s.displayName).join(', ')}`);
    console.log('');

    // 保存快速调研结果
    if (!fs.existsSync(OUTPUT_DIR)) {
      fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const quickDir = path.join(OUTPUT_DIR, 'quick-checks');
    if (!fs.existsSync(quickDir)) {
      fs.mkdirSync(quickDir, { recursive: true });
    }

    // 保存快速报告
    const quickReportPath = path.join(quickDir, `${timestamp}.md`);
    fs.writeFileSync(quickReportPath, result.report);
    console.log('📄 快速报告已保存:', quickReportPath);

    // 更新latest.json（如果配置了）
    if (options.updateLatest) {
      StandardOutputManager.saveToFile(result, lastPath, { reportType: 'quick' });
      console.log('📄 latest.json 已更新');
    }

    // 周期变化告警
    if (phaseChanged && options.alertOnChange) {
      console.log('');
      console.log('🔔 周期变化告警已触发');
      // TODO: 集成告警管理器
    }

    console.log('');

    return {
      success: true,
      result,
      phaseChanged,
      previousPhase: lastPhase,
    };

  } catch (error) {
    console.error('');
    console.error('❌ 快速调研失败:', error);
    console.error('');
    return { success: false, error };
  }
}

// 命令行使用
// npx tsx quick-check.ts --reason "CPI数据发布" --update --alert
if (require.main === module) {
  const args = process.argv.slice(2);
  const options: QuickCheckOptions = {};

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--reason' && args[i + 1]) {
      options.reason = args[i + 1];
      i++;
    } else if (args[i] === '--update') {
      options.updateLatest = true;
    } else if (args[i] === '--alert') {
      options.alertOnChange = true;
    }
  }

  runQuickCheck(options)
    .then(result => {
      process.exit(result.success ? 0 : 1);
    })
    .catch(err => {
      console.error(err);
      process.exit(1);
    });
}

export { runQuickCheck };
