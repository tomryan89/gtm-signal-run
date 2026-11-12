"""Companies House filing-history signals for pilot entities (last 12 months from the run date).

  python src/ch_signals.py

Per entity, per category (officers / capital / mortgage), pages back until filings are older than 12 months.
Board turnover: 3+ director appointments/resignations on one entity in 12 months, dated from the latest.
New funding (SH01) / new charge (MR01): every filing in 12 months, dated by the filing's action date.
Output: data/interim/ch_signals.csv (one row per qualifying filing, plus one row per board-turnover entity)."""
from datetime import date

import pandas as pd

import companies_house as ch
from cma import months_back
import time

from common import INTERIM, OUTPUT, log, paths, settings

ST = settings()
F = ST["ch_filings"]
RUN = date.fromisoformat(ST["run"]["run_date"])
SINCE = months_back(RUN, ST["rules"]["lookback_months"]).isoformat()


def filings(num, category):
    """Filings of one category in the window. Uses the per-category pages cached in the pilot when they exist;
    otherwise one uncategorised listing per company (Step 7: one call covers officers, capital and charges)."""
    if not (ch.RAW / "ch" / "filing" / f"{num}_{category}_0.json").exists():
        return [i for i in all_filings(num) if i.get("category") == category]
    out, start = [], 0
    while True:
        d = ch.get(f"/company/{num}/filing-history", "filing", f"{num}_{category}_{start}",
                   params={"items_per_page": 100, "start_index": start, "category": category})
        items = (d or {}).get("items", [])
        out += items
        if not items or min(i.get("date", "9999") for i in items) < SINCE or start + 100 >= (d or {}).get("total_count", 0):
            return [i for i in out if SINCE <= (i.get("action_date") or i.get("date", "")) <= RUN.isoformat()]
        start += 100


def all_filings(num):
    out, start = [], 0
    while True:
        d = ch.get(f"/company/{num}/filing-history", "filing_all", f"{num}_{start}",
                   params={"items_per_page": 100, "start_index": start})
        items = (d or {}).get("items", [])
        out += items
        if not items or min(i.get("date", "9999") for i in items) < SINCE or start + 100 >= (d or {}).get("total_count", 0):
            return [i for i in out if SINCE <= (i.get("action_date") or i.get("date", "")) <= RUN.isoformat()]
        start += 100


def link(num, i):
    return f"https://find-and-update.company-information.service.gov.uk/company/{num}/filing-history"


def pre_ipo(num):
    """Point 19: re-registered from private to public in the last 12 months. Read from the company profile
    (already downloaded): a previous name ending Limited/Ltd that ceased in the window, while the company is now a plc."""
    prof = ch.profile(num) or {}
    if prof.get("type") != "plc":
        return None
    for pn in prof.get("previous_company_names") or []:
        ceased = pn.get("ceased_on", "")
        if SINCE <= ceased <= RUN.isoformat() and pn.get("name", "").upper().rstrip(". ").endswith(("LIMITED", "LTD")):
            return ceased, pn["name"], prof.get("company_name", "")
    return None


def main():
    P = paths()
    p = pd.read_csv(P["entities"], dtype=str).fillna("")
    uk = p[(p.country == "UK") & p.entity_id.str.match(r"^[A-Z0-9]{8}$")]
    rows = []
    # point 14: board turnover is counted on each group's top company only (may be a parent outside the universe)
    # a UK group's top is its id company; a foreign-parent group can have several UK tops (each directly under
    # the foreign parent) and each is checked
    tops = uk[uk.top_company_number != ""][["group_id", "top_company_number"]].drop_duplicates()
    tops["top_company_number"] = [gid[3:] if gid.startswith("UK:") else t for gid, t in zip(tops.group_id, tops.top_company_number)]
    tops = tops.drop_duplicates()
    t0 = time.time()
    print(f"{len(tops)} group top companies, {len(uk)} UK companies", flush=True)
    for k, x in enumerate(tops.itertuples(), 1):
        num = x.top_company_number
        if k % 500 == 0:
            print(f"  tops {k}/{len(tops)}  {(time.time() - t0) / 60:.0f} min", flush=True)
        ch.profile(num)                       # next accounts due date (score.py) comes from the top's profile
        offi = [i for i in filings(num, "officers") if i.get("type") in F["director_changes"]]
        if len(offi) >= ST["rules"]["board_turnover_min_changes"]:
            latest = max(i.get("action_date") or i["date"] for i in offi)
            name = (ch.profile(num) or {}).get("company_name", num)
            rows.append(dict(group_id=x.group_id, entity_id=num, entity_name=name, signal="board turnover", date=latest,
                             source_link=link(num, None),
                             detail=f"top company: {len(offi)} director appointments/resignations since {SINCE}"))
    for k, e in enumerate(uk.itertuples(), 1):
        prof = ch.profile(e.entity_id) or {}
        is_plc = prof.get("type") == "plc"
        for cat, types, label in (("capital", F["funding"], "new funding (SH01)"), ("mortgage", F["charges"], "new charge (MR01)")):
            if label.startswith("new funding") and is_plc:
                continue              # point 13: share allotments by plcs are routine (schemes, scrip) - ignored
            for i in filings(e.entity_id, cat):
                if i.get("type") in types:
                    rows.append(dict(group_id=e.group_id, entity_id=e.entity_id, entity_name=e.entity_name, signal=label,
                                     date=i.get("action_date") or i["date"], source_link=link(e.entity_id, i),
                                     detail=f"{i.get('type')} filed {i.get('date')} ({i.get('description', '')})"))
        ipo = pre_ipo(e.entity_id)
        if ipo:
            rows.append(dict(group_id=e.group_id, entity_id=e.entity_id, entity_name=e.entity_name,
                             signal="pre-IPO (re-registered as plc)", date=ipo[0],
                             source_link=f"https://find-and-update.company-information.service.gov.uk/company/{e.entity_id}",
                             detail=f"was '{ipo[1]}', now '{ipo[2]}' (name changed {ipo[0]})"))
        if k % 500 == 0:
            print(f"  companies {k}/{len(uk)}  {(time.time() - t0) / 60:.0f} min", flush=True)
    pd.DataFrame(rows).to_csv(P["ch_signals"], index=False)
    log("companies_house", "filing_signals_done", scope=P["scope"], secs=round(time.time() - t0), entities=len(uk), tops=len(tops), signals=len(rows))
    print(f"{len(uk)} UK companies, {len(tops)} group top companies checked, {len(rows)} filing signals")


if __name__ == "__main__":
    main()
