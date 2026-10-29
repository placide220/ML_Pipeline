"""Task 2 — Load the household power dataset into MongoDB.

Collections
  households       one document per household, sub-meters embedded as an array
  readings         native time-series collection, one document per minute
  daily_summaries  one document per day with its 24 hourly aggregates embedded
                   (built from `readings` with an aggregation pipeline + $out)

Usage (MongoDB must be running: `docker compose up -d mongo`):
    uv run database/mongodb/load_mongo.py
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from bson import json_util
from pymongo import ASCENDING, MongoClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = PROJECT_ROOT / "household_power_consumption.txt"
SAMPLE_DOCUMENTS_FILE = Path(__file__).with_name("sample_documents.json")

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://root:rootpass@localhost:27017/?authSource=admin")
DATABASE_NAME = "household_power"
HOUSEHOLD_ID = "SCEAUX-01"
BATCH_SIZE = 50_000  # number of documents sent to MongoDB in one insert_many call

HOUSEHOLD_DOCUMENT = {
    "_id": HOUSEHOLD_ID,
    "location": "Sceaux (7 km from Paris)",
    "country": "FR",
    "data_source": "UCI ML Repository / Kaggle — Individual household electric power consumption",
    "sampling_rate": "1 minute",
    "sub_meters": [
        {"code": "kitchen", "raw_column": "Sub_metering_1", "area": "Kitchen",
         "appliances": ["dishwasher", "oven", "microwave"], "unit": "Wh"},
        {"code": "laundry", "raw_column": "Sub_metering_2", "area": "Laundry room",
         "appliances": ["washing machine", "tumble-drier", "refrigerator", "light"], "unit": "Wh"},
        {"code": "water_heater_ac", "raw_column": "Sub_metering_3", "area": "Water heater & AC",
         "appliances": ["electric water-heater", "air-conditioner"], "unit": "Wh"},
    ],
}

# Order in which the fields of a reading are shown in sample_documents.json.
READING_FIELD_ORDER = ["ts", "meta", "is_missing", "global_active_power_kw", "global_reactive_power_kvar",
                       "voltage_v", "global_intensity_a", "sub_metering_wh"]


def read_raw_dataset() -> pd.DataFrame:
    """Read the semicolon-separated file. '?' (and the empty last field of missing rows) become NaN."""
    raw_data = pd.read_csv(DATA_FILE, sep=";", na_values=["?", ""], low_memory=False)
    raw_data["timestamp"] = pd.to_datetime(raw_data["Date"] + " " + raw_data["Time"], format="%d/%m/%Y %H:%M:%S")
    return raw_data.drop(columns=["Date", "Time"]).sort_values("timestamp", ignore_index=True)


def build_reading_documents(raw_data: pd.DataFrame):
    """Yield one document per minute. Missing minutes keep only ts/meta and is_missing=True."""
    timestamps = raw_data["timestamp"].dt.to_pydatetime()
    measurements = raw_data[["Global_active_power", "Global_reactive_power", "Voltage", "Global_intensity",
                             "Sub_metering_1", "Sub_metering_2", "Sub_metering_3"]].to_numpy()
    meta = {"household_id": HOUSEHOLD_ID}

    for timestamp, row in zip(timestamps, measurements):
        (active_power, reactive_power, voltage, intensity,
         kitchen_energy, laundry_energy, water_heater_ac_energy) = row

        # In the raw file a missing minute has every measurement missing at once.
        if np.isnan(active_power):
            yield {"ts": timestamp, "meta": meta, "is_missing": True}
            continue

        yield {
            "ts": timestamp,
            "meta": meta,
            "is_missing": False,
            "global_active_power_kw": float(active_power),
            "global_reactive_power_kvar": float(reactive_power),
            "voltage_v": float(voltage),
            "global_intensity_a": float(intensity),
            "sub_metering_wh": {
                "kitchen": float(kitchen_energy),
                "laundry": float(laundry_energy),
                "water_heater_ac": float(water_heater_ac_energy),
            },
        }


# Aggregation pipeline: readings -> one document per day with its hours embedded.
DAILY_SUMMARY_PIPELINE = [
    # 1. Ignore missing minutes (they have no measurements).
    {"$match": {"is_missing": False}},

    # 2. One group per household + day + hour: hourly totals and averages.
    {"$group": {
        "_id": {"household_id": "$meta.household_id",
                "date": {"$dateTrunc": {"date": "$ts", "unit": "day"}},
                "hour": {"$hour": "$ts"}},
        "observed_minutes": {"$sum": 1},
        "avg_active_power_kw": {"$avg": "$global_active_power_kw"},
        "peak_active_power_kw": {"$max": "$global_active_power_kw"},
        "min_voltage_v": {"$min": "$voltage_v"},
        "max_voltage_v": {"$max": "$voltage_v"},
        "energy_kwh": {"$sum": {"$divide": ["$global_active_power_kw", 60]}},  # 1 minute at P kW = P/60 kWh
        "kitchen_wh": {"$sum": "$sub_metering_wh.kitchen"},
        "laundry_wh": {"$sum": "$sub_metering_wh.laundry"},
        "water_heater_ac_wh": {"$sum": "$sub_metering_wh.water_heater_ac"},
    }},

    # 3. Sort so the hours are pushed into the array in order 0..23.
    {"$sort": {"_id.household_id": 1, "_id.date": 1, "_id.hour": 1}},

    # 4. One group per household + day: daily totals, plus the hourly groups as an array.
    {"$group": {
        "_id": {"household_id": "$_id.household_id", "date": "$_id.date"},
        "observed_minutes": {"$sum": "$observed_minutes"},
        "peak_active_power_kw": {"$max": "$peak_active_power_kw"},
        "min_voltage_v": {"$min": "$min_voltage_v"},
        "max_voltage_v": {"$max": "$max_voltage_v"},
        "total_energy_kwh": {"$sum": "$energy_kwh"},
        "kitchen_wh": {"$sum": "$kitchen_wh"},
        "laundry_wh": {"$sum": "$laundry_wh"},
        "water_heater_ac_wh": {"$sum": "$water_heater_ac_wh"},
        "hourly": {"$push": {
            "hour": "$_id.hour",
            "observed_minutes": "$observed_minutes",
            "avg_active_power_kw": {"$round": ["$avg_active_power_kw", 4]},
            "peak_active_power_kw": "$peak_active_power_kw",
            "energy_kwh": {"$round": ["$energy_kwh", 4]},
            "sub_metering_wh": {"kitchen": "$kitchen_wh", "laundry": "$laundry_wh",
                                "water_heater_ac": "$water_heater_ac_wh"},
        }},
    }},

    # 5. Shape the final document (field names and order as stored).
    {"$project": {
        "_id": 0,
        "household_id": "$_id.household_id",
        "date": "$_id.date",
        "year": {"$year": "$_id.date"},
        "month": {"$month": "$_id.date"},
        "day_of_week": {"$isoDayOfWeek": "$_id.date"},
        "observed_minutes": "$observed_minutes",
        "missing_minutes": {"$literal": 0},  # filled in by add_missing_minutes()
        "avg_active_power_kw": {"$round": [{"$divide": [{"$multiply": ["$total_energy_kwh", 60]},
                                                        "$observed_minutes"]}, 4]},
        "peak_active_power_kw": "$peak_active_power_kw",
        "voltage_v": {"min": "$min_voltage_v", "max": "$max_voltage_v"},
        "total_energy_kwh": {"$round": ["$total_energy_kwh", 4]},
        "sub_metering_wh": {"kitchen": "$kitchen_wh", "laundry": "$laundry_wh",
                            "water_heater_ac": "$water_heater_ac_wh"},
        # Whole-house energy (Wh) not captured by any of the three sub-meters.
        "unmetered_wh": {"$round": [{"$subtract": [{"$multiply": ["$total_energy_kwh", 1000]},
                                                   {"$add": ["$kitchen_wh", "$laundry_wh",
                                                             "$water_heater_ac_wh"]}]}, 3]},
        "hourly": "$hourly",
    }},

    # 6. Write the result into the daily_summaries collection (replacing it).
    {"$sort": {"date": 1}},
    {"$out": "daily_summaries"},
]


def insert_readings(database, raw_data: pd.DataFrame) -> None:
    """Create the time-series collection and insert every minute, BATCH_SIZE documents at a time."""
    database.create_collection(
        "readings",
        timeseries={"timeField": "ts", "metaField": "meta", "granularity": "minutes"},
    )
    current_batch = []
    inserted_count = 0
    for reading_document in build_reading_documents(raw_data):
        current_batch.append(reading_document)
        if len(current_batch) == BATCH_SIZE:
            database.readings.insert_many(current_batch, ordered=False)
            inserted_count += len(current_batch)
            current_batch = []
            print(f"  {inserted_count:,}", end="\r", flush=True)
    if current_batch:
        database.readings.insert_many(current_batch, ordered=False)
        inserted_count += len(current_batch)
    print(f"  {inserted_count:,} readings inserted")


def add_missing_minutes(database) -> None:
    """Store how many minutes are missing on each day.

    The daily pipeline skips missing minutes, so days with no data at all are not in
    daily_summaries yet; those are created here (upsert) with observed_minutes = 0.
    """
    minutes_per_day = database.readings.aggregate([
        {"$group": {"_id": {"$dateTrunc": {"date": "$ts", "unit": "day"}},
                    "missing_minutes": {"$sum": {"$cond": ["$is_missing", 1, 0]}},
                    "total_minutes": {"$sum": 1}}},
    ])
    for day_counts in minutes_per_day:
        if day_counts["missing_minutes"] == 0:
            continue
        day = day_counts["_id"]
        update = {"$set": {"missing_minutes": day_counts["missing_minutes"]}}
        day_has_no_data = day_counts["missing_minutes"] == day_counts["total_minutes"]
        if day_has_no_data:
            update["$setOnInsert"] = {"year": day.year, "month": day.month, "day_of_week": day.isoweekday(),
                                      "observed_minutes": 0, "hourly": []}
        database.daily_summaries.update_one({"household_id": HOUSEHOLD_ID, "date": day}, update, upsert=True)


def in_field_order(reading_document: dict) -> dict:
    """Time-series collections store fields column-wise, so restore a readable field order."""
    return {field: reading_document[field] for field in READING_FIELD_ORDER if field in reading_document}


def write_sample_documents(database) -> None:
    """Save one example of each document type to sample_documents.json (used in the report)."""
    christmas_eve_2008 = pd.Timestamp("2008-12-24").to_pydatetime()
    sample_documents = {
        "households": database.households.find_one(),
        "readings (observed minute)": in_field_order(database.readings.find_one({"is_missing": False}, {"_id": 0})),
        "readings (missing minute)": in_field_order(database.readings.find_one({"is_missing": True}, {"_id": 0})),
        "daily_summaries": database.daily_summaries.find_one({"date": christmas_eve_2008}, {"_id": 0}),
    }
    SAMPLE_DOCUMENTS_FILE.write_text(
        json_util.dumps(sample_documents, indent=2, json_options=json_util.RELAXED_JSON_OPTIONS))
    print(f"Sample documents written to {SAMPLE_DOCUMENTS_FILE.relative_to(PROJECT_ROOT)}")


def main() -> None:
    if not DATA_FILE.exists():
        sys.exit(f"Data file not found: {DATA_FILE}")

    client = MongoClient(MONGO_URI)
    database = client[DATABASE_NAME]

    # Start from empty collections so the script can be re-run safely.
    for collection_name in ("households", "readings", "daily_summaries"):
        database.drop_collection(collection_name)

    start_time = time.time()
    print(f"Reading {DATA_FILE.name} ...")
    raw_data = read_raw_dataset()
    missing_count = raw_data["Global_active_power"].isna().sum()
    print(f"  {len(raw_data):,} rows, {missing_count:,} missing minutes")

    database.households.insert_one(HOUSEHOLD_DOCUMENT)

    print("Inserting minute readings into the time-series collection ...")
    insert_readings(database, raw_data)

    print("Building daily_summaries with the aggregation pipeline ...")
    database.readings.aggregate(DAILY_SUMMARY_PIPELINE, allowDiskUse=True)
    add_missing_minutes(database)
    database.daily_summaries.create_index([("household_id", ASCENDING), ("date", ASCENDING)], unique=True)
    database.daily_summaries.create_index([("year", ASCENDING), ("month", ASCENDING)])

    document_counts = {collection_name: database[collection_name].count_documents({})
                       for collection_name in ("households", "readings", "daily_summaries")}
    print("Collections:", document_counts)

    write_sample_documents(database)
    print(f"Done in {time.time() - start_time:.0f}s")


if __name__ == "__main__":
    main()
