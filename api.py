from fastapi import FastAPI
import TimeTable
import json
import time
import re

# first run Classes.py
# then run TimeTable.py
# to run
# fastapi dev api.py

app = FastAPI()

with open("data/classes.json") as f:
    CLASSES = json.load(f)

@app.get("/")
async def root():
    return {}

@app.get("/timetable")
async def timetable(className):
    with open(f"data/classes/{className}.json") as f:
        return json.load(f)

@app.get("/timetable/{day}")
async def timetableDay(day, className):
    with open(f"data/classes/{className.lower()}.json") as f:
        data = json.load(f)

    return {
        "times": data.get("times"),
        "groups": data.get("groups"),
        "lessons": data.get("lessons").get(day),
        "date": data.get("date")
    }
    
@app.get("/subs")
async def subs(className):
    return {}

@app.get("/classes")
async def classes():
    with open("data/classes.json") as f:
        return json.load(f)
    
@app.get("/class")
async def getClass(classId = None, className = None):
    with open("data/classes.json") as f:
        data = json.load(f)

    if classId:
        return {"num": data["num"], classId: data["classes"][classId]}
    if className:
        return next(k for k, v in data["classes"].items() if v == className)