"""PCOM-01 prediction service (based on riehlegroup/pcom-course-setup).

Put this file in the root of the pcom-01-training-data repo, next to code/ and model/.
It calls code/predict.py unchanged, so the CLI and the service give the same answer.
"""
import io
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import pandas as pd
import requests
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.abspath(__file__))
PREDICT_SCRIPT = os.path.join(ROOT, "code", "predict.py")
LOG_FILE = os.path.join(ROOT, "service.log")
SEVERITIES = ["low", "moderate", "high", "critical", "unknown"]
TARGETS = [f"target_ghsa_{s}_count_90d" for s in SEVERITIES]
EXTRA_ARGS = os.environ.get("PCOM_PREDICT_ARGS", "").split()  # e.g. "--expected"

app = FastAPI(title="PCOM-01 Prediction API")


class EvaluationBody(BaseModel):
    testdata_download_endpoint: str
    prediction_upload_endpoint: str


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def add_purl_if_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Round inputs come without purl. predict.py picks the latest version from purl,
    so build a stand-in purl that orders versions by published_at."""
    if "purl" in df.columns and df["purl"].notna().all():
        return df
    df = df.copy()
    order = pd.to_datetime(df["published_at"], utc=True, errors="coerce").rank(method="first")
    df["purl"] = [f"pkg:npm/unknown@0.0.{int(r)}" for r in order.fillna(0)]
    log("input had no purl: added stand-in purl ordered by published_at")
    return df


def rule_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """Backup answer: 1 if the package had an advisory of that severity in the last 3 months."""
    row = {}
    for s, t in zip(SEVERITIES, TARGETS):
        cols = [f"ghsa_{s}_count_M{i}" for i in range(3) if f"ghsa_{s}_count_M{i}" in df.columns]
        recent = pd.to_numeric(df[cols].iloc[-1], errors="coerce").fillna(0).sum() if cols else 0
        row[t] = 1 if (recent > 0 and s != "unknown") else 0
    return pd.DataFrame([row])


def clean_output(pred: pd.DataFrame) -> pd.DataFrame:
    """Exactly one row, exactly the five target columns, no NaN, no negatives."""
    row = {}
    for t in TARGETS:
        value = pd.to_numeric(pred[t].iloc[0], errors="coerce") if t in pred.columns else 0
        value = 0 if pd.isna(value) else max(float(value), 0.0)
        row[t] = int(value) if value.is_integer() else round(value, 4)
    return pd.DataFrame([row], columns=TARGETS)


def run_model(df: pd.DataFrame) -> pd.DataFrame:
    try:
        df = add_purl_if_missing(df)
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = os.path.join(tmp, "input.csv"), os.path.join(tmp, "output.csv")
            df.to_csv(inp, index=False)
            proc = subprocess.run(
                [sys.executable, PREDICT_SCRIPT, inp, out, *EXTRA_ARGS],
                capture_output=True, text=True, timeout=60, cwd=ROOT,
            )
            if proc.stderr.strip():
                log(f"predict.py stderr: {proc.stderr.strip()[:2000]}")
            if proc.returncode != 0:
                raise RuntimeError(f"predict.py exit code {proc.returncode}")
            pred = pd.read_csv(out)
        result = clean_output(pred)
        log(f"model prediction: {result.to_dict('records')[0]}")
        return result
    except Exception as e:  # never send nothing: use the rule instead
        log(f"model failed ({e}); using rule fallback")
        return clean_output(rule_fallback(df))


def start_prediction(download_url: str, upload_url: str) -> None:
    try:
        res = requests.get(download_url, timeout=30)
        res.raise_for_status()
        input_data = pd.read_csv(io.StringIO(res.text), sep=",", decimal=".")
        log(f"downloaded input: {input_data.shape[0]} rows, {input_data.shape[1]} columns")

        prediction = run_model(input_data)
        assert len(prediction) == 1, "Prediction DataFrame must contain exactly 1 row"

        buf = io.StringIO()
        prediction.to_csv(buf, sep=",", decimal=".", header=True, index=False)
        files = {"predictions": ("prediction.csv", buf.getvalue(), "text/csv")}
        up = requests.post(upload_url, files=files, timeout=30)
        up.raise_for_status()
        log(f"upload ok: {up.text[:500]}")
    except Exception as e:
        log(f"ERROR in start_prediction: {e}")


@app.post("/predict", status_code=200)
async def prediction(payload: EvaluationBody, background_tasks: BackgroundTasks):
    log("received /predict call")
    background_tasks.add_task(
        start_prediction, payload.testdata_download_endpoint, payload.prediction_upload_endpoint
    )
    return {"status": "prediction started"}


@app.get("/health", status_code=200)
async def health():
    return {"health": "up"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
