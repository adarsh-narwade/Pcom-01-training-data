# Step 1: flatten GitHub-reviewed npm advisories into data/ghsa_npm_advisories.csv.
import csv, glob, json, os, subprocess, sys

adv_dir = sys.argv[1] if len(sys.argv) > 1 else "advisory-database"
rows = []
for f in glob.glob(os.path.join(adv_dir, "advisories/github-reviewed/*/*/*/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    names = {a["package"]["name"] for a in d.get("affected", [])
             if a["package"].get("ecosystem") == "npm"}
    for n in names:
        rows.append({"ghsa_id": d["id"], "package": n, "published": d["published"],
                     "severity": (d.get("database_specific", {}).get("severity") or "").upper(),
                     "withdrawn": d.get("withdrawn", "")})
rows.sort(key=lambda r: (r["package"], r["published"], r["ghsa_id"]))
os.makedirs("data", exist_ok=True)
with open("data/ghsa_npm_advisories.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader(); w.writerows(rows)
head = subprocess.check_output(["git", "-C", adv_dir, "log", "-1", "--format=%H,%cI"]).decode().strip()
open("data/SNAPSHOT.txt", "w").write(head + "\n")
print(len(rows), "advisory-package pairs; snapshot", head)
