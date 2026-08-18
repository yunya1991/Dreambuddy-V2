const scenarios = ["balanced", "custom-heavy", "system-heavy", "execution-heavy"];
const baseUrl = process.env.UI_MAP_BASE_URL || "http://127.0.0.1:3456";

async function main() {
  for (let round = 0; round < 10; round++) {
    for (const scenario of scenarios) {
      const response = await fetch(`${baseUrl}/ui-map?scenario=${scenario}`);
      const html = await response.text();
      if (!response.ok) throw new Error(`${scenario} failed: ${response.status}`);
      if (!html.includes("自定义策略")) throw new Error(`${scenario} missing 自定义策略`);
      if (!html.includes("系统策略")) throw new Error(`${scenario} missing 系统策略`);
      if (!html.includes("策略主线")) throw new Error(`${scenario} missing 策略主线`);
      if (!html.includes("用户上下文索引系统")) throw new Error(`${scenario} missing 用户上下文索引系统`);
      if (!html.includes("系统研究索引体系")) throw new Error(`${scenario} missing 系统研究索引体系`);
    }
  }
  console.log("ui-map pressure check ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
