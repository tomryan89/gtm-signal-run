"""Companies House API client. Every response is cached in data/raw/ch/<kind>/; nothing is fetched twice.
Rate limit: 600 requests per 5 minutes. We pace at ~1.9/s and honour 429 + the rate-limit headers."""
import json
import os
import time

import requests

from common import RAW, log, pace

BASE = "https://api.company-information.service.gov.uk"
_session = requests.Session()
_last = [0.0]
MIN_GAP = 0.52  # seconds between requests -> ~577 per 5 min


def _key():
    k = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
    if not k:
        raise SystemExit("COMPANIES_HOUSE_API_KEY missing from .env")
    return k


def get(path: str, kind: str, cache_id: str, params: dict | None = None):
    """GET BASE+path, cached as data/raw/ch/<kind>/<cache_id>.json. Returns dict, or None for 404."""
    dest = RAW / "ch" / kind / f"{cache_id}.json"
    if dest.exists():
        d = json.loads(dest.read_text())
        return None if d.get("_status") == 404 else d
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(8):
        pace("companies_house", MIN_GAP)
        try:
            r = _session.get(BASE + path, params=params, auth=(_key(), ""), timeout=60)
        except requests.RequestException as e:
            log("companies_house", "error", path=path, error=str(e)[:200])
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 401:
            raise SystemExit("Companies House rejected the API key (401). Check COMPANIES_HOUSE_API_KEY in .env.")
        if r.status_code == 429:
            reset = r.headers.get("X-Ratelimit-Reset")
            pause = max(5, int(reset) - int(time.time())) if reset and reset.isdigit() else 60
            log("companies_house", "rate_limit_pause", path=path, wait_s=pause)
            time.sleep(min(pause, 330))
            continue
        if r.status_code >= 500:
            log("companies_house", "server_error", path=path, status=r.status_code)
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            dest.write_text(json.dumps({"_status": 404}))
            log("companies_house", "not_found", path=path)
            return None
        r.raise_for_status()
        dest.write_text(r.text)
        log("companies_house", "request", path=path)
        return r.json()
    log("companies_house", "gave_up", path=path)
    raise RuntimeError(f"Companies House: gave up on {path}")


def profile(number: str):
    return get(f"/company/{number}", "profile", number)
