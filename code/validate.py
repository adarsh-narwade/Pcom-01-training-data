# Step 4: check data/training_data.csv against the record schema rules. Exit code 1 on errors.
import csv, re, sys
from schema import COLUMNS, MONTHS, REQUIRED, SEVS, TIMESTAMPS
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
errors, warns, seen = [], 0, set()
with open("data/training_data.csv", encoding="utf-8") as fh:
    rd = csv.DictReader(fh)
    if rd.fieldnames != COLUMNS:
        sys.exit("header does not match the schema column list")
    for n, r in enumerate(rd, start=2):
        def bad(msg): errors.append(f"line {n}: {msg}")
        p = r["purl"]
        if p in seen: bad("duplicate purl")
        seen.add(p)
        if not p.startswith("pkg:npm/") or len(p) > 2048 or "@" not in p[8:]: bad("bad purl " + p[:60])
        for c in REQUIRED:
            if r[c] == "": bad(f"required {c} is empty")
        for c in TIMESTAMPS:
            if not TS.match(r[c]): bad(f"{c} wrong format")
        for c in COLUMNS:
            if c in TIMESTAMPS or c == "purl" or r[c] == "": continue
            if not r[c].isdigit(): bad(f"{c} must be an integer >= 0")
        if r["published_at"] < r["package_created_at"]: warns += 1
        for s in SEVS:   # the last 12 full months can never exceed the full history
            tot = sum(int(r[f"ghsa_{s}_count_M{k}"]) for k in range(MONTHS))
            if tot > int(r[f"ghsa_{s}_count"]): bad(f"{s}: monthly sum exceeds history")
print("rows checked:", len(seen), "| errors:", len(errors), "| published_at before package_created_at (warning):", warns)
for e in errors[:20]: print(e)
sys.exit(1 if errors else 0)
