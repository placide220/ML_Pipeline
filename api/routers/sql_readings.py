"""CRUD + time-series endpoints backed by MySQL (power_readings + sub_meter_readings)."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from .. import config
from ..db import mysql_conn
from ..schemas import ReadingCreate, ReadingUpdate

router = APIRouter(prefix="/sql/readings", tags=["MySQL"])
R = config.READINGS_TABLE
S = config.SUB_READINGS_TABLE
SC = config.SUB_READINGS_COLUMNS
COLS = ", ".join(config.MEASURES)


def _sub_metering(cur, household_id: int, ts: datetime) -> dict:
    cur.execute(
        f"SELECT {SC['meter']} AS m, {SC['value']} AS v FROM {S} "
        f"WHERE household_id=%s AND {SC['ts']}=%s", (household_id, ts))
    out = {name: None for name in config.SUB_METER_IDS.values()}
    for row in cur.fetchall():
        name = config.SUB_METER_IDS.get(row["m"])
        if name:
            out[name] = float(row["v"]) if row["v"] is not None else None
    return out


def _fetch_one(cur, household_id: int, ts: datetime):
    cur.execute(
        f"SELECT reading_ts, household_id, {COLS} FROM {R} "
        f"WHERE household_id=%s AND reading_ts=%s", (household_id, ts))
    row = cur.fetchone()
    if row:
        row["sub_metering"] = _sub_metering(cur, household_id, ts)
    return row


def _write_sub(cur, household_id, ts, sub: dict):
    inv = {v: k for k, v in config.SUB_METER_IDS.items()}
    for name, value in sub.items():
        if value is None or name not in inv:
            continue
        cur.execute(
            f"INSERT INTO {S} (household_id, {SC['ts']}, {SC['meter']}, {SC['value']}) "
            f"VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE {SC['value']}=VALUES({SC['value']})",
            (household_id, ts, inv[name], value))


# ---- time-series endpoints (declared BEFORE /{ts} so they are not captured by it) ----
@router.get("/latest", summary="Latest non-missing record")
def latest(household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT reading_ts FROM {R} WHERE household_id=%s AND is_missing=0 "
            f"ORDER BY reading_ts DESC LIMIT 1", (household_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "No readings found")
        return _fetch_one(cur, household_id, row["reading_ts"])


@router.get("/range", summary="Records between start (inclusive) and end (exclusive)")
def by_range(
    start: datetime,
    end: datetime,
    household_id: int = config.DEFAULT_HOUSEHOLD_ID,
    resolution: Literal["minute", "hour"] = "minute",
    include_missing: bool = False,
    limit: int = Query(10000, ge=1, le=100000),
):
    if end <= start:
        raise HTTPException(422, "end must be after start")
    miss = "" if include_missing else "AND is_missing=0"
    with mysql_conn() as conn, conn.cursor() as cur:
        if resolution == "minute":
            cur.execute(
                f"SELECT reading_ts, {COLS} FROM {R} WHERE household_id=%s "
                f"AND reading_ts>=%s AND reading_ts<%s {miss} ORDER BY reading_ts LIMIT %s",
                (household_id, start, end, limit))
        else:
            avgs = ", ".join(f"AVG({c}) AS {c}" for c in config.MEASURES)
            cur.execute(
                f"SELECT DATE_FORMAT(reading_ts,'%%Y-%%m-%%d %%H:00:00') AS reading_ts, {avgs} "
                f"FROM {R} WHERE household_id=%s AND reading_ts>=%s AND reading_ts<%s {miss} "
                f"GROUP BY 1 ORDER BY 1 LIMIT %s", (household_id, start, end, limit))
        rows = cur.fetchall()
    return {"count": len(rows), "resolution": resolution, "data": rows}


# ---- CRUD ----
@router.post("", status_code=201, summary="Create a reading")
def create(body: ReadingCreate):
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {R} WHERE household_id=%s AND reading_ts=%s",
                    (body.household_id, body.reading_ts))
        existing = cur.fetchone()
        if existing:
            raise HTTPException(409, "A reading already exists for this timestamp")
        cur.execute(
            f"INSERT INTO {R} (household_id, reading_ts, {COLS}) VALUES (%s,%s,%s,%s,%s,%s)",
            (body.household_id, body.reading_ts, body.global_active_power,
             body.global_reactive_power, body.voltage, body.global_intensity))
        if body.sub_metering:
            _write_sub(cur, body.household_id, body.reading_ts, body.sub_metering.model_dump())
        return _fetch_one(cur, body.household_id, body.reading_ts)


@router.get("/{ts}", summary="Read one reading by timestamp (ISO 8601)")
def read_one(ts: datetime, household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    with mysql_conn() as conn, conn.cursor() as cur:
        row = _fetch_one(cur, household_id, ts)
    if not row:
        raise HTTPException(404, "Reading not found")
    return row


@router.put("/{ts}", summary="Update a reading")
def update(ts: datetime, body: ReadingUpdate, household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    data = body.model_dump(exclude_unset=True)
    sub = data.pop("sub_metering", None)
    if not data and not sub:
        raise HTTPException(422, "Nothing to update")
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {R} WHERE household_id=%s AND reading_ts=%s", (household_id, ts))
        if not cur.fetchone():
            raise HTTPException(404, "Reading not found")
        if data:
            sets = ", ".join(f"{k}=%s" for k in data)  # keys come from the pydantic model, not the client
            cur.execute(f"UPDATE {R} SET {sets} WHERE household_id=%s AND reading_ts=%s",
                        (*data.values(), household_id, ts))
        if sub:
            _write_sub(cur, household_id, ts, sub)
        return _fetch_one(cur, household_id, ts)


@router.delete("/{ts}", summary="Delete a reading")
def delete(ts: datetime, household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {S} WHERE household_id=%s AND {SC['ts']}=%s", (household_id, ts))
        cur.execute(f"DELETE FROM {R} WHERE household_id=%s AND reading_ts=%s", (household_id, ts))
        if cur.rowcount == 0:
            raise HTTPException(404, "Reading not found")
    return {"deleted": ts.isoformat()}
