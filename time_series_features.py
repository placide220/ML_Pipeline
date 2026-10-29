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
