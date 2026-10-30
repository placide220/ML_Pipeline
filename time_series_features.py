"""Reusable lag and rolling-window feature helpers.

Shared with the model-training and prediction-script parts of the project,
so the exact same features are built everywhere.
"""
import pandas as pd


def add_lags(df: pd.DataFrame, col: str, lags: list[int]) -> pd.DataFrame:
    """Add one column per lag: value of `col` shifted back by `lag` steps."""
    out = df.copy()
    for lag in lags:
        out[f"{col}_lag{lag}"] = out[col].shift(lag)
    return out


def add_rolling(df: pd.DataFrame, col: str, windows: list[int]) -> pd.DataFrame:
    """Add rolling mean columns. shift(1) keeps the current value out of its
    own window, so the feature only uses past data (no leakage)."""
    out = df.copy()
    for w in windows:
        out[f"{col}_roll{w}"] = out[col].shift(1).rolling(window=w).mean()
    return out


# ---------------------------------------------------------------------------
# Model features (Task 1C training  <->  Task 4 scripts/predict.py)
# ---------------------------------------------------------------------------
TARGET_COL = "Global_active_power"
LAGS = [1, 2, 24, 168]          # previous hour, 2 h ago, same hour yesterday, same hour last week
ROLL_WINDOWS = [168, 720]       # 7-day and 30-day moving averages (in hours)
FEATURE_COLUMNS = [
    "lag_1", "lag_2", "lag_24", "lag_168",
    "roll_mean_168", "roll_mean_720",
    "hour", "day_of_week", "is_weekend", "month",
]


def build_model_features(hourly: pd.Series) -> pd.DataFrame:
    """Turn an hourly Global_active_power series (regular hourly index) into the
    model's feature table. Every feature uses only values strictly before the
    target hour, and the definitions match make_features() in scripts/predict.py.
    Rows without a full 720-hour history are dropped."""
    df = hourly.rename(TARGET_COL).to_frame()
    df = add_lags(df, TARGET_COL, LAGS)
    df = add_rolling(df, TARGET_COL, ROLL_WINDOWS)
    df = df.rename(columns={f"{TARGET_COL}_lag{l}": f"lag_{l}" for l in LAGS}
                   | {f"{TARGET_COL}_roll{w}": f"roll_mean_{w}" for w in ROLL_WINDOWS})
    idx = df.index
    df["hour"] = idx.hour
    df["day_of_week"] = idx.dayofweek
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    df["month"] = idx.month
    return df.dropna()[FEATURE_COLUMNS + [TARGET_COL]]
