"""Step 4: score, band and rank the pilot groups (Reference A), and export the pilot spreadsheet.

  python src/score.py   -> output/step4/pilot_ranked.xlsx (+ csv), copied to Uploads

Score = need + timing. Each signal family counts once per group (the best one):
  need families (no decay): principal risk (3 named / 1 passing); sector (highest of authorised financial 2,
  critical infrastructure 2, intermediary or adviser 1, other regulated 1, pharmaceuticals 1).
  trigger families (decayed by age from the run date): hiring (highest of 4 / 3 / 2), new senior manager 4,
  merger 3, pre-IPO 2, board turnover 1, new funding or charge 1, headcount growth 1.
Job adverts are scored on title keywords only until Step 5 (model check)."""
import json
import re
import shutil
from datetime import date

import pandas as pd

import companies_house as ch
from common import INTERIM, OUTPUT, log, paths, settings, to_uploads

ST = settings()
NP, TP = ST["points"]["need"], ST["points"]["trigger"]
RUN = date.fromisoformat(ST["run"]["run_date"])
P = paths()
OUT = P["dir4"]



def rule(stype):
    """(need|trigger, family, points) for a signal type."""
    s = stype
    if s == "principal risk named": return "need", "principal risk", NP["principal_risk_named"]
    if s == "principal risk passing mention": return "need", "principal risk", NP["principal_risk_passing"]
    if s == "authorised financial firm": return "need", "sector", NP["authorised_financial"]
    if s.startswith("authorised financial firm (intermediary"): return "need", "sector", NP["authorised_intermediary"]
    if s.startswith("critical infrastructure"): return "need", "sector", NP["critical_infrastructure"]
    if s.startswith("other regulated sector"): return "need", "sector", NP["other_regulated"]
    if s == "pharmaceuticals": return "need", "sector", NP["pharmaceuticals"]
    if s in ("hiring: third-party risk role", "hiring: security leader"): return "trigger", "hiring", TP["hiring_tprm_or_security_leader"]
    if s.startswith("hiring: senior leader"): return "trigger", "hiring", TP["hiring_senior_leader"]
    if s.startswith("hiring:"): return "trigger", "hiring", TP["hiring_wider_or_operating_change"]
    if s.startswith("new senior manager"): return "trigger", "new senior manager", TP["new_smf4_smf5"]
    if s.startswith("merger") and "smaller bolt-on" in s: return "trigger", "merger", TP["merger_bolt_on"]
    if s.startswith("merger"): return "trigger", "merger", TP["merger"]
    # stage 2: news and regulator enforcement share one family; incidents at the account; ransomware and peers
    if s.startswith("regulatory enforcement"): return "trigger", "regulatory enforcement", TP["regulatory_enforcement"]
    if s.startswith("regulatory governance downgrade"): return "trigger", "regulatory enforcement", TP["governance_downgrade"]
    if s.startswith("operational incident or supplier failure"): return "trigger", "incident at the account", TP["news_incident"]
    if s.startswith("claimed ransomware victim"): return "trigger", "ransomware claim", TP["ransomware_claim"]
    if s.startswith("peer incident"): return "trigger", "peer incident", TP["peer_incident"]
    if s.startswith("pre-IPO"): return "trigger", "pre-IPO", TP["pre_ipo"]
    if s == "board turnover": return "trigger", "board turnover", TP["board_turnover"]
    if s.startswith(("new funding", "new charge")): return "trigger", "new funding or charge", TP["new_funding_or_charge"]
    if s.startswith("headcount growth"): return "trigger", "headcount growth", TP["headcount_growth"]
    raise ValueError(f"no scoring rule for signal type '{stype}'")


def decay(d):
    try:
        dt = date.fromisoformat(str(d)[:10])
    except ValueError:
        return 0.0, None
    months = max(0.0, (RUN - dt).days / 30.4375)
    for limit, mult in ST["decay"]["bands"]:
        if months < limit:
            return mult, round(months, 1)
    return 0.0, round(months, 1)


