"""Checks of code/predict.py: python tests/test_predict.py   (run from the repository root)"""
import csv, glob, os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRED = [sys.executable, os.path.join(ROOT, "code", "predict.py")]
TARGETS = [f"target_ghsa_{s}_count_90d" for s in ("low", "moderate", "high", "critical", "unknown")]
tmp = tempfile.mkdtemp()
fails = 0


def run(inp, out=None, *extra):
    out = out or os.path.join(tmp, "out.csv")
    if os.path.exists(out):
        os.remove(out)
    t = time.time()
    p = subprocess.run(PRED + [inp, out, *extra], capture_output=True, text=True)
    return p, out, time.time() - t


def check(name, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))


def valid_output(path):
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    return (len(rows) == 2 and rows[0] == TARGETS and len(rows[1]) == 5
            and all(v.isdigit() for v in rows[1]))


samples = sorted(glob.glob(os.path.join(ROOT, "tests", "input_*.csv")))
for f in samples:
    p, out, secs = run(f)
    check(f"{os.path.basename(f)}: valid one-record output, under 10 s", p.returncode == 0 and valid_output(out) and secs < 10, f"{secs:.1f} s")

src = samples[0]
rows = list(csv.DictReader(open(src, newline="")))
fields = list(rows[0])

# decimal output for float form fields
p, out, _ = run(src, None, "--expected")
vals = list(csv.reader(open(out)))[1] if p.returncode == 0 else []
check("--expected writes five decimals between 0 and 1.5", len(vals) == 5 and all(0 <= float(v) <= 1.5 for v in vals), str(vals))

# prerelease with a higher version number must not be chosen as the latest version
pre = dict(rows[0]); pre["purl"] = pre["purl"].rsplit("@", 1)[0] + "@99.0.0-beta.1"
path = os.path.join(tmp, "prerelease.csv")
with open(path, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows + [pre])
p, out, _ = run(path); p0, out0, _ = run(src)
check("prerelease row is ignored", p.returncode == 0 and open(out).read() == open(out0).read())

# optional columns missing (only required ones present)
req = [c for c in fields if not c.startswith(("package_downloads", "package_download_days", "issues_", "pull_requests_"))
       and c not in TARGETS and c not in ("unpacked_size", "file_count")]
path = os.path.join(tmp, "fewer_columns.csv")
with open(path, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=req, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
p, out, _ = run(path)
check("works without optional and target columns", p.returncode == 0 and valid_output(out))

# one row only, windows-style line endings and a byte-order mark
path = os.path.join(tmp, "one_row_crlf.csv")
with open(path, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\r\n"); w.writeheader(); w.writerow(rows[0])
p, out, _ = run(path)
check("single row, CRLF and BOM", p.returncode == 0 and valid_output(out))

# empty cells where numbers should be
bad = dict(rows[0]); [bad.__setitem__(c, "") for c in fields if c.startswith("ghsa_") or c.endswith("dependency_count")]
path = os.path.join(tmp, "blanks.csv")
with open(path, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerow(bad)
p, out, _ = run(path)
check("empty cells do not crash it", p.returncode == 0 and valid_output(out))

# two packages in one file: warns, still answers
other = os.path.join(ROOT, "tests", "input_clean_package.csv")
if len(samples) > 1 and os.path.exists(other):
    path = os.path.join(tmp, "two_packages.csv")
    r2 = list(csv.DictReader(open(other, newline="")))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows[:3] + r2[:3])
    p, out, _ = run(path)
    check("two packages: warning and an answer", p.returncode == 0 and "more than one package" in p.stderr and valid_output(out))

# broken inputs give a clear message, not a traceback
path = os.path.join(tmp, "empty.csv"); open(path, "w").write("purl,published_at\n")
p, _, _ = run(path)
check("empty file: clear error", p.returncode != 0 and "Traceback" not in p.stderr, p.stderr.strip()[:60])

# model file missing or unreadable: falls back to the rule and still writes the answer
model = os.path.join(ROOT, "model", "model.joblib"); backup = model + ".bak"
shutil.move(model, backup)
try:
    p, out, _ = run(src)
    check("no model file: fallback rule answers", p.returncode == 0 and valid_output(out) and "fallback" in p.stderr)
    p, out, _ = run(src, None, "--expected")
    check("no model file, --expected: still writes an answer", p.returncode == 0 and len(list(csv.reader(open(out)))[1]) == 5)
finally:
    shutil.move(backup, model)

print(f"\n{fails} failed" if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
