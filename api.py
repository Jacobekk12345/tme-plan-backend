from fastapi import FastAPI
import TimeTable

# to run
# fastapi dev api.py

app = FastAPI()

tt = TimeTable.TimeTable("4tp")

@app.get("/")
async def root():
    return {"usage": {"timetable?className={className}": "get the timetable for a class", "timetable/{day}?className={className}": "get the timetable for one day for a class", "subs?className={}": "get the substitutions", "classes": "get all the classes"}}

@app.get("/timetable")
async def timetable(className):
    return tt.getTimeTable()

@app.get("/timetable/{day}")
async def timetableDay(day, className):
    return tt.getDay(day)

@app.get("/subs")
async def subs(className):
    return {}

@app.get("/classes")
async def classes():
    return {}
