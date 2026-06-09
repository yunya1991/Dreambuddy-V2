from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT_PATH = Path("/tmp/task5_manual_check.json")
SCREENSHOT_PATH = Path("/tmp/task5_manual_check.png")


def main() -> None:
    requests: list[str] = []
    result: dict[str, object] = {
        "page": "/feed",
        "status_badge": None,
        "timeline_items": [],
        "used_invoke_api": False,
        "used_realtime_stream": False,
        "used_localhost_5001": False,
        "send_result": "unknown",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", lambda request: requests.append(request.url))

        page.goto("http://127.0.0.1:3456/feed", wait_until="networkidle")
        page.get_by_role("button", name="Dream Agent").click()

        page.wait_for_selector("text=Dream Agent")
        page.wait_for_timeout(1500)
        result["status_badge"] = page.locator("text=实时已连接").first.text_content(timeout=3000)

        page.get_by_placeholder("输入你的问题...").fill("请返回一条测试响应")
        page.get_by_role("button", name="发送").click()
        page.wait_for_timeout(3000)

        timeline = page.locator("text=实时状态流").locator("..")
        if timeline.count() > 0:
            texts = timeline.locator("div.text-xs.text-gray-600").all_text_contents()
            result["timeline_items"] = [text.strip() for text in texts if text.strip()]

        content = page.content()
        if "后端调用失败" in content:
            result["send_result"] = "failed"
        elif "请求已完成" in content:
            result["send_result"] = "completed"

        page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        browser.close()

    result["used_invoke_api"] = any("/api/dream-agent/invoke" in url for url in requests)
    result["used_realtime_stream"] = any("/api/realtime/stream" in url for url in requests)
    result["used_localhost_5001"] = any("localhost:5001" in url for url in requests)
    result["requests"] = requests

    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
