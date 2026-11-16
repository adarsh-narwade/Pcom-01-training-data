"""Step 5: evaluate the approach and train the final model -> model/model.joblib, model/metrics.json.

Evaluation (strict, 5 folds): packages are put into 5 groups by a hash of the package name. For each group,
the model is trained on the other packages' rows before a cut date and tested on this group's rows after it.
So the model never sees the test packages or the test period. Results of the 5 folds are pooled.

Run on your own machine before the competition round, so the saved model matches your scikit-learn version:
    python code/05_train.py"""
import csv, hashlib, json, math, os, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
from features import FEATURE_NAMES, SEVS, TARGETS, features, split_purl, ts

DATA, MODEL_DIR = "data/training_data.csv", "model"
THRESHOLD = 0.5          # predict "at least one" only if the model is more than 50% sure
MIN_POS_ROWS, MIN_POS_PKGS = 20, 4

rows = list(csv.DictReader(open(DATA, encoding="utf-8")))
X = np.array([features(r) for r in rows], dtype=float)
Y = np.array([[int(r[t]) for t in TARGETS] for r in rows])            # counts per severity
pkg = np.array([split_purl(r["purl"])[0] for r in rows])
when = np.array([ts(r["published_at"]) for r in rows])
n_rows = Counter(pkg)
# Sampling correction. The sample has extra packages picked because they have advisories. Using the random
# popular packages as the natural mix, give "has advisory" and "never had one" packages their natural weight.
adv_pkgs = {r["package"] for r in csv.DictReader(open("data/ghsa_npm_advisories.csv", encoding="utf-8")) if not r["withdrawn"]}
group = {r["package"]: r["group"] for r in csv.DictReader(open("data/packages.csv"))}
has_adv = {p: p in adv_pkgs for p in n_rows}
random_pkgs = [p for p in n_rows if group.get(p) == "popular_random"]
share_adv = sum(has_adv[p] for p in random_pkgs) / len(random_pkgs)     # natural share of packages with an advisory
n_adv = sum(has_adv.values())
stratum_w = {True: share_adv * len(n_rows) / n_adv, False: (1 - share_adv) * len(n_rows) / (len(n_rows) - n_adv)}
print(f"natural share of packages with an advisory (from the random group): {share_adv:.3f}")
sw = np.array([stratum_w[has_adv[p]] for p in pkg])                    # evaluation weight of a row
w = sw / np.sqrt([n_rows[p] for p in pkg])                             # training weight: also, packages count about equally
w_lr = w                                                               # logistic regression: small weights are fine
w_gb = w * (30.0 / w.mean())                                           # same ratios, larger scale: trees ignore tiny weights
print(f"{len(rows)} rows, {len(n_rows)} packages, {len(FEATURE_NAMES)} features")
for j, s in enumerate(SEVS):
    pos = Y[:, j] > 0
    print(f"  {s:9s} positive rows {pos.sum():5d} in {len(set(pkg[pos])):3d} packages")


def hgb():
    # With so few positives the trees are forced to be simple: more past advisories can only raise the risk,
    # and a longer time since the last advisory can only lower it.
    cst = [1 if (n.startswith("ghsa_") or n == "advisory_months_in_last12") else (-1 if n == "months_since_last_advisory" else 0)
           for n in FEATURE_NAMES]
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=100,
                                          l2_regularization=1.0, monotonic_cst=cst, random_state=0)


def logreg():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=500))


def prep_lr(A):                                   # logistic regression needs filled cells and tamed counts
    A = np.nan_to_num(A, nan=0.0)
    return np.sign(A) * np.log1p(np.abs(A))


def usable(y, mask):
    pos = mask & (y > 0)
    return pos.sum() >= MIN_POS_ROWS and len(set(pkg[pos])) >= MIN_POS_PKGS


def typical_count(y, mask):
    vals = y[mask & (y > 0)]
    return int(max(1, round(float(np.median(vals))))) if len(vals) else 1


# ---------- evaluation ----------
def fit(Xa, ya, tr):
    g = hgb().fit(Xa, ya, sample_weight=w_gb[tr])
    l = logreg().fit(prep_lr(Xa), ya, logisticregression__sample_weight=w_lr[tr])
    return {"gbdt": g, "logreg": l}


def probs(models, A):
    pg = models["gbdt"].predict_proba(A)[:, 1]
    pl = models["logreg"].predict_proba(prep_lr(A))[:, 1]
    return {"gbdt": pg, "logreg": pl, "mean": (pg + pl) / 2}


cut = float(np.quantile(when, 0.70))
fold = np.array([int(hashlib.md5(p.encode()).hexdigest(), 16) % 5 for p in pkg])
te_all = when >= cut
NAMES = ("gbdt", "logreg", "mean")
P = {n: np.zeros((len(rows), len(SEVS))) for n in NAMES}
for k in range(5):
    tr, te = (fold != k) & (when < cut), (fold == k) & te_all
    for j in range(len(SEVS)):
        if usable(Y[:, j], tr):
            m = fit(X[tr], Y[tr, j] > 0, tr)
            for n, p in probs(m, X[te]).items():
                P[n][te, j] = p
