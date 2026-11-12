"""Step 1: build the universe of legal entities that pass the fit filter (size, private sector, alive).

Outputs (output/step1/):
  universe.csv - one row per entity that passes all three tests
  removed.csv  - every entity dropped, with the test that dropped it
Run `python src/check_alive.py` first so Companies House statuses are cached; entities without a cached
status are marked 'alive_pending' and are not treated as passing."""
import json

import re

import pandas as pd

from common import INTERIM, OUTPUT, RAW, settings
from names import norm, norm_ch_number

S = settings()["universe"]
OUT = OUTPUT / "step1"


# ------------------------------------------------------------------ UK sources
def load_gpg():
    frames = []
    for y in S["gpg_years"]:
        g = pd.read_csv(RAW / "gpg" / f"gpg_{y}.csv", dtype=str)
        g["year"] = y
        frames.append(g)
    g = pd.concat(frames)
    g["ch"] = g.CompanyNumber.map(norm_ch_number)
    g["sic"] = g.SicCodes.fillna("").str.replace(r"\s", "", regex=True).str.strip(",")
    g = g.sort_values("year").drop_duplicates("EmployerId", keep="last")   # latest filing per employer
    return g[["EmployerId", "EmployerName", "ch", "sic", "EmployerSize", "year"]]


def load_msr():
    frames = []
    for y in S["msr_years"]:
        m = pd.read_csv(RAW / "msr" / f"msr_{y}.csv", dtype=str, encoding="utf-8-sig",
                        usecols=["StatementYear", "OrganisationName", "CompanyNumber", "Turnover", "SectorType"])
        frames.append(m)
    m = pd.concat(frames)
    m["ch"] = m.CompanyNumber.map(norm_ch_number)
    m = m.sort_values("StatementYear").drop_duplicates(["ch", "OrganisationName"], keep="last")
    return m


def load_housing():
    r = pd.read_excel(RAW / "rsh" / "rsh_2026-10-20.xlsx", dtype=str)
    r.columns = [c.strip() for c in r.columns]
    return r.rename(columns={"Organisation name": "name", "Registration number": "reg"})


def load_ofs():
    o = pd.read_excel(RAW / "ofs" / "ofs_register_2026-11-10.xlsx", sheet_name="Register", header=2, dtype=str)
    o = o.rename(columns={o.columns[0]: "name", o.columns[2]: "trading", o.columns[3]: "ukprn"})
    o["trading"] = o.trading.fillna("").map(lambda t: [x.strip() for x in str(t).split("\n")
                                                       if x.strip() and x.strip() != "Not applicable"])
    return o[o.name.notna()][["name", "trading", "ukprn"]]


def ch_profile(num):
    p = RAW / "ch" / "profile" / f"{num}.json"
    return json.loads(p.read_text()) if p.exists() else None


