"""
Substitutions.py

Scrapes substitution ("zastepstwa") data from the EduPage substitution
calendar and writes one JSON file per day into `data/subs/`.

The page renders its content with JavaScript (the raw HTML `requests` gets
back has no `data-date` / `.cell` content), so this uses Playwright to load
a real (headless) browser, wait for the calendar to render, and click
through days exactly like a user would -- rather than guessing at an
internal URL/query-param scheme.

Install once:
    pip install playwright
    playwright install chromium

Usage (standalone):
    python Substitutions.py

Usage (from api.py, same pattern as Classes.scrape_and_save() /
Teachers.scrape_and_save()):
    await Substitutions.scrape_and_save()
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
import dotenv

dotenv.load_dotenv()

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

OUTPUT_DIR = "data/subs"
META_FILE = os.path.join(OUTPUT_DIR, "_meta.json")


class SubstitutionScraper:
    """Fetches and parses the EduPage substitution calendar.

    Attributes:
        base_url: URL of the substitution calendar page.
        output_dir: Directory where per-day JSON files are written.
    """

    BASE_URL = "https://tme.edupage.org/substitution/"
    OUTPUT_DIR = OUTPUT_DIR

    # CSS selector that only appears once the calendar/data has rendered.
    READY_SELECTOR = "[data-date]"

    def __init__(
        self,
        base_url: str = BASE_URL,
        output_dir: str = OUTPUT_DIR,
        headless: bool = os.getenv("DEBUG") == "1",
        timeout_ms: int = 15_000,    
    ) -> None:
        self.base_url = base_url
        self.output_dir = output_dir
        self.headless = headless
        self.timeout_ms = timeout_ms

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def run(self, days: int = 7) -> None:
        """Fetch `days` consecutive (non-weekend) days starting from the
        currently selected day and write one JSON file per day.

        Args:
            days: total number of days to fetch (the initially selected
                day plus `days - 1` more days by clicking "next").
        """
        self._reset_output_dir()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            page = browser.new_page()
            page.goto(self.base_url, timeout=self.timeout_ms)
            self._wait_ready(page)

            for i in range(days):
                print(f"\rScraping substitutions: day {i + 1}/{days}", end="", flush=True)

                soup = BeautifulSoup(page.content(), "html.parser")

                date = self._get_selected_date(soup)
                data = self._parse_day(soup, date)
                if not self._is_weekend(page):
                    self._write(date, data)

                if not self._go_to_next_day(page):
                    break

            print()
            browser.close()

    # ------------------------------------------------------------------ #
    # browser interaction
    # ------------------------------------------------------------------ #

    def _wait_ready(self, page: Page) -> None:
        page.wait_for_selector(self.READY_SELECTOR, timeout=self.timeout_ms)

    def _is_weekend(self, page: Page) -> bool:
        """True if the currently selected calendar cell is a weekend."""
        selected = page.query_selector(".cell.selected")
        if selected is None:
            return False
        class_list = (selected.get_attribute("class") or "").split()
        return "weekend" in class_list

    def _go_to_next_day(self, page: Page) -> bool:
        """Clicks the next non-weekend `.cell` after `.cell.selected`.
        Returns False if there isn't one (e.g. end of the loaded range)."""
        next_cell = page.query_selector(
            ".cell.selected ~ .cell:not(.weekend)"
        )
        if next_cell is None:
            return False

        current_date = page.eval_on_selector(
            "[data-date]", "el => el.getAttribute('data-date')"
        )

        next_cell.click()

        # Wait until the rendered data-date actually changes, rather than
        # a fixed sleep -- more reliable against network/render jitter.
        page.wait_for_function(
            """(prevDate) => {
                const el = document.querySelector('[data-date]');
                return el && el.getAttribute('data-date') !== prevDate;
            }""",
            arg=current_date,
            timeout=self.timeout_ms,
        )
        return True

    # ------------------------------------------------------------------ #
    # parsing
    # ------------------------------------------------------------------ #

    def _get_selected_date(self, soup: BeautifulSoup) -> str:
        """Returns the machine-readable date (e.g. '2026-06-25') from the
        `data-date` attribute -- NOT the human-readable cell text (which
        looks like 'Ni\\n06.09.' and isn't a valid/clean filename)."""
        subs_list = soup.find(attrs={"data-date": True})
        if subs_list is None:
            raise ValueError("No element with a data-date attribute found on the page.")
        return subs_list["data-date"].strip()

    def _parse_day(self, soup: BeautifulSoup, date: str) -> dict:
        data: dict = {}

        subs_list = soup.find("div", attrs={"data-date": date})
        if subs_list is None:
            return data

        for section in subs_list.find_all("div", class_="section"):
            header = section.select_one(".header > span")
            if header is None:
                print("WARNING: section with no '.header > span', skipping. HTML was:")
                print(section.prettify())
                continue

            class_name = header.text.strip()
            data.setdefault(class_name, {})

            for row in section.find_all("div", class_="row"):
                parsed = self._parse_row(row)
                if parsed is None:
                    continue
                lesson_nrs, entry = parsed
                # A single row can cover a range of hours (e.g. "5. - 7."
                # on the site). Give each hour in the range its own entry
                # (with the same substitution details) instead of a single
                # combined key.
                for lesson_nr in lesson_nrs:
                    data[class_name][lesson_nr] = dict(entry)

        return data

    @staticmethod
    def _expand_lesson_range(raw_period: str) -> list[str]:
        """Turns a period string like '(5.)' or '(5. - 7.)' into a list of
        individual lesson-number strings, e.g. ['5'] or ['5', '6', '7'].

        Falls back to returning the cleaned string as a single-item list
        if it doesn't look like a simple numeric (range) value.
        """
        cleaned = (
            raw_period.replace("(", "")
            .replace(")", "")
            .replace(".", "")
            .strip()
        )
        # Normalize possible dash variants (-, en dash, em dash) to "-".
        normalized = cleaned.replace("–", "-").replace("—", "-")

        if "-" in normalized:
            start_str, end_str = (p.strip() for p in normalized.split("-", 1))
            if start_str.isdigit() and end_str.isdigit():
                start, end = int(start_str), int(end_str)
                if start <= end:
                    return [str(n) for n in range(start, end + 1)]
            # Not a clean numeric range -- fall back to the raw cleaned text.
            return [normalized]

        return [cleaned]

    def _parse_row(self, row) -> tuple[list[str], dict] | None:
        info = row.select_one(".info > span")
        period = row.select_one(".period > span")

        if info is None or period is None:
            print("WARNING: row missing '.info > span' or '.period > span', skipping. HTML was:")
            print(row.prettify())
            return None

        for old in info.find_all("s"):
            old.extract()

        sub_text = info.get_text(" ", strip=True).replace(", (*)", "")
        is_cancelled = "Anulowano" in sub_text

        lesson_nrs = self._expand_lesson_range(period.text)

        entry = {
            "isCancelled": is_cancelled,
            "teacher": None,
            "classroom": None,
            "subject": None,
            "group": None,
        }

        if is_cancelled or "Zastępstwa" not in sub_text:
            return lesson_nrs, entry

        sub_first, sub_second = sub_text.split(" - Zastępstwa", 1)

        if "Zmień salę lekcyjną" in sub_second:
            sub_second, sub_third = sub_second.split(", Zmień salę lekcyjną", 1)
            if "➔" in sub_third:
                entry["classroom"] = (
                    sub_third.split("➔")[-1].replace(", (*)", "").strip()
                )

        first_parts = sub_first.split(",")
        if len(first_parts) > 1 and ":" in first_parts[1]:
            entry["group"] = first_parts[1].split(":")[0].strip()

        if "➔" in sub_first:
            entry["subject"] = sub_first.split("➔")[-1].strip()

        if "➔" in sub_second:
            entry["teacher"] = sub_second.split("➔")[-1].strip()

        return lesson_nrs, entry

    # ------------------------------------------------------------------ #
    # output
    # ------------------------------------------------------------------ #

    def _reset_output_dir(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        for f in glob.glob(os.path.join(self.output_dir, "*")):
            if os.path.abspath(f) == os.path.abspath(META_FILE):
                continue
            os.remove(f)

    def _write(self, date: str, data: dict) -> None:
        safe_date = "".join(c for c in date if c not in '\\/:*?"<>|').strip()
        path = os.path.join(self.output_dir, f"{safe_date}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


# ---------------------------------------------------------------------- #
# api.py integration (same pattern as Classes.scrape_and_save() /
# Teachers.scrape_and_save()): a sync Playwright scrape run off the event
# loop in a worker thread, with a small JSON "date" marker api.py can use
# to decide whether the cached data is stale.
# ---------------------------------------------------------------------- #

def _run_scrape(days: int) -> None:
    SubstitutionScraper().run(days=days)


async def scrape_and_save(days: int = 7) -> dict:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(ThreadPoolExecutor(max_workers=1), _run_scrape, days)

    meta = {"date": time.time()}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


if __name__ == "__main__":
    asyncio.run(scrape_and_save())