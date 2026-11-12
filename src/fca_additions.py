"""Points 9 and 10 (Tom, 11 Nov 2026): add regulated firms that the pay gap and modern slavery files miss.
Their size is "unconfirmed".

  python src/fca_additions.py pra       # point 9: every bank, building society and insurer on the PRA's lists
  python src/fca_additions.py adverts   # point 10: advert employers on the FCA Register as an investment firm or
                                        # a payment or e-money institution
Both write to data/interim/fca_additions.csv (one row per entity), which build_universe.py adds to the universe and
fca.py match adds to the FCA firm table. Every FCA and Companies House reply is cached (never fetched twice).

PRA lists: the Bank of England refuses scripted downloads, so Tom downloads the three CSVs into Uploads and they
are copied to data/raw/pra/. Each row has the firm's FRN; the FCA record gives its Companies House number.
A firm with no Companies House number on its FCA record is added as "FRN-<number>" (its own group).
Advert employers: an FCA name search for the employer name; a hit counts only when its name without legal-form
words equals the employer's name without them. Several different firms with that name go to review."""
import csv
import io
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

import companies_house as ch
from common import INTERIM, RAW, ROOT, UPLOADS as _UP, log, settings
from fca import firm, get, permissions, strip_postcode
from names import norm, norm_ch_number

ST = settings()
S = ST["fca"]
A = ST["additions"]
OUTF = INTERIM / "fca_additions.csv"
REVIEW = INTERIM / "fca_additions_review.csv"
UPLOADS = _UP or (RAW / "pra")   # the PRA lists are read from UPLOADS_DIR when set
COLS = ["entity_id", "name", "frn", "fca_name", "fca_status", "fca_ch_number", "fca_type", "fca_type_reason",
        "fca_points_tier", "added_by", "detail", "source_link"]


def save(rows, review, added_by):
    old = pd.read_csv(OUTF, dtype=str).fillna("") if OUTF.exists() else pd.DataFrame(columns=COLS)
    old = old[old.added_by != added_by]
    new = pd.concat([old, pd.DataFrame(rows, columns=COLS)]).drop_duplicates(["entity_id", "frn"])
    new.to_csv(OUTF, index=False)
    oldr = pd.read_csv(REVIEW, dtype=str).fillna("") if REVIEW.exists() else pd.DataFrame(columns=["added_by"])
    pd.concat([oldr[oldr.added_by != added_by], pd.DataFrame(review)]).to_csv(REVIEW, index=False)


_NOCH = None


def no_number_entities():
    """Universe entries without a Companies House number (pay gap 'GPG-', Irish 'CRO-'), by normalised name.
    A name shared by two entries is left out (ambiguous)."""
    global _NOCH
    if _NOCH is None:
        u = pd.read_csv(ROOT / "output" / "step1" / "universe.csv", dtype=str).fillna("")
        u = u[u.entity_id.str.startswith(("GPG-", "CRO-"))]
        k = u.name.map(norm)
        _NOCH = dict(zip(k[~k.duplicated(keep=False)], u.entity_id[~k.duplicated(keep=False)]))
    return _NOCH


def entity_for(frn):
    """(entity_id, fca record). The Companies House number on the FCA record; else an existing universe entry
    without a company number whose name is exactly the FCA name (e.g. Nationwide Building Society in the pay gap
    file, an Irish DAC); else FRN-<frn>."""
    f = firm(frn)
    chn = norm_ch_number(f.get("Companies House Number") or "")
    if chn:
        return chn, f
    same = no_number_entities().get(norm(f.get("Organisation Name") or ""))
    return (same or f"FRN-{frn}"), f


def link(frn):
    return f"https://register.fca.org.uk/s/firm?id={frn}"


