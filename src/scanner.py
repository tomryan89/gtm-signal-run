"""Import the listed-company app (risk scanner) results: principal-risk verdicts.

  python src/scanner.py

Matching (Reference C, point 7):
 1. company number, if the file has one (the 9 Nov 2026 file has no company-number column);
 2. exact normalised name, after tidying listing-style names: "Barr (A.G.) Plc" -> "A.G. Barr Plc",
    "Berkeley Group Holdings (The) Plc" -> "The Berkeley Group Holdings Plc", "Ld" -> "Limited";
    first against the universe, then foreign parents of groups, then Companies House search (one company only);
 3. the brand lookup table (data/interim/brand_lookup.csv), where Tom has confirmed a group.
A company found at Companies House but not in the universe is attached to the group of any universe entity it
is a parent of. If it is not, and its verdict is "yes" or "passing mention", it becomes its own group,
flagged "size from listing". Everything else goes to review.
Output: data/interim/scanner_matches.csv, scanner_review.csv"""
import re
import shutil

import pandas as pd

from brands import lookup as brand_lookup
from common import INTERIM, OUTPUT, RAW, UPLOADS, log, settings
from group_accounts import resolve_by_name
from names import norm

S = settings()["scanner"]


def tidy(name):
    n = re.sub(r"\s+", " ", name or "").strip()
    n = re.sub(r"\s*\(\s*the\s*\)\s*", " ", n, flags=re.I).strip()          # "(The)" anywhere
    n = re.sub(r"\bLd\.?$", "Limited", n)
    # "Barr (A.G.) Plc" / "Wetherspoon ( J.D.) Plc" / "Fisher (James) & Sons Plc": move the bracket to the front
    m = re.match(r"^([A-Za-z][\w'’-]*) \(\s*([^)]+?)\s*\)(.*)$", n)
    if m and not re.search(r"\b(holdings|uk|contractors|group|international)\b", m.group(2), re.I):
        n = f"{m.group(2)} {m.group(1)}{m.group(3)}"
    return n


def main():
    src = RAW / "scanner" / S["file"].split("/")[-1]
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(UPLOADS / S["file"], src)   # the listed-company app's results workbook, from UPLOADS_DIR
    v = pd.read_excel(src, sheet_name="Results", dtype=str).fillna("")
    import openpyxl
    ws = openpyxl.load_workbook(src)["Results"]
    hdr = [c.value for c in ws[1]]
    col = hdr.index("full report (online viewer)")
    v["report_link"] = [(r[col].hyperlink.target if r[col].hyperlink else "") for r in ws.iter_rows(min_row=2)][:len(v)]
    numcol = next((c for c in v.columns if "company number" in c.lower() or c.lower() in ("crn", "company_number")), None)

    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    grp = dict(zip(g.entity_id, g.group_id))
    fp = set(g.group_id[g.group_id.str.startswith("FP:")])
    # parent of a universe entity: the number appears anywhere in an entity's ownership path
    parent_of = {}
    for gid, path in zip(g.group_id, g.path):
        for n in [p for p in path.split(" > ") if p][1:]:
            parent_of.setdefault(n, gid)
    exact = {}
    for e in u.itertuples():
        exact.setdefault(norm(e.name), set()).add(e.entity_id)
    brands = brand_lookup()
    m, r = [], []
    for i, d in v.iterrows():
        name = tidy(d["company"])
        base = dict(ticker=d["ticker"], company=d["company"], name_used=name, verdict=d["verdict"],
                    risk_title=d["risk title"], quote=d["quote"], quote_verified=d["quote verified"],
                    report_date=d["FY end"], source_link=d["report_link"], flag="")
        if d["verdict"] not in ("yes", "passing mention", "no"):
            r.append({**base, "reason": f"verdict is '{d['verdict']}'"}); continue
        num = (d.get(numcol) or "").strip() if numcol else ""
        ids, how = ({num} if num else None), "company number"
        if not ids:
            ids, how = exact.get(norm(name)), "exact name (universe)"
        if not ids and f"FP:{norm(name)}" in fp:
            ids, how = {f"FP:{norm(name)}"}, "exact name (foreign parent of a group)"
        if not ids and norm(name) in brands:
            ids, how = {brands[norm(name)]}, "brand lookup"
        if not ids:
            n2 = resolve_by_name(name)
            ids, how = ({n2} if n2 else None), "exact name (Companies House search)"
        if not ids:
            if d["verdict"] in ("yes", "passing mention"):       # point 6 (Tom, 11 Nov)
                m.append({**base, "match": "own group by name (no UK company record)", "entity_id": f"LISTED-{norm(name)}",
                          "group_id": f"LISTED:{norm(name)}", "listed_company_number": "",
                          "flag": "size from listing, no UK company record"}); continue
            r.append({**base, "reason": "no company with exactly this name (or several)"}); continue
        groups = {grp.get(x) or (x if x.startswith(("FP:", "UK:", "IE:", "SOLO:", "LISTED:")) else None) for x in ids}
        if None in groups:
            x = sorted(ids)[0]
            if x in parent_of:
                m.append({**base, "match": how + ", parent of a universe entity", "entity_id": "",
                          "group_id": parent_of[x], "listed_company_number": x}); continue
            if d["verdict"] in ("yes", "passing mention"):
                m.append({**base, "match": how + ", own group", "entity_id": f"LISTED-{x}",
                          "group_id": f"LISTED:{x}", "listed_company_number": x, "flag": "size from listing"}); continue
            r.append({**base, "entity_id": x, "reason": "listed company not in the universe (verdict 'no', so not added)"})
            continue
        if len(groups) != 1:
            r.append({**base, "reason": "name matches several groups"}); continue
        m.append({**base, "match": how, "entity_id": sorted(ids)[0], "group_id": groups.pop(), "listed_company_number": ""})
    mm, rr = pd.DataFrame(m), pd.DataFrame(r)
    mm.to_csv(INTERIM / "scanner_matches.csv", index=False)
    rr.to_csv(INTERIM / "scanner_review.csv", index=False)
    log("scanner", "matched", rows=len(v), matched=len(m), review=len(r), company_number_column=bool(numcol))
    print(f"company-number column in file: {numcol or 'none'}")
    print(f"{len(v)} rows: {len(m)} matched, {len(r)} to review")
    print(mm.groupby(["verdict"]).size().to_string()); print(mm.match.value_counts().to_string())
    print(rr.reason.value_counts().to_string())


if __name__ == "__main__":
    main()
