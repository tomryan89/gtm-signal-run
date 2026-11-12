"""CMA merger cases opened in the last 12 months (GOV.UK Search API), parties matched to the universe.

  python src/cma.py

Raw: data/raw/cma/cases_<from date>.json (fetched once). Parties come from the case description
("acquisition by X of Y") and title ("X / Y merger inquiry"). A party is matched on exact normalised name,
or near-exact (same name ignoring legal-form words like Limited/plc/Group) when that points at one group only.
Anything else goes to data/interim/cma_review.csv."""
import json
import re
from datetime import date

import pandas as pd

from common import INTERIM, OUTPUT, RAW, fetch, log, settings
from jobs import core
from names import norm

ST = settings()


def months_back(d, m):
    y, mo = d.year, d.month - m
    while mo <= 0:
        mo += 12; y -= 1
    return date(y, mo, min(d.day, 28))


SUFFIX = re.compile(r"(limited|ltd\.?|plc|inc\.?|incorporated|corporation|corp\.?|s\.?a\.?|n\.?v\.?|b\.?v\.?|ag|se|"
                    r"gmbh|l\.?p\.?|llp|company|unlimited|co\.?|kg|holdings|group)$", re.I)


def split_list(text):
    """'A, B and C' -> [A, B, C]; 'Daily Mail and General Trust plc' stays whole; 'Inc.' rejoins its name."""
    parts = [p.strip() for p in re.split(r",\s+", text) if p.strip()]
    merged = []
    for p in parts:
        if merged and re.fullmatch(r"(inc\.?|ltd\.?|llc|l\.?p\.?|co\.?,?)", p, re.I):
            merged[-1] += ", " + p
        else:
            merged.append(p)
    out = []
    for k, p in enumerate(merged):
        bits = re.split(r"\s+and\s+", p)
        if len(bits) > 1 and len(merged) > 1 and k == len(merged) - 1:          # "A, B and C"
            out += [b.strip() for b in bits]
        elif len(bits) == 2 and SUFFIX.search(bits[0].strip()):
            out += [b.strip() for b in bits]
        else:
            out.append(p)
    return out


def clean(piece, extra):
    """Strip business descriptions around a company name; aliases and 'through X' owners go to extra."""
    t = piece.strip(" .")
    t = re.sub(r",?\s*following which.*$", "", t, flags=re.I)
    t = re.sub(r"\s*\((in administration|including [^)]*)\)", "", t, flags=re.I)
    m = re.search(r"\((?:through|via) ([^)]+)\)", t)
    if m:
        extra.append(m.group(1)); t = t.replace(m.group(0), "").strip()
    m = re.search(r"\(trading as ([^)]+)\)", t)
    if m:
        extra.append(m.group(1)); t = t.replace(m.group(0), "").strip()
    m = re.search(r"\(the [^)]* of ([^)]+)\)", t)          # "G.I. Hadfield (the ... business of Enva Group)"
    if m:
        extra.append(m.group(1)); t = t.replace(m.group(0), "").strip()
    m = re.search(r"\(([^)]{2,40})\)$", t)                  # short alias: "Sky UK Limited", "(ITV)"
    if m and not re.match(r"(the|uk|ireland)\b", m.group(1), re.I):
        extra.append(m.group(1)); t = t[:m.start()].strip()
    t = re.sub(r"^(the )?(majority of the |certain )?[\w\s()-]*?\b(business(es)?|assets|operations)( [\w-]+)? of ", "", t, flags=re.I)
    t = re.sub(r"^an? (indirect )?(minority|majority) (shareholding|stake|interest) in ", "", t, flags=re.I)
    t = re.sub(r"^(\d+ )?care homes managed by ", "", t, flags=re.I)
    t = re.sub(r"[’']s [^,]*\bbusiness.*$", "", t)
    return t.strip(" .,")


def parties(title, desc):
    """Return [(role, party)] from the case description, plus the title's short names as aliases."""
    d = re.split(r"(?<=[a-z)])\.\s+(?=[A-Z])", (desc or "").strip())[0]      # first sentence ("G.I. Hadfield" safe)
    d = re.sub(r"^.*?\b(?:investigat\w*|seeking views on)\b\s+(?:and cleared\s+)?(?:the\s+)?", "", d, flags=re.I)
    d = re.sub(r",?\s*following which.*$", "", d, flags=re.I)
    d = re.sub(r"\s*\((in administration|including [^)]*)\)", "", d, flags=re.I)
    d = re.sub(r",? through their joint venture (\w+),", r" and \1", d)
    out, extra = [], []
    pats = [(r"^(?:\d+ )?(?:completed |anticipated )?acquisitions? by (?P<a>.+?) of (?P<b>.+)$", "buyer", "target"),
            (r"^acquisition of (?P<b>.+?) by (?P<a>.+)$", "buyer", "target"),
            (r"^(?:merger|joint venture) between (?P<a>.+?) and (?P<b>.+)$", "party", "party")]
    for pat, ra, rb in pats:
        m = re.match(pat, d.strip(" ."), re.I)
        if m:
            for role, grp in ((ra, "a"), (rb, "b")):
                for piece in ([m.group(grp)] if ra == "party" else split_list(m.group(grp))):
                    c = clean(piece, extra)
                    if c:
                        out.append((role, c))
            break
    out += [("alias", x.strip(" .")) for x in extra]
    t = re.sub(r"\s*(merger inquiry|merger inquiries|merger)\s*$", "", title or "", flags=re.I)
    for p in re.split(r"\s+/\s+", t):
        p = re.sub(r"\s*\([^)]*\)$", "", p).strip()
        if p and p.lower() not in {x[1].lower() for x in out} and not re.match(r"(multiple|.*\bJV$|.* and )", p, re.I):
            out.append(("title name", p))
    return out


def main():
    run = date.fromisoformat(ST["run"]["run_date"])
    since = months_back(run, ST["rules"]["lookback_months"]).isoformat()
    f = fetch("https://www.gov.uk/api/search.json", RAW / "cma" / f"cases_{since}.json", "govuk_cma",
              params={"filter_format": "cma_case", "filter_case_type": "mergers", "filter_opened_date": f"from:{since}",
                      "count": 500, "fields": "title,link,opened_date,closed_date,case_state,description,outcome_type"})
    cases = json.loads(f.read_text())["results"]
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    grp = dict(zip(g.entity_id, g.group_id))
    exact, near = {}, {}
    for e in u.itertuples():
        exact.setdefault(norm(e.name), set()).add(e.entity_id)
        near.setdefault(core(e.name), set()).add(e.entity_id)
    for gid, gname in g[["group_id", "group_name"]].drop_duplicates().itertuples(index=False):
        if gid.startswith("FP:") and core(gname):
            near.setdefault(core(gname), set()).add(gid)
    from brands import lookup as brand_lookup
    brands = brand_lookup()
    from common import ROOT
    ovf = ROOT / "corrections" / "cma_overrides.csv"
    ov = pd.read_csv(ovf, dtype=str, keep_default_na=False) if ovf.exists() else pd.DataFrame(columns=["case", "party", "override"])
    cma_ov = {(a.strip(), b): o for a, b, o in zip(ov.case, ov.party, ov.override)}
    sig, rev = [], []
    for c in cases:
        link = "https://www.gov.uk" + c["link"]
        for role, p in parties(c.get("title"), c.get("description")):
            ov = cma_ov.get((c.get("title", "").strip(), p))
            if ov is not None:
                base = dict(case=c.get("title"), opened=c.get("opened_date"), role=role, party=p, source_link=link)
                if ov == "none":
                    rev.append({**base, "reason": "set to no group by Tom"}); continue
                sig.append({**base, "match": "Tom's correction", "entity_id": "", "group_id": ov}); continue
            ids, how = exact.get(norm(p)), "exact name"
            if not ids:
                ids, how = near.get(core(p)), "near-exact name (legal-form words ignored)"
            if not ids and norm(p) in brands:
                ids, how = {brands[norm(p)]}, "brand lookup"
            base = dict(case=c.get("title"), opened=c.get("opened_date"), role=role, party=p, source_link=link)
            if not ids:
                rev.append({**base, "reason": "party not found in the universe"}); continue
            groups = {grp.get(i, i) for i in ids}
            if len(groups) > 1:
                rev.append({**base, "reason": f"party name matches {len(groups)} groups"}); continue
            ent = sorted(i for i in ids if not i.startswith(("FP:", "UK:", "IE:", "SOLO:", "LISTED:")))
            sig.append({**base, "match": how, "entity_id": ent[0] if len(ent) == 1 else "", "group_id": groups.pop()})
    pd.DataFrame(sig).to_csv(INTERIM / "cma_matches.csv", index=False)
    pd.DataFrame(rev).to_csv(INTERIM / "cma_review.csv", index=False)
    log("govuk_cma", "matched", cases=len(cases), matched=len(sig), review=len(rev))
    print(f"{len(cases)} cases since {since}; {len(sig)} parties matched, {len(rev)} to review")
    # point 8: one table of case, parties and matched group for Tom to confirm
    gname = dict(zip(g.group_id, g.group_name))
    tab = pd.concat([pd.DataFrame(sig).assign(status="matched"), pd.DataFrame(rev).assign(status="not matched")])
    tab["group_name"] = tab.get("group_id", pd.Series(dtype=str)).map(gname)
    tab = tab.reindex(columns=["opened", "case", "role", "party", "status", "group_id", "group_name", "match", "reason",
                               "source_link"]).fillna("").sort_values(["opened", "case", "role"], ascending=[False, True, True])
    tab["tom_confirms (Y/N or correct group)"] = ["Y (Tom 11 Nov)" if st == "matched" and m != "brand lookup"
                                                  else "Y (Tom, point 10 via brand lookup)" if st == "matched" else ""
                                                  for st, m in zip(tab.status, tab.match)]
    tab.to_csv(INTERIM / "cma_table.csv", index=False)


if __name__ == "__main__":
    main()
