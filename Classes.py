import asyncio
import json
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

async def scrape_timetable():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("https://tme.edupage.org/timetable/")

        dropdown = await page.wait_for_selector("div.skgd > div > div > div > span")
        await dropdown.click()

        await page.wait_for_selector(".dropDownPanel.asc-context-menu li a")
        li_anchors = await page.query_selector_all(".dropDownPanel.asc-context-menu li a")

        names = []
        for el in li_anchors:
            text = (await el.inner_text()).strip()
            names.append(text)

        results = {}

        num_value = None

        for i, name in enumerate(names):
            await dropdown.click()
            await page.wait_for_selector(".dropDownPanel.asc-context-menu li a")
            items = await page.query_selector_all(".dropDownPanel.asc-context-menu li a")
            await items[i].click()

            caret = await page.wait_for_selector(".fa.fa-caret-down")
            await caret.click()

            menu_item = await page.wait_for_selector(".dropDownPanel.asc-context-menu.top-border li a")

            dialog_future = asyncio.get_event_loop().create_future()

            async def handle_dialog(dialog):
                if not dialog_future.done():
                    dialog_future.set_result(dialog.default_value)
                await dialog.accept()

            page.on("dialog", handle_dialog)
            await menu_item.click()

            try:
                url = await asyncio.wait_for(dialog_future, timeout=3.0)
                params = parse_qs(urlparse(url.strip()).query)

                if num_value is None and "num" in params:
                    num_value = params["num"][0]

                class_value = params.get("class", [None])[0]
                if class_value is not None:
                    results[class_value] = name

            except asyncio.TimeoutError:
                pass

            finally:
                page.remove_listener("dialog", handle_dialog)

        await browser.close()

        with open("classes.json", "w", encoding="utf-8") as f:
            json.dump({"num": num_value, "classes": results}, f, ensure_ascii=False, indent=2)

asyncio.run(scrape_timetable())