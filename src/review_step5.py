"""Tom's Step 5 workbook: classified adverts, briefs, rescored ranking, cost report, Part 1/3 answers."""
import json

import pandas as pd

from common import INTERIM, OUTPUT, settings

ST = settings()
M = ST["models"]
OUT = OUTPUT / "GTM Step 5 pilot 2026-11-11.xlsx"


def main():
    c = pd.read_csv(INTERIM / "job_classified.csv", dtype=str).fillna("")
    for col in ("haiku_in", "haiku_out", "opus_in", "opus_out"):
        c[col] = pd.to_numeric(c[col], errors="coerce").fillna(0)
    c["cost_usd"] = pd.to_numeric(c.cost_usd)
    b = pd.read_csv(INTERIM / "briefs.csv", dtype=str).fillna("")
    for col in ("input_tokens", "output_tokens", "cost_usd"):
        b[col] = pd.to_numeric(b.get(col, 0), errors="coerce").fillna(0)
    T = pd.read_csv(OUTPUT / "step4" / "pilot_ranked.csv", dtype=str).fillna("")
    K = pd.read_csv(OUTPUT / "step4" / "pilot_ranked_keyword_only.csv", dtype=str).fillna("").set_index("group_id")
    j = pd.read_csv(INTERIM / "job_adverts.csv", dtype=str).fillna("")
    bm = dict(zip(b.group_id, zip(b.what_changed, b.why_it_matters, b.opening_line, b.brief_date)))
    T["brief"] = T.group_id.map(lambda g: "\n".join(bm[g][:3]) if g in bm else "")
    T["brief_date"] = T.group_id.map(lambda g: bm[g][3] if g in bm else "")
    T["band_keyword_only"] = T.group_id.map(K.band)
    T["total_keyword_only"] = T.group_id.map(K.total)

    n, opus = len(c), int((c.sent_to_opus == "True").sum())
    h_in, h_out, o_in, o_out = c.haiku_in.sum(), c.haiku_out.sum(), c.opus_in.sum(), c.opus_out.sum()
    ph, po_, pf = M["price"][M["classify_first"]], M["price"][M["classify_unsure"]], M["price"][M["briefs"]]
    h_cost = h_in / 1e6 * ph[0] + h_out / 1e6 * ph[1]
    o_cost = o_in / 1e6 * po_[0] + o_out / 1e6 * po_[1]
    per_h = h_cost / n
    per_o = o_cost / max(1, opus)
    share = opus / n
    per_ad = per_h + share * per_o
    nb = int((b.cost_usd > 0).sum())
    per_b = b.cost_usd.sum() / max(1, nb)
    tied = int((j.group_id != "").sum())
    cost = pd.DataFrame([
        ["Adverts classified", n, ""],
        ["Haiku: input / output tokens", f"{int(h_in):,} / {int(h_out):,}", f"${h_cost:.4f} (${per_h:.5f} per advert)"],
        ["Sent to Opus (Haiku confidence below high)", f"{opus} of {n} ({share:.0%})", ""],
        ["Opus: input / output tokens", f"{int(o_in):,} / {int(o_out):,}", f"${o_cost:.4f} (${per_o:.5f} per advert sent)"],
        ["Classification cost per advert, all in", "", f"${per_ad:.5f}"],
        ["Briefs written", f"{nb} of {len(b)}", ""],
        ["Fable: input / output tokens", f"{int(b.input_tokens.sum()):,} / {int(b.output_tokens.sum()):,}",
         f"${b.cost_usd.sum():.4f} (${per_b:.4f} per brief)"],
        ["Pilot model spend (this step)", "", f"${h_cost + o_cost + b.cost_usd.sum():.2f}"],
        ["Brand lookup batch (Step 3 rerun)", "", "$0.50"],
        ["", "", ""],
        ["PROJECTED FULL RUN (measured per-item costs)", "", ""],
        [f"Classify adverts tied to a group in this pull ({tied:,})", "", f"${tied * per_ad:.2f}"],
        ["Classify 20,000 adverts (Reference E assumption)", "", f"${20000 * per_ad:.2f}"],
        ["300 briefs (Reference E)", "", f"${300 * per_b:.2f}"],
        ["Full run total (20,000 adverts + 300 briefs)", "", f"${20000 * per_ad + 300 * per_b:.2f}"],
        ["Note", "Opus share is high because 106 of 108 adverts had only a ~500-character snippet; Haiku "
                 "seldom says 'high' on so little text. With full advert text it should fall.", ""],
    ], columns=["Item", "Volume", "Cost"])
    adv = c[["group_name", "employer", "title", "location", "posted", "why", "text_source", "advert_text", "category",
             "haiku_category", "haiku_confidence", "model_category", "model_confidence", "model_reason", "sent_to_opus",
             "link", "cost_usd"]].rename(columns={"category": "keyword_category", "why": "selected_because"})
    briefs = b[["rank", "group_name", "band", "total", "brief_date", "what_changed", "why_it_matters", "opening_line",
                "evidence", "cost_usd"] + (["note"] if "note" in b else [])]
    changes = T[(T.band != T.band_keyword_only) | (T.total != T.total_keyword_only)][
        ["rank", "group_name", "band_keyword_only", "band", "total_keyword_only", "total"]]
    rest = pd.read_csv(OUTPUT / "step1" / "restored_no_number_top50.csv", dtype=str).fillna("")
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str)
    notes = pd.DataFrame([
        ["9", "Lloyds 'new funding (SH01)' dated 2026-09-28", "It is on LLOYDS BANK GENERAL INSURANCE LIMITED (00204373), "
              "company type 'ltd', not a plc. The plc rule is working; this SH01 counts correctly."],
        ["1", "Investor brand exception", "Applied. Jupiter Fund Management plc, Jupiter Fund Management Group Ltd and "
              "Jupiter Asset Management Group Ltd are now one group (UK:06150195, 7 companies)."],
        ["2", "New sponsors", "Applied. A sponsor name now has to START the owner's name: 'Partners Group' was wrongly "
              "matching 'Health Partners Group Limited', 'The & Partners Group' and 'Top Online Partners Group'."],
        ["3", "Investor siblings via a shared holding company", "NOT applied. The ownership records name the investor "
              "directly (e.g. 'KKR & Co. Inc.' for Dale House Solar, Trowbridge Energy, Yews Solar...): the intermediate "
              "holding company is not in the data. A stand-in (same investor + same registered office) is in "
              "'Investor siblings (not applied)'; it would wrongly join Viridor, Punch Taverns and ERM, which share "
              "KKR's London office address."],
        ["4", "Numeric foreign parent names", "Applied (already in place): e.g. '2283485 Alberta Ltd' -> INTACT INSURANCE UK LIMITED."],
        ["5", "Sector label", "Applied."], ["6", "Band-first sorting", "Applied."],
        ["7", "30 merge proposals + Citibank UK + Morgan Stanley", "Applied, all 31 entity moves and the Morgan Stanley group merge."],
        ["8", "Wise, Morgan Stanley, Finsbury", "Applied. SGN re-pointed to UK:12122658: adding Brookfield as an investor "
              "split the old Brookfield group, and SGN's group now stops below Brookfield."],
        ["10", "50 adverts", "The Act now groups alone had 94 adverts behind them (Lloyds, Tesco, JPMorgan... have many), "
               "so all 108 keyword-matched pilot adverts were classified rather than 50."],
        ["15", "No-number pay gap entries restored", f"{int(u.entity_id.str.startswith('GPG-').sum())} restored (public-body "
               "name words: council, NHS (incl. 'N H S'), police, authority, department, government, parliament, fire and "
               "rescue, combined authority). Many of the largest restored are clearly public bodies your words don't catch: "
               "Home Office, Ministry of Defence, HMRC, health boards, constabularies, ambulance trusts, Bank of England, "
               "Transport for London (about 104 by extra words such as ministry, constabulary, health board, ambulance, "
               "hospital, agency, crown, HM). Not removed - your call. The pilot is unaffected."],
        ["16", "All FCA banks, building societies and insurers", "Needs new downloads, so not done. The FCA API cannot list "
               "firms by permission. It would need: the PRA's published lists of banks, building societies and insurers "
               "(3 files), then for each firm (~1,000) an FCA search, firm record and permissions (~3,500 FCA calls, "
               "~45 min) and a Companies House profile and ownership record (~2,000 calls, ~20 min)."],
        ["17", "Advert employers on the FCA Register", "Needs new downloads, so not done. 659 employers (794 adverts) are not "
               "in the universe; each needs an FCA name search (659 calls), then the firm record and permissions for "
               "exact matches (estimate 200-400 calls) and a Companies House profile for the company number (~100). "
               "About 15-20 minutes."],
    ], columns=["point", "item", "answer"])
    sib = pd.read_csv(OUTPUT / "step2" / "investor_sibling_proposals.csv", dtype=str).fillna("")
    summary = pd.DataFrame([
        ["What this is", "Step 5 on the pilot: model-classified adverts, rescored ranking, 10 why-now briefs."],
        ["Bands after model verdicts", ", ".join(f"{k} {v}" for k, v in T.band.value_counts().items())],
        ["Adverts the model called irrelevant", f"{int((c.model_category == 'irrelevant').sum())} of {n}"],
        ["Groups whose band or score changed with the model", len(changes)],
        ["Share of keyword adverts tied to a group (whole UK pull)", f"{(j.group_id != '').mean():.1%}"],
        ["Model spend this step", f"${h_cost + o_cost + b.cost_usd.sum():.2f}"],
        ["Tabs", "Adverts | Briefs | Ranked list | Keyword vs model | Cost report | Answers | Restored top 50 | Investor siblings (not applied)"],
    ], columns=["Item", "Value"])
    with pd.ExcelWriter(OUT) as w:
        for name, df in [("Summary", summary), ("Adverts", adv), ("Briefs", briefs), ("Ranked list", T),
                         ("Keyword vs model", changes), ("Cost report", cost), ("Answers", notes),
                         ("Restored top 50", rest), ("Investor siblings (not applied)", sib)]:
            df.to_excel(w, sheet_name=name, index=False); ws = w.sheets[name]; ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(70, max(9, max(len(str(c_.value or "")) for c_ in col[:150]) + 2))
    print("written", OUT); print(cost.to_string(index=False))


if __name__ == "__main__":
    main()
