import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException

import Classes, Teachers, Substitutions
import TimeTable

DATA_DIR = Path("data")
CLASSES_FILE = DATA_DIR / "classes.json"
TEACHERS_FILE = DATA_DIR / "teachers.json"
# Timestamp of the last fully successful refresh, stored inside each
# data/subs/<date>.json file under this key.
REFRESH_KEY = "refreshed"

DAILY_REFRESH_HOUR = 20              # refresh daily at 20:00 (server local time)
MAX_DATA_AGE = timedelta(days=1)     # older than this -> refresh immediately
RETRY_DELAY_S = 30 * 60              # if a refresh fails, retry every 30 min

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------- file helpers

def _load_json(path: Path | str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        # e.g. a scraper is halfway through writing the file
        logger.warning("Could not parse %s", path)
        return None


def _data_path(base: Path, name: str) -> Path:
    """Build base/<name>.json from user input, refusing anything that could
    escape `base` (e.g. className=../../secrets)."""
    if not name or "\x00" in name or name != Path(name).name:
        raise HTTPException(400, "Invalid name")
    path = (base / f"{name}.json").resolve()
    if base.resolve() not in path.parents:
        raise HTTPException(400, "Invalid name")
    return path


# ------------------------------------------------------------------ staleness

def _has_cached_data() -> bool:
    if not all(_load_json(f) is not None for f in (CLASSES_FILE, TEACHERS_FILE)):
        return False
    # the timetables live in their own folders; if either is empty, rebuild
    return all(any((DATA_DIR / d).glob("*.json")) for d in ("classes", "teachers"))


def _subs_files() -> list[Path]:
    subs_dir = DATA_DIR / "subs"
    if not subs_dir.is_dir():
        return []
    # skip files starting with "_" (e.g. _meta.json, which belongs to Substitutions)
    return [p for p in subs_dir.glob("*.json") if not p.name.startswith("_")]


def _read_last_refresh() -> datetime | None:
    """Newest refresh timestamp found in the subs files."""
    stamps = []
    for path in _subs_files():
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        try:
            stamps.append(datetime.fromisoformat(data[REFRESH_KEY]))
        except (KeyError, TypeError, ValueError):
            pass
    return max(stamps, default=None)


def _write_last_refresh() -> None:
    """Stamp every subs file with the current time (called after a successful refresh)."""
    now = datetime.now().isoformat()
    for path in _subs_files():
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        data[REFRESH_KEY] = now
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic, so API reads never see a half-written file


def _is_stale() -> bool:
    if not _has_cached_data():
        return True
    last = _read_last_refresh()
    return last is None or datetime.now() - last > MAX_DATA_AGE


# -------------------------------------------------------------------- refresh

# Each step is independent: one failing (e.g. the substitutions scraper) must
# not stop the others. Order matters only where DEPENDS says so.
STEPS = {
    "classes":       Classes.scrape_and_save,
    "teachers":      Teachers.scrape_and_save,
    "timetables":    TimeTable.updateAll,          # needs fresh classes + teachers
    "substitutions": Substitutions.scrape_and_save,
}
DEPENDS = {"timetables": ("classes", "teachers")}


async def _run_steps(pending: list[str]) -> list[str]:
    """Runs the given steps once. Returns the ones that failed or were skipped."""
    failed: list[str] = []
    for name in pending:
        if any(dep in failed for dep in DEPENDS.get(name, ())):
            logger.warning("Refresh: skipping %s (a step it depends on failed)", name)
            failed.append(name)
            continue
        logger.info("Refresh: %s...", name)
        try:
            await STEPS[name]()
        except Exception:
            logger.exception("Refresh: %s failed", name)
            failed.append(name)
    return failed


async def _refresh_until_success() -> None:
    """Runs every step; retries only the ones that failed, every RETRY_DELAY_S."""
    pending = list(STEPS)
    while True:
        pending = await _run_steps(pending)
        if not pending:
            break
        logger.info("Still failing: %s. Retrying those in %d min",
                    ", ".join(pending), RETRY_DELAY_S // 60)
        await asyncio.sleep(RETRY_DELAY_S)
    _write_last_refresh()  # only when EVERY step has succeeded
    logger.info("Refresh finished OK")


def _seconds_until_next_daily_refresh() -> float:
    now = datetime.now()
    next_run = now.replace(hour=DAILY_REFRESH_HOUR, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


async def _refresh_loop() -> None:
    """Scrapes at startup only if data is missing/stale, then once a day at
    DAILY_REFRESH_HOUR. Endpoints never scrape -- they only read the cache."""
    if _is_stale():
        logger.info("Cached data missing or older than %s, refreshing now", MAX_DATA_AGE)
        await _refresh_until_success()

    while True:
        wait_s = _seconds_until_next_daily_refresh()
        logger.info("Next scheduled refresh in %.1fh", wait_s / 3600)
        await asyncio.sleep(wait_s)
        await _refresh_until_success()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs in the background so the API starts answering immediately
    # (serving stale data / 503s) instead of blocking on a long scrape.
    task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)


# ------------------------------------------------------------------ endpoints
# Plain `def` endpoints run in FastAPI's threadpool, so the blocking file
# reads don't stall the event loop (and the refresh task).

@app.get("/")
async def root():
    return {}


@app.get("/teachers")
def get_teachers():
    data = _load_json(TEACHERS_FILE)
    if data is None:
        raise HTTPException(503, "Teacher data not available yet")
    return data


@app.get("/teacher")
def get_teacher(teacherId: str | None = None, teacherName: str | None = None):
    data = _load_json(TEACHERS_FILE)
    if data is None:
        raise HTTPException(503, "Teacher data not available yet")
    if teacherId:
        name = data["teachers"].get(teacherId)
        if not name:
            raise HTTPException(404, "Teacher not found")
        return {"num": data["num"], teacherId: name}
    if teacherName:
        match = next((k for k, v in data["teachers"].items() if v == teacherName), None)
        if not match:
            raise HTTPException(404, "Teacher not found")
        return {"teacherId": match}
    raise HTTPException(400, "Provide teacherId or teacherName")


@app.get("/classes")
def get_classes():
    data = _load_json(CLASSES_FILE)
    if data is None:
        raise HTTPException(503, "Class data not available yet")
    return data


@app.get("/class")
def get_class(classId: str | None = None, className: str | None = None):
    data = _load_json(CLASSES_FILE)
    if data is None:
        raise HTTPException(503, "Class data not available yet")
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


@app.get("/subs/{date}")
def get_subs(date: str):
    data = _load_json(_data_path(DATA_DIR / "subs", date))
    if data is None:
        raise HTTPException(404, f"No substitution data for '{date}'")
    return data


def _load_timetable(className: str | None, teacherName: str | None) -> dict:
    if className:
        base, name = DATA_DIR / "classes", className.lower()
    elif teacherName:
        # teacher files are saved under the normalized name ("Jan Kowalski" -> "jankowalski")
        base, name = DATA_DIR / "teachers", TimeTable.normalize(teacherName)
    else:
        raise HTTPException(400, "Please provide className or teacherName")

    data = _load_json(_data_path(base, name))
    if data is None:
        raise HTTPException(404, f"No timetable for '{className or teacherName}'")
    return data


@app.get("/timetable")
def get_timetable(className: str | None = None, teacherName: str | None = None):
    return _load_timetable(className, teacherName)


@app.get("/timetable/{day}")
def get_timetable_day(day: str, className: str | None = None, teacherName: str | None = None):
    data = _load_timetable(className, teacherName)

    lessons = data.get("lessons", {}).get(day)
    if lessons is None:
        raise HTTPException(404, f"No data for day '{day}'")

    return {
        "times":   data["times"],
        "groups":  data["groups"],
        "lessons": lessons,
        "date":    data["date"],
    }