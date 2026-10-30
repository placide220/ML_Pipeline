"""CRUD + time-series endpoints backed by the MongoDB time-series collection `readings`
(timeField=ts, metaField=meta -> meta.household_id).

Time-series collections have restrictions: deleteOne is not supported (we use delete_many with an
exact ts filter), and the ts / meta fields cannot be modified by an update."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from .. import config
from ..db import mongo_db
from ..schemas import ReadingCreate, ReadingUpdate

router = APIRouter(prefix="/mongo/readings", tags=["MongoDB"])
HIDE = {"_id": 0}


def _col():
    return mongo_db()[config.READINGS_COLLECTION]


def _clean(doc: dict) -> dict:
    """Flatten the stored document to the same shape the SQL endpoints return."""
    if doc is None:
        return None
    meta = doc.pop("meta", {}) or {}
    doc["household_id"] = meta.get("household_id")
    doc["reading_ts"] = doc.pop("ts")
    doc.pop("_id", None)
    return doc


@router.get("/latest", summary="Latest non-missing record")
def latest(household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    doc = _col().find_one({"meta.household_id": household_id, "is_missing": {"$ne": True}},
                          HIDE, sort=[("ts", -1)])
    if not doc:
        raise HTTPException(404, "No readings found")
    return _clean(doc)


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
    match = {"meta.household_id": household_id, "ts": {"$gte": start, "$lt": end}}
    if not include_missing:
        match["is_missing"] = {"$ne": True}
    if resolution == "minute":
        rows = [_clean(d) for d in _col().find(match, HIDE).sort("ts", 1).limit(limit)]
    else:
        group = {"_id": {"$dateTrunc": {"date": "$ts", "unit": "hour"}}}
        group.update({m: {"$avg": f"${m}"} for m in config.MEASURES})
        pipeline = [{"$match": match}, {"$group": group}, {"$sort": {"_id": 1}}, {"$limit": limit}]
        rows = []
        for d in _col().aggregate(pipeline):
            d["reading_ts"] = d.pop("_id")
            rows.append(d)
    return {"count": len(rows), "resolution": resolution, "data": rows}


@router.post("", status_code=201, summary="Create a reading")
def create(body: ReadingCreate):
    col = _col()
    if col.count_documents({"meta.household_id": body.household_id, "ts": body.reading_ts}, limit=1):
        raise HTTPException(409, "A reading already exists for this timestamp")
    doc = {
        "ts": body.reading_ts,
        "meta": {"household_id": body.household_id},
        **{m: getattr(body, m) for m in config.MEASURES},
    }
    if body.sub_metering:
        doc["sub_metering"] = body.sub_metering.model_dump()
    col.insert_one(doc)
    return _clean(col.find_one({"meta.household_id": body.household_id, "ts": body.reading_ts}, HIDE))


@router.get("/{ts}", summary="Read one reading by timestamp (ISO 8601)")
def read_one(ts: datetime, household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    doc = _col().find_one({"meta.household_id": household_id, "ts": ts}, HIDE)
    if not doc:
        raise HTTPException(404, "Reading not found")
    return _clean(doc)


@router.put("/{ts}", summary="Update a reading")
def update(ts: datetime, body: ReadingUpdate, household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    data = body.model_dump(exclude_unset=True)
    sub = data.pop("sub_metering", None)
    if sub:
        data.update({f"sub_metering.{k}": v for k, v in sub.items() if v is not None})
    if not data:
        raise HTTPException(422, "Nothing to update")
    flt = {"meta.household_id": household_id, "ts": ts}
    # A previously-missing minute becomes a real reading once values are written.
    res = _col().update_many(flt, {"$set": data, "$unset": {"is_missing": ""}})
    if res.matched_count == 0:
        raise HTTPException(404, "Reading not found")
    return _clean(_col().find_one(flt, HIDE))


@router.delete("/{ts}", summary="Delete a reading")
def delete(ts: datetime, household_id: int = config.DEFAULT_HOUSEHOLD_ID):
    res = _col().delete_many({"meta.household_id": household_id, "ts": ts})
    if res.deleted_count == 0:
        raise HTTPException(404, "Reading not found")
    return {"deleted": ts.isoformat()}
