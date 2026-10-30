"""Central configuration. Everything that depends on the Task 2 schema lives here,
so if a table/column/collection name differs in your repo you only change this file."""
import os
from dotenv import load_dotenv

load_dotenv()

MYSQL = dict(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "power_db"),
    charset="utf8mb4",
)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "power_db")
DEFAULT_HOUSEHOLD_ID = int(os.getenv("DEFAULT_HOUSEHOLD_ID", "1"))

# ---- SQL schema names (check against database/01_schema.sql) ----
READINGS_TABLE = "power_readings"
SUB_READINGS_TABLE = "sub_meter_readings"
# sub_meters.sub_meter_id -> field name used in the API / Mongo "sub_metering" object
SUB_METER_IDS = {1: "kitchen", 2: "laundry", 3: "water_heater_ac"}
SUB_READINGS_COLUMNS = dict(ts="reading_ts", meter="sub_meter_id", value="energy_wh")

# ---- Mongo names (check against database/load_mongo.py) ----
READINGS_COLLECTION = "readings"

MEASURES = [
    "global_active_power",
    "global_reactive_power",
    "voltage",
    "global_intensity",
]
