#!/bin/bash
# 多场景压力测试脚本
# 测试 S 系列策略链的 LLM 动态响应、灵活意图识别、样式多样性

API="http://localhost:3000/api/chat"
SESSION="stress_test_$(date +%s)"

echo "=============================================="
echo "  S 系列策略链 - 多场景压力测试"
echo "  测试时间: $(date)"
echo "  Session: $SESSION"
echo "=============================================="

# 通用请求函数
call_api() {
  local label="$1"
  local message="$2"
  local session_id="${3:-$SESSION}"
  local thinking_mode="${4:-deep}"
  local output_file="$5"

  echo ""
  echo "--- [$label] ---"
  echo "  message: $message"
  echo "  session: $session_id"

  local start_time=$(date +%s%3N)
  local response=$(curl -s -X POST "$API" \
    -H "Content-Type: application/json" \
    -d "{
      \"message\": \"$message\",
      \"session_id\": \"$session_id\",
      \"thinking_mode\": \"$thinking_mode\"
    }" 2>&1)
  local end_time=$(date +%s%3N)
  local duration=$((end_time - start_time))

  local http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API" \
    -H "Content-Type: application/json" \
    -d "{
      \"message\": \"$message\",
      \"session_id\": \"$session_id\",
      \"thinking_mode\": \"$thinking_mode\"
    }" 2>/dev/null)

  echo "  HTTP: $http_code | 耗时: ${duration}ms"

  # 检查成功字段
  local success=$(echo "$response" | grep -o '"success":[^,}]*' | head -1)
  echo "  success: $success"

  # 检查策略链字段
  local chain_state=$(echo "$response" | grep -o '"strategyChainState":[^,}]*' | head -1)
  echo "  strategyChainState: $chain_state"

  # 检查当前步骤
  local current_step=$(echo "$response" | grep -o '"currentStep":"[^"]*"' | head -1)
  echo "  currentStep: $current_step"

  # 检查响应内容长度
  local content_len=$(echo "$response" | grep -o '"content":"[^"]*"' | head -1 | wc -c)
  echo "  content长度: ~${content_len} chars"

  # 检查是否有 LLM 样式标签
  local style_tag=$(echo "$response" | grep -oE '📊 数据驱动视角|📖 叙事解读视角|✅ 清单式视角' | head -1)
  echo "  响应样式: $style_tag"

  # 检查 intent
  local intent=$(echo "$response" | grep -o '"intent":"[^"]*"' | head -1)
  echo "  intent: $intent"

  # 检查路由链
  local routing=$(echo "$response" | grep -o '"chain":\[[^]]*\]' | head -1)
  echo "  routing.chain: $routing"

  if [ -n "$output_file" ]; then
    echo "$response" > "$output_file"
  fi

  # 提取 content 前 300 字符预览
  local preview=$(echo "$response" | grep -o '"content":"[^"]*"' | head -1 | cut -c1-300)
  if [ -n "$preview" ]; then
    echo "  内容预览: ${preview:0:200}..."
  fi
}

echo ""
echo "=============================================="
echo "【场景1】正常深度分析 - BTC 启动 S 系列"
echo "=============================================="
call_api "场景1" "我想深度分析一下 BTC 走势，制定一个交易策略" "s1_btc_001" "deep" "/tmp/scene1.json"

echo ""
echo "=============================================="
echo "【场景2】正常继续 - S1→S2"
echo "=============================================="
call_api "场景2-继续" "继续" "s1_btc_001" "deep" "/tmp/scene2.json"

echo ""
echo "=============================================="
echo "【场景3】灵活意图 - 跳过设计直接到验证"
echo "=============================================="
call_api "场景3-跳过" "跳过设计直接到验证" "s1_btc_001" "deep" "/tmp/scene3.json"

echo ""
echo "=============================================="
echo "【场景4】灵活意图 - 调整参数"
echo "=============================================="
call_api "场景4-调整" "把止损改成 1%，风险稍微提高一些" "s1_btc_001" "deep" "/tmp/scene4.json"

echo ""
echo "=============================================="
echo "【场景5】灵活意图 - 只看结论摘要"
echo "=============================================="
call_api "场景5-摘要" "只看当前阶段的结论摘要" "s1_btc_001" "deep" "/tmp/scene5.json"

