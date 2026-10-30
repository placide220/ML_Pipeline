#!/usr/bin/env python3
"""Task 4 - end-to-end forecast script.

 A. fetch time-series records from the API (MySQL or MongoDB endpoint)
 B. preprocess them like Task 1 (hourly resample, interpolate short gaps, seasonal-profile for long gaps)
 C. load the trained model
 D. predict the next hour(s) of Global_active_power (kW)

Example:
    python scripts/predict.py --source sql
    python scripts/predict.py --source mongo --steps 6 --model models/best_model.joblib
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests

HISTORY_DAYS = 31          # 744 h: enough for lag_168 and the 30-day rolling mean
MAX_INTERP_HOURS = 4       # Task 1: gaps <= 240 min -> linear (time) interpolation
TARGET = "global_active_power"


# --------------------------------------------------------------------------- A. fetch
def fetch_history(api_url: str, source: str, household_id: int) -> pd.Series:
    base = f"{api_url.rstrip('/')}/{source}/readings"
    r = requests.get(f"{base}/latest", params={"household_id": household_id}, timeout=15)
    r.raise_for_status()
    latest = r.json()
    end = pd.to_datetime(latest["reading_ts"])
    start = end - pd.Timedelta(days=HISTORY_DAYS)
    r = requests.get(f"{base}/range", timeout=60, params={
        "start": start.isoformat(), "end": (end + pd.Timedelta(minutes=1)).isoformat(),
        "household_id": household_id, "resolution": "hour",
        "include_missing": False, "limit": 100000})
    r.raise_for_status()
    rows = r.json()["data"]
    if not rows:
        sys.exit("API returned no records for the requested window")
    df = pd.DataFrame(rows)
    df["reading_ts"] = pd.to_datetime(df["reading_ts"])
    print(f"[A] fetched {len(df)} hourly records from /{source}/readings "
          f"({df['reading_ts'].min()} -> {df['reading_ts'].max()}); latest minute = {end}")
    return df.set_index("reading_ts")[TARGET].astype(float)


# --------------------------------------------------------------------------- B. preprocess
def preprocess(series: pd.Series) -> pd.Series:
    full_index = pd.date_range(series.index.min().floor("h"), series.index.max().floor("h"), freq="h")
    s = series.reindex(full_index)
    n_missing = int(s.isna().sum())
    s = s.interpolate(method="time", limit=MAX_INTERP_HOURS, limit_area="inside")
    if s.isna().any():  # long gaps: same weekday/hour profile of the fetched window
        profile = s.groupby([s.index.dayofweek, s.index.hour]).transform("mean")
        s = s.fillna(profile).fillna(s.mean())
    print(f"[B] preprocessed: {n_missing} missing hours filled, {len(s)} hourly rows")
    return s


def make_features(history: pd.Series, ts: pd.Timestamp) -> dict:
    """Features for hour `ts`, using only values strictly before `ts` (no leakage).
    Keep in sync with time_series_features.py used at training time."""
    past = history[history.index < ts]
    lag = lambda h: history.get(ts - pd.Timedelta(hours=h), np.nan)
    return {
        "lag_1": lag(1), "lag_2": lag(2), "lag_24": lag(24), "lag_168": lag(168),
        "roll_mean_168": past.iloc[-168:].mean(),     # 7-day moving average
        "roll_mean_720": past.iloc[-720:].mean(),     # 30-day moving average
        "hour": ts.hour, "day_of_week": ts.dayofweek,
        "is_weekend": int(ts.dayofweek >= 5), "month": ts.month,
    }


# --------------------------------------------------------------------------- C/D. model + predict
def load_model(model_path: Path, features_path: Path):
    model = joblib.load(model_path)
    if features_path.exists():
        cols = json.loads(features_path.read_text())
    elif hasattr(model, "feature_names_in_"):
        cols = list(model.feature_names_in_)
    else:
        sys.exit("Cannot determine feature order: save it with json.dump(list(X_train.columns), ...) "
                 f"to {features_path}")
    print(f"[C] loaded {type(model).__name__} from {model_path} ({len(cols)} features)")
    return model, cols


def forecast(model, cols, history: pd.Series, steps: int, log_target: bool) -> pd.Series:
    hist = history.copy()
    preds = {}
    for _ in range(steps):
        ts = hist.index[-1] + pd.Timedelta(hours=1)
        feats = make_features(hist, ts)
        missing = [c for c in cols if c not in feats]
        if missing:
            sys.exit(f"Model expects features this script does not build: {missing}. "
                     "Add them to make_features() or import your own from time_series_features.py")
        X = pd.DataFrame([feats])[cols]
        y = float(model.predict(X)[0])
        y = float(np.expm1(y)) if log_target else y
        preds[ts] = max(y, 0.0)
        hist.loc[ts] = preds[ts]      # recursive multi-step: feed the prediction back as history
    return pd.Series(preds, name="predicted_global_active_power_kW")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-url", default="http://localhost:8000")
    p.add_argument("--source", choices=["sql", "mongo"], default="sql")
    p.add_argument("--household-id", type=int, default=1)
    p.add_argument("--model", type=Path, default=Path("models/best_model.joblib"))
    p.add_argument("--features", type=Path, default=Path("models/feature_columns.json"))
    p.add_argument("--steps", type=int, default=1, help="hours to forecast ahead")
    p.add_argument("--log-target", action="store_true", help="model was trained on log1p(target)")
    a = p.parse_args()

    raw = fetch_history(a.api_url, a.source, a.household_id)          # A
    hourly = preprocess(raw)                                          # B
    model, cols = load_model(a.model, a.features)                     # C
    out = forecast(model, cols, hourly, a.steps, a.log_target)        # D
    print(f"[D] forecast (kW):\n{out.round(3).to_string()}")


if __name__ == "__main__":
    main()
