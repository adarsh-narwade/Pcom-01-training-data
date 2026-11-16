"""Features shared by training (05_train.py) and prediction (predict.py).
Everything here only uses columns of the PCOM-01 record schema, so a row of the competition
input file can be turned into features in the same way as a row of the training data."""
import math
import re
from datetime import datetime, timezone

SEVS = ["low", "moderate", "high", "critical", "unknown"]
TARGETS = [f"target_ghsa_{s}_count_90d" for s in SEVS]
MONTHS = 12
NAN = float("nan")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(.*)$")


def num(x):
    """Cell -> float. Empty or broken cells become NaN (= unknown)."""
    try:
        return float(x) if x not in (None, "") else NAN
    except ValueError:
        return NAN


def ts(x):
    """RFC 3339 timestamp -> epoch seconds (NaN if missing)."""
    try:
        return datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (AttributeError, ValueError):
        return NAN


def split_purl(purl):
    """pkg:npm/%40scope/name@1.2.3 -> ('@scope/name', '1.2.3')"""
    body = purl.split("pkg:npm/", 1)[-1]
    name, _, version = body.rpartition("@")
    return name.replace("%40", "@"), version.split("?")[0].split("#")[0]


def version_key(purl):
    """Sort key for 'latest = highest semantic version'. Prereleases rank below stable ones."""
    _, version = split_purl(purl)
    m = _SEMVER.match(version.split("+")[0])
    if not m:
        return (-1, 0, 0, 0)
    stable = 0 if m.group(4).startswith("-") else 1
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), stable)


def _sum(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return float(sum(vals)) if vals else NAN


def _log1p(v):
    return math.log1p(v) if not math.isnan(v) and v >= 0 else NAN


def _cols(row, pattern):
    return [num(row.get(pattern.format(k=k), "")) for k in range(MONTHS)]


FEATURE_NAMES = (
    ["package_age_days", "dependency_count", "optional_dependency_count", "peer_dependency_count",
     "dev_dependency_count", "bundled_dependency_count", "log_unpacked_size", "log_file_count",
     "releases_last3", "releases_last6", "releases_last12"]
    + [f"ghsa_{s}_history" for s in SEVS] + ["ghsa_total_history", "ghsa_older_than_12m"]
    + [f"ghsa_{s}_last{w}" for s in SEVS + ["total"] for w in (3, 6, 12)]
    + ["months_since_last_advisory", "advisory_months_in_last12"]
)


def features(row):
    """One schema row (dict of strings) -> list of floats, in FEATURE_NAMES order."""
    created, published = ts(row.get("package_created_at")), ts(row.get("published_at"))
    f = [(published - created) / 86400.0]
    f += [num(row.get(c, "")) for c in ("dependency_count", "optional_dependency_count",
                                        "peer_dependency_count", "dev_dependency_count",
                                        "bundled_dependency_count")]
    f += [_log1p(num(row.get("unpacked_size", ""))), _log1p(num(row.get("file_count", "")))]
    rel = _cols(row, "package_stable_release_count_M{k}")
    f += [_sum(rel[:3]), _sum(rel[:6]), _sum(rel[:12])]
    hist = [num(row.get(f"ghsa_{s}_count", "")) for s in SEVS]
    total_hist = _sum(hist)
    monthly = {s: _cols(row, f"ghsa_{s}" + "_count_M{k}") for s in SEVS}
    monthly["total"] = [_sum([monthly[s][k] for s in SEVS]) for k in range(MONTHS)]
    last12_total = _sum(monthly["total"])
    f += hist + [total_hist,
                 max(total_hist - last12_total, 0.0) if not math.isnan(total_hist + last12_total) else NAN]
    for s in SEVS + ["total"]:
        f += [_sum(monthly[s][:3]), _sum(monthly[s][:6]), _sum(monthly[s][:12])]
    active = [k for k in range(MONTHS) if monthly["total"][k] > 0]
    f += [float(min(active)) if active else float(MONTHS + 1), float(len(active))]
    assert len(f) == len(FEATURE_NAMES)
    return f