SIC_SECTION = [(1, 3, "Agriculture"), (5, 9, "Mining and energy extraction"), (10, 33, "Manufacturing"),
               (35, 35, "Energy"), (36, 39, "Water and waste"), (41, 43, "Construction"),
               (45, 47, "Wholesale and retail"), (49, 53, "Transport and logistics"), (55, 56, "Hospitality"),
               (58, 63, "Information and communication"), (64, 66, "Financial services"), (68, 68, "Real estate"),
               (69, 75, "Professional services"), (77, 82, "Business support"), (84, 84, "Public administration"),
               (85, 85, "Education"), (86, 88, "Health and care"), (90, 93, "Arts and leisure"), (94, 96, "Other services")]


def sector(codes):
    for c in re.split(r"[,;]", codes or ""):
        d = re.sub(r"\D", "", c[:-2] if c.endswith(".0") else c)[:2]
        if d.isdigit():
            n = int(d)
            for a, b, name in SIC_SECTION:
                if a <= n <= b:
                    return name
    return ""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    S = pd.read_csv(P["signals"], dtype=str).fillna("")
    pg = pd.read_csv(P["groups"], dtype=str).fillna("")
    pe = pd.read_csv(P["entities"], dtype=str).fillna("")
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    uinfo = u.set_index("entity_id")
    R = pd.read_csv(P["review"], dtype=str).fillna("")
    # speed: index members, signals and review rows by group once (Step 7 has ~11,000 groups)
    pe_by = dict(tuple(pe.groupby("group_id")))
    from sectors import lead_member
    sb_all, ic_all = dict(zip(u.entity_id, u.size_band)), dict(zip(u.entity_id, u.industry_code))
    fca = pd.read_csv(OUTPUT.parent / "data" / "interim" / "fca_firms.csv", dtype=str).fillna("")
    fs_entities = set(fca[(fca.counts_as_financial == "True") & fca.fca_type.isin(ST["sector_label"]["financial_fca_types"])].entity_id)
    nrev_by = R.groupby("group_id").size().to_dict() if "group_id" in R else {}

    S[["kind", "family", "points"]] = S.signal_type.apply(lambda t: pd.Series(rule(t)))
    dec = S.date.map(decay)
    S["decay"] = [1.0 if k == "need" else d[0] for k, d in zip(S.kind, dec)]
    S["age_months"] = [("" if k == "need" else d[1]) for k, d in zip(S.kind, dec)]
    S["value"] = S.points.astype(float) * S.decay
    # the counted signal per group and family: highest value, then most recent
    S = S.sort_values(["group_id", "family", "value", "date"], ascending=[True, True, False, False])
    S["counted"] = ~S.duplicated(["group_id", "family"])

    rows = []
    bands = ST["bands"]
    S_by = dict(tuple(S[S.counted].groupby("group_id")))
    empty = S.iloc[0:0]
    for g in pg.itertuples():
        m = pe_by.get(g.group_id, pe.iloc[0:0])
        sg = S_by.get(g.group_id, empty)
        need = sg[sg.kind == "need"].value.sum()
        timing = sg[sg.kind == "trigger"].value.sum()
        hire = sg[sg.family == "hiring"].value.sum()
        # point 1 (Tom, 11 Nov): Act now needs timing 3+ AND a counted trigger worth 3+ before decay
        # (third-party risk role, security leader, senior leader advert, new Senior Manager, merger)
        strong = sg[(sg.kind == "trigger") & (sg.value > 0) & (sg.family != "peer incident")
                    & (sg.points.astype(float) >= bands["act_now_min_trigger_points"])]
        # full run review point 1: Warming needs timing 2+; below that, Strong fit or Fit only by need
        band = ("Act now" if timing >= bands["act_now_min_timing"] and len(strong) else
                "Warming" if timing >= bands["warming_min_timing"] else
                "Strong fit" if need >= bands["strong_fit_min_need"] else "Fit only")
        top3 = sg[sg.value > 0].sort_values(["value", "date"], ascending=[False, False]).head(3)
        ev = {}
        for i, x in enumerate(top3.itertuples(), 1):
            ev[f"signal {i}"] = x.signal_type
            ev[f"signal {i} date"] = x.date
            ev[f"signal {i} entity"] = f"{x.entity_name} ({x.entity_id})" if x.entity_id else x.entity_name
            ev[f"signal {i} source"] = x.source_link
        sb = [uinfo.size_band.get(e, "") for e in m.entity_id if e in uinfo.index]
        staff = [b for b in sb if "staff" in b]
        size = (max(staff, key=lambda b: ST["universe"]["min_staff_bands"].index(b.replace(" staff", ""))
                    if b.replace(" staff", "") in ST["universe"]["min_staff_bands"] else -1) if staff
                else next((b for b in sb if b and b != "unconfirmed"), "unconfirmed"))
        # full run review point 2: FCA-authorised bank / building society / insurer / investment firm / payment
        # institution -> Financial services; universities register -> Education; housing register -> Housing;
        # otherwise the industry code of the largest member (holding and head-office codes ignored)
        ids = [e for e in m.entity_id if e in uinfo.index]
        reg = " ".join(uinfo.regulated.get(e, "") for e in ids)
        # v4 item 6 (Tom, 13 Nov 2026): "Financial services" only when the largest member or the top company is a
        # financial firm (FCA bank / building society / insurer / investment firm / payment institution, or on the
        # Central Bank of Ireland register); a group that merely owns a small authorised firm keeps its main sector
        from sectors import band_rank as _br
        largest = max(ids, key=lambda e: _br(sb_all.get(e, "")), default="")
        topc = next((t for t in m.top_company_number if t), g.group_id[3:] if g.group_id.startswith("UK:") else "")
        fin = lambda e: e in fs_entities or "CBI" in uinfo.regulated.get(e, "")
        if (largest and fin(largest)) or (topc and fin(topc)):
            sec = "Financial services"
        elif "university" in reg:
            sec = "Education"
        elif "housing" in reg:
            sec = "Housing"
        else:
            sec = sector(",".join(lead_member(ids, sb_all, ic_all)[1]))
        top = g.group_id[3:] if g.group_id.startswith("UK:") else next((t for t in m.top_company_number if t), "")
        due = ((ch.profile(top) or {}).get("accounts") or {}).get("next_due", "") if top else ""
        flags = []
        if (m.flag == "Irish grouping unchecked").any(): flags.append("grouping unchecked")
        if sb and all(b in ("", "unconfirmed") for b in sb): flags.append("size unconfirmed")
        for f in ("joint venture - check", "owned by a non-company body - check"):
            if (m.flag == f).any(): flags.append(f)
        if (m.investor != "").any(): flags.append("owned by an investor")
        nrev = int(nrev_by.get(g.group_id, 0))
        if nrev: flags.append(f"{nrev} unmatched signals in review")
        rows.append(dict(group_id=g.group_id, group_name=m.group_name.iloc[0] if len(m) else g.group_name,
                         band=band, total=round(need + timing, 2), need=round(need, 2), trigger_after_decay=round(timing, 2),
                         hiring_points=round(hire, 2), country="/".join(sorted(set(m.country))), sector=sec,
                         size_band=size, size_confirmed="no" if size == "unconfirmed" else "yes", entities=len(m),
                         entity_list="; ".join(f"{n} ({i})" for n, i in zip(m.entity_name, m.entity_id)),
                         **ev, next_accounts_due=due, brief="", brief_date="", flags="; ".join(flags),
                         pilot_stratum=g.stratum, investor="; ".join(sorted(set(m.investor) - {""}))))
    T = pd.DataFrame(rows)
    T["_b"] = T.band.map({b: i for i, b in enumerate(ST["sector_label"]["band_order"])})
    T = T.sort_values(["_b", "total", "trigger_after_decay", "need", "group_name"],
                      ascending=[True, False, False, False, True]).drop(columns=["_b"])
    T.insert(0, "rank", range(1, len(T) + 1))
    T["act_now_on_job_advert_alone"] = (T.band == "Act now") & (T.trigger_after_decay - T.hiring_points < bands["act_now_min_timing"])
    # v6 item 1 (Tom, 13 Nov 2026): Act now / Warming / Strong fit groups take Opus's known_as and sector
    # (src/names_sectors.py); every other group keeps the rule-based sector and is known by its group name in normal
    # capitalisation
    from names_sectors import BANDS as NS_BANDS, nice_case
    T["rule_sector"] = T.sector
    T["known_as"] = T.group_name.map(nice_case)
    T["sector_source"] = "rule (industry codes / registers)"
    nsf = INTERIM / "names_sectors.csv"
    if nsf.exists():
        ns = pd.read_csv(nsf, dtype=str).fillna("").set_index("group_id")
        ok = T.band.isin(NS_BANDS) & T.group_id.isin(ns[ns.sector != ""].index)
        T.loc[ok, "sector"] = T.loc[ok, "group_id"].map(ns.sector)
        T.loc[ok, "known_as"] = T.loc[ok, "group_id"].map(ns.known_as).where(lambda k: k != "", T.loc[ok, "known_as"])
        T.loc[ok, "sector_source"] = "model (Opus, from the group's name, members and brands)"
        miss = T.band.isin(NS_BANDS) & ~ok
        if miss.any():
            print(f"WARNING: {int(miss.sum())} top-band groups have no model name/sector (rule-based kept)")
    T.to_csv(P["ranked"], index=False)
    Ssc = S.merge(T[["group_id", "group_name", "rank", "band"]], on="group_id", how="left", suffixes=("_signal", ""))
    Ssc = Ssc[["rank", "group_id", "group_name", "band", "entity_name", "entity_id", "signal_type", "kind", "family", "points", "date",
               "age_months", "decay", "value", "counted", "source", "source_link", "detail"]].sort_values(
        ["rank", "kind", "value"], ascending=[True, True, False])
    Ssc.to_csv(P["scored"], index=False)

    rep = {"pilot groups": len(T), "bands": T.band.value_counts().to_dict(),
           "Act now on a job advert alone": int(T.act_now_on_job_advert_alone.sum()),
           "groups with no signal at all": int((T.total == 0).sum())}
    P["score_report"].write_text(json.dumps(rep, indent=1))
    log("score", "done", **rep)
    rules = pd.DataFrame([
        ["Run date (decay counted from)", ST["run"]["run_date"]],
        ["Need (no decay)", "principal risk 3 (passing mention 1) + the highest sector need: authorised financial "
                            "firm 2, critical infrastructure 2, intermediary/adviser 1, other regulated 1, pharmaceuticals 1"],
        ["Timing (decayed)", "hiring highest of 4/3/2, new SMF4/5 4, merger 3, pre-IPO 2, board turnover 1, "
                             "new funding or charge 1, headcount growth 1; each once per group"],
        ["Decay", "under 3 months full, 3-6 half, 6-12 quarter, older nothing"],
        ["Bands", "Act now: timing 3+ and at least one trigger worth 3+ before decay; Warming: other timing 2+; "
                  "Strong fit: need 3+ and no timing; Fit only: the rest"],
        ["Job adverts", "scored on title keywords only until Step 5 (model check)"],
    ], columns=["Rule", "Value"])
    if P["scope"] == "full":       # the full run's spreadsheet is built by review_full.py (with briefs)
        print(json.dumps(rep, indent=1)); return
    with pd.ExcelWriter(P["xlsx"]) as w:
        for name, df in [("Ranked list", T), ("Signals scored", Ssc), ("Rules", rules)]:
            df.to_excel(w, sheet_name=name, index=False); ws = w.sheets[name]; ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(9, max(len(str(c.value or "")) for c in col[:150]) + 2))
    if ST["run"].get("pilot_upload", True):     # off for stage 2: keep Tom's earlier pilot file in Uploads
        to_uploads(P["xlsx"])
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
