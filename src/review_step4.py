"""Tom's Step 4 workbook: the ranked pilot plus answers to his 11 Nov corrections (points 8-11)."""
import json

import pandas as pd

from brands import table as brand_table
from common import INTERIM, OUTPUT, ROOT

OUT = OUTPUT / "GTM Step 4 pilot ranked 2026-11-11.xlsx"
O4 = OUTPUT / "step4"


def main():
    T = pd.read_csv(O4 / "pilot_ranked.csv", dtype=str).fillna("")
    S = pd.read_csv(O4 / "pilot_signals_scored.csv", dtype=str).fillna("")
    rep = json.loads((O4 / "score_report.json").read_text())
    j = pd.read_csv(INTERIM / "job_adverts.csv", dtype=str).fillna("")
    ov = pd.read_csv(ROOT / "corrections" / "brand_overrides.csv", dtype=str, keep_default_na=False)
    p10 = ov[ov.note.str.startswith("point 10")].rename(columns={"name": "brand", "override": "mapped to", "note": "answer"})
    rm = pd.read_csv(OUTPUT / "step1" / "removed.csv", dtype=str).fillna("")
    nc = rm[rm.detail == "pay gap entry with no company or register number"]
    mutual = nc[nc.name.str.contains(r"building society|friendly society|mutual|co-operative", case=False)][["name", "test", "detail"]]
    mp = pd.read_csv(OUTPUT / "step2" / "merge_proposals.csv", dtype=str).fillna("")
    lk = brand_table()[["name", "sources", "adverts", "model_answer", "confidence", "tom_override", "override_note", "final",
                        "model_reason"]]
    cma = pd.read_csv(INTERIM / "cma_table.csv", dtype=str).fillna("")
    not_applied = pd.DataFrame([
        ["10", "Lockton", "Lockton Companies LLP is not in the source files; set to none (as you asked for now)."],
        ["10", "Nationwide", "Nationwide Building Society was removed: its pay gap entry has no company number "
                             "(building societies have an FCA mutual number instead)."],
        ["10", "Bloomberg", "Bloomberg LP was removed: pay gap entry with no company number. Bloomberg UK Limited is not in the files."],
        ["10", "OakNorth, Airwallex, Huel, ICE (Futures Europe / Clear Europe), Lockton Companies LLP",
         "Never in the pay gap or modern slavery files used (2025-2026 / 2024-2027)."],
        ["10", "TalkTalk", "TalkTalk Telecom Group Limited is not in the files. TalkTalk Group Limited and TalkTalk Telecom "
                           "Limited are, but were removed by the alive test (in administration, insolvency history)."],
        ["10", "Finsbury Food Group", "Finsbury Food Group Limited is not in the files. Its subsidiary Nicholas & Harris "
                                      "Limited is, in group UK:15091858 (UK Frisbee Debtco). Not mapped - say if you want it."],
        ["10", "Venator", "Venator Materials UK Limited is only in the 2024 pay gap and 2021 modern slavery files, outside "
                          "the years used."],
        ["10", "DMG Media Limited", "Not in the files; mapped Daily Mail and General Trust plc to Associated Newspapers Limited instead."],
        ["10", "RSA / More Than", "Found by company number: Royal & Sun Alliance Insurance Limited 00093792 is now named "
                                  "INTACT INSURANCE UK LIMITED. Mapped to its group (foreign parent 2283485 Alberta Ltd)."],
        ["10", "British Steel", "Found by company number: British Steel Limited 12303256 is now named 2026 TRANSFEROR "
                                "COMPANY LIMITED (Jingye group). Mapped, but the trading business may have moved company."],
        ["10", "SGN", "Mapped as asked, but SGN's group is Brookfield Corporation, which also holds Center Parcs: Brookfield "
                      "is not on the investor list, so the walk did not stop below it."],
        ["9", "general rule", "Drafted, not applied: see 'Merge proposals (not applied)'."],
        ["jobs", "Wise, Morgan Stanley", "Now match two groups each and go to review (Wise: Wise Group Plc and The Wise "
                                         "Group charity; Morgan Stanley: its UK group and its Eaton Vance foreign-parent group). "
                                         "Before, 'Wise' wrongly matched the charity. Candidates for the next lookup round."],
    ], columns=["point", "item", "what happened"])
    summary = pd.DataFrame([
        ["Pilot groups", rep["pilot groups"]],
        *[[f"Band: {b}", n] for b, n in rep["bands"].items()],
        ["Groups with no signal at all", rep["groups with no signal at all"]],
        ["Act now that needs a job advert to get there", rep["Act now on a job advert alone"]],
        ["Act now where the job advert alone gives 3+", int(((T.band == "Act now") & (T.hiring_points.astype(float) >= 3)).sum())],
        ["Share of keyword job adverts tied to a group (whole UK pull)", f"{(j.group_id != '').mean():.1%} (was 28.4%; 20.7% at first)"],
        ["Job adverts are scored on", "title keywords only until Step 5"],
        ["Building societies / friendly societies removed for no company number", f"{len(mutual)} (see 'Point 10 answers')"],
    ], columns=["Measure", "Value"])
    with pd.ExcelWriter(OUT) as w:
        for name, df in [("Summary", summary), ("Ranked list", T), ("Signals scored", S),
                         ("Not applied or flagged", not_applied), ("Point 10 answers", p10),
                         ("Mutuals removed", mutual), ("Merge proposals (not applied)", mp),
                         ("Brand lookup (final)", lk), ("CMA table", cma)]:
            df.to_excel(w, sheet_name=name, index=False); ws = w.sheets[name]; ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(9, max(len(str(c.value or "")) for c in col[:150]) + 2))
    print("written", OUT); print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
