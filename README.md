# PCOM-01 training data (Homework 3)

Training data for predicting new npm vulnerabilities in the 90 days after a package version.
One row per stable npm version, following the PCOM-01 record schema (224 columns, 78 required).

## What is in this repo

- `data/training_data.csv`: the dataset (13,380 rows from 225 packages; 240 were picked, 15 had no usable rows). Empty cell = NULL.
- `data/packages.csv`: which packages were picked and why.
- `data/ghsa_npm_advisories.csv`: flat copy of the GitHub-reviewed npm advisories used for the GHSA columns.
- `data/SNAPSHOT.txt`: commit hash and date of the advisory database that was used.
- `data/build_summary.json`: rows and positives per group.
- `code/`: the four scripts that make everything. Standard library only, Python 3.11 or newer.

## How to rebuild it

```
git clone --depth 1 --filter=blob:none --sparse https://github.com/github/advisory-database.git advisory-database
git -C advisory-database sparse-checkout set advisories/github-reviewed
python code/extract_advisories.py advisory-database
python code/select_packages.py
python code/build_dataset.py
python code/validate.py
```

The npm search results change over time, so step 2 can pick other packages on a later run.
Use the committed `data/packages.csv` to get the same packages again (skip step 2).

## Sources

- npm registry (`registry.npmjs.org`): publish times, dependency lists, tarball size, file count.
- GitHub Advisory Database (GitHub-reviewed advisories, ecosystem npm): all GHSA columns and targets.

## Which columns are filled

- Filled: `purl`, `package_created_at`, `published_at`, the five dependency counts, `unpacked_size` and
  `file_count` (empty for old versions that do not have them), `package_stable_release_count_M0..M11`,
  all `ghsa_*` columns and all `target_*` columns.
- Empty (NULL) for now: `package_downloads_*` and `package_download_days_observed_*` (the npm downloads API
  was not reachable when I built this), and all GitHub issue and pull request series (rate limits without a token).
  These are optional in the schema. I plan to add them later.

## Choices I made (please check against the Documentation tab of the schema)

- The prediction time of a row is its `published_at`.
- `M0` is the last full UTC calendar month before the month of `published_at`. `M1` is the month before that, and so on.
- GHSA counts are per package. A GHSA counts if it names the package, whatever versions it lists as affected.
- Withdrawn advisories are left out. Each GHSA is counted once per package.
- History counts use advisories published before `published_at`. Targets use advisories published in the 90 days after it.
- Severity is the severity in the current advisory snapshot, not the severity on the prediction date.
- Only stable versions (`x.y.z`) are used. Rows whose 90-day window had not finished at the snapshot date are left out.
- `bundled_dependency_count` counts the names in `bundleDependencies`. If it is `true`, all `dependencies` count.

## Packages and a bias to know about

- 120 `popular_random`: random popular packages from the npm search API. I did not look at their advisories when picking them.
- 120 `advisory_enriched`: random packages that have at least one advisory, added to get more positive rows.
- Because of the second group, positives are more common here (5.3% of rows) than in all of npm. Do not read the
  positive rate as a real-world rate.
- Many rows of one package look alike. Split train and test by time, and keep whole packages together if possible.

## Checks

`code/04_validate.py` checks the column list, required fields, unique purls, timestamp format, non-negative integers,
and that the 12 monthly GHSA counts never exceed the full-history count. It reports 0 errors on the committed data.
