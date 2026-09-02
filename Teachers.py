import asyncio
import json
import time
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

DATA_FILE = "data/teachers.json"
URL = "https://tme.edupage.org/timetable/"

def _run_scrape():
    try:
        return asyncio.run(_scrape())
    except Exception as e:
        if "Executable doesn't exist" in str(e):
            print(
                "Playwright browsers are not installed.\n"
                "Run: playwright install"
            )
        raise

async def _scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(URL)

        dropdown = page.locator('div.skgd > div > div > div > span[title="Nauczyciele"]')

        await dropdown.click()
        await page.wait_for_selector(".dropDownPanel.asc-context-menu li a")

        names = [
            (await el.inner_text()).strip()
            for el in await page.query_selector_all(".dropDownPanel.asc-context-menu li a")
        ]

        results = {}
        num_value = None

        for i, name in enumerate(names):
            print(f"\rLoading teachers: {i + 1}/{len(names)}", end="", flush=True)
            await dropdown.click()
            await page.wait_for_selector(".dropDownPanel.asc-context-menu li a")
            items = await page.query_selector_all(".dropDownPanel.asc-context-menu li a")
            await items[i].click()

            caret = await page.wait_for_selector(".fa.fa-caret-down")
            await caret.click()
            menu_item = await page.wait_for_selector(".dropDownPanel.asc-context-menu.top-border li a")

            dialog_future = asyncio.get_event_loop().create_future()

            async def handle_dialog(dialog, f=dialog_future):
                if not f.done():
                    f.set_result(dialog.default_value)
                await dialog.accept()

            page.on("dialog", handle_dialog)
            await menu_item.click()

            try:
                url = await asyncio.wait_for(dialog_future, timeout=3.0)
                params = parse_qs(urlparse(url.strip()).query)
                if num_value is None:
                    num_value = params.get("num", [None])[0]
                teacher_value = params.get("teacher", [None])[0]
                if teacher_value:
                    results[teacher_value] = name
            except asyncio.TimeoutError:
                pass
            finally:
                page.remove_listener("dialog", handle_dialog)

        await browser.close()
        return {"date": time.time(), "num": num_value, "teachers": results}

async def scrape_and_save():
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(ThreadPoolExecutor(max_workers=1), _run_scrape)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

if __name__ == "__main__":
    asyncio.run(scrape_and_save())