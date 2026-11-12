"""FCA Register API: which UK entities are authorised firms, and new SMF4/SMF5 holders.

  python src/fca.py match   # name search for every UK company, confirmed by the Companies House number on the FCA record
  python src/fca.py smf     # SMF4/SMF5 holders and start dates for authorised firms in the pilot sample

Every reply is cached in data/raw/fca/<kind>/<id>.json, so a rerun never fetches twice and resumes where it stopped.
A match needs BOTH an exact normalised name AND the same Companies House number on the FCA firm record.
Same name with a different or missing number goes to review, never matched."""
import json
import os
import re
import sys
import time

import pandas as pd
import requests

from common import INTERIM, OUTPUT, RAW, log, pace, paths, settings
from names import norm, norm_ch_number

S = settings()["fca"]
BASE = "https://register.fca.org.uk/services/V0.1"
_s = requests.Session()
_last = [0.0]


def get(path, kind, cache_id, params=None):
    dest = RAW / "fca" / kind / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', cache_id)[:150]}.json"
    if dest.exists():
        return json.loads(dest.read_text())
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = {"X-Auth-Email": os.environ["FCA_EMAIL"], "X-Auth-Key": os.environ["FCA_API_KEY"]}
    for attempt in range(6):
        pace("fca", S["min_gap_seconds"])
        try:
            r = _s.get(BASE + path, params=params, headers=h, timeout=60)
        except requests.RequestException as e:
            log("fca", "error", path=path, error=str(e)[:200]); time.sleep(10 * (attempt + 1)); continue
        if r.status_code in (401, 403):
            raise SystemExit(f"FCA rejected the request ({r.status_code}). Check FCA_EMAIL / FCA_API_KEY in .env.")
        if r.status_code == 500 and "LimitException" in r.text:
            # the FCA's own search cannot run this query (name too short/common): permanent, so record it, no retry
            d = {"_status": 500, "_error": "FCA search too broad for this name"}
            dest.write_text(json.dumps(d)); log("fca", "search_too_broad", path=path, params=params)
            return d
        if r.status_code == 429 or r.status_code >= 500:
            pause = int(r.headers.get("Retry-After", 60)) if str(r.headers.get("Retry-After", "")).isdigit() else 60
            log("fca", "rate_limit_pause" if r.status_code == 429 else "server_error", path=path, wait_s=pause)
            time.sleep(pause); continue
        try:
            d = r.json()
        except ValueError:
            d = {"_status": r.status_code, "_text": r.text[:300]}
        dest.write_text(json.dumps(d))
        log("fca", "request", path=path, status=r.status_code)
        return d
    raise RuntimeError(f"FCA: gave up on {path}")


def strip_postcode(n):
    return re.sub(r"\s*\(Postcode:.*?\)\s*$", "", n or "")


def firm(frn):
    d = get(f"/Firm/{frn}", "firm", frn)
    return (d.get("Data") or [{}])[0] if isinstance(d, dict) else {}


# ------------------------------------------------------------------ match
def match():
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    uk = u[(u.country == "UK") & (u.id_type == "Companies House")]
    rows, review, t0 = [], [], time.time()
    # points 9 and 10: firms added from the PRA lists / advert employers already carry their FRN and firm type
    ap = INTERIM / "fca_additions.csv"
    add = pd.read_csv(ap, dtype=str).fillna("") if ap.exists() else pd.DataFrame(columns=["entity_id"])
    add = add[add.entity_id.isin(u.entity_id)]
    for x in add.drop_duplicates(["entity_id", "frn"]).itertuples():
        rows.append(dict(entity_id=x.entity_id, entity_name=x.name, frn=x.frn, fca_name=x.fca_name,
                         fca_status=x.fca_status, fca_ch_number=x.fca_ch_number, source_link=x.source_link,
                         authorised=True, fca_type=x.fca_type, fca_type_reason=x.fca_type_reason,
                         counts_as_financial=True, fca_points_tier=x.fca_points_tier, added_by=x.added_by))
    only_added = set(add.entity_id) - set(u[~u.sources.str.fullmatch(r"(PRA list|advert employer on FCA Register)(; .*)?")].entity_id)
    uk = uk[~uk.entity_id.isin(only_added)]
    print(f"{len(uk)} UK companies to check on the FCA Register")
    for k, e in enumerate(uk.itertuples(), 1):
        target = norm(e.name)
        d = get("/Search", "search", e.entity_id, params={"q": e.name, "type": "firm"})
        if d.get("_error"):
            review.append(dict(entity_id=e.entity_id, entity_name=e.name, reason=d["_error"])); continue
        hits = [x for x in (d.get("Data") or []) if isinstance(x, dict) and norm(strip_postcode(x.get("Name"))) == target]
        for h in hits:
            frn, status = h.get("Reference Number"), h.get("Status", "")
            f = firm(frn)
            chn = norm_ch_number(f.get("Companies House Number") or "")
            base = dict(entity_id=e.entity_id, entity_name=e.name, frn=frn, fca_name=strip_postcode(h.get("Name")),
                        fca_status=status, fca_ch_number=chn,
                        source_link=f"https://register.fca.org.uk/s/search?q={frn}&type=Companies")
            if chn == e.entity_id:
                if not any(r["entity_id"] == chn and r["frn"] == frn for r in rows):   # already added (PRA list)
                    rows.append({**base, "authorised": status in S["authorised_statuses"]})
            elif status in S["authorised_statuses"]:
                review.append({**base, "reason": "same name on FCA Register but Companies House number is "
                               + (f"{chn}, not {e.entity_id}" if chn else "missing")})
        if k % 500 == 0:
            print(f"  {k}/{len(uk)}  {(time.time() - t0) / 60:.0f} min", flush=True)
    m = pd.DataFrame(rows)
    m["added_by"] = m.get("added_by", pd.Series(dtype=str)).fillna("")
    m.to_csv(INTERIM / "fca_firms.csv", index=False)
    pd.DataFrame(review).to_csv(INTERIM / "fca_review.csv", index=False)
    auth = m[m.authorised] if len(m) else m
    log("fca", "match_done", checked=len(uk), matched=len(m), authorised=len(auth), review=len(review))
    print(f"matched {len(m)} FCA records, {auth.entity_id.nunique() if len(m) else 0} entities authorised, {len(review)} to review")


# ------------------------------------------------------------------ firm type (point 11)
def permissions(frn):
    out, pg = [], 1
    while True:
        d = get(f"/Firm/{frn}/Permissions", "permissions", frn if pg == 1 else f"{frn}_p{pg}",
                params=None if pg == 1 else {"pgnp": pg})
        data = d.get("Data") or {}
        out += list(data.keys()) if isinstance(data, dict) else []
        if not (d.get("ResultInfo") or {}).get("Next"):
            return out
        pg += 1


def firm_type(frn, search_status):
    """Return (type, reason). type is '' when the firm earns no points."""
    f = firm(frn)
    psd = f.get("PSD / EMD Status") or ""
    for t, vals in S["psd_emd"].items():
        if psd in vals:
            return t, f"PSD / EMD Status: {psd}"
    if search_status not in S["authorised_statuses"]:
        return "", f"status {search_status}"
    perms = set(permissions(frn))
    low = {p.lower() for p in perms}
    for t, names in S["firm_types"].items():
        hit = [n for n in names if n.lower() in low]
        if hit:
            return t, "permission: " + "; ".join(hit)
    for t, names in S["firm_types_1pt"].items():
        hit = [n for n in names if n.lower() in low]
        if hit:
            return t, "permission: " + "; ".join(hit)
    return "", "no bank, insurer, investment or payment permission" + (" (no permissions listed)" if not perms else "")


