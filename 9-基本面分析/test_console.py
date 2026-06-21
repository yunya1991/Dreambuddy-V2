from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Catch console messages
    page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
    page.on("pageerror", lambda exc: print(f"PAGE ERROR: {exc}"))

    # 新前端：Next.js on port 3000
    print("Navigating to http://127.0.0.1:3000/dashboard/fundamental/overview")
    page.goto('http://127.0.0.1:3000/dashboard/fundamental/overview', wait_until='networkidle')

    # Wait a bit just in case
    page.wait_for_timeout(2000)

    browser.close()
