# Step 3: build data/training_data.csv, one row per stable npm version.

# Assumptions (see README): prediction time P = published_at of the row;
# M0 = last full UTC calendar month before the month of P, M1 the month before, ...;
# GHSA counts are per package (any affected version), withdrawn advisories are excluded;
# rows whose 90-day window is not finished at the advisory snapshot are left out.
import bisect, csv, json, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from schema import COLUMNS, MONTHS, SEVS

WINDOW = timedelta(days=90)
MAX_STABLE_VERSIONS = 3000
STABLE = re.compile(r"^\d+\.\d+\.\d+$")

def parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

def month_start(dt, back):
    idx = dt.year * 12 + dt.month - 1 - back
    return datetime(idx // 12, idx % 12 + 1, 1, tzinfo=timezone.utc)

def count_in(sorted_ts, lo, hi):          # lo <= x < hi
    return bisect.bisect_left(sorted_ts, hi) - bisect.bisect_left(sorted_ts, lo)

def size(x):
    return len(x) if isinstance(x, (dict, list)) else 0

def make_purl(name, version):
    if name.startswith("@"):
        scope, rest = name[1:].split("/", 1)
        return f"pkg:npm/%40{urllib.parse.quote(scope, safe='')}/{urllib.parse.quote(rest, safe='')}@{version}"
    return f"pkg:npm/{urllib.parse.quote(name, safe='')}@{version}"

def fetch(name):
    url = "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@")
    last = None
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pcom-01-student-project"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return name, json.load(r)
        except Exception as e:
            last = e; time.sleep(2 * (i + 1))
    print("FAILED", name, last, file=sys.stderr)
    return name, None

snap = parse(open("data/SNAPSHOT.txt").read().strip().split(",")[1])
adv = defaultdict(lambda: {s: [] for s in SEVS})
for r in csv.DictReader(open("data/ghsa_npm_advisories.csv", encoding="utf-8")):
    if r["withdrawn"]:
        continue
    sev = r["severity"].lower()
    sev = sev if sev in SEVS[:4] else "unknown"
    adv[r["package"]][sev].append(parse(r["published"]).timestamp())
for p in adv.values():
    for s in SEVS:
        p[s].sort()

def build_rows(name, doc):
    t, versions = doc.get("time", {}), doc.get("versions", {})
    if "created" not in t:
        return [], "no created time"
    stable = [v for v in versions if STABLE.match(v) and v in t]
    if len(stable) > MAX_STABLE_VERSIONS:
        return [], "too many versions"
    created = fmt(parse(t["created"]))
    rel = sorted(parse(t[v]).timestamp() for v in stable)
    a = adv.get(name, {s: [] for s in SEVS})
    out = []
    for v in sorted(stable, key=lambda x: tuple(map(int, x.split(".")))):
        P = parse(t[v])
        if P + WINDOW > snap:
            continue                      # outcome window not finished
        m, dist = versions[v], versions[v].get("dist") or {}
        bd = m.get("bundleDependencies", m.get("bundledDependencies"))
        bundled = len(m.get("dependencies") or {}) if bd is True else (len(set(bd)) if isinstance(bd, list) else 0)
        row = {"purl": make_purl(name, v), "package_created_at": created, "published_at": fmt(P),
               "unpacked_size": dist.get("unpackedSize"), "file_count": dist.get("fileCount"),
               "dependency_count": size(m.get("dependencies")),
               "optional_dependency_count": size(m.get("optionalDependencies")),
               "peer_dependency_count": size(m.get("peerDependencies")),
               "dev_dependency_count": size(m.get("devDependencies")),
               "bundled_dependency_count": bundled}
        pts, end = P.timestamp(), (P + WINDOW).timestamp()
        for k in range(MONTHS):
            lo, hi = month_start(P, k + 1).timestamp(), month_start(P, k).timestamp()
            row[f"package_stable_release_count_M{k}"] = count_in(rel, lo, hi)
            for s in SEVS:
                row[f"ghsa_{s}_count_M{k}"] = count_in(a[s], lo, hi)
        for s in SEVS:
            row[f"ghsa_{s}_count"] = bisect.bisect_left(a[s], pts)                       # published before P
            row[f"target_ghsa_{s}_count_90d"] = bisect.bisect_right(a[s], end) - bisect.bisect_right(a[s], pts)
        out.append(row)
    return out, "ok"

pkgs = list(csv.DictReader(open("data/packages.csv")))
groups = {r["package"]: r["group"] for r in pkgs}
stats = defaultdict(lambda: {"packages": 0, "rows": 0, "rows_with_new_ghsa": 0})
skipped = []
with open("data/training_data.csv", "w", newline="", encoding="utf-8") as fh, \
     ThreadPoolExecutor(max_workers=8) as ex:
    w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n"); w.writeheader()
    for name, doc in ex.map(fetch, [r["package"] for r in pkgs]):
        if doc is None:
            skipped.append((name, "download failed")); continue
        rows, why = build_rows(name, doc)
        if why != "ok":
            skipped.append((name, why)); continue
        g = stats[groups[name]]; g["packages"] += 1; g["rows"] += len(rows)
        g["rows_with_new_ghsa"] += sum(1 for r in rows if any(r[f"target_ghsa_{s}_count_90d"] for s in SEVS))
        w.writerows(rows)                  # None is written as an empty cell = NULL
summary = {"snapshot": snap.isoformat(), "groups": stats, "skipped": skipped}
json.dump(summary, open("data/build_summary.json", "w"), indent=2)
print(json.dumps(summary, indent=2))