def build_uk():
    gpg, msr = load_gpg(), load_msr()
    staff_ok, turn_ok = set(S["min_staff_bands"]), set(S["min_turnover_bands"])
    ents = {}      # entity_id -> dict
    removed = []

    def ent(eid, **kw):
        e = ents.setdefault(eid, dict(entity_id=eid, name="", id_type="", country="UK", industry_code="",
                                      staff_band="", turnover_band="", regulated="", flags=set(), sources=set()))
        for k, v in kw.items():
            if k in ("flags", "sources"):
                e[k] |= set(v)
            elif v and not e.get(k):
                e[k] = v
        return e

    # pay gap employers
    for r in gpg.itertuples():
        if r.ch:
            ent(r.ch, name=r.EmployerName, id_type="Companies House", industry_code=r.sic,
                staff_band=r.EmployerSize, sources=["gender pay gap"])
        else:
            ent(f"GPG-{r.EmployerId}", name=r.EmployerName, id_type="Pay gap employer id (no company number)",
                industry_code=r.sic, staff_band=r.EmployerSize, sources=["gender pay gap"])
    # modern slavery statements (size only). Organisations declaring themselves Public are not used.
    for r in msr.itertuples():
        if r.SectorType == "Public":
            continue
        if r.ch:
            ent(r.ch, name=r.OrganisationName, id_type="Companies House",
                turnover_band=r.Turnover, sources=["modern slavery registry"])

    # housing providers and universities: attach to an existing entity by exact normalised name, else own entity
    by_name = {}
    for eid, e in ents.items():
        by_name.setdefault(norm(e["name"]), []).append(eid)
    for label, df, idcol, prefix in [("housing provider", load_housing(), "reg", "RSH"),
                                     ("university / HE provider", load_ofs(), "ukprn", "OFS")]:
        for r in df.itertuples():
            if label == "housing provider" and str(r.Designation).strip().lower() == "local authority":
                removed.append(dict(entity_id=f"{prefix}-{getattr(r, idcol)}", name=r.name, country="UK",
                                    test="private sector", detail="housing register: local authority"))
                continue
            hits = by_name.get(norm(r.name), [])
            for alt in getattr(r, "trading", []) if not hits else []:
                hits = by_name.get(norm(alt), [])
                if hits:
                    break
            if len(hits) == 1:
                ent(hits[0], regulated=label, sources=[f"{label} register"], flags=[f"{prefix} {getattr(r, idcol)}"])
            else:
                if len(hits) > 1:
                    flag = [f"name matches {len(hits)} pay-gap/registry entities; not merged"]
                else:
                    flag = []
                ent(f"{prefix}-{getattr(r, idcol)}", name=r.name, id_type=f"{label} register",
                    regulated=label, sources=[f"{label} register"], flags=flag)

    # ---------------- tests
    keep = []
    for eid, e in ents.items():
        e["flags"] = "; ".join(sorted(e["flags"]))
        e["sources"] = "; ".join(sorted(e["sources"]))
        base = dict(entity_id=eid, name=e["name"], country="UK")
        # size
        if e["staff_band"] in staff_ok:
            e["size_test"], e["size_band"] = "250+ staff (pay gap)", e["staff_band"] + " staff"
        elif e["turnover_band"] in turn_ok:
            e["size_test"], e["size_band"] = "£36m+ turnover (modern slavery registry)", e["turnover_band"]
        else:
            why = f"staff band '{e['staff_band'] or 'none'}', turnover band '{e['turnover_band'] or 'none'}'"
            removed.append({**base, "test": "size", "detail": why})
            continue
        # private sector
        prof = ch_profile(eid) if e["id_type"] == "Companies House" else None
        if prof and prof.get("sic_codes"):
            e["industry_code"] = e["industry_code"] or ",".join(prof["sic_codes"])
        codes = [c for c in e["industry_code"].split(",") if c]
        if codes and all(c.startswith(tuple(S["public_admin_code_prefixes"])) for c in codes):
            ctype = (prof or {}).get("type", "")
            if ctype in S["company_types_exempt_from_code_test"]:
                e["flags"] = "; ".join(filter(None, [e["flags"],
                                       f"public administration code {e['industry_code']} (kept: company type {ctype})"]))
            else:
                removed.append({**base, "test": "private sector",
                                "detail": f"public administration code {e['industry_code']}"
                                          f" ({'company type ' + ctype if ctype else 'not a company'})"})
                continue
        if eid.startswith("GPG-"):
            # point 8: no company number -> stays only with no public sector marker and no public-body word.
            # Entries tied to the universities or housing register come in through that register: the code "1"
            # marker (which universities carry) is not applied to them, the name words are.
            low_n = re.sub(r"\bn\s*h\s*s\b", "nhs", (e["name"] or "").lower())     # "N H S" is NHS
            hitp = [w for w in S["public_body_words"] if re.search(rf"\b{re.escape(w)}\b", low_n)]
            if not e["regulated"] and S["gpg_public_sector_code"] in codes:
                removed.append({**base, "test": "private sector",
                                "detail": "pay gap entry with no company number and the public sector marker (code 1)"})
                continue
            if hitp:
                removed.append({**base, "test": "private sector",
                                "detail": f"pay gap entry with no company number and a public-body name ({hitp[0]})"})
                continue
            if not e["regulated"] and re.search(rf"\b{S['gpg_university_word']}\b", low_n):
                removed.append({**base, "test": "private sector",
                                "detail": "pay gap university with no company number (universities come from the OfS register only)"})
                continue
            if not e["regulated"]:
                e["flags"] = "; ".join(filter(None, [e["flags"], "no company number: alive not checked, no ownership record"]))
        why = school(e["name"], codes)
        if why:
            removed.append({**base, "test": "private sector", "detail": why})
            continue
        low = f" {e['name'].lower()} "
        hit = [w for w in S["public_name_flags"] if f" {w} " in low or f" {w}," in low]
        if hit:
            e["flags"] = "; ".join(filter(None, [e["flags"], f"public-sector word in name: {', '.join(hit)}"]))
        # alive
        if e["id_type"] == "Companies House":
            if prof is None:
                e["alive"] = "pending"
            elif prof.get("_status") == 404:
                removed.append({**base, "test": "alive", "detail": "not found at Companies House"})
                continue
            elif prof.get("company_status") is None and prof.get("type") in S["ch_types_without_status"]:
                e["alive"] = "status not held by Companies House"
                e["flags"] = "; ".join(filter(None, [e["flags"], f"alive unverified ({prof.get('type')})"]))
                e["name"] = prof.get("company_name", e["name"])
            elif prof.get("company_status") not in S["ch_alive_statuses"] or prof.get("has_insolvency_history"):
                removed.append({**base, "test": "alive",
                                "detail": f"status {prof.get('company_status')}"
                                          f"{', insolvency history' if prof.get('has_insolvency_history') else ''}"})
                continue
            else:
                e["alive"] = prof.get("company_status")
                e["name"] = prof.get("company_name", e["name"])
        elif eid.startswith("GPG-"):
            e["alive"] = "not checked (no company number)"
        else:
            e["alive"] = "on register (no Companies House record)"
        keep.append(e)
    return keep, removed


