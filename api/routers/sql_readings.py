"""MySQL endpoints. Tables: households, power_readings, sub_meter_readings (see 01_schema.sql).
sub_meter_readings has no timestamp: it is linked to a minute through power_readings.reading_id."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from .. import config
from ..db import mysql_conn
from ..schemas import ReadingCreate, ReadingUpdate

router = APIRouter(prefix="/sql/readings", tags=["MySQL"])
COLS = ", ".join(f"r.{c}" for c in config.MEASURES)
BASE = ("FROM power_readings r JOIN households h ON h.household_id = r.household_id "
        "WHERE h.household_code = %s")


def _with_sub(cur, row):
    if not row:
        return None
    rid = row.pop("reading_id")
    cur.execute("SELECT sub_meter_id, energy_wh FROM sub_meter_readings WHERE reading_id=%s", (rid,))
    sub = {name: None for name in config.SUB_METER_IDS.values()}
    for s in cur.fetchall():
        sub[config.SUB_METER_IDS[s["sub_meter_id"]]] = float(s["energy_wh"])
    row["sub_metering_wh"] = sub
    return row


def _get(cur, household: str, ts: datetime):
    cur.execute(f"SELECT r.reading_id, r.reading_ts, h.household_code AS household_id, {COLS}, r.is_missing "
                f"{BASE} AND r.reading_ts=%s", (household, ts))
    return _with_sub(cur, cur.fetchone())


def _write_sub(cur, reading_id: int, sub: dict):
    inv = {v: k for k, v in config.SUB_METER_IDS.items()}
    for name, value in sub.items():
        if value is not None:
            cur.execute("INSERT INTO sub_meter_readings (reading_id, sub_meter_id, energy_wh) VALUES (%s,%s,%s) "
                        "ON DUPLICATE KEY UPDATE energy_wh=VALUES(energy_wh)", (reading_id, inv[name], value))


@router.get("/latest", summary="Latest non-missing record")
def latest(household_id: str = config.DEFAULT_HOUSEHOLD):
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT r.reading_ts {BASE} AND r.is_missing=0 ORDER BY r.reading_ts DESC LIMIT 1",
                    (household_id,))
        hit = cur.fetchone()
        if not hit:
            raise HTTPException(404, "No readings found")
        return _get(cur, household_id, hit["reading_ts"])


@router.get("/range", summary="Records between start (inclusive) and end (exclusive)")
def by_range(start: datetime, end: datetime, household_id: str = config.DEFAULT_HOUSEHOLD,
             resolution: Literal["minute", "hour"] = "minute", include_missing: bool = False,
             limit: int = Query(10000, ge=1, le=100000)):
    if end <= start:
        raise HTTPException(422, "end must be after start")
    miss = "" if include_missing else "AND r.is_missing=0"
    with mysql_conn() as conn, conn.cursor() as cur:
        if resolution == "minute":
            cur.execute(f"SELECT r.reading_ts, {COLS} {BASE} AND r.reading_ts>=%s AND r.reading_ts<%s {miss} "
                        f"ORDER BY r.reading_ts LIMIT %s", (household_id, start, end, limit))
        else:
            avgs = ", ".join(f"AVG(r.{c}) AS {c}" for c in config.MEASURES)
            cur.execute(f"SELECT DATE_FORMAT(r.reading_ts,'%%Y-%%m-%%d %%H:00:00') AS reading_ts, {avgs} "
                        f"{BASE} AND r.reading_ts>=%s AND r.reading_ts<%s {miss} "
                        f"GROUP BY 1 ORDER BY 1 LIMIT %s", (household_id, start, end, limit))
        rows = cur.fetchall()
    return {"count": len(rows), "resolution": resolution, "data": rows}


@router.post("", status_code=201, summary="Create a reading")
def create(body: ReadingCreate):
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT household_id FROM households WHERE household_code=%s", (body.household_id,))
        h = cur.fetchone()
        if not h:
            raise HTTPException(404, f"Unknown household {body.household_id}")
        cur.execute("SELECT 1 FROM power_readings WHERE household_id=%s AND reading_ts=%s",
                    (h["household_id"], body.reading_ts))
        if cur.fetchone():
            raise HTTPException(409, "A reading already exists for this timestamp")
        cur.execute(f"INSERT INTO power_readings (household_id, reading_ts, {', '.join(config.MEASURES)}) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (h["household_id"], body.reading_ts, *[getattr(body, m) for m in config.MEASURES]))
        if body.sub_metering_wh:
            _write_sub(cur, cur.lastrowid, body.sub_metering_wh.model_dump())
        return _get(cur, body.household_id, body.reading_ts)


@router.get("/{ts}", summary="Read one reading by timestamp (ISO 8601)")
def read_one(ts: datetime, household_id: str = config.DEFAULT_HOUSEHOLD):
    with mysql_conn() as conn, conn.cursor() as cur:
        row = _get(cur, household_id, ts)
    if not row:
        raise HTTPException(404, "Reading not found")
    return row


@router.put("/{ts}", summary="Update a reading")
def update(ts: datetime, body: ReadingUpdate, household_id: str = config.DEFAULT_HOUSEHOLD):
    data = body.model_dump(exclude_unset=True)
    sub = data.pop("sub_metering_wh", None)
    if not data and not sub:
        raise HTTPException(422, "Nothing to update")
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT r.reading_id {BASE} AND r.reading_ts=%s", (household_id, ts))
        hit = cur.fetchone()
        if not hit:
            raise HTTPException(404, "Reading not found")
        if data:
            sets = ", ".join(f"{k}=%s" for k in data)       # keys come from the pydantic model
            cur.execute(f"UPDATE power_readings SET {sets} WHERE reading_id=%s", (*data.values(), hit["reading_id"]))
        if sub:
            _write_sub(cur, hit["reading_id"], sub)
        return _get(cur, household_id, ts)


@router.delete("/{ts}", summary="Delete a reading")
def delete(ts: datetime, household_id: str = config.DEFAULT_HOUSEHOLD):
    with mysql_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT r.reading_id {BASE} AND r.reading_ts=%s", (household_id, ts))
        hit = cur.fetchone()
        if not hit:
            raise HTTPException(404, "Reading not found")
        cur.execute("DELETE FROM power_readings WHERE reading_id=%s", (hit["reading_id"],))  # cascades to sub_meter_readings
    return {"deleted": ts.isoformat()}