# ------------------------------------------------------------------ point 9: PRA lists
def read_pra(path):
    """Rows (section, firm name, FRN) from one PRA CSV. Each section starts with a title line, then a header
    line starting 'Firm Name'. Insurer continuation rows (more regulated activities) have no name or FRN."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    out, section, last = [], "", ""
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        first = cells[0]
        frn = next((c for c in cells[1:3] if re.fullmatch(r"\d{4,7}", c)), "")
        if first.lower() == "firm name":
            continue
        if frn and first:
            out.append(dict(section=section, name=first, frn=frn))
        elif first and not frn and len([c for c in cells if c]) == 1:
            last, section = section, first        # a title line (list title or section title)
    return out


def pra():
    src = RAW / "pra"
    src.mkdir(parents=True, exist_ok=True)
    for pat in A["pra_files"]:
        for f in UPLOADS.glob(pat):
            if not (src / f.name).exists():
                shutil.copy(f, src / f.name)
    files = sorted(p for pat in A["pra_files"] for p in src.glob(pat))
    if not files:
        raise SystemExit("no PRA list CSVs in data/raw/pra or Uploads - Tom downloads them (see the step report)")
    firms = []
    for f in files:
        rows = read_pra(f)
        kind = "insurer" if "insur" in f.name.lower() else "bank or building society"
        for r in rows:
            firms.append({**r, "kind": kind, "file": f.name})
        print(f"{f.name}: {len(rows)} firms in {len({r['section'] for r in rows})} sections")
    P = pd.DataFrame(firms).drop_duplicates(["frn"])
    rows, review = [], []
    for k, r in enumerate(P.itertuples(), 1):
        if any(w in r.section.lower() for w in A["pra_skip_section_words"]):
            review.append(dict(added_by="PRA list", item=f"{r.name} (FRN {r.frn})", section=r.section,
                               reason="not added: insurance special purpose vehicle (not an operating insurer)"))
            continue
        eid, f = entity_for(r.frn)
        if not f:
            review.append(dict(added_by="PRA list", item=f"{r.name} (FRN {r.frn})", section=r.section,
                               reason="FRN not found on the FCA Register"))
            continue
        rows.append(dict(entity_id=eid, name=f.get("Organisation Name") or r.name, frn=r.frn,
                         fca_name=f.get("Organisation Name", ""), fca_status=f.get("Status", ""),
                         fca_ch_number=eid if not eid.startswith(("FRN-", "GPG-", "CRO-")) else "", fca_type=r.kind,
                         fca_type_reason=f"PRA list ({r.file}): {r.section}", fca_points_tier="2",
                         added_by="PRA list", detail=r.section, source_link=link(r.frn)))
        if k % 100 == 0:
            print(f"  {k}/{len(P)}", flush=True)
    save(rows, review, "PRA list")
    o = pd.DataFrame(rows)
    log("additions", "pra_done", firms=len(P), added=len(o), review=len(review))
    print(f"{len(P)} PRA firms; {len(o)} rows ({(~o.entity_id.str.startswith('FRN-')).sum()} with a Companies House "
          f"number); {len(review)} to review")


# ------------------------------------------------------------------ point 10: advert employers
def wanted_type(frn, status):
    """investment firm or payment / e-money institution (point 10), else ''."""
    f = firm(frn)
    psd = f.get("PSD / EMD Status") or ""
    for t, vals in S["psd_emd"].items():
        if psd in vals:
            return t, f"PSD / EMD Status: {psd}"
    if status not in S["authorised_statuses"]:
        return "", ""
    low = {p.lower() for p in permissions(frn)}
    hit = [n for n in S["firm_types"]["investment firm"] if n.lower() in low]
    return ("investment firm", "permission: " + "; ".join(hit)) if hit else ("", "")


def adverts():
    from jobs import core
    j = pd.read_csv(INTERIM / "job_adverts.csv", dtype=str).fillna("")
    emp = j[j.review_reason == "employer not in the universe"].employer
    names = sorted(set(emp))
    print(f"{len(names)} advert employers not in the universe ({len(emp)} adverts)")
    rows, review = [], []
    for k, name in enumerate(names, 1):
        target = core(name)
        if not target:
            continue
        d = get("/Search", "search", f"advert_{name}", params={"q": name, "type": "firm"})
        if d.get("_error"):
            review.append(dict(added_by="advert employer", item=name, reason=d["_error"])); continue
        hits = [x for x in (d.get("Data") or []) if isinstance(x, dict)
                and core(strip_postcode(x.get("Name"))) == target]
        qual = []
        for h in hits:
            frn = h.get("Reference Number")
            t, why = wanted_type(frn, h.get("Status", ""))
            if t:
                qual.append((frn, h, t, why))
        if len({q[0] for q in qual}) > 1:
            eids = {entity_for(q[0])[0] for q in qual}
            if len(eids) > 1:
                review.append(dict(added_by="advert employer", item=name,
                                   reason=f"name matches {len(eids)} FCA firms: " + ", ".join(q[0] for q in qual[:5])))
                continue
        for frn, h, t, why in qual[:1]:
            eid, f = entity_for(frn)
            rows.append(dict(entity_id=eid, name=f.get("Organisation Name") or strip_postcode(h.get("Name")), frn=frn,
                             fca_name=strip_postcode(h.get("Name")), fca_status=h.get("Status", ""),
                             fca_ch_number=eid if not eid.startswith(("FRN-", "GPG-", "CRO-")) else "", fca_type=t, fca_type_reason=why,
                             fca_points_tier="2", added_by="advert employer",
                             detail=f"advert employer '{name}' ({int((emp == name).sum())} adverts)",
                             source_link=link(frn)))
        if k % 100 == 0:
            print(f"  {k}/{len(names)}", flush=True)
    save(rows, review, "advert employer")
    log("additions", "adverts_done", employers=len(names), added=len(rows), review=len(review))
    print(f"{len(rows)} advert employers are FCA investment or payment firms; {len(review)} to review")


if __name__ == "__main__":
    {"pra": pra, "adverts": adverts}[sys.argv[1]]()