echo ""
echo "=============================================="
echo "【场景6】灵活意图 - 详细解释"
echo "=============================================="
call_api "场景6-解释" "详细解释一下当前策略的设计逻辑" "s1_btc_001" "deep" "/tmp/scene6.json"

echo ""
echo "=============================================="
echo "【场景7】灵活意图 - 直接落地执行"
echo "=============================================="
call_api "场景7-落地" "方案已经很完善了，直接落地执行" "s1_btc_001" "deep" "/tmp/scene7.json"

echo ""
echo "=============================================="
echo "【场景8】不同标的 - 黄金(XAU)分析"
echo "=============================================="
call_api "场景8-黄金" "帮我分析一下黄金走势" "s2_gold_001" "deep" "/tmp/scene8.json"

echo ""
echo "=============================================="
echo "【场景9】不同标的 - ETH 分析"
echo "=============================================="
call_api "场景9-ETH" "分析 ETH 的交易策略" "s3_eth_001" "deep" "/tmp/scene9.json"

echo ""
echo "=============================================="
echo "【场景10】快速分析模式"
echo "=============================================="
call_api "场景10-快速" "快速分析一下 BTC 当前走势" "s4_quick_001" "quick" "/tmp/scene10.json"

echo ""
echo "=============================================="
echo "【场景11】英文输入"
echo "=============================================="
call_api "场景11-英文" "Analyze BTC and give me a trading strategy" "s5_en_001" "deep" "/tmp/scene11.json"

echo ""
echo "=============================================="
echo "【场景12】空消息/无效输入"
echo "=============================================="
call_api "场景12-空" "" "s6_empty_001" "quick" "/tmp/scene12.json"

echo ""
echo "=============================================="
echo "【场景13】样式多样性 - 同一标的重复请求（验证3种风格是否出现）"
echo "=============================================="
echo "连续3次快速分析 BTC（应看到不同样式标签）:"
for i in 1 2 3; do
  call_api "样式测试-$i" "分析 BTC 走势" "style_test_$(date +%s)" "deep"
done

echo ""
echo "=============================================="
echo "【场景14】并发压力测试 - 5个并发请求"
echo "=============================================="
echo "同时发起 5 个不同标的的深度分析..."
start_parallel=$(date +%s%3N)

# 并发执行 5 个请求
curl -s -X POST "$API" -H "Content-Type: application/json" \
  -d '{"message":"深度分析 BTC","session_id":"parallel_1","thinking_mode":"deep"}' > /tmp/para1.json &
curl -s -X POST "$API" -H "Content-Type: application/json" \
  -d '{"message":"深度分析 ETH","session_id":"parallel_2","thinking_mode":"deep"}' > /tmp/para2.json &
curl -s -X POST "$API" -H "Content-Type: application/json" \
  -d '{"message":"分析黄金","session_id":"parallel_3","thinking_mode":"deep"}' > /tmp/para3.json &
curl -s -X POST "$API" -H "Content-Type: application/json" \
  -d '{"message":"分析 SOL","session_id":"parallel_4","thinking_mode":"deep"}' > /tmp/para4.json &
curl -s -X POST "$API" -H "Content-Type: application/json" \
  -d '{"message":"分析 BNB","session_id":"parallel_5","thinking_mode":"deep"}' > /tmp/para5.json &

wait  # 等待所有后台任务完成

end_parallel=$(date +%s%3N)
parallel_duration=$((end_parallel - start_parallel))
echo "5 并发总耗时: ${parallel_duration}ms"

for i in 1 2 3 4 5; do
  local success=$(grep -o '"success":[^,}]*' /tmp/para$i.json | head -1)
  local step=$(grep -o '"currentStep":"[^"]*"' /tmp/para$i.json | head -1)
  echo "  并发$i: $success | $step"
done

echo ""
echo "=============================================="
echo "【场景15】选项数字回复（1/2/3/4）"
echo "=============================================="
call_api "选项1" "1" "s7_opt_001" "deep"
call_api "选项2" "2" "s7_opt_001" "deep"

echo ""
echo "=============================================="
echo "测试完成 - $(date)"
echo "=============================================="