print(f"\nEVALUATION  pooled test rows {te_all.sum()} in {len(set(pkg[te_all]))} packages, rows after "
      f"{datetime.fromtimestamp(cut, timezone.utc):%Y-%m-%d}")
last12 = {s: np.nan_to_num(X[:, FEATURE_NAMES.index(f"ghsa_{s}_last12")]) for s in SEVS}
report = {"cut": datetime.fromtimestamp(cut, timezone.utc).strftime("%Y-%m-%d"), "test_rows": int(te_all.sum()),
          "test_packages": len(set(pkg[te_all])), "natural_share_with_advisory": round(share_adv, 3), "severity": {}}
for j, s in enumerate(SEVS):
    y = Y[te_all, j] > 0
    info = {"test_positive_rows": int(y.sum()), "test_positive_packages": len(set(pkg[te_all][y]))}
    if y.sum():
        info["base_rate"] = round(float(y.mean()), 4)
        info["base_rate_natural_mix"] = round(float(np.average(y, weights=sw[te_all])), 4)
        for n in NAMES + ("rule",):
            sc = last12[s][te_all] if n == "rule" else P[n][te_all, j]
            info[f"pr_auc_{n}"] = round(float(average_precision_score(y, sc)), 3)
            info[f"pr_auc_{n}_natural_mix"] = round(float(average_precision_score(y, sc, sample_weight=sw[te_all])), 3)
    report["severity"][s] = info
    print(s, json.dumps(info))

# score of the whole "any severity" question at different thresholds (any = highest probability over the severities)
any_true = (Y[te_all] > 0).any(axis=1)
report["any_by_threshold"] = {}
for n in NAMES:
    pa = P[n][te_all].max(axis=1)
    for thr in (0.5, 0.3, 0.2, 0.1, 0.05):
        pred = pa >= thr
        tp = float(np.sum(sw[te_all] * (pred & any_true)))
        key = f"{n}@{thr}"
        report["any_by_threshold"][key] = {
            "rows_flagged": int(pred.sum()),
            "precision": round(float((pred & any_true).sum() / max(1, pred.sum())), 3),
            "recall": round(float((pred & any_true).sum() / max(1, any_true.sum())), 3),
            "precision_natural_mix": round(tp / max(1e-9, float(np.sum(sw[te_all] * pred))), 3),
            "recall_natural_mix": round(tp / max(1e-9, float(np.sum(sw[te_all] * any_true))), 3)}
rule_pred = np.array([last12[s][te_all] > 0 for s in SEVS]).any(axis=0)
tp = float(np.sum(sw[te_all] * (rule_pred & any_true)))
report["any_by_threshold"]["rule(advisory in last 12m)"] = {
    "rows_flagged": int(rule_pred.sum()),
    "precision": round(float((rule_pred & any_true).sum() / max(1, rule_pred.sum())), 3),
    "recall": round(float((rule_pred & any_true).sum() / max(1, any_true.sum())), 3),
    "precision_natural_mix": round(tp / max(1e-9, float(np.sum(sw[te_all] * rule_pred))), 3),
    "recall_natural_mix": round(tp / max(1e-9, float(np.sum(sw[te_all] * any_true))), 3)}
print("\nanyone-severity question by threshold (natural_mix = reweighted to the natural package mix):")
for k, v in report["any_by_threshold"].items():
    print(f"  {k:30s} {v}")

# the final method = best pooled natural-mix PR-AUC over moderate and high (the two severities with most positives)
score = {n: np.mean([report["severity"][s].get(f"pr_auc_{n}_natural_mix", 0) for s in ("moderate", "high")]) for n in NAMES}
METHOD = max(score, key=score.get)
report["method_scores"] = {n: round(float(v), 3) for n, v in score.items()}
report["final_method"] = METHOD
print("\nmethod scores", report["method_scores"], "-> final method:", METHOD)

# ---------- final model on all data ----------
models, typical = {}, {}
mask = np.ones(len(rows), bool)
for j, s in enumerate(SEVS):
    typical[s] = typical_count(Y[:, j], mask)
    if usable(Y[:, j], mask):
        models[s] = fit(X, Y[:, j] > 0, mask)
    else:
        models[s] = None
        print(f"  no model for {s}: too few positives, will always predict 0")
os.makedirs(MODEL_DIR, exist_ok=True)
snapshot = open("data/SNAPSHOT.txt").read().strip()
joblib.dump({"models": models, "method": METHOD, "typical_count": typical, "threshold": THRESHOLD,
             "feature_names": FEATURE_NAMES, "sklearn": sklearn.__version__, "n_rows": len(rows),
             "n_packages": len(n_rows), "natural_share_with_advisory": share_adv, "snapshot": snapshot},
            os.path.join(MODEL_DIR, "model.joblib"), compress=3)
json.dump(report, open(os.path.join(MODEL_DIR, "metrics.json"), "w"), indent=1)
print("saved model/model.joblib and model/metrics.json")
