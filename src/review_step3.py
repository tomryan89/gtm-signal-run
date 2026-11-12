"""Build Tom's Step 3 (rerun) review workbook in Uploads: before-and-after summary, large groups, brand lookup,
CMA table, signals and review."""
import json

import pandas as pd

from common import INTERIM, OUTPUT

O, B = OUTPUT / "step3", OUTPUT / "before_changes"
OUT = OUTPUT / "GTM Step 3 rerun review 2026-11-11.xlsx"


def metrics(groups, jobs, scanner, report):
    g = pd.read_csv(groups, dtype=str).fillna("")
    j = pd.read_csv(jobs, dtype=str).fillna("")
    s = pd.read_csv(scanner, dtype=str).fillna("")
    r = json.loads(report.read_text())
    return {
        "Entities in the universe": len(g),
        "Account groups": g.group_id.nunique(),
        "Groups with more than 10 entities": int((g.group_id.value_counts() > 10).sum()),
        "Irish groups": int(g[g.country == "IE"].group_id.nunique()),
        "Job adverts matching keywords": len(j),
        "Share of those adverts tied to a group": f"{(j.group_id != '').mean():.1%}",
        "Share with no named employer (recruiter)": f"{(j.recruiter != '').mean():.1%}",
        "Listed-company results attached to a group (of 481)": len(s),
        "  of which 'yes' or 'passing mention'": int(s.verdict.isin(["yes", "passing mention"]).sum()),
        "Pilot groups": r["pilot groups"], "Pilot entities": r["pilot entities"],
        "Signals for the pilot": r["signals"],
    }, r["signals by type"]


def main():
    before, bt = metrics(B / "step2" / "groups.csv", B / "job_adverts.csv", B / "scanner_matches.csv",
                         B / "step3" / "signals_report.json")
    after, at = metrics(OUTPUT / "step2" / "groups.csv", INTERIM / "job_adverts.csv", INTERIM / "scanner_matches.csv",
                        O / "signals_report.json")
    ba = pd.DataFrame({"Measure": list(after), "Before": [before.get(k, "") for k in after], "After": list(after.values())})
    types = sorted(set(bt) | set(at), key=lambda t: -at.get(t, 0))
    sbt = pd.DataFrame({"Signal type": types, "Before": [bt.get(t, 0) for t in types], "After": [at.get(t, 0) for t in types]})

    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    g["group_size"] = g.group_size.astype(int)
    big = g[g.group_size > 10]
    bigl = big.groupby("group_id").agg(group_name=("group_name", "first"), entities=("entity_id", "size"),
                                       parent_name=("parent_name", "first"), investor=("investor", "first"),
                                       sample_members=("entity_name", lambda s: "; ".join(list(s)[:6]))) \
        .reset_index().sort_values("entities", ascending=False)
    bigl["looks right? (Y/N)"] = ""
    inv = g[g.investor != ""].drop_duplicates("group_id")[["group_id", "group_name", "investor", "group_size"]]

    S = pd.read_csv(O / "signals.csv", dtype=str).fillna("")
    R = pd.read_csv(O / "review.csv", dtype=str).fillna("")
    pg = pd.read_csv(O / "pilot_groups.csv", dtype=str).fillna("")
    rep = json.loads((O / "signals_report.json").read_text())
    r20 = S.sample(20, random_state=20261111)[["group_name", "entity_name", "signal_type", "date", "source_link", "detail"]]
    r20["true? (Y/N)"] = ""; r20["date right? (Y/N)"] = ""
    lk = pd.read_csv(INTERIM / "brand_lookup.csv", dtype=str).fillna("")
    lk["check first"] = ""
    lk.loc[lk.confidence.isin(["medium", "low"]), "check first"] = "medium/low confidence"
    lk.loc[lk.name.isin(["Hays", "JN Bentley"]), "check first"] = "looks wrong - please check"
    cma = pd.read_csv(INTERIM / "cma_table.csv", dtype=str).fillna("")
    rm = pd.read_csv(OUTPUT / "step1" / "removed.csv", dtype=str).fillna("")
    rm_new = rm[(rm.test == "Central Bank register") | rm.detail.str.contains("education|school", case=False)]
    fca = pd.read_csv(INTERIM / "fca_firms.csv", dtype=str).fillna("")
    fca = fca[(fca.authorised == "True") | (fca.fca_type != "")][["entity_id", "entity_name", "frn", "fca_status", "fca_type",
                                                                  "fca_type_reason", "source_link"]]

    summary = [
        ["What this is", "Step 2 and Step 3 rerun after your 20 changes (11 Nov 2026), on the same pilot entities."],
        ["", ""], ["YOUR CHECKS", ""],
        ["1", "'Before and after' tab: the headline numbers you asked for."],
        ["2", "'Large groups' tab: every group with more than 10 entities (members in 'Large group members')."],
        ["3", "'Brand lookup' tab: Opus's pick for each name. Correct any row in 'tom_override' (a group_id, 'none' "
              "or 'recruiter'); 'check first' marks the ones to look at. Rows marked unsure are not applied."],
        ["4", "'CMA table' tab: each case, its parties and the matched group. Fill in 'tom_confirms'."],
        ["5", "'Random 20' tab: open each link; is the signal true and the date right?"],
        ["", ""], ["NOTES", ""],
        ["Group names", "Groups are named after the member with the largest pay gap staff band, as asked. Where a "
                        "staff company files the pay gap report, that becomes the name (e.g. Aviva -> 'AVIVA EMPLOYMENT "
                        "SERVICES LIMITED'). Foreign parents are in the 'parent_name' column."],
        ["Investors", "Industry codes 64304/66300 also catch some ordinary holding companies, and sponsor names also "
                      "stop at their own operating companies (e.g. Macquarie). See 'Investor stops'."],
        ["Pilot", f"Same 811 entities as before, minus those removed from the universe; they now sit in "
                  f"{rep['pilot groups']} groups ({rep['pilot entities']} entities). Split: "
                  + ", ".join(f"{k} {v}" for k, v in pg.stratum.value_counts().items())],
        ["Listed-company file", "Has no company-number column, so matching is by name (after tidying) and the lookup."],
        ["Board turnover", "Now counted on each group's top company only. UK only (no free Irish director data)."],
        ["Brand lookup cost", "One Opus batch, 165 names: $0.50 (estimate was $0.77)."],
        ["Schools", "Removed by education code or by name word; a few name-only matches may be borderline (see "
                    "'Removed in rerun')."],
    ]
    with pd.ExcelWriter(OUT) as w:
        for name, df in [("Summary", pd.DataFrame(summary, columns=["Item", "Value"])), ("Before and after", ba),
                         ("Signals by type", sbt), ("Large groups", bigl),
                         ("Large group members", big.sort_values(["group_size", "group_id"], ascending=[False, True])),
                         ("Brand lookup", lk), ("CMA table", cma), ("Random 20", r20), ("Signals", S), ("Review", R),
                         ("Pilot groups", pg), ("Investor stops", inv), ("FCA firm types", fca),
                         ("Removed in rerun", rm_new)]:
            df.to_excel(w, sheet_name=name, index=False); ws = w.sheets[name]; ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(70, max(10, max(len(str(c.value or "")) for c in col[:200]) + 2))
    print("written", OUT)
    print(ba.to_string(index=False)); print(sbt.to_string(index=False))


if __name__ == "__main__":
    main()
