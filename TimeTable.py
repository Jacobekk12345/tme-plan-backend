from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import asyncio
import json
import os
import re
import shutil
import sys
import time
import unicodedata

import dotenv

dotenv.load_dotenv()

CLASSES_FILE = "data/classes.json"
TEACHERS_FILE = "data/teachers.json"
CLASSES_DIR = "data/classes"
TEACHERS_DIR = "data/teachers"

# Give up early (instead of waiting 30s per page for ~100 pages) if the site
# is clearly down.
MAX_CONSECUTIVE_FAILURES = 5

TIMES = [
    ("7:20",  "8:05"),
    ("8:15",  "9:00"),
    ("9:10",  "9:55"),
    ("10:05", "10:50"),
    ("11:00", "11:45"),
    ("11:55", "12:40"),
    ("12:50", "13:35"),
    ("14:00", "14:45"),
    ("14:55", "15:40"),
    ("15:50", "16:35"),
    ("16:45", "17:30"),
    ("17:35", "18:20"),
]

DAYS = ["Pn", "Wt", "Sr", "Czw", "Pt"]

DAY_BOUNDARIES = [858 + i * 513 for i in range(4)]
TIME_BOUNDARIES = [420 + int(i * 127.5) for i in range(12)]


def reset_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize(name):
    normalized = name.replace("ł", "l").replace("Ł", "L")  # NFKD doesn't decompose ł/Ł
    normalized = unicodedata.normalize('NFKD', normalized)
    ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-zA-Z0-9]', '', ascii_only).lower()

def get_day(x):
    x = float(x)
    for i, boundary in enumerate(DAY_BOUNDARIES):
        if x < boundary:
            return DAYS[i]
    return DAYS[-1]

def get_start_time(y):
    y = float(y)
    closest = min(range(len(TIME_BOUNDARIES)), key=lambda i: abs(TIME_BOUNDARIES[i] - y))
    return TIMES[closest][0]

def get_slot_count(height):
    return round(float(height) / 127.5)

class TimeTable:
    def __init__(self, num=None):
        self.__groups = []
        self._num = num
        self._playwright = None
        self._browser = None
        self._page = None

    async def start(self):
        if self._num is None:
            self._num = _read_json(CLASSES_FILE).get("num")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(not os.getenv("DEBUG") == "1")
        self._page = await self._browser.new_page()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def __navigate_and_get_svg(self, url):
        await self._page.goto(url)
        svg = await self._page.wait_for_selector("svg")
        return await svg.inner_html()

    async def __fetchClass(self, classId):
        self.__groups = []  # groups belong to ONE timetable, don't carry over from the previous one
        url = f"https://tme.edupage.org/timetable/view.php?num={self._num}&class={classId}"
        html = await self.__navigate_and_get_svg(url)
        lessons = self.__parse_svg(html)
        return {
            "times": TIMES,
            "groups": list(self.getGroups()),
            "lessons": self.__sort_lessons_by_day(lessons),
            "date": time.time()
        }

    async def __fetchTeacher(self, teacherId):
        self.__groups = []
        url = f"https://tme.edupage.org/timetable/view.php?num={self._num}&teacher={teacherId}"
        html = await self.__navigate_and_get_svg(url)
        lessons = self.__parse_svg(html, True)
        return {
            "times": TIMES,
            "groups": list(self.getGroups()),
            "lessons": self.__sort_lessons_by_day(lessons),
            "date": time.time()
        }

    async def getTimeTable(self, classId):
        return await self.__fetchClass(classId)

    async def getTeacherTimeTable(self, teacherId):
        return await self.__fetchTeacher(teacherId)

    async def getDay(self, classId, day):
        if day not in DAYS:
            raise ValueError(f"Invalid day: '{day}'. Valid days: {DAYS}")
        result = await self.__fetchClass(classId)
        return {
            "times": TIMES,
            "groups": self.getGroups(),
            "lessons": result["lessons"][day],
            "date": time.time()
        }

    def addGroup(self, group):
        if group not in self.__groups:
            self.__groups.append(group)

    def getGroups(self):
        return self.__groups

    def __parse_lesson(self, title_tag, short_name_tag, teacher=False):
        rect = title_tag.parent
        lines = [l.strip() for l in title_tag.text.strip().splitlines() if l.strip()]
        sname = short_name_tag.text.strip()

        lesson = {
            "subject": lines[0],
            "day": get_day(rect.get("x")),
            "start_time": get_start_time(rect.get("y")),
            "slot_count": get_slot_count(rect.get("height")),
            "subject_short": sname,
            "group": None,
            "teacher": None,
            "classroom": None,
        }

        if teacher:
            if len(lines) == 4:
                lesson["className"] = lines[1]
                lesson["group"] = lines[2]
                lesson["classroom"] = lines[3]

                if not lines[2][0].isdigit():
                    self.addGroup(lines[1])

            elif len(lines) == 3:
                lesson["className"] = lines[1]
                lesson["group"] = lines[2]

        else:
            if len(lines) == 4:
                lesson["group"] = lines[1]
                lesson["teacher"] = lines[2]
                lesson["classroom"] = lines[3]

                if not lines[1][0].isdigit():
                    self.addGroup(lines[1])

            elif len(lines) == 3:
                lesson["teacher"] = lines[1]
                lesson["classroom"] = lines[2]

            elif len(lines) == 2:
                lesson["teacher"] = lines[1]

        if lesson["classroom"]:
            lesson["classroom"] = lesson["classroom"].split(" - ")[0]

        elif lesson["group"]:   # yes its the classroom too lazy to fix
            lesson["group"] = lesson["group"].split(" - ")[0]

        return lesson

    def __sort_lessons_by_day(self, lessons):
        start_times = [t[0] for t in TIMES]
        sorted_lessons = {day: [[] for _ in TIMES] for day in DAYS}

        for lesson in lessons:
            day = lesson["day"]
            start_index = start_times.index(lesson["start_time"])

            for i in range(lesson["slot_count"]):
                slot = start_index + i
                if slot < len(TIMES):
                    lesson_copy = lesson.copy()
                    lesson_copy["start_time"] = TIMES[slot][0]
                    lesson_copy["end_time"] = TIMES[slot][1]
                    sorted_lessons[day][slot].append(lesson_copy)

        sorted_by_group = {}

        for day in sorted_lessons:
            if len(day) == 1:
                continue
            sorted_by_group[day] = [
                # "group" is None (not missing) for lessons without a group, and
                # comparing None with str raises TypeError -> use "" instead
                sorted(slot, key=lambda lesson: lesson.get("group") or "")
                for slot in sorted_lessons[day]
            ]

        return sorted_by_group

    def __parse_svg(self, html, teacher = False):
        soup = BeautifulSoup(f"<svg>{html}</svg>", "html.parser")
        return [
            self.__parse_lesson(title, title.parent.find_previous_sibling("text", attrs={"dominant-baseline": "central"}), teacher)
            for title in soup.find_all("title")
        ]


