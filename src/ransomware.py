"""Stage 2 item 3 (Tom, 12 Nov 2026): claimed ransomware victims from ransomware.live (Pro API; written approval for
this project's use is held by Tom - see "ransomware_live_approval" in the project folder).

  python src/ransomware.py pull    # 2 countries x 13 months = 26 calls, 3 s apart (limit 60/minute), saved
  python src/ransomware.py victims # -> data/interim/ransomware_victims.csv

API: GET https://api-pro.ransomware.live/victims/?country=GB&year=2026&month=10 with the X-API-KEY header (key in
.env only). The month filter is the month ransomware.live discovered the listing; the attack date is also kept."""
import json
import os
import sys
import time
from datetime import date

import pandas as pd
import requests

from common import INTERIM, RAW, log, settings

ST = settings()
RUN = date.fromisoformat(ST["run"]["run_date"])
DIR = RAW / "ransomware_live"
COUNTRIES = {"GB": "UK", "IE": "IE"}


def months():
    y, m = RUN.year - 1, RUN.month          # 13 calendar months: the run month a year ago up to the run month
    out = []
    for _ in range(13):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def pull():
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ["RANSOMWARE_LIVE_API_KEY"]
    calls = [(c, y, m) for c in COUNTRIES for y, m in months()]
    print(f"{len(calls)} calls", flush=True)
    for c, y, m in calls:
        f = DIR / f"{c}_{y}_{m:02d}.json"
        if f.exists():
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(5):
            time.sleep(3)
            r = requests.get("https://api-pro.ransomware.live/victims/", headers={"X-API-KEY": key},
                             params={"country": c, "year": y, "month": f"{m:02d}"}, timeout=120)
            if r.status_code == 429:
                w = int(r.headers.get("Retry-After", "60"))
                log("ransomware_live", "rate_limit_pause", seconds=w); time.sleep(w); continue
            break
        log("ransomware_live", "request", country=c, year=y, month=m, status=r.status_code)
        if r.status_code == 200:
            d = r.json()
            d.pop("client", None)                # the account name is not kept
            f.write_text(json.dumps(d))
        else:
            print("status", r.status_code, c, y, m)


def victims():
    rows = []
    since = date(RUN.year - 1, RUN.month, RUN.day).isoformat()
    for f in sorted(DIR.glob("*.json")):
        for v in json.loads(f.read_text()).get("victims", []):
            ad = (v.get("attackdate") or "")[:10]
            dd = (v.get("discovered") or "")[:10]
            dt = min(x for x in (ad, dd) if x) if (ad or dd) else ""
            rows.append(dict(victim_id=v.get("id", ""), victim=v.get("victim", ""), website=v.get("website", ""),
                             country=COUNTRIES.get(v.get("country", ""), v.get("country", "")),
                             sector=v.get("activity", ""), ransomware_group=v.get("group", ""),
                             attack_date=ad, discovered=dd, date=dt, press=v.get("press") or "",
                             permalink=v.get("permalink", ""), description=(v.get("description") or "")[:300]))
    V = pd.DataFrame(rows).drop_duplicates("victim_id")
    V = V[V.date >= since]
    V.to_csv(INTERIM / "ransomware_victims.csv", index=False)
    log("ransomware_live", "victims", n=len(V), **{k: int(v) for k, v in V.country.value_counts().items()})
    print(len(V), "victims"); print(V.country.value_counts().to_string())


if __name__ == "__main__":
    {"pull": pull, "victims": victims}[sys.argv[1]]()
