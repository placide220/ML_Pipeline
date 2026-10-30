#!/usr/bin/env python3
"""Task 4 - end-to-end forecast script.

 A. fetch time-series records from the API (MySQL or MongoDB endpoint)
 B. preprocess them like Task 1 (hourly series, interpolate short gaps, weekday/hour profile for long gaps)
 C. load the trained model
 D. predict the next hour(s) of Global_active_power (kW)

Lag / rolling features are built with add_lags() and add_rolling() imported from time_series_features.py,
i.e. the same code used for training. Which lags/windows to build (and the column prefix) is read from the
model's saved feature list, so the names always match what the model was trained on.

Example:
    python scripts/predict.py --source sql
    python scripts/predict.py --source mongo --steps 6 --model models/best_model.joblib
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", Path.cwd()):          # where time_series_features.py may live
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
try:
    from time_series_features import add_lags, add_rolling
except ImportError:
    sys.exit("Cannot import time_series_features.py. Run from the repo root or add its folder to PYTHONPATH.")

API_COLUMN = "global_active_power_kw"   # field name returned by the API
DEFAULT_HISTORY_DAYS = 31               # used only if the feature list is not readable before fetching
MAX_INTERP_HOURS = 4                    # Task 1: gaps <= 240 min -> linear (time) interpolation


# ----------------------------------------------------------------------- helpers on the feature list
def _numbers(cols, kind):
    return sorted({int(m.group(1)) for c in cols if (m := re.search(rf"_{kind}(\d+)$", c))})


def infer_target_col(cols, default=API_COLUMN):
    """Column prefix used at training time, taken from names like '<prefix>_lag1' / '<prefix>_roll168'."""
    prefixes = {re.sub(r"_(lag|roll)\d+$", "", c) for c in cols if re.search(r"_(lag|roll)\d+$", c)}
    return prefixes.pop() if len(prefixes) == 1 else default


def peek_feature_columns(features_path: Path):
    return json.loads(features_path.read_text()) if features_path.exists() else None


def history_days_for(cols):
    if not cols:
        return DEFAULT_HISTORY_DAYS
    need = max(_numbers(cols, "lag") + _numbers(cols, "roll") + [24]) + 48     # hours
    return math.ceil(need / 24)


# --------------------------------------------------------------------------- A. fetch
def fetch_history(api_url: str, source: str, household_id: str, days: int) -> pd.Series:
    base = f"{api_url.rstrip('/')}/{source}/readings"
    r = requests.get(f"{base}/latest", params={"household_id": household_id}, timeout=15)
    r.raise_for_status()
    end = pd.to_datetime(r.json()["reading_ts"])
    start = end - pd.Timedelta(days=days)
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
    return df.set_index("reading_ts")[API_COLUMN].astype(float)


# --------------------------------------------------------------------------- B. preprocess
def preprocess(series: pd.Series) -> pd.Series:
    full_index = pd.date_range(series.index.min().floor("h"), series.index.max().floor("h"), freq="h")
    s = series.reindex(full_index)
    n_missing = int(s.isna().sum())
    s = s.interpolate(method="time", limit=MAX_INTERP_HOURS, limit_area="inside")
    if s.isna().any():   # longer gaps: weekday/hour profile of the fetched window (approximates the Task 1 profile)
        profile = s.groupby([s.index.dayofweek, s.index.hour]).transform("mean")
        s = s.fillna(profile).fillna(s.mean())
    print(f"[B] preprocessed: {n_missing} missing hours filled, {len(s)} hourly rows")
    return s


def calendar_features(ts: pd.Timestamp) -> dict:
    """time_series_features.py has no calendar helper, so these names come from the training notebook.
    Several common aliases are produced; only the ones the model lists are used. If your model uses
    another name, add it here."""
    return {"hour": ts.hour, "day_of_week": ts.dayofweek, "dayofweek": ts.dayofweek,
            "is_weekend": int(ts.dayofweek >= 5), "month": ts.month}


def build_features(history: pd.Series, ts: pd.Timestamp, cols, target_col: str) -> dict:
    """Features for hour `ts` from values strictly before it: a NaN placeholder row for `ts` is appended and the
    training helpers are applied (add_rolling shifts by 1, so the placeholder never leaks into its own window)."""
    df = history.rename(target_col).to_frame()
    df.loc[ts] = np.nan
    df = df.sort_index()
    lags, windows = _numbers(cols, "lag"), _numbers(cols, "roll")
    if lags:
        df = add_lags(df, target_col, lags)
    if windows:
        df = add_rolling(df, target_col, windows)
    row = df.iloc[-1].to_dict()
    row.update(calendar_features(ts))
    return row


# --------------------------------------------------------------------------- C. model
def load_model(model_path: Path, features_path: Path):
    model = joblib.load(model_path)
    cols = peek_feature_columns(features_path)
    if cols is None:
        if hasattr(model, "feature_names_in_"):
            cols = list(model.feature_names_in_)
        else:
            sys.exit(f"Cannot determine feature order: save it to {features_path} "
                     "with json.dump(list(X_train.columns), ...)")
    print(f"[C] loaded {type(model).__name__} from {model_path} ({len(cols)} features)")
    return model, cols


# --------------------------------------------------------------------------- D. predict
def forecast(model, cols, history: pd.Series, steps: int, log_target: bool, target_col: str) -> pd.Series:
    hist, preds = history.copy(), {}
    for _ in range(steps):
        ts = hist.index[-1] + pd.Timedelta(hours=1)
        feats = build_features(hist, ts, cols, target_col)
        missing = [c for c in cols if c not in feats]
        if missing:
            sys.exit(f"Model expects columns this script cannot build: {missing}. "
                     "Add them to calendar_features() or pass --target-col if the prefix differs.")
        if any(pd.isna(feats[c]) for c in cols):
            bad = [c for c in cols if pd.isna(feats[c])]
            sys.exit(f"Not enough history to build {bad}. Increase the fetched window.")
        X = pd.DataFrame([feats])[cols]
        y = float(model.predict(X)[0])
        y = float(np.expm1(y)) if log_target else y
        preds[ts] = max(y, 0.0)
        hist.loc[ts] = preds[ts]      # recursive multi-step: prediction becomes history
    return pd.Series(preds, name="predicted_global_active_power_kW")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-url", default="http://localhost:8000")
    p.add_argument("--source", choices=["sql", "mongo"], default="sql")
    p.add_argument("--household-id", default="SCEAUX-01")
    p.add_argument("--model", type=Path, default=Path("models/best_model.joblib"))
    p.add_argument("--features", type=Path, default=Path("models/feature_columns.json"))
    p.add_argument("--steps", type=int, default=1, help="hours to forecast ahead")
    p.add_argument("--log-target", action="store_true", help="model was trained on log1p(target)")
    p.add_argument("--target-col", help="column prefix used in training feature names (default: inferred)")
    a = p.parse_args()

    days = history_days_for(peek_feature_columns(a.features))
    raw = fetch_history(a.api_url, a.source, a.household_id, days)    # A
    hourly = preprocess(raw)                                          # B
    model, cols = load_model(a.model, a.features)                     # C
    target_col = a.target_col or infer_target_col(cols)
    out = forecast(model, cols, hourly, a.steps, a.log_target, target_col)   # D
    print(f"[D] forecast (kW):\n{out.round(3).to_string()}")


if __name__ == "__main__":
    main()
