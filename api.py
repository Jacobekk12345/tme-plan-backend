import json
import time
import asyncio
from fastapi import FastAPI, HTTPException
import Classes, Teachers
import TimeTable

CLASSES_FILE = "data/classes.json"
TEACHERS_FILE = "data/teachers.json"
CACHE_TTL = 86400  # 24 hours

app = FastAPI()
_refresh_task = None


def _load_cached_classes() -> dict | None:
    try:
        with open(CLASSES_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def _load_cached_teachers() -> dict | None:
    try:
        with open(TEACHERS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


async def _refresh():
    await Classes.scrape_and_save()
    await Teachers.scrape_and_save()
    await TimeTable.updateAll()

async def load_or_refresh_classes() -> dict:
    global _refresh_task
    cached = _load_cached_classes()

    # nothing cached, user must wait
    if cached is None:
        await _refresh()
        return _load_cached_classes()
    # old data
    if time.time() - cached.get("date", 0) >= CACHE_TTL:
        if _refresh_task is None or _refresh_task.done():
            _refresh_task = asyncio.create_task(_refresh())

    return cached

async def load_or_refresh_teachers() -> dict:
    global _refresh_task
    cached = _load_cached_teachers()

    # nothing cached, user must wait
    if cached is None:
        await _refresh()
        return _load_cached_teachers()
    # old data
    if time.time() - cached.get("date", 0) >= CACHE_TTL:
        if _refresh_task is None or _refresh_task.done():
            _refresh_task = asyncio.create_task(_refresh())

    return cached

@app.get("/")
async def root():
    return {}

@app.get("/teachers")
async def get_teachers():
    data = await load_or_refresh_teachers()
    return data

@app.get("/teacher")
async def get_teacher(teacherId: str = None, teacherName: str = None):
    data = await load_or_refresh_teachers()
    if teacherId:
        name = data["teachers"].get(teacherId)
        if not name:
            raise HTTPException(404, "Teacher not found")
        return {"num": data["num"], teacherId: name}
    if teacherName:
        match = next((k for k, v in data["teacher"].items() if v == teacherName), None)
        if not match:
            raise HTTPException(404, "Teacher not found")
        return {"teacherId": match}
    raise HTTPException(400, "Provide teacherId or teacherName")


@app.get("/classes")
async def get_classes():
    data = await load_or_refresh_classes()
    return data

@app.get("/class")
async def get_class(classId: str = None, className: str = None):
    data = await load_or_refresh_classes()
    if classId:
        name = data["classes"].get(classId)
        if not name:
            raise HTTPException(404, "Class not found")
        return {"num": data["num"], classId: name}
    if className:
        match = next((k for k, v in data["classes"].items() if v == className), None)
        if not match:
            raise HTTPException(404, "Class not found")
        return {"classId": match}
    raise HTTPException(400, "Provide classId or className")

@app.get("/timetable")
async def get_timetable(className: str = None, teacherName: str = None):
    if (className):
        await load_or_refresh_classes()
        try:
            with open(f"data/classes/{className.lower()}.json") as f:
                return json.load(f)
        except FileNotFoundError:
            raise HTTPException(404, f"No timetable for '{className}'")
    elif teacherName:
        await load_or_refresh_teachers()
        try:
            with open(f"data/teachers/{teacherName.lower()}.json") as f:
                return json.load(f)
        except FileNotFoundError:
            raise HTTPException(404, f"No timetable for '{teacherName}'")
    else:
        raise HTTPException(404, f"Please provide className or teacherName")

@app.get("/timetable/{day}")
async def get_timetable_day(day: str, className: str = None, teacherName: str = None):
    if (className):
        await load_or_refresh_classes()
        try:
            with open(f"data/classes/{className.lower()}.json") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise HTTPException(404, f"No timetable for '{className}'")

        lessons = data.get("lessons", {}).get(day)
        if lessons is None:
            raise HTTPException(404, f"No data for day '{day}'")

        return {
            "times":   data["times"],
            "groups":  data["groups"],
            "lessons": lessons,
            "date":    data["date"],
        }
    elif (teacherName):
        await load_or_refresh_teachers()
        try:
            with open(f"data/teachers/{teacherName.lower()}.json") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise HTTPException(404, f"No timetable for '{teacherName}'")

        lessons = data.get("lessons", {}).get(day)
        if lessons is None:
            raise HTTPException(404, f"No data for day '{day}'")

        return {
            "times":   data["times"],
            "groups":  data["groups"],
            "lessons": lessons,
            "date":    data["date"],
        }
    else:
        raise HTTPException(404, f"Please provide className or teacherName")

@app.get("/subs")
async def subs(className: str):
    return {}