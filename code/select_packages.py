# Step 2: choose packages -> data/packages.csv (group = popular_random | advisory_enriched).
# popular_random: random sample of popular packages from the npm search API. Advisory status is NOT used to choose them, so some of them get advisories later, as in real life.
# advisory_enriched: extra random sample of packages with at least one non-withdrawn GHSA, to get more positive rows. (Picking packages by 'never had an advisory' would hide the answer in the sampling, so that is deliberately not done.)

import csv, json, random, urllib.parse, urllib.request

N_EACH, SEED = 120, 42
QUERIES = ["utility", "cli", "react", "express", "typescript", "logger", "http", "date", "test",
           "parser", "validator", "stream", "webpack", "babel", "eslint", "async", "string", "json"]
rows = list(csv.DictReader(open("data/ghsa_npm_advisories.csv", encoding="utf-8")))
all_adv = {r["package"] for r in rows}
live_adv = sorted({r["package"] for r in rows if not r["withdrawn"]})

def search(q, offset):
    url = "https://registry.npmjs.org/-/v1/search?" + urllib.parse.urlencode(
        {"text": q, "size": 250, "from": offset, "popularity": 1.0, "quality": 0.1, "maintenance": 0.1})
    req = urllib.request.Request(url, headers={"User-Agent": "pcom-01-student-project"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return [o["package"]["name"] for o in json.load(r)["objects"]]

pool = []
for q in QUERIES:
    for off in (0, 250):
        try: pool += search(q, off)
        except Exception as e: print("search failed", q, off, e)
pool = sorted(set(pool))
rnd = random.Random(SEED)
popular = rnd.sample(pool, min(N_EACH, len(pool)))
rest = [n for n in live_adv if n not in set(popular)]
chosen = [(n, "popular_random") for n in popular]
chosen += [(n, "advisory_enriched") for n in rnd.sample(rest, min(N_EACH, len(rest)))]
with open("data/packages.csv", "w", newline="") as fh:
    w = csv.writer(fh, lineterminator="\n"); w.writerow(["package", "group"]); w.writerows(chosen)
print(len(chosen), "packages;", "popular candidates:", len(pool))
