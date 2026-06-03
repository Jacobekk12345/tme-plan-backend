# for now uses strona.html instead of scraping the website every time

class IdiotException(Exception):
    pass

from bs4 import BeautifulSoup
import json

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
    def __init__(self, className):
        self.__class = className
        self.__timetable = {}
        self.__groups = []
        self.__makeTimeTable()

    def __makeTimeTable(self):
        # replace with actual timetable of self.__class
        try:
            with open("strona.html", encoding="utf-8") as f:
                html = f.read()
        except FileNotFoundError:
            raise IdiotException("Przeczytaj pierwsza linie w TimeTable.py brotato")

        self.__lessons = self.__parse_svg(html)

        self.__result = {
            "times": TIMES,
            "groups": self.getGroups(),
            "lessons": self.__sort_lessons_by_day(self.__lessons),
        }

    def getGroups(self):
        return self.__groups

    def getTimeTable(self):
        return self.__result
    
    def addGroup(self, group):
        if (group not in self.__groups):
            self.__groups.append(group)

    def getDay(self, day):
        if day not in DAYS:
            raise ValueError(f"Invalid day: '{day}'. Valid days: {DAYS}")
        
        return {
            "times": TIMES,
            "groups": self.getGroups(),
            "lessons": self.__result["lessons"][day]
        }

    def __parse_lesson(self, title_tag, short_name_tag):
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

        if len(lines) == 4:
            lesson["group"] = lines[1]
            lesson["teacher"] = lines[2]
            lesson["classroom"] = lines[3]

            if (not lines[1][0].isdigit()):
                self.addGroup(lines[1])

        elif len(lines) == 3:
            lesson["teacher"] = lines[1]
            lesson["classroom"] = lines[2]

        if lesson["classroom"]:
            lesson["classroom"] = lesson["classroom"].split(" - ")[0]

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

    def __parse_svg(self, html):
        soup = BeautifulSoup(html, "html.parser")
        return [
            self.__parse_lesson(title, title.parent.find_previous_sibling("text", attrs={"dominant-baseline": "central"}))
            for title in soup.find_all("title")
        ]

if __name__ == '__main__':
    tt = TimeTable("4tp")
    with open("testttttt.json", "w") as f:
        json.dump(tt.getTimeTable(), f, indent=4)
