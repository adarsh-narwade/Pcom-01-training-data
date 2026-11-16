# PCOM-01: predicting new npm vulnerabilities

Training data (Homework 3) and the prediction function (Homework 5) for the PCOM-01 prediction competition.
Given the version history of one npm package, predict how many new GitHub-reviewed security advisories
(GHSAs) the package gets in the 90 days after its latest version, split by severity.

## Quick start

```
pip install -r requirements.txt
python code/05_train.py                                   # trains on data/training_data.csv, writes model/ (about 10 s)
python tests/test_predict.py                              # checks the prediction function
python code/predict.py input.csv result.csv               # the prediction function
```

Run `05_train.py` once on your own machine. The saved model file depends on the scikit-learn version, and
`predict.py` falls back to a simple rule (with a warning) if it cannot read the model.

## The prediction function

`python code/predict.py INPUT.csv [OUTPUT.csv] [--threshold 0.5]`

- Input: CSV with rows of **one** npm package in the PCOM-01 record schema. Order of rows does not matter.
  Prereleases are ignored. The latest version is the highest semantic version, not the newest timestamp.
- Output: a CSV with one record: `target_ghsa_{low,moderate,high,critical,unknown}_count_90d`.
- Runs in about 1 to 2 seconds. The probabilities behind the answer are printed to the terminal.
- `--threshold` is the probability needed to predict a count above 0 (default 0.5). Lower it to flag more packages.

## Approach

- Binary question per severity: will the package get at least one new advisory of this severity in 90 days?
  If yes, the predicted count is the typical count seen in the training data (1 for every severity at the moment).
- 38 features from the record schema: package age, dependency counts, size, release counts, advisory counts
  over the full history and over the last 3, 6 and 12 months, and months since the last advisory.
- Final model: logistic regression (counts are log-transformed). A gradient-boosted tree model (my first plan)
  and an average of both are trained and compared in `05_train.py`. The comparison picks the best method.
- Rows are weighted so that every package counts about equally, and so that packages with advisories have
  their natural share (see below). `unknown` severity never occurs in the data, so it is always predicted 0.

## Evaluation (5 folds, pooled)

Packages are split into 5 groups by a hash of their name. Each group is tested on its rows after 2024-05-31
with a model trained on the other groups' rows before that date. No test package and no test period is
seen in training. 6,845 test rows from 408 packages. Numbers are PR-AUC (higher is better).

| Severity | Positive test rows (packages) | Base rate | Logistic regression | Trees | Rule: advisory in last 12 months |
|---|---|---|---|---|---|
| low | 88 (11) | 0.013 | 0.013 | 0.013 | 0.106 |
| moderate | 221 (30) | 0.032 | 0.193 | 0.073 | 0.096 |
| high | 448 (47) | 0.065 | 0.132 | 0.084 | 0.142 |
| critical | 136 (17) | 0.020 | 0.019 | 0.030 | 0.022 |

Reading this honestly:

- The model is clearly better than chance only for moderate severity. For high severity the simple rule is as good.
  For low and critical nothing beats the base rate by much.
- At threshold 0.5 the model flags very few rows (14 of 6,845) and is right about 79% of the time, but it finds
  under 2% of the packages that get a new advisory. The rule flags 538 rows with 27% precision and 20% recall.
- The positives come from few packages (11 to 47 per severity), so these numbers are noisy.
- Full numbers are in `model/metrics.json`.

## Data

- `data/training_data.csv`: 22,816 rows from 712 packages, 224 columns of the record schema. Empty cell = NULL.
- 747 packages were picked and 712 had usable rows: 500 `popular_random` picks (random popular npm packages,
  chosen without looking at advisories) and 247 `advisory_enriched` picks (chosen because they have at least one
  advisory, to get more positives).
- Long histories are thinned to at most 80 evenly spaced versions per package. Rows whose 90-day window had not
  finished at the advisory snapshot (2026-11-01) are left out.
- Sources: npm registry (versions, dates, dependencies, size) and the GitHub Advisory Database (GHSA columns).
- Columns left empty for now: downloads and the GitHub issue and pull request series. Only
  `package_stable_release_count_M*` is filled among the time series. The model does not use the empty columns.

### Sampling correction

Only 2.2% of the random popular packages ever had an advisory. The extra advisory packages would otherwise make
the model believe that risk is much more common than it is. `05_train.py` therefore gives packages with and
without advisories the weights they have in the random sample.

### Choices still to confirm against the Documentation tab of the schema sheet

- The prediction time of a row is its `published_at`. `M0` is the last full UTC month before it.
- GHSA counts are per package, whatever versions an advisory lists. Withdrawn advisories are excluded.
- Severity is the current severity in the advisory snapshot, not the severity on the prediction date.

## Limits

- Few independent positive packages, and the package choice is partly biased. More packages are the next step.
- Many columns of the schema are still empty. Downloads and GitHub activity may carry real signal.
- The model only knows advisory history, package age, size, dependencies and release activity.
- A prediction of 0 for everything is right most of the time for an average package. The model adds something only
  for packages with a clear recent advisory history.

## Rebuilding the data

```
git clone --depth 1 --filter=blob:none --sparse https://github.com/github/advisory-database.git advisory-database
git -C advisory-database sparse-checkout set advisories/github-reviewed
python code/01_extract_advisories.py advisory-database
python code/02_select_packages.py        # skip to keep data/packages.csv
python code/03_build_dataset.py
python code/04_validate.py
```

## Files

- `code/features.py`: features, shared by training and prediction
- `code/01_extract_advisories.py` to `code/04_validate.py`: data pipeline and checks
- `code/05_train.py`: evaluation and training
- `code/predict.py`: the prediction function
- `model/`: trained model and metrics
- `tests/`: sample inputs and `test_predict.py`
