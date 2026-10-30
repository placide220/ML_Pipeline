"""MongoDB endpoints on the time-series collection `readings` (timeField=ts, metaField=meta).
Document shape (from load_mongo.py): ts, meta.household_id, is_missing, global_active_power_kw, ...,
sub_metering_wh{kitchen,laundry,water_heater_ac}.
Time-series limits: deleteOne is unsupported (we use delete_many on an exact ts) and ts/meta cannot be updated."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from .. import config
from ..db import mongo_db
from ..schemas import ReadingCreate, ReadingUpdate

router = APIRouter(prefix="/mongo/readings", tags=["MongoDB"])
HIDE = {"_id": 0}


def _col():
    return mongo_db()["readings"]


def _clean(doc):
    """Return the same shape as the SQL endpoints."""
    if doc is None:
        return None
    meta = doc.pop("meta", {}) or {}
    doc["household_id"] = meta.get("household_id")
    doc["reading_ts"] = doc.pop("ts")
    doc.pop("_id", None)
    return doc


@router.get("/latest", summary="Latest non-missing record")
def latest(household_id: str = config.DEFAULT_HOUSEHOLD):
    doc = _col().find_one({"meta.household_id": household_id, "is_missing": False}, HIDE, sort=[("ts", -1)])
    if not doc:
        raise HTTPException(404, "No readings found")
    return _clean(doc)


@router.get("/range", summary="Records between start (inclusive) and end (exclusive)")
def by_range(start: datetime, end: datetime, household_id: str = config.DEFAULT_HOUSEHOLD,
             resolution: Literal["minute", "hour"] = "minute", include_missing: bool = False,
             limit: int = Query(10000, ge=1, le=100000)):
    if end <= start:
        raise HTTPException(422, "end must be after start")
    match = {"meta.household_id": household_id, "ts": {"$gte": start, "$lt": end}}
    if not include_missing:
        match["is_missing"] = False
    if resolution == "minute":
        rows = [_clean(d) for d in _col().find(match, HIDE).sort("ts", 1).limit(limit)]
    else:
        group = {"_id": {"$dateTrunc": {"date": "$ts", "unit": "hour"}}}
        group.update({m: {"$avg": f"${m}"} for m in config.MEASURES})
        rows = []
        for d in _col().aggregate([{"$match": match}, {"$group": group}, {"$sort": {"_id": 1}}, {"$limit": limit}]):
            d["reading_ts"] = d.pop("_id")
            rows.append(d)
    return {"count": len(rows), "resolution": resolution, "data": rows}


@router.post("", status_code=201, summary="Create a reading")
def create(body: ReadingCreate):
    col = _col()
    key = {"meta.household_id": body.household_id, "ts": body.reading_ts}
    if col.count_documents(key, limit=1):
        raise HTTPException(409, "A reading already exists for this timestamp")
    doc = {"ts": body.reading_ts, "meta": {"household_id": body.household_id}, "is_missing": False,
           **{m: getattr(body, m) for m in config.MEASURES}}
    if body.sub_metering_wh:
        doc["sub_metering_wh"] = {k: v for k, v in body.sub_metering_wh.model_dump().items() if v is not None}
    col.insert_one(doc)
    return _clean(col.find_one(key, HIDE))


@router.get("/{ts}", summary="Read one reading by timestamp (ISO 8601)")
def read_one(ts: datetime, household_id: str = config.DEFAULT_HOUSEHOLD):
    doc = _col().find_one({"meta.household_id": household_id, "ts": ts}, HIDE)
    if not doc:
        raise HTTPException(404, "Reading not found")
    return _clean(doc)


@router.put("/{ts}", summary="Update a reading")
def update(ts: datetime, body: ReadingUpdate, household_id: str = config.DEFAULT_HOUSEHOLD):
    data = body.model_dump(exclude_unset=True)
    sub = data.pop("sub_metering_wh", None)
    if sub:
        data.update({f"sub_metering_wh.{k}": v for k, v in sub.items() if v is not None})
    if not data:
        raise HTTPException(422, "Nothing to update")
    key = {"meta.household_id": household_id, "ts": ts}
    res = _col().update_many(key, {"$set": {**data, "is_missing": False}})
    if res.matched_count == 0:
        raise HTTPException(404, "Reading not found")
    return _clean(_col().find_one(key, HIDE))


@router.delete("/{ts}", summary="Delete a reading")
def delete(ts: datetime, household_id: str = config.DEFAULT_HOUSEHOLD):
    res = _col().delete_many({"meta.household_id": household_id, "ts": ts})
    if res.deleted_count == 0:
        raise HTTPException(404, "Reading not found")
    return {"deleted": ts.isoformat()}