def school(name, codes):
    """Point 10: academy trusts and schools. Removed when every industry code is primary/secondary education,
    or the name contains one of the education words."""
    digits = [re.sub(r"\D", "", c.split(".0")[0] if c.endswith(".0") else c) for c in codes if c]
    if digits and all(d in S["education_codes"] for d in digits):
        return f"primary/secondary education code {','.join(codes)}"
    low = (name or "").lower()
    hit = [w for w in S["education_name_words"] if re.search(rf"\b{re.escape(w)}\b", low)]
    return f"school / academy trust (name contains '{hit[0]}')" if hit else ""


# ------------------------------------------------------------------ Ireland
def build_ie():
    """Irish size rule: employers in the 250+ band on the Irish Gender Pay Gap Portal export (size confirmed),
    tied to CRO by exact name. If settings say so, Central Bank-authorised firms not on the portal are also
    kept, marked 'size unconfirmed'."""
    cro = pd.read_csv(RAW / "cro" / "companies.csv", dtype=str)
    cro["company_status"] = cro.company_status.str.strip()
    cro["n"] = cro.company_name.map(norm)
    by_name = cro.groupby("n").company_num.apply(list).to_dict()
    cro = cro.set_index("company_num")
    keep, removed, review = {}, [], []

    def test_cro(num, base):
        c = cro.loc[num]
        nace = c.nace_v2_code if isinstance(c.nace_v2_code, str) else ""
        if nace.startswith(tuple(S["public_admin_code_prefixes"])):
            removed.append({**base, "test": "private sector", "detail": f"public administration code {nace}"})
            return None
        why = school(c.company_name, [nace])
        if why:
            removed.append({**base, "test": "private sector", "detail": why})
            return None
        if c.company_status not in S["cro_alive_statuses"]:
            removed.append({**base, "test": "alive", "detail": f"CRO status {c.company_status}"})
            return None
        return nace

    # 1. Irish gender pay gap portal export (Tom's manual download)
    gp = pd.read_csv(RAW / "ie_gpg" / S["ie_gpg_file"], dtype=str)
    gp = gp.sort_values("Year").drop_duplicates("Employer Name", keep="last")
    for r in gp.itertuples():
        name, sector = r._1, str(r.NACE)
        base = dict(entity_id=f"IEGPG-{name}", name=name, country="IE")
        if r._4 not in S["ie_gpg_size_bands"]:
            removed.append({**base, "test": "size", "detail": f"Irish pay gap band {r._4}"})
            continue
        if "public administration" in sector.lower():
            removed.append({**base, "test": "private sector", "detail": f"Irish pay gap sector: {sector}"})
            continue
        nums = by_name.get(norm(name), [])
        if len(nums) != 1:
            review.append(dict(source="Irish gender pay gap portal", name=name, detail=sector,
                               reason="no exact CRO name match" if not nums else
                               f"name matches {len(nums)} CRO companies"))
            continue
        base = dict(entity_id=f"CRO-{nums[0]}", name=cro.loc[nums[0]].company_name, country="IE")
        nace = test_cro(nums[0], base)
        if nace is None:
            continue
        keep[base["entity_id"]] = dict(**base, id_type="CRO", industry_code=nace, size_band="250+ staff",
                                       size_test="250+ staff (Irish pay gap portal)", regulated="",
                                       alive="CRO status Normal", sources="Irish gender pay gap portal", flags="")

    # 2. Central Bank-authorised firms
    cbi = pd.read_csv(INTERIM / "cbi_firms.csv", dtype=str).fillna("")
    in_scope = cbi.register.str.startswith(tuple(S["cbi_keep_registers"])) & (
        ~cbi.register.str.contains("Section 10") | cbi.institution_type.isin(S["cbi_section10_keep_types"]))
    for r in cbi[~in_scope].itertuples():
        why = (f"Section 10 institution type '{r.institution_type}'" if "Section 10" in r.register
               else "register not in scope: " + re.sub(r" as at.*$", "", r.register))
        eid = f"CRO-{r.cro_num}" if r.cro_num else f"CU-{r.ref}"
        removed.append(dict(entity_id=eid, name=r.name, country="IE", test="Central Bank register", detail=why))
    cbi = cbi[in_scope]
    for num, g in cbi.groupby("cro_num"):
        regs = "; ".join(sorted(set(g.register.str.replace(r" as at.*$", "", regex=True))))
        if num == "":          # credit unions: not CRO companies; identified by their CU number
            if S["ie_keep_cbi_unconfirmed"]:
                for r in g.itertuples():
                    keep[f"CU-{r.ref}"] = dict(entity_id=f"CU-{r.ref}", name=r.name, country="IE",
                                               id_type="Central Bank credit union number", industry_code="64.19",
                                               size_band="unconfirmed",
                                               size_test="Central Bank-authorised (size unconfirmed)",
                                               regulated="authorised financial (CBI)", alive="on Central Bank register",
                                               sources=regs, flags="size unconfirmed")
            continue
        eid = f"CRO-{num}"
        if eid in keep:        # already in via the pay gap portal: size confirmed, add regulated status
            keep[eid]["regulated"] = "authorised financial (CBI)"
            keep[eid]["sources"] += "; " + regs
            continue
        base = dict(entity_id=eid, name=cro.loc[num].company_name, country="IE")
        if not S["ie_keep_cbi_unconfirmed"]:
            removed.append({**base, "test": "size", "detail": "Central Bank firm not on Irish pay gap portal"})
            continue
        nace = test_cro(num, base)
        if nace is None:
            continue
        keep[eid] = dict(**base, id_type="CRO", industry_code=nace, size_band="unconfirmed",
                         size_test="Central Bank-authorised (size unconfirmed)", regulated="authorised financial (CBI)",
                         alive="CRO status Normal", sources=regs, flags="size unconfirmed")
    for r in pd.read_csv(INTERIM / "cbi_review.csv", dtype=str).fillna("").itertuples():
        review.append(dict(source=r.register, name=r.name, detail=f"ref {r.ref}".strip(), reason=r.reason))
    removed = [r for r in removed if not (r["test"] == "Central Bank register" and r["entity_id"] in keep)]
    return list(keep.values()), removed, review


# ------------------------------------------------------------------ points 9 and 10: FCA / PRA additions
def build_additions(have):
    """Firms from data/interim/fca_additions.csv (PRA lists, advert employers on the FCA Register). Already in the
    universe: the source is noted. New: added with size unconfirmed, after the Companies House alive test."""
    import companies_house as ch
    p = INTERIM / "fca_additions.csv"
    if not p.exists():
        return [], []
    a = pd.read_csv(p, dtype=str).fillna("")
    keep, removed = {}, []
    for r in a.itertuples():
        src = "PRA list" if r.added_by == "PRA list" else "advert employer on FCA Register"
        if r.entity_id in have:
            e = have[r.entity_id]
            e["sources"] = "; ".join(filter(None, [e["sources"], src])) if src not in e["sources"] else e["sources"]
            continue
        if r.entity_id in keep:
            keep[r.entity_id]["sources"] += "" if src in keep[r.entity_id]["sources"] else f"; {src}"
            continue
        base = dict(entity_id=r.entity_id, name=r.name, country="UK")
        row = dict(**base, industry_code="", size_band=settings()["additions"]["size_label"],
                   size_test=f"{src} (size unconfirmed)", regulated="", sources=src,
                   flags="size unconfirmed")
        if r.entity_id.startswith("FRN-"):
            keep[r.entity_id] = dict(**row, id_type="FCA Register (no Companies House number)",
                                     alive=f"FCA status {r.fca_status}")
            keep[r.entity_id]["flags"] += "; no Companies House number on the FCA record"
            continue
        prof = ch.profile(r.entity_id)
        if prof is None:
            removed.append({**base, "test": "alive", "detail": f"{src}: not found at Companies House"})
            continue
        st = settings()["universe"]
        if prof.get("company_status") not in st["ch_alive_statuses"] or prof.get("has_insolvency_history"):
            removed.append({**base, "test": "alive", "detail": f"{src}: status {prof.get('company_status')}"})
            continue
        keep[r.entity_id] = dict(**row, id_type="Companies House", alive=prof.get("company_status"))
        keep[r.entity_id].update(name=prof.get("company_name", r.name), industry_code=",".join(prof.get("sic_codes") or []))
    return list(keep.values()), removed


