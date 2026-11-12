"""Stage 2 item 2 (Tom, 12 Nov 2026): acquisitions from Companies House ownership records.

  python src/ch_acquisitions.py   -> data/interim/ch_acquisitions.csv (signals + every candidate with its reason)

A group's top UK company has a new controlling owner when a corporate owner (a "corporate entity" or "legal person"
person with significant control) holding more than 50% of shares or votes, or the right to appoint the board, was
notified in the last 12 months, AND a different owner ceased within 90 days either side of that date (the one it
replaced). Not counted (internal reorganisation): the new owner is a member of the same group, or the old and new
owners have the same name without legal-form words. Uses the ownership records saved in Step 2 (no new requests).
Signal: "merger, acquisition or separation (Companies House: new controlling owner)", 3 points, dated from the
notified date; same family as the CMA and news merger signals, so it counts once.
A rule pass removes names that start with the same word; Opus then reads each remaining candidate (company, new and
old owners) and says whether it is an external change of control or an internal reorganisation (stage2_model acq);
only external changes count."""
from datetime import date, timedelta

import pandas as pd

from common import INTERIM, RAW, log, paths, settings
from jobs import core

ST = settings()
P = paths()
RUN = date.fromisoformat(ST["run"]["run_date"])
SINCE = RUN - timedelta(days=365)
CONTROL = ("ownership-of-shares-50-to-75-percent", "ownership-of-shares-75-to-100-percent",
           "voting-rights-50-to-75-percent", "voting-rights-75-to-100-percent",
           "right-to-appoint-and-remove-directors")
CORP = ("corporate-entity-person-with-significant-control", "legal-person-person-with-significant-control")


def d(s):
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


GENERIC = {"the", "mr", "mrs", "ms", "dr", "uk", "british", "international", "global", "group", "holdings", "holding"}


def first(name):
    w = [x for x in core(name).split() if x not in GENERIC]
    return w[0] if w else ""


def regno(p):
    n = ((p.get("identification") or {}).get("registration_number") or "").strip().upper().replace(" ", "")
    return n.zfill(8) if n.isdigit() else n


def main():
    import json
    e = pd.read_csv(P["entities"], dtype=str).fillna("")
    members = {gid: set(m.entity_id) | {x.split(":", 1)[-1] for x in m.entity_id} for gid, m in e.groupby("group_id")}
    rows = []
    for gid, m in e.groupby("group_id"):
        top = gid[3:] if gid.startswith("UK:") else next((t for t in m.top_company_number if t), "")
        f = RAW / "ch" / "psc" / f"{top}.json"
        if not top or not f.exists() or not f.stat().st_size:
            continue
        items = json.loads(f.read_text()).get("items", [])
        for p in items:
            nd = d(p.get("notified_on"))
            if p.get("kind") not in CORP or not nd or nd < SINCE or nd > RUN:
                continue
            if not set(p.get("natures_of_control") or []) & set(CONTROL):
                continue
            old = [q for q in items if q is not p and d(q.get("ceased_on"))
                   and abs((d(q["ceased_on"]) - nd).days) <= 90 and q.get("name") != p.get("name")]
            base = dict(group_id=gid, group_name=m.group_name.iloc[0], company_number=top,
                        company_name=m[m.entity_id.str.endswith(top)].entity_name.iloc[0] if m.entity_id.str.endswith(top).any() else "",
                        new_owner=p.get("name", ""), new_owner_number=regno(p),
                        new_owner_country=(p.get("address") or {}).get("country", ""), notified_on=nd.isoformat(),
                        control="; ".join(p.get("natures_of_control") or []),
                        previous_owner="; ".join(q.get("name", "") for q in old),
                        previous_ceased_on="; ".join(q.get("ceased_on", "") for q in old),
                        source_link=f"https://find-and-update.company-information.service.gov.uk/company/{top}/persons-with-significant-control")
            if not old:
                rows.append({**base, "counts": False, "reason": "no different owner ceased within 90 days (new owner added, not a replacement)"})
            elif regno(p) and (regno(p) in members.get(gid, set()) or f"UK:{regno(p)}" in members.get(gid, set())):
                rows.append({**base, "counts": False, "reason": "internal reorganisation: new owner is in the same group"})
            elif core(p.get("name", "")) and all(core(p.get("name", "")) == core(q.get("name", "")) for q in old):
                rows.append({**base, "counts": False, "reason": "internal reorganisation: same owner name"})
            elif any(first(p.get("name", "")) and first(p.get("name", "")) == first(q.get("name", "")) for q in old):
                rows.append({**base, "counts": False, "reason": "internal reorganisation: old and new owner names start the same"})
            else:
                rows.append({**base, "counts": True, "reason": "new controlling owner replacing a different owner"})
    R = pd.DataFrame(rows).sort_values(["counts", "notified_on"], ascending=[False, False])
    R = R.drop_duplicates(["group_id", "new_owner", "notified_on"])
    R.to_csv(INTERIM / "ch_acquisitions.csv", index=False)
    log("ch_acquisitions", "done", candidates=len(R), counted=int(R.counts.sum()),
        **{k[:40]: int(v) for k, v in R.reason.value_counts().items()})
    print(R.reason.value_counts().to_string())


if __name__ == "__main__":
    main()
