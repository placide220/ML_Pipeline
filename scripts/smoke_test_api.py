#!/usr/bin/env python3
"""Exercises every endpoint on both databases and prints PASS/FAIL (use the output as evidence in the report).
    python scripts/smoke_test_api.py http://localhost:8000
"""
import sys
import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TS = "2030-01-01T00:00:00"      # far-future minute that cannot clash with the real data
fails = 0


def check(name, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")


for src in ("sql", "mongo"):
    u = f"{BASE}/{src}/readings"
    requests.delete(f"{u}/{TS}")                                     # clean up leftovers
    r = requests.get(f"{u}/latest")
    check(f"[{src}] GET latest", r.status_code == 200, r.json().get("reading_ts", "") if r.ok else r.text)
    body = {"reading_ts": TS, "household_id": "SCEAUX-01", "global_active_power_kw": 1.5, "global_reactive_power_kvar": 0.1,
            "voltage_v": 240.0, "global_intensity_a": 6.2,
            "sub_metering_wh": {"kitchen": 1, "laundry": 0, "water_heater_ac": 17}}
    r = requests.post(u, json=body)
    check(f"[{src}] POST create", r.status_code == 201, r.text[:80])
    check(f"[{src}] POST duplicate -> 409", requests.post(u, json=body).status_code == 409)
    r = requests.get(f"{u}/{TS}")
    check(f"[{src}] GET one", r.status_code == 200 and abs(r.json()["global_active_power_kw"] - 1.5) < 1e-6)
    r = requests.put(f"{u}/{TS}", json={"global_active_power_kw": 2.25})
    check(f"[{src}] PUT update", r.status_code == 200 and abs(r.json()["global_active_power_kw"] - 2.25) < 1e-6)
    r = requests.get(f"{u}/range", params={"start": "2030-01-01T00:00:00", "end": "2030-01-01T01:00:00"})
    check(f"[{src}] GET range (minute)", r.status_code == 200 and r.json()["count"] == 1)
    r = requests.get(f"{u}/range", params={"start": "2010-11-25T00:00:00", "end": "2010-11-26T00:00:00",
                                           "resolution": "hour"})
    check(f"[{src}] GET range (hour)", r.status_code == 200 and r.json()["count"] > 0, f"count={r.json().get('count')}")
    check(f"[{src}] POST invalid -> 422", requests.post(u, json={**body, "voltage_v": 999}).status_code == 422)
    check(f"[{src}] DELETE", requests.delete(f"{u}/{TS}").status_code == 200)
    check(f"[{src}] GET after delete -> 404", requests.get(f"{u}/{TS}").status_code == 404)

print("\nALL PASSED" if not fails else f"\n{fails} CHECK(S) FAILED")
sys.exit(1 if fails else 0)
