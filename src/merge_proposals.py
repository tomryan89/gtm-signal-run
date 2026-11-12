"""Point 9 draft rule - NOT applied, proposals only (output/step2/merge_proposals.csv).

 a) a UK branch record (company number starting BR or FC) joins the group whose foreign parent has the same name;
 b) an Irish entity joins a UK or foreign-parent group when the brand lookup maps the same brand to both
    (the brand's name, ignoring legal-form words, is the start of the Irish entity's name)."""
import re

import pandas as pd

from brands import table as brand_table
from common import OUTPUT
from jobs import core

LEGAL = r"\b(ag|aktiengesellschaft|s\.?a\.?|n\.?v\.?|b\.?v\.?|se|plc|inc\.?|incorporated|corporation|corp\.?|n\.?a\.?|" \
        r"national association|llc|gmbh|limited|ltd\.?|company|co\.?|branch|uk branch|london branch|dac|designated activity)\b"


def key(name):
    n = re.sub(r"\(.*?\)|,", " ", (name or "").lower())
    n = re.sub(r"\b(uk|london|united kingdom)\s+branch\b", " ", n)
    n = re.sub(LEGAL, " ", n)
    return core(n)


def main():
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    gname = dict(zip(g.group_id, g.group_name))
    fp = {}
    for gid, pn in g[g.group_id.str.startswith("FP:")][["group_id", "parent_name"]].drop_duplicates().itertuples(index=False):
        if key(pn):
            fp.setdefault(key(pn), set()).add(gid)
    rows = []
    br = g[g.entity_id.str.match(r"^(BR|FC)\d")]
    for e in br.itertuples():
        hits = fp.get(key(e.entity_name), set()) - {e.group_id}
        if len(hits) == 1:
            t = hits.pop()
            rows.append(dict(rule="a) UK branch -> foreign parent of the same name", entity_id=e.entity_id,
                             entity_name=e.entity_name, from_group=e.group_id, from_group_name=e.group_name,
                             to_group=t, to_group_name=gname[t], basis=f"name key '{key(e.entity_name)}'"))
    from common import settings
    canon = {i: ids[0] for ids in settings()["grouping"].get("merges", []) for i in ids}
    t = brand_table()
    ie = g[g.country == "IE"]
    for b in t.itertuples():
        f = canon.get(b.final, b.final)
        if not f or f.lower() in ("none", "unsure", "recruiter") or not f.startswith(("UK:", "FP:")):
            continue
        k = key(b.name)
        if not k or len(k) < 3:
            continue
        for e in ie.itertuples():
            if e.group_id != f and (key(e.entity_name) == k or key(e.entity_name).startswith(k + " ")):
                rows.append(dict(rule="b) Irish entity -> group the brand lookup maps the brand to", entity_id=e.entity_id,
                                 entity_name=e.entity_name, from_group=e.group_id, from_group_name=e.group_name,
                                 to_group=f, to_group_name=gname.get(f, ""), basis=f"brand '{b.name}'"))
    p = pd.DataFrame(rows).drop_duplicates(["entity_id", "to_group"])
    p.to_csv(OUTPUT / "step2" / "merge_proposals.csv", index=False)
    print(p.rule.value_counts().to_string() if len(p) else "no proposals")
    print(p[["rule", "entity_name", "from_group_name", "to_group_name"]].to_string())


if __name__ == "__main__":
    main()


def investor_siblings():
    """Point 3 stand-in (NOT applied): ownership records name the investor directly, so the shared intermediate
    holding company is not recorded. Proposal: single-company groups under the same investor that share a
    registered office address."""
    import companies_house as ch
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    one = g[(g.investor != "") & (g.group_size.astype(int) == 1)].copy()
    one["inv"] = one.investor.str.replace(r"\s*\(.*$", "", regex=True).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)

    def addr(n):
        a = (ch.profile(n) or {}).get("registered_office_address") or {}
        return " ".join(str(a.get(k, "")) for k in ("premises", "address_line_1", "postal_code")).upper().strip()
    one["addr"] = one.top_company_number.map(addr)
    rows = []
    for (inv, ad), m in one[one.addr != ""].groupby(["inv", "addr"]):
        if len(m) > 1:
            for e in m.itertuples():
                rows.append(dict(investor=e.investor, address=ad, entity_id=e.entity_id, entity_name=e.entity_name,
                                 group_id=e.group_id, would_join=m.group_id.iloc[0]))
    p = pd.DataFrame(rows)
    p.to_csv(OUTPUT / "step2" / "investor_sibling_proposals.csv", index=False)
    print(f"{p.would_join.nunique() if len(p) else 0} proposed combined groups from {len(p)} single-company groups")
    print(p[["investor", "entity_name", "address"]].head(30).to_string() if len(p) else "")


if __name__ == "__main__" and "siblings" in __import__("sys").argv:
    investor_siblings()
