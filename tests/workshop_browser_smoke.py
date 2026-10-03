"""Exercise a running Jarvis UI, login, live frame, and bounding box overlay.

Set JARVIS_TEST_URL and JARVIS_TEST_TOKEN. The URL must already pass any edge SSO.
Run `python tests/workshop_browser_smoke.py`; screenshots are optional via
JARVIS_TEST_SCREENSHOT_DIR. No credentials are printed or saved in screenshots.
"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    url = os.environ.get("JARVIS_TEST_URL", "http://localhost:5173").rstrip("/")
    token = os.environ["JARVIS_TEST_TOKEN"]
    async with async_playwright() as p:
        args = ["--no-sandbox"]
        if mapping := os.getenv("JARVIS_TEST_HOST_MAPPING"):
            args += [f"--host-resolver-rules={mapping}", "--no-proxy-server"]
        browser = await p.chromium.launch(headless=True, args=args,
            executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = await page.goto(url + "/dashboard.html")
        assert response.status == 200, f"Dashboard HTTP {response.status}"
        login = page.get_by_label("Access token")
        if await login.is_visible():
            await login.fill(token)
            await page.get_by_role("button", name="Unlock", exact=True).click()
        live = page.get_by_role("button", name="View live camera", exact=True).first
        await live.wait_for(timeout=30000)
        await live.click()
        image = page.locator(".live-camera:not(.hidden) img")
        await page.wait_for_function("() => { const i=document.querySelector('.live-camera:not(.hidden) img'); return i && i.naturalWidth>0; }", timeout=30000)
        await page.wait_for_function("() => [...document.querySelectorAll('.live-camera:not(.hidden) p')].some(p => p.textContent.includes('detections · scan'))", timeout=180000)
        # A particular scene may have no objects; any returned boxes must render
        # inside the current view. Real camera evidence supplies detection counts.
        for box in await page.locator(".live-boxes .scan-box").all():
            assert await box.is_visible()
            geometry = await box.bounding_box()
            assert geometry["width"] > 0 and geometry["height"] > 0
        if directory := os.getenv("JARVIS_TEST_SCREENSHOT_DIR"):
            Path(directory).mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(Path(directory) / "jarvis-live-dashboard.png"), full_page=True)
        print("Dashboard/login/live camera/detection rendering: PASS")
        await page.get_by_role("button", name="Close live camera", exact=True).click()
        assert await page.locator(".live-camera:not(.hidden)").count() == 0
        await page.goto(url + "/")
        await page.get_by_role("button", name="Record command", exact=True).wait_for()
        assert not errors, errors
        print("Homepage controls and JavaScript: PASS")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
