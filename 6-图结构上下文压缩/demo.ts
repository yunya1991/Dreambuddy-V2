import { ContextCompressor } from './compressor';

const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED = '\x1b[31m';
const BOLD = '\x1b[1m';
const BLUE = '\x1b[34m';
const CYAN = '\x1b[36m';
const RESET = '\x1b[0m';

function section(title: string, emoji: string = '📦') {
  console.log(`\n${BOLD}${emoji}  ${title}${RESET}`);
  console.log('─'.repeat(70));
}

function ok(msg: string) { console.log(`  ${GREEN}✓${RESET} ${msg}`); }
function warn(msg: string) { console.log(`  ${YELLOW}⚠${RESET} ${msg}`); }
function info(msg: string) { console.log(`    → ${msg}`); }

function printBlueprint(blueprint: ReturnType<ContextCompressor['createBlueprint']>) {
  console.log(`\n${BOLD}${BLUE}🏗️ 蓝图结构${RESET}`);
  console.log(`  ID: ${blueprint.id}`);
  console.log(`  名称: ${blueprint.name}`);
  console.log(`  节点数: ${blueprint.nodes.size}`);
  console.log(`  边数: ${blueprint.edges.length}`);
  
  console.log(`\n  ${BOLD}节点${RESET}:`);
  blueprint.nodes.forEach((node, id) => {
    console.log(`    ${node.type === 'module' ? '📦' : '⚙️'} ${id}: ${node.name} (${node.description})`);
  });

  console.log(`\n  ${BOLD}数据流向${RESET}:`);
  blueprint.edges.forEach(edge => {
    console.log(`    ${edge.source} → ${edge.target} [${edge.dataFlow.type}]`);
  });
}

function printArchitecture(arch: ReturnType<ContextCompressor['expandToArchitecture']>) {
  console.log(`\n${BOLD}${CYAN}🔀 架构图(DAG)${RESET}`);
  console.log(`  ID: ${arch.id}`);
  console.log(`  入口: ${arch.entryPoint}`);
  console.log(`  节点数: ${arch.nodes.size}`);
  console.log(`  边数: ${arch.edges.length}`);
  
  console.log(`\n  ${BOLD}步骤节点${RESET}:`);
  arch.nodes.forEach((node, id) => {
    const requires = node.requires?.join(', ') || '无';
    const branches = node.branches?.map(b => `[${b.condition}]→${b.target}`).join(' ') || '';
    console.log(`    📋 ${id}: ${node.name} | 依赖: ${requires} ${branches}`);
  });
}

function printChronicle(chronicle: ReturnType<ContextCompressor['expandToChronicle']>, title: string = '时间线') {
  console.log(`\n${BOLD}${YELLOW}⏱️ ${title}${RESET}`);
  console.log(`  ID: ${chronicle.id}`);
  console.log(`  执行ID: ${chronicle.executionId}`);
  console.log(`  节点数: ${chronicle.nodes.size}`);
  console.log(`  边数: ${chronicle.edges.length}`);
  console.log(`  耗时: ${chronicle.completedAt ? chronicle.completedAt - chronicle.startedAt : '进行中'}ms`);
  
  console.log(`\n  ${BOLD}执行详情${RESET}:`);
  const nodesArray = Array.from(chronicle.nodes.values()).sort((a, b) => a.startTime - b.startTime);
  nodesArray.forEach(node => {
    const status = node.metadata.status === 'completed' ? GREEN + '✓' + RESET : 
                   node.metadata.status === 'compressed' ? YELLOW + '◉' + RESET : '◯';
    console.log(`    ${status} ${node.architectureNodeId}: ${node.metadata.latencyMs}ms | ${node.metadata.tokenCost.toFixed(0)} tokens`);
  });
}

function printCompressionResult(result: ReturnType<ContextCompressor['compress']>) {
  console.log(`\n${BOLD}${GREEN}📊 压缩结果${RESET}`);
  console.log(`  压缩率: ${(result.compressionRatio * 100).toFixed(1)}%`);
  console.log(`  保留上下文: ${result.retainedContext.toFixed(1)}%`);
  
  console.log(`\n  ${BOLD}丢弃的详情${RESET}:`);
  result.discardedDetails.forEach(item => {
    console.log(`    ${YELLOW}${item.nodeId}: ${item.reason}${RESET}`);
  });
  
  console.log(`\n  ${BOLD}压缩后的架构图${RESET}: ${result.compressedArchitecture.nodes.size} 个节点`);
  console.log(`  ${BOLD}压缩后的时间线${RESET}: ${result.compressedChronicle.nodes.size} 个节点`);
}

