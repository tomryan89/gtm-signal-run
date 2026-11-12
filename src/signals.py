"""Step 3 output: one row per signal for the pilot groups, plus one review file.

  python src/signals.py

Inputs (all in data/interim): fca_firms, fca_smf, job_adverts, cma_matches, ch_signals, scanner_matches,
and the regulated column of the Step 1 universe (Central Bank, housing, universities).
Output: output/step3/signals.csv, review.csv, signals_report.json"""
import json
from datetime import date

import pandas as pd

from common import INTERIM, OUTPUT, log, paths, settings

P = paths()
ST = settings()
CBI_LINK = "https://registers.centralbank.ie/"
RSH_LINK = "https://www.gov.uk/government/publications/registered-providers-of-social-housing"
OFS_LINK = "https://www.officeforstudents.org.uk/for-providers/regulatory-resources/the-ofs-register/"


def rd(name):
    p = INTERIM / name
    return pd.read_csv(p, dtype=str).fillna("") if p.exists() and p.stat().st_size > 1 else pd.DataFrame()


def main():
    pe = pd.read_csv(P["entities"], dtype=str).fillna("")
    pg = pd.read_csv(P["groups"], dtype=str).fillna("")
    gname = dict(zip(pg.group_id, pg.group_name))
    ename = dict(zip(pe.entity_id, pe.entity_name))
    egroup = dict(zip(pe.entity_id, pe.group_id))
    inpilot = set(pg.group_id)
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    sig, rev = [], []
    canon = {i: ids[0] for ids in settings()["grouping"].get("merges", []) for i in ids}

    def add(group, entity, stype, kind, dt, link, detail, source):
        group = egroup.get(entity, canon.get(group, group))   # v4: a signal follows its entity's current group;
                                                              # v5: a signal without an entity follows a merged group
        sig.append(dict(group_id=group, group_name=gname.get(group, ""), entity_id=entity, entity_name=ename.get(entity, ""),
                        signal_type=stype, need_or_trigger=kind, date=dt, source=source, source_link=link, detail=detail))

    # --- need: authorised financial firm (FCA)
    f = rd("fca_firms.csv")
    for x in f[(f.counts_as_financial == "True") & f.entity_id.isin(pe.entity_id)].itertuples():
        t = "authorised financial firm" if x.fca_points_tier == "2" else "authorised financial firm (intermediary or adviser)"
        add(egroup[x.entity_id], x.entity_id, t, "need", "", x.source_link,
            f"FCA FRN {x.frn}: {x.fca_type} ({x.fca_type_reason})", "FCA Register")
    # point 12: critical infrastructure / pharmaceuticals, from industry codes. Full run review point 3: only when it
    # is the sector of the group's largest member (sectors.lead_member), not any small subsidiary's code
    from sectors import lead_member
    sectors = ST["sector_codes"]
    ie_map = ST.get("sector_codes_ie", {})
    sb, ic = dict(zip(u.entity_id, u.size_band)), dict(zip(u.entity_id, u.industry_code))
    ctry = dict(zip(u.entity_id, u.country))
    for gid, m in pe.groupby("group_id", sort=False):
        lead, codes = lead_member(list(m.entity_id), sb, ic)
        if not lead:
            continue
        for label, prefixes in sectors.items():
            if ctry.get(lead) == "IE":     # 4-digit NACE: 5-digit UK codes only through the Irish table
                pre = tuple(ie_map[p_] if len(p_) == 5 else p_ for p_ in prefixes if len(p_) < 5 or p_ in ie_map)
                hit = [c for c in codes if pre and c.startswith(pre)]
            else:
                hit = [c for c in codes if c.startswith(tuple(prefixes))]
            if hit:
                add(gid, lead, label, "need", "",
                    f"https://find-and-update.company-information.service.gov.uk/company/{lead}"
                    if ctry.get(lead) == "UK" else "https://opendata.cro.ie/",
                    f"industry code {', '.join(hit)} (the group's largest member)",
                    "Companies House" if ctry.get(lead) == "UK" else "CRO")
                break
    # point 18: headcount growth (pay gap staff band moved up)
    hg = rd("headcount_growth.csv")
    for x in hg[hg.entity_id.isin(pe.entity_id)].itertuples() if len(hg) else []:
        add(egroup[x.entity_id], x.entity_id, "headcount growth (pay gap band up)", "trigger", x.date,
            f"https://gender-pay-gap.service.gov.uk/viewing/search-results?search={x.employer.replace(' ', '+')}",
            f"{x.EmployerSize_prev} ({x.year_prev}) -> {x.EmployerSize_last} ({x.year_last}); report submitted {x.date}",
            "UK gender pay gap service")
    fr = rd("fca_review.csv")
    for x in fr[fr.entity_id.isin(pe.entity_id)].itertuples() if len(fr) else []:
        rev.append(dict(source="FCA Register", group_id=egroup[x.entity_id], item=x.entity_name, reason=x.reason,
                        source_link=getattr(x, "source_link", "")))
    # --- need: regulated (Central Bank / housing / universities), from the Step 1 registers
    for x in u[u.entity_id.isin(pe.entity_id) & (u.regulated != "")].itertuples():
        if "CBI" in x.regulated:
            add(egroup[x.entity_id], x.entity_id, "authorised financial firm", "need", "", CBI_LINK, x.sources[:200], "Central Bank of Ireland")
        elif "housing" in x.regulated:
            add(egroup[x.entity_id], x.entity_id, "other regulated sector (housing)", "need", "", RSH_LINK, "Registered provider of social housing", "RSH register")
        elif "university" in x.regulated:
            add(egroup[x.entity_id], x.entity_id, "other regulated sector (universities)", "need", "", OFS_LINK, "On the OfS register", "OfS register")
    # --- need: principal risk (listed-company app)
    s = rd("scanner_matches.csv")
    for x in s.itertuples() if len(s) else []:
        g = x.group_id
        if g in inpilot and x.verdict in ("yes", "passing mention"):
            add(g, x.entity_id if x.entity_id in ename else "", "principal risk named" if x.verdict == "yes" else
                "principal risk passing mention", "need", x.report_date, x.source_link,
                f"{x.risk_title}: \"{x.quote[:300]}\"",
                f"{x.company} annual report {x.report_date[:4]}".strip())     # point 7: cite the report, not the app
    # --- stage 2 (Tom, 12 Nov 2026): signals built by stage2_signals.py (Slices A, B, D), when switched on
    if ST.get("stage2", {}).get("include_in_scoring"):
        s2 = rd("stage2_signals.csv")
        for x in s2[s2.group_id.isin(inpilot)].itertuples() if len(s2) else []:
            add(x.group_id, x.entity_id if x.entity_id in ename else "", x.signal_type, x.kind, x.date, x.source_link,
                x.detail, x.source)
    # --- trigger: SMF4 / SMF5
    m = rd(P["smf"].name)
    for x in m[m.in_window == "True"].drop_duplicates(["entity_id", "irn", "function"]).itertuples() if len(m) else []:
        add(x.group_id, x.entity_id, "new senior manager (SMF4/SMF5)", "trigger", x.start, x.source_link,
            f"{x.person} ({x.irn}): {x.function}, from {x.start}", "FCA Register")
    # --- trigger: job adverts
    j = rd("job_adverts.csv")
    if len(j):
        # Step 5: where the model has classified an advert, its verdict replaces the keyword category;
        # "irrelevant" adverts score nothing
        jc = rd(P["classified"].name)
        verdict = dict(zip(jc.advert_id, zip(jc.model_category, jc.model_confidence, jc.model_reason))) if len(jc) else {}
        to_type = {"third-party risk role": "third-party risk role", "security leader": "security leader",
                   "senior leader": "senior leader (procurement, risk, compliance)",
                   "wider role": "wider risk/compliance/procurement role", "operating change role": "operating change role"}
        for x in j[j.group_id.isin(inpilot)].itertuples():
            cat, how = x.category, "keyword match only"
            if x.advert_id in verdict and verdict[x.advert_id][0]:
                mc, conf, why = verdict[x.advert_id]
                if mc == "irrelevant":
                    continue
                cat, how = to_type[mc], f"model: {mc} ({conf}) - {why}"
            add(x.group_id, x.entity_id, f"hiring: {cat}", "trigger", x.posted or x.pulled_on, x.link,
                f"\"{x.title}\" at {x.employer} ({x.source}, posted {x.posted}, pulled {x.pulled_on}; matched by "
                f"{x.match}; {how})", x.source)
        for x in j[j.review_reason.str.startswith(("employer name matches", "no employer", "employer name looks",
                                                   "advert text", "employer is a recruitment", "employer looks like a public"))].itertuples():
            rev.append(dict(source=x.source, group_id="", item=f"{x.title} | {x.employer}", reason=x.review_reason,
                            source_link=x.link))
    # --- trigger: CMA merger cases
    c = rd("cma_matches.csv")
    for x in c[c.group_id.isin(inpilot)].drop_duplicates(["case", "group_id"]).itertuples() if len(c) else []:
        add(x.group_id, x.entity_id, "merger, acquisition or separation", "trigger", x.opened, x.source_link,
            f"{x.case} (party: {x.party}; {x.match})", "CMA / GOV.UK")
    for x in rd("cma_review.csv").itertuples():
        rev.append(dict(source="CMA / GOV.UK", group_id="", item=f"{x.case} | party: {x.party}", reason=x.reason,
                        source_link=x.source_link))
    # --- trigger: Companies House filings
    h = rd(P["ch_signals"].name)
    for x in h.itertuples() if len(h) else []:
        add(x.group_id, x.entity_id, x.signal, "trigger", x.date, x.source_link, x.detail, "Companies House")
    # --- scanner rows that could not be matched
    for x in rd("scanner_review.csv").itertuples():
        rev.append(dict(source="Listed-company app", group_id="", item=f"{x.company} ({x.verdict})", reason=x.reason,
                        source_link=x.source_link))

    S, R = pd.DataFrame(sig), pd.DataFrame(rev)
    S = S.sort_values(["group_name", "need_or_trigger", "signal_type", "date"])
    S.to_csv(P["signals"], index=False)
    R.to_csv(P["review"], index=False)
    ja = j if len(j) else pd.DataFrame(columns=["recruiter", "group_id", "review_reason"])
    ja = ja.fillna("")
    nrec = int((ja.recruiter != "").sum())
    sc = rd("scanner_matches.csv")
    g2 = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    rep = {"pilot groups": len(pg), "pilot entities": len(pe), "signals": len(S),
           "share of keyword job adverts tied to a group (whole universe)":
               f"{(ja.group_id != '').mean():.1%}" if len(ja) else "",
           "listed-company results attached to a group": int(len(sc)),
           "listed-company results attached (yes / passing mention)": int(sc.verdict.isin(["yes", "passing mention"]).sum()) if len(sc) else 0,
           "Irish groups (whole universe)": int(g2[g2.country == "IE"].group_id.nunique()),
           "groups with more than 10 entities (whole universe)": int((g2.group_id.value_counts() > 10).sum()),
           "signals by type": S.signal_type.value_counts().to_dict() if len(S) else {},
           "pilot groups with at least one signal": int(S.group_id.nunique()) if len(S) else 0,
           "review rows": len(R), "review by source and reason": R.groupby(["source", "reason"]).size().to_dict() if len(R) else {},
           "job adverts matching keywords": len(ja),
           "job adverts with no named employer (recruiter)": f"{nrec} ({nrec / max(1, len(ja)):.1%})",
           "job adverts matched to a group (whole universe)": int((ja.group_id != "").sum()),
           "job adverts whose employer is not in the universe": int((ja.review_reason == "employer not in the universe").sum())}
    rep["review by source and reason"] = {" | ".join(k): v for k, v in rep["review by source and reason"].items()}
    P["signals_report"].write_text(json.dumps(rep, indent=1))
    log("signals", "built", signals=len(S), review=len(R))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