def classify_firms():
    f = pd.read_csv(INTERIM / "fca_firms.csv", dtype=str).fillna("")
    if "added_by" not in f:
        f["added_by"] = ""
    pre = f[f.added_by != ""].copy()          # PRA-list / advert-employer firms keep the type they were added with
    f = f[f.added_by == ""].copy()
    cand = f[(f.authorised == "True") | f.frn.map(lambda x: bool((firm(x).get("PSD / EMD Status") or "").startswith("Authorised")))]
    print(f"{len(cand)} FCA records to classify")
    types, reasons = {}, {}
    for k, x in enumerate(cand.itertuples(), 1):
        types[x.Index], reasons[x.Index] = firm_type(x.frn, x.fca_status)
        if k % 200 == 0:
            print(f"  {k}/{len(cand)}", flush=True)
    f["fca_type"] = f.index.map(types).fillna("")
    f["fca_type_reason"] = f.index.map(reasons).fillna("")
    f["counts_as_financial"] = f.fca_type != ""
    f["fca_points_tier"] = f.fca_type.map(lambda t: 2 if t in S["firm_types"] or t in S["psd_emd"] else 1 if t else 0)
    f = pd.concat([f.astype(str), pre.astype(str)])
    f.to_csv(INTERIM / "fca_firms.csv", index=False)
    fin = f.counts_as_financial == "True"
    log("fca", "classified", records=len(cand), financial=int(fin.sum()))
    print(f.fca_type.value_counts().to_string())
    print("entities that count:", f[fin].entity_id.nunique())


# ------------------------------------------------------------------ SMF4 / SMF5
def approved_people(frn):
    """IRNs of people currently approved at the firm. The FCA lists approved people first, then certified
    and former staff, so we page until a page has no approved person."""
    out, pg = [], 1
    while True:
        d = get(f"/Firm/{frn}/Individuals", "individuals", f"{frn}_p{pg}", params={"pgnp": pg})
        data = [x for x in (d.get("Data") or []) if isinstance(x, dict)]
        appr = [x for x in data if "Approved by regulator" in (x.get("Status") or "")]
        out += [(x["IRN"], x.get("Name", "")) for x in appr]
        if not appr or not (d.get("ResultInfo") or {}).get("Next"):
            return out
        pg += 1


def smf():
    from datetime import date, datetime
    from cma import months_back
    st = settings()
    run = date.fromisoformat(st["run"]["run_date"])
    since = months_back(run, st["rules"]["lookback_months"])
    P = paths()
    p = pd.read_csv(P["entities"], dtype=str).fillna("")
    f = pd.read_csv(INTERIM / "fca_firms.csv", dtype=str).fillna("")
    f = f[(f.authorised == "True") & f.entity_id.isin(p.entity_id)].merge(p[["entity_id", "group_id"]], on="entity_id")
    rows = []
    print(f"{len(f)} authorised firms in scope ({P['scope']})", flush=True)
    t0 = time.time()
    for k, x in enumerate(f.itertuples(), 1):
        if k % 50 == 0:
            print(f"  firms {k}/{len(f)}  {(time.time() - t0) / 60:.0f} min", flush=True)
        for irn, name in approved_people(x.frn):
            d = get(f"/Individuals/{irn}/CF", "cf", irn)
            for block in d.get("Data") or []:
                for cf in (block.get("Current") or {}).values():
                    code = (cf.get("Name") or "").split(" ")[0]
                    if code not in S["smf_codes"] or not (cf.get("URL") or "").endswith(f"/Firm/{x.frn}"):
                        continue
                    try:
                        start = datetime.strptime(cf.get("Effective Date", ""), "%d/%m/%Y").date()
                    except ValueError:
                        continue
                    rows.append(dict(group_id=x.group_id, entity_id=x.entity_id, entity_name=x.entity_name, frn=x.frn,
                                     irn=irn, person=name, function=cf.get("Name"), start=start.isoformat(),
                                     in_window=since <= start <= run, source_link=x.source_link))
    o = pd.DataFrame(rows)
    o.to_csv(P["smf"], index=False)
    n = int(o.in_window.sum()) if len(o) else 0
    log("fca", "smf_done", firms=len(f), holders=len(o), new_in_12m=n)
    print(f"{len(o)} current SMF4/SMF5 holders, {n} started in the last 12 months")


if __name__ == "__main__":
    {"match": match, "smf": smf, "classify": classify_firms}[sys.argv[1]]()