async function main() {
  console.log(`\n${BOLD}════════════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}  图结构上下文压缩模块 - 演示${RESET}`);
  console.log(`${BOLD}  B→A→C 正向展开 + C→A→B 回溯压缩${RESET}`);
  console.log(`${BOLD}════════════════════════════════════════════════════════${RESET}`);

  const compressor = new ContextCompressor();

  section('步骤1: 创建蓝图(Blueprint) - 顶层架构', '🏗️');
  const blueprint = compressor.createBlueprint('量化分析系统');
  printBlueprint(blueprint);
  ok('蓝图创建完成');

  section('步骤2: B→A 展开为架构图(Architecture) - DAG依赖', '🔀');
  const arch = compressor.expandToArchitecture(blueprint.id);
  printArchitecture(arch);
  ok('架构图展开完成');

  section('步骤3: A→C 展开为时间线(Chronicle) - 执行记录', '⏱️');
  const chronicle = compressor.expandToChronicle(arch.id, `exec_${Date.now()}`);
  printChronicle(chronicle);
  ok('时间线展开完成');

  section('步骤4: C→A→B 回溯压缩', '🗜️');
  const compressionResult = compressor.compress(chronicle.id, 0.5);
  printCompressionResult(compressionResult);
  ok('压缩完成');

  section('步骤5: 压缩效果对比', '📈');
  console.log(`\n${BOLD}原始时间线${RESET}:`);
  printChronicle(chronicle);
  
  console.log(`\n${BOLD}压缩后时间线${RESET}:`);
  printChronicle(compressionResult.compressedChronicle, '压缩后时间线');

  section('步骤6: 多轮压缩演示', '🔄');
  const originalSize = JSON.stringify(chronicle).length;
  const ratios = [0.3, 0.5, 0.7];
  
  console.log(`\n${BOLD}不同压缩比下的效果${RESET}:`);
  console.log(`  原始大小: ${originalSize} bytes`);
  
  ratios.forEach(ratio => {
    const result = compressor.compress(chronicle.id, ratio);
    const compressedSize = JSON.stringify(result.compressedChronicle).length;
    console.log(`\n  目标压缩比: ${ratio * 100}%`);
    console.log(`    实际压缩后: ${compressedSize} bytes (${(compressedSize / originalSize * 100).toFixed(1)}%)`);
    console.log(`    保留上下文: ${result.retainedContext.toFixed(1)}%`);
    console.log(`    丢弃详情: ${result.discardedDetails.length} 项`);
  });

  section('步骤7: 正向循环演示 - 多次展开→压缩', '🔁');
  let currentBlueprint = blueprint;
  for (let i = 0; i < 3; i++) {
    console.log(`\n  ${BOLD}第 ${i + 1} 轮循环${RESET}:`);
    
    const newArch = compressor.expandToArchitecture(currentBlueprint.id);
    const newChronicle = compressor.expandToChronicle(newArch.id, `exec_round_${i}_${Date.now()}`);
    const compressResult = compressor.compress(newChronicle.id, 0.4);
    
    console.log(`    展开架构节点: ${newArch.nodes.size}`);
    console.log(`    展开时间线节点: ${newChronicle.nodes.size}`);
    console.log(`    压缩后节点: ${compressResult.compressedArchitecture.nodes.size}`);
    console.log(`    压缩率: ${(compressResult.compressionRatio * 100).toFixed(1)}%`);
    
    currentBlueprint = compressResult.blueprint;
  }
  ok('3轮正向循环完成');

  console.log(`\n${BOLD}════════════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}  ${GREEN}演示完成！${RESET}`);
  console.log(`${BOLD}  核心价值：用图结构替代文本压缩${RESET}`);
  console.log(`${BOLD}  上下文关系通过节点和边保留，而非文字描述${RESET}`);
  console.log(`${BOLD}════════════════════════════════════════════════════════${RESET}`);
}

main().catch(err => {
  console.error(`${RED}演示失败: ${err.message}${RESET}`);
  process.exit(1);
});
