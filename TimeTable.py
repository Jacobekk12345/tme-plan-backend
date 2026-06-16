import asyncio
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

DATA_DIR = "data/classes"
os.makedirs(DATA_DIR, exist_ok=True)

TIMES = [
    ("7:20",  "8:05"),  ("8:15",  "9:00"),  ("9:10",  "9:55"),
    ("10:05", "10:50"), ("11:00", "11:45"), ("11:55", "12:40"),
    ("12:50", "13:35"), ("14:00", "14:45"), ("14:55", "15:40"),
    ("15:50", "16:35"), ("16:45", "17:30"), ("17:35", "18:20"),
]
DAYS = ["Pn", "Wt", "Sr", "Czw", "Pt"]
DAY_BOUNDARIES  = [858 + i * 513 for i in range(4)]
TIME_BOUNDARIES = [420 + int(i * 127.5) for i in range(12)]

def _get_day(x):
    x = float(x)
    for i, boundary in enumerate(DAY_BOUNDARIES):
        if x < boundary:
            return DAYS[i]
    return DAYS[-1]

def _get_start_time(y):
    y = float(y)
    closest = min(range(len(TIME_BOUNDARIES)), key=lambda i: abs(TIME_BOUNDARIES[i] - y))
    return TIMES[closest][0]

def _get_slot_count(height):
    return round(float(height) / 127.5)

def _safe_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '-', name).split(" (")[0].lower()


def _run_scrape(num, class_id):
    return asyncio.run(_scrape_class(num, class_id))

async def _scrape_class(num, class_id):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(f"https://tme.edupage.org/timetable/view.php?num={num}&class={class_id}")
        svg = await page.wait_for_selector("svg")
        html = await svg.inner_html()
        await browser.close()
    return html


class TimetableParser:
    def __init__(self):
        self._groups = []

    def parse(self, html) -> list:
        soup = BeautifulSoup(f"<svg>{html}</svg>", "html.parser")
        return [
            self._parse_lesson(title, title.parent.find_previous_sibling(
                "text", attrs={"dominant-baseline": "central"}
            ))
            for title in soup.find_all("title")
        ]

    def _parse_lesson(self, title_tag, short_name_tag):
        rect = title_tag.parent
        lines = [l.strip() for l in title_tag.text.strip().splitlines() if l.strip()]

        lesson = {
            "subject":       lines[0],
            "subject_short": short_name_tag.text.strip(),
            "day":           _get_day(rect.get("x")),
            "start_time":    _get_start_time(rect.get("y")),
            "slot_count":    _get_slot_count(rect.get("height")),
            "group":         None,
            "teacher":       None,
            "classroom":     None,
        }

        if len(lines) == 4:
            lesson["group"], lesson["teacher"], lesson["classroom"] = lines[1], lines[2], lines[3]
            if not lines[1][0].isdigit():
                self._add_group(lines[1])
        elif len(lines) == 3:
            lesson["teacher"], lesson["classroom"] = lines[1], lines[2]

        if lesson["classroom"]:
            lesson["classroom"] = lesson["classroom"].split(" - ")[0]

        return lesson

    def _add_group(self, group):
        if group not in self._groups:
            self._groups.append(group)

    def get_groups(self):
        return self._groups

    def sort_by_day(self, lessons) -> dict:
        start_times = [t[0] for t in TIMES]
        sorted_lessons = {day: [[] for _ in TIMES] for day in DAYS}

        for lesson in lessons:
            day = lesson["day"]
            start_index = start_times.index(lesson["start_time"])
            for i in range(lesson["slot_count"]):
                slot = start_index + i
                if slot < len(TIMES):
                    copy = {**lesson, "start_time": TIMES[slot][0], "end_time": TIMES[slot][1]}
                    sorted_lessons[day][slot].append(copy)

        return {
            day: [sorted(slot, key=lambda l: l.get("group") or "") for slot in slots]
            for day, slots in sorted_lessons.items()
            if len(day) > 1
        }


async def fetch_timetable(num, class_id) -> dict:
    loop = asyncio.get_event_loop()
    html = await loop.run_in_executor(
        ThreadPoolExecutor(max_workers=1), _run_scrape, num, class_id
    )
    parser = TimetableParser()
    lessons = parser.parse(html)
    return {
        "times":   TIMES,
        "groups":  parser.get_groups(),
        "lessons": parser.sort_by_day(lessons),
        "date":    time.time(),
    }


async def update_all(classes_data: dict):
    num = classes_data["num"]
    classes = classes_data["classes"]
    total = len(classes)

    for i, (class_id, name) in enumerate(classes.items(), 1):
        print(f"\rUpdating timetables: {i}/{total}", end="", flush=True)
        data = await fetch_timetable(num, class_id)
        path = os.path.join(DATA_DIR, f"{_safe_filename(name)}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    print()