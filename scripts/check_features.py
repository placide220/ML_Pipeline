#!/usr/bin/env python3
"""Verify predict.py can build every feature the trained model expects (names AND prefix).
    python scripts/check_features.py [--model models/best_model.joblib] [--features models/feature_columns.json]
Exit 0 = every expected column can be built; 1 = something is missing."""
import argparse, json, sys
from pathlib import Path
import joblib, numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import predict

p = argparse.ArgumentParser()
p.add_argument("--model", type=Path, default=Path("models/best_model.joblib"))
p.add_argument("--features", type=Path, default=Path("models/feature_columns.json"))
p.add_argument("--target-col")
a = p.parse_args()

model = joblib.load(a.model)
expected = predict.peek_feature_columns(a.features) or list(getattr(model, "feature_names_in_", []))
if not expected:
    sys.exit("No saved feature list and the model has no feature_names_in_.")
if hasattr(model, "feature_names_in_") and list(model.feature_names_in_) != expected:
    print("WARNING: feature_columns.json differs from model.feature_names_in_ (order or names)")

target = a.target_col or predict.infer_target_col(expected)
n = predict.history_days_for(expected) * 24
idx = pd.date_range("2010-01-01", periods=n, freq="h")
hist = pd.Series(np.random.default_rng(0).random(n) + 0.5, idx)
built = predict.build_features(hist, idx[-1] + pd.Timedelta(hours=1), expected, target)

missing = [c for c in expected if c not in built]
nan = [c for c in expected if c in built and pd.isna(built[c])]
print(f"model expects ({len(expected)}): {expected}")
print(f"target prefix used: {target}")
print("CANNOT BUILD:", missing or "none")
print("NaN with a full history window:", nan or "none")
print("Lags parsed:", predict._numbers(expected, "lag"), "| rolling windows parsed:", predict._numbers(expected, "roll"))
sys.exit(1 if missing or nan else 0)
