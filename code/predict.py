#!/usr/bin/env python3
"""Prediction function for PCOM-01.

    python code/predict.py INPUT.csv [OUTPUT.csv] [--threshold 0.5] [--expected]

INPUT.csv  rows of ONE npm package in the PCOM-01 record schema (one row per stable version).
OUTPUT.csv one record with the five prediction-goal columns (default: prediction.csv):
           target_ghsa_{low,moderate,high,critical,unknown}_count_90d
           Default: whole-number counts. With --expected: expected counts as decimals
           (probability x typical count), for float form fields or error-based scoring.
The latest version (highest semantic version) is the one that is predicted.
Runs in about 2 to 3 seconds. If the model file cannot be loaded, a simple rule is used instead."""
import argparse
import csv
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from features import FEATURE_NAMES, SEVS, TARGETS, features, num, split_purl, version_key  # noqa: E402

MODEL_PATH = os.path.join(HERE, "..", "model", "model.joblib")


def read_latest_row(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("purl") or "").strip()]
    if not rows:
        sys.exit("error: the input file has no rows with a purl")
    for need in ("purl", "published_at"):
        if need not in rows[0]:
            sys.exit(f"error: column '{need}' is missing in the input file")
    first_pkg = split_purl(rows[0]["purl"])[0]
    same = [r for r in rows if split_purl(r["purl"])[0] == first_pkg]
    if len(same) != len(rows):
        print(f"warning: file has more than one package, using {first_pkg}", file=sys.stderr)
    return max(same, key=lambda r: version_key(r["purl"]))


def rule_fallback(row):
    """No model: predict 1 for a severity that had an advisory in the last 3 months."""
    out = []
    for s in SEVS:
        recent = [num(row.get(f"ghsa_{s}_count_M{k}", "")) for k in range(3)]
        out.append(1 if any(v > 0 for v in recent) else 0)      # NaN > 0 is False
    return out


def predict_counts(row, threshold=None):
    """Returns (whole-number counts, probabilities, expected counts)."""
    try:
        import joblib
        import numpy as np
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bundle = joblib.load(MODEL_PATH)
        assert bundle["feature_names"] == FEATURE_NAMES
        x = np.array([features(row)], dtype=float)
        thr = bundle["threshold"] if threshold is None else threshold
        counts, probs = [], []
        for s in SEVS:
            m = bundle["models"][s]
            p = 0.0
            if m is not None:
                pg = float(m["gbdt"].predict_proba(x)[0, 1])
                xl = np.nan_to_num(x, nan=0.0)
                pl = float(m["logreg"].predict_proba(np.sign(xl) * np.log1p(np.abs(xl)))[0, 1])    # same as prep_lr in 05_train.py
                p = {"gbdt": pg, "logreg": pl, "mean": (pg + pl) / 2}[bundle["method"]]
            probs.append(round(p, 3))
            counts.append(int(bundle["typical_count"][s]) if p >= thr else 0)
        expected = [round(pr * int(bundle["typical_count"][s]), 4) for s, pr in zip(SEVS, probs)]
        return counts, probs, expected
    except Exception as e:                      # never fail without writing an answer
        print(f"warning: model not usable ({type(e).__name__}: {e}); using the fallback rule. "
              f"Run 'python code/05_train.py' to rebuild it.", file=sys.stderr)
        return rule_fallback(row), None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output", nargs="?", default="prediction.csv")
    ap.add_argument("--threshold", type=float, default=None, help="probability needed to predict a count above 0")
    ap.add_argument("--expected", action="store_true", help="write expected counts (decimals) instead of whole numbers")
    a = ap.parse_args()
    row = read_latest_row(a.input)
    counts, probs, expected = predict_counts(row, a.threshold)
    values = expected if (a.expected and expected is not None) else counts
    with open(a.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(TARGETS)
        w.writerow(values)
    print(f"{row['purl']} -> {dict(zip(SEVS, counts))}"
          + (f"  probabilities {dict(zip(SEVS, probs))}  expected counts {dict(zip(SEVS, expected))}" if probs else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()