async def _fetch_all(items, fetch, filename_for, out_dir, old_dir, label):
    """Fetch every item into out_dir. One bad page doesn't sink the run: its
    previous file (if any) is carried over. Raises only if things look
    completely broken."""
    total = len(items)
    failed = []
    consecutive = 0

    for i, (item_id, name) in enumerate(items.items()):
        print(f"\rLoading {label}: {i + 1}/{total}", end="", flush=True)
        filename = filename_for(name) + ".json"
        try:
            data = await fetch(item_id)
        except Exception as e:
            failed.append(name)
            consecutive += 1
            print(f"\nFailed to load '{name}': {e!r}")
            old = os.path.join(old_dir, filename)
            if os.path.exists(old):
                shutil.copy2(old, os.path.join(out_dir, filename))  # keep last good copy
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                raise RuntimeError(f"{consecutive} {label} in a row failed -- giving up")
            continue

        consecutive = 0
        with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    print()

    if failed:
        print(f"Warning: {len(failed)}/{total} {label} failed: {', '.join(failed)}")
    if total and len(failed) == total:
        raise RuntimeError(f"All {label} failed to load")


def _class_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '-', name).split(" (")[0].lower()


def _swap_dir(tmp, final):
    if os.path.exists(final):
        shutil.rmtree(final)
    os.replace(tmp, final)


async def _update_all():
    # Read the JSONs NOW, not at import time: the class/teacher scrapers have
    # just rewritten them, and `num` (the timetable version) may have changed.
    classes = _read_json(CLASSES_FILE)
    teachers = _read_json(TEACHERS_FILE)
    num = classes.get("num")
    if not num:
        raise RuntimeError("data/classes.json has no 'num'; re-run the class scraper")

    # Build into temp folders and only swap them in once everything worked, so a
    # failed run never leaves you with empty/half-empty timetable folders.
    tmp_classes, tmp_teachers = CLASSES_DIR + ".tmp", TEACHERS_DIR + ".tmp"
    reset_dir(tmp_classes)
    reset_dir(tmp_teachers)

    try:
        async with TimeTable(num) as tt:
            await _fetch_all(classes.get("classes", {}), tt.getTimeTable,
                             _class_filename, tmp_classes, CLASSES_DIR, "classes")
            await _fetch_all(teachers.get("teachers", {}), tt.getTeacherTimeTable,
                             normalize, tmp_teachers, TEACHERS_DIR, "teachers")
    except BaseException:
        shutil.rmtree(tmp_classes, ignore_errors=True)
        shutil.rmtree(tmp_teachers, ignore_errors=True)
        raise

    _swap_dir(tmp_classes, CLASSES_DIR)
    _swap_dir(tmp_teachers, TEACHERS_DIR)


def _run_update():
    # Own event loop in a worker thread, like Classes.py / Teachers.py. On Windows
    # it must be a Proactor loop for Playwright; `fastapi dev` (uvicorn reload)
    # switches the main loop to a Selector loop, where Playwright can't start.
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_update_all())
    except Exception as e:
        if "Executable doesn't exist" in str(e):
            print("Playwright browsers are not installed.\nRun: playwright install")
        raise
    finally:
        loop.close()


async def updateAll():
    await asyncio.to_thread(_run_update)


if __name__ == '__main__':
    asyncio.run(updateAll())