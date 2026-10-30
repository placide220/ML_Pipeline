"""Names taken from database/01_schema.sql and database/mongodb/load_mongo.py."""
import os
from dotenv import load_dotenv

load_dotenv()

MYSQL = dict(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "household_power"),
    charset="utf8mb4",
)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:rootpass@localhost:27017/?authSource=admin")
MONGO_DB = os.getenv("MONGO_DB", "household_power")

# The API identifies a household by its code (MySQL households.household_code == Mongo meta.household_id).
DEFAULT_HOUSEHOLD = os.getenv("DEFAULT_HOUSEHOLD", "SCEAUX-01")

# Same field names in MySQL columns, Mongo documents and the API.
MEASURES = ["global_active_power_kw", "global_reactive_power_kvar", "voltage_v", "global_intensity_a"]
# sub_meters.sub_meter_id (MySQL) <-> key inside Mongo's `sub_metering_wh` object
SUB_METER_IDS = {1: "kitchen", 2: "laundry", 3: "water_heater_ac"}