def final_removals(rows):
    """Full run review point 6: FE and sixth-form colleges (codes 85310/85320/85410 with the public sector code "1"),
    education trusts and partnerships by name, and named entries. Universities are not touched."""
    S = settings()["universe"]
    fe, words = set(S["fe_college_codes"]), [w.lower() for w in S["remove_name_words"]]
    names = {norm(n) for n in S["remove_names"]}
    keep, out = [], []
    for e in rows:
        codes = {re.sub(r"\D", "", c) for c in re.split(r"[,;]", e.get("industry_code") or "") if c.strip()}
        low = (e.get("name") or "").lower()
        why = ("further education or sixth-form college (code " + ", ".join(sorted(codes & fe)) + " with public sector code 1)"
               if codes & fe and S["gpg_public_sector_code"] in codes else
               next((f"name contains '{w}'" for w in words if w in low), "") or
               ("named for removal" if norm(e.get("name") or "") in names else ""))
        if why:
            out.append(dict(entity_id=e["entity_id"], name=e["name"], country=e["country"], test="public sector or education",
                            detail=why))
        else:
            keep.append(e)
    return keep, out


COLS = ["entity_id", "name", "id_type", "country", "industry_code", "size_band", "size_test", "regulated",
        "alive", "sources", "flags"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    uk_k, uk_r = build_uk()
    ie_k, ie_r, ie_rev = build_ie()
    add_k, add_r = build_additions({e["entity_id"]: e for e in uk_k + ie_k})
    uk_k += add_k
    uk_r += add_r
    uk_k, extra = final_removals(uk_k)
    uk_r += extra
    ie_k, extra = final_removals(ie_k)
    ie_r += extra
    pd.DataFrame(ie_rev).to_csv(OUT / "review.csv", index=False)
    u = pd.DataFrame(uk_k + ie_k).reindex(columns=COLS).sort_values(["country", "name"])
    r = pd.DataFrame(uk_r + ie_r).sort_values(["test", "name"])
    u.to_csv(OUT / "universe.csv", index=False)
    r.to_csv(OUT / "removed.csv", index=False)
    print("universe:", len(u), u.country.value_counts().to_dict())
    print("  alive pending:", (u.alive == "pending").sum())
    print("review:", len(ie_rev))
    print("removed:", len(r), r.groupby(["country", "test"]).size().to_dict())


if __name__ == "__main__":
    main()
