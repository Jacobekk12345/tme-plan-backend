from playwright.async_api import async_playwright
import asyncio
import time
import re
import unicodedata
import os
import dotenv
import shutil

dotenv.load_dotenv()

DEBUG = os.getenv("DEBUG") == "TRUE"


def reset_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)

reset_dir("data/teachers")
reset_dir("data/classes")

from bs4 import BeautifulSoup
import json

with open("data/classes.json") as f:
    CLASSES = json.load(f)
    NUM = CLASSES.get("num")

with open("data/teachers.json", encoding='utf-8') as f:
    TEACHERS = json.load(f)

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

def normalize(name):
    normalized = name.replace("ł", "l")
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
    def __init__(self):
        self.__groups = []
        self._playwright = None
        self._browser = None
        self._page = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=not DEBUG)
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
        url = f"https://tme.edupage.org/timetable/view.php?num={NUM}&class={classId}"
        html = await self.__navigate_and_get_svg(url)
        lessons = self.__parse_svg(html)
        return {
            "times": TIMES,
            "groups": self.getGroups(),
            "lessons": self.__sort_lessons_by_day(lessons),
            "date": time.time()
        }

    async def __fetchTeacher(self, teacherId):
        url = f"https://tme.edupage.org/timetable/view.php?num={NUM}&teacher={teacherId}"
        html = await self.__navigate_and_get_svg(url)
        lessons = self.__parse_svg(html, True)
        return {
            "times": TIMES,
            "groups": self.getGroups(),
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
                sorted(slot, key=lambda lesson: lesson.get("group", ""))
                for slot in sorted_lessons[day]
            ]

        return sorted_by_group

    def __parse_svg(self, html, teacher = False):
        soup = BeautifulSoup(f"<svg>{html}</svg>", "html.parser")
        return [
            self.__parse_lesson(title, title.parent.find_previous_sibling("text", attrs={"dominant-baseline": "central"}), teacher)
            for title in soup.find_all("title")
        ]

async def updateTimetables(tt):
    length = len(CLASSES.get("classes").items())
    for i, (classId, name) in enumerate(CLASSES.get("classes").items()):
        print(f"\rLoading classes: {i + 1}/{length}", end="", flush=True)
        safe_name = re.sub(r'[<>:"/\\|?*]', '-', name).split(" (")[0].lower()
        data = await tt.getTimeTable(classId)
        with open(f"data/classes/{safe_name}.json", "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    print()

async def updateTeacherTimetables(tt):
    length = len(TEACHERS.get("teachers").items())
    for i, (teacherId, name) in enumerate(TEACHERS.get("teachers").items()):
        print(f"\rLoading teachers: {i + 1}/{length}", end="", flush=True)
        safe_name = normalize(name)
        data = await tt.getTeacherTimeTable(teacherId)
        with open(f"data/teachers/{safe_name}.json", "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    print()

async def updateAll():
    async with TimeTable() as tt:
        await updateTimetables(tt)
        await updateTeacherTimetables(tt)

if __name__ == '__main__':
    asyncio.run(updateAll())