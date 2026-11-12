"""Shared helpers: settings, paths, cached downloads, run log."""
from __future__ import annotations

import json
import os
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUTPUT = ROOT / "output"
RUN_LOG = ROOT / "data" / "run_log.jsonl"

load_dotenv(ROOT / ".env")
# where finished spreadsheets are copied for review (optional; set UPLOADS_DIR in .env). Unset: files stay in the
# project only.
UPLOADS = Path(os.environ["UPLOADS_DIR"]) if os.environ.get("UPLOADS_DIR") else None


def to_uploads(f) -> None:
    """Copy a finished file to UPLOADS_DIR when it is set."""
    import shutil
    if UPLOADS:
        shutil.copy(f, UPLOADS / Path(f).name)
UA = "gtm-signals research script (python-requests)"


def settings() -> dict:
    with open(ROOT / "settings.toml", "rb") as f:
        return tomllib.load(f)


def log(source: str, event: str, **kw) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source, "event": event, **kw}
    with open(RUN_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def fetch(url: str, dest: Path, source: str, *, headers: dict | None = None, params: dict | None = None,
          auth=None, retries: int = 5, min_bytes: int = 1) -> Path:
    """Download url to dest once. If dest exists, reuse it (never fetch twice)."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = {"User-Agent": UA, **(headers or {})}
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = requests.get(url, headers=h, params=params, auth=auth, timeout=300, stream=True)
        except requests.RequestException as e:
            log(source, "error", url=url, error=str(e)[:200], attempt=attempt)
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            wait = int(r.headers.get("Retry-After", 30 * (attempt + 1)))
            log(source, "rate_limit_pause" if r.status_code == 429 else "server_error",
                url=url, status=r.status_code, wait_s=wait)
            time.sleep(wait)
            continue
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        tmp.rename(dest)
        log(source, "download", url=url, bytes=dest.stat().st_size, secs=round(time.time() - t0, 1))
        return dest
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


def paths() -> dict:
    """Where Steps 3-5 read and write. settings.toml [run] scope: "pilot" (the 300-group sample) or "full"
    (every group, Step 7). The pilot's files are left untouched by a full run."""
    if settings()["run"].get("scope", "pilot") == "pilot":
        s3, s4 = OUTPUT / "step3", OUTPUT / "step4"
        return dict(scope="pilot", groups=s3 / "pilot_groups.csv", entities=s3 / "pilot_entities.csv",
                    signals=s3 / "signals.csv", review=s3 / "review.csv", signals_report=s3 / "signals_report.json",
                    dir4=s4, ranked=s4 / "pilot_ranked.csv", scored=s4 / "pilot_signals_scored.csv",
                    score_report=s4 / "score_report.json", xlsx=s4 / "pilot_ranked.xlsx",
                    sample=INTERIM / "classify_sample.csv", classified=INTERIM / "job_classified.csv",
                    briefs=INTERIM / "briefs.csv", ch_signals=INTERIM / "ch_signals.csv", smf=INTERIM / "fca_smf.csv")
    f = OUTPUT / "full"
    return dict(scope="full", groups=f / "groups.csv", entities=f / "entities.csv", signals=f / "signals.csv",
                review=f / "review.csv", signals_report=f / "signals_report.json", dir4=f, ranked=f / "ranked.csv",
                scored=f / "signals_scored.csv", score_report=f / "score_report.json", xlsx=f / "ranked.xlsx",
                sample=INTERIM / "classify_full_input.csv", classified=INTERIM / "job_classified_full.csv",
                briefs=INTERIM / "briefs_full.csv", ch_signals=INTERIM / "ch_signals_full.csv",
                smf=INTERIM / "fca_smf_full.csv")


def pace(name: str, gap: float) -> None:
    """Wait so that calls to one API, across every running process, are at least `gap` seconds apart
    (a shared timestamp file under a lock), so two scripts running at once never exceed the rate limit."""
    import fcntl
    p = RAW / f".pace_{name}"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read().strip() or 0)
        except ValueError:
            last = 0.0
        wait = gap - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time())); f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
