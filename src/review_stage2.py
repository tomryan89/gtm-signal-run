"""Stage 2 review pack (Tom, 12 Nov 2026): one workbook after the four slice pilots. Reads saved outputs only.

  python src/review_stage2.py   -> output/stage2/GTM Stage 2 pilot review <date>.xlsx (+ copy in Uploads)"""
import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from common import INTERIM, OUTPUT, ROOT, settings, to_uploads

ST = settings()
OUT = OUTPUT / "stage2"
FILE = OUT / f"GTM Stage 2 pilot review {date.today().isoformat()}.xlsx"
START = "2026-11-11T22:05"            # stage 2 began (run log)


def write(path, sheets):
    with pd.ExcelWriter(path) as w:
        for name, df in sheets:
            df.to_excel(w, sheet_name=name[:31], index=False)
            ws = w.sheets[name[:31]]
            ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(70, max(9, max(len(str(c.value or ""))
                                                                                     for c in col[:200]) + 2))


def runlog():
    rows = [json.loads(l) for l in open(ROOT / "data" / "run_log.jsonl") if l[8:24] >= START[:16] or json.loads(l)["ts"] >= START]
    L = pd.DataFrame(rows)
    L["t"] = pd.to_datetime(L.ts)
    out = []
    for src, g in L.groupby("source"):
        g = g.sort_values("t")
        gaps = g.t.diff().dt.total_seconds().fillna(0)
        out.append(dict(source=src, requests=int(g.event.isin(["request", "download"]).sum()),
                        failures=int(g.event.isin(["error", "server_error", "gave_up"]).sum()),
                        refused_rate_limit=int((g.event == "rate_limit_pause").sum()),
                        http_errors=int((pd.to_numeric(g.get("status"), errors="coerce").fillna(200) >= 400).sum()) if "status" in g else 0,
                        active_minutes=round(gaps[gaps <= 600].sum() / 60, 1),
                        first=g.ts.iloc[0][:16], last=g.ts.iloc[-1][:16]))
    return pd.DataFrame(out), L


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pg = pd.read_csv(OUTPUT / "step3" / "pilot_groups.csv", dtype=str).fillna("")
    gname = dict(zip(pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).group_id,
                     pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).group_name))
    rl, L = runlog()
    ev = L[L.event.isin(["done"]) & L.source.isin(["slice_a", "stage2_model"])]
    spend = pd.to_numeric(ev.get("cost_usd", ev.get("cost")), errors="coerce").fillna(0).sum() + \
        pd.to_numeric(ev.get("cost"), errors="coerce").fillna(0).sum() if len(ev) else 0

    # ---------------- Slice A
    A = pd.read_csv(INTERIM / "slice_a_results.csv", dtype=str).fillna("")
    sec = A[A.status == "section found"].copy()
    sec["section_text"] = [(ROOT / p).read_text()[:30000] if p else "" for p in sec.section_path]
    rest = A[A.status != "section found"].groupby("reason", group_keys=False).apply(lambda g: g.head(5)).head(50 - len(sec))
    a50 = pd.concat([sec, rest])[["group_name", "company", "company_name", "chosen", "made_up_to", "accounts_type", "format",
                                   "status", "reason", "verdict", "risk_title", "quote", "quote_verified", "supply_chain",
                                   "tprm_programme", "reason_model", "source_link", "section_text"]
                                  if "reason_model" in A else
                                  ["group_name", "company", "company_name", "chosen", "made_up_to", "accounts_type", "format",
                                   "status", "reason", "verdict", "risk_title", "quote", "quote_verified", "supply_chain",
                                   "tprm_programme", "source_link", "section_text"]]
    acost = float(pd.to_numeric(L[(L.source == "slice_a") & (L.event == "done")].get("cost"), errors="coerce").fillna(0).sum())
    nsec, nscope = len(sec), len(A)
    full_groups = 10836
    full_sec = round(full_groups * nsec / nscope)
    a_counts = pd.DataFrame([
        ["Pilot groups in scope (no listed-company result)", nscope],
        ["Section found and read by Opus", nsec],
        ["  verdict yes", int((A.verdict == "yes").sum())], ["  verdict passing mention", int((A.verdict == "passing mention").sum())],
        ["  verdict no", int((A.verdict == "no").sum())],
        ["    of which supply chain risk is a principal risk (would count under the Slice A wording)",
         int(((A.verdict == "no") & (A.supply_chain == "True")).sum())],
        ["Couldn't check: scanned PDF with no text (no text recognition)", int(A.reason.str.startswith("scanned").sum())],
        ["Couldn't check: no full (or medium) accounts filed by the top company or the largest member",
         int(A.reason.str.startswith("no full accounts").sum())],
        ["Couldn't check: no UK company (Irish groups, bodies without Companies House accounts)", int(A.reason.str.startswith("no UK company").sum())],
        ["Couldn't check: other", int((A.status == "couldn't check").sum() - A.reason.str.startswith(("scanned", "no full accounts", "no UK company")).sum())],
        ["No section found", int((A.status == "no section found").sum())],
        ["Pilot model cost", f"${acost:.2f} (${acost / max(1, nsec):.4f} per section; instructions cached)"],
        ["", ""],
        ["FULL RUN PROJECTION", ""],
        ["Groups in scope", f"{full_groups:,}"],
        ["Sections expected (pilot rate)", f"about {full_sec:,}"],
        ["Model cost", f"about ${full_sec * acost / max(1, nsec):.0f} (Opus batch)"],
        ["Companies House requests", f"about {full_groups * 4:,} (accounts list, document details, document; ~6-7 hours at the limit)"],
        ["Storage", "about 20 GB of saved documents (pilot: 520 MB for 245 documents)"],
        ["Note", "Most large private companies' accounts are image scans (215 of 245 pilot documents), so most groups "
                 "end 'couldn't check' without text recognition. Every section found came from structured (XHTML) accounts."],
    ], columns=["Item", "Value"])

    # ---------------- Slice B
    n = pd.read_csv(INTERIM / "news_matched.csv", dtype=str).fillna("")
    stories = pd.read_csv(INTERIM / "news_stories.csv", dtype=str).fillna("")
    per = n.groupby("story_id").agg(
        model_returned=("organisation", lambda s: "; ".join(f"{o} -> {t} ({c})" for o, t, c in
                                                          zip(s, n.loc[s.index, "event_type"], n.loc[s.index, "confidence"]) if o)),
        matched_groups=("group_id", lambda s: "; ".join(f"{g} {gname.get(g, '')}" for g in s if g)),
        event_date=("event_date", "first"))
    b100 = stories.merge(per, left_on="story_id", right_index=True, how="left").head(100)[
        ["story_id", "seendate", "title", "domain", "sourcecountry", "topics", "model_returned", "event_date", "matched_groups", "url"]]
    nst = len(stories)
    with_event = n[n.event_type != "none"].story_id.nunique()
    matched = n[n.group_id != ""].story_id.nunique()
    bcost = 0.0747
    b_counts = pd.DataFrame([
        ["Articles saved (GDELT)", int(json.loads(L[(L.source == 'gdelt') & (L.event == 'stories')].iloc[-1].to_json())["articles"])
         if len(L[(L.source == 'gdelt') & (L.event == 'stories')]) else ""],
        ["Stories after removing duplicates", nst],
        ["Stories where the model found a counting event", with_event],
        ["Stories matched to a group in the universe", f"{matched} ({matched / max(1, nst):.0%} of stories; "
                                                        f"{matched / max(1, with_event):.0%} of stories with an event)"],
        ["Pilot groups that received a news signal", int(n[n.group_id.isin(pg.group_id)].group_id.nunique())],
        ["Model cost (116 stories)", f"${bcost:.2f}"],
        ["", ""],
        ["SOURCE PROBLEM", "GDELT's search API refused most requests (429, 'one request every 5 seconds') even 30 s - 7 min "
                           "apart; 5 of 81 searches completed in ~2 hours. It also returned UK/Irish articles only for "
                           "6-9 Nov 2026: the week before was empty. In practice it covers days, not 6 months. Pull stopped."],
        ["FULL RUN PROJECTION (if a 6-month source is found)", "about 26 weeks x 116 stories = ~3,000 stories, about $2 "
                                                               "on Opus; matching and the brand lookup batch under $1."],
        ["Article first paragraphs", "Not fetched: GDELT gives headlines only, and each news site's terms would need "
                                     "checking one by one. Headlines only in this pilot."],
    ], columns=["Item", "Value"])

    # ---------------- Slice C
    c = pd.DataFrame([
        ["Status", "Stopped before any pull, as instructed: commercial use is not clearly allowed."],
        ["Terms (T&C, updated 19 Aug 2026), section 5.2", "Commercial use of the Data is strictly prohibited without prior "
                                                          "written approval from the owner of Ransomware.live."],
        ["Section 5.1", "Free non-commercial use only (personal research, academic, awareness, open source, government)."],
        ["API page", "The free API 'is not intended for corporate or business use'; corporate users must read the T&C. "
                     "A free Pro API key exists (500,000 calls a month) but the T&C still apply."],
        ["Plain reading", "A sales team's prospecting pull is commercial use. It needs written approval from the owner "
                          "(support form at ransomware.live/support, or api@ransomware.live). Not legal advice."],
        ["Matched victims", "None (not pulled)."],
        ["Peer signal lists for 5 victims", "None (not pulled). The peer rule is built into scoring and does not count "
                                            "towards the Act now 'trigger worth 3+' test."],
    ], columns=["Item", "Reading"])

    # ---------------- Slice D
    r = pd.read_csv(INTERIM / "reg_matched.csv", dtype=str).fillna("")
    d_all = r[["source", "title", "date", "verdict", "organisation", "action_date", "confidence", "reason", "group_id",
               "match", "review", "link"]].copy()
    d_all["group_name"] = d_all.group_id.map(gname).fillna("")
    d_read = pd.DataFrame([
        ["Regulator of Social Housing (GOV.UK)", "read", "250 decisions; judgement text read from each GOV.UK page"],
        ["CMA (GOV.UK)", "read", "96 non-merger cases and items"],
        ["FCA final notices", "read", "107 notices via the FCA sitemap (robots.txt allows it; search pages are disallowed)"],
        ["ICO enforcement", "read", "41 pages via the ICO sitemap, 6 s apart (its crawl delay)"],
        ["Bank of England / PRA", "partly read", "RSS feeds only hold their 50 newest items (news back to Jul 2026, PRA "
                                                 "publications back to Mar 2026), not 12 months. Python's default client "
                                                 "is refused (403); the copies saved by the source test were used."],
        ["Ofgem", "not read", "Publishes enforcement on ofgem.gov.uk, not GOV.UK (16 GOV.UK items, none enforcement)"],
        ["Ofwat", "not read", "Not on GOV.UK search (0 items)"],
        ["The Pensions Regulator", "not read", "Publishes on its own site (7 GOV.UK items, none enforcement)"],
        ["Office for Students", "not read", "Publishes on its own site (2 GOV.UK items)"],
    ], columns=["Regulator", "Status", "Detail"])
    dcost = 1.1628 + 0.7627

    # ---------------- pilot before / after
    bef = pd.read_csv(OUT / "pilot_ranked_before.csv", dtype=str).fillna("")
    aft = pd.read_csv(OUT / "pilot_ranked_after.csv", dtype=str).fillna("")
    x = bef[["group_id", "group_name", "band", "total"]].merge(aft[["group_id", "rank", "band", "total"]], on="group_id",
                                                               suffixes=(" before", " after"))
    x["changed"] = (x["band before"] != x["band after"]).map({True: "band changed", False: ""})
    x.loc[(x.changed == "") & (x["total before"] != x["total after"]), "changed"] = "score changed"
    s2 = pd.read_csv(INTERIM / "stage2_signals.csv", dtype=str).fillna("")
    s2p = s2[s2.group_id.isin(pg.group_id)]
    x["stage 2 signals"] = x.group_id.map(s2p.groupby("group_id").apply(
        lambda g: "; ".join(f"{a} ({b})" for a, b in zip(g.signal_type, g.date))))
    x = x.sort_values("rank", key=lambda s: pd.to_numeric(s))
    bands = pd.DataFrame({"before": bef.band.value_counts(), "after": aft.band.value_counts()}).fillna(0).astype(int)

    # ---------------- cost
    cost = pd.DataFrame([
        ["Slice A: principal risks (Opus batch, 28 sections)", f"${acost:.2f}"],
        ["Slice B: news (Opus batch, 116 stories)", f"${bcost:.2f}"],
        ["Slice D: regulator items (Opus batch, 619 items + 250 housing judgements re-read with full text)", f"${dcost:.2f}"],
        ["Slice C", "$0 (not pulled)"],
        ["Briefs", "$0 (no pilot group changed band)"],
        ["Stage 2 spend so far", f"${acost + bcost + dcost:.2f} of $40 approved"],
        ["", ""],
        ["FULL RUN PROJECTION (count-based)", ""],
        ["Slice A", f"about ${full_sec * acost / max(1, nsec):.0f}"],
        ["Slice B", "about $2 (only if a 6-month news source is found)"],
        ["Slice D", "$0 more: every item is already classified; the full run only matches them to all groups"],
        ["Briefs for groups whose band changes", "under $2"],
        ["Total", f"about ${full_sec * acost / max(1, nsec) + 4:.0f}, under the $40 ceiling"],
    ], columns=["Item", "Cost"])

    careers = pd.DataFrame([
        ["Scope", "Irish groups (554) and the top 300: about 850 groups."],
        ["Step 1: find the careers site", "We hold no company websites. Each group needs its website and careers page "
                                          "found (a model with web search, or a search API), then checked by hand for a "
                                          "sample. About 2-3 hours of run time; model cost about $3-5."],
        ["Step 2: detect the job board", "Probe the public job board APIs: Greenhouse (boards-api), Lever (postings "
                                         "API), Ashby (posting API), SmartRecruiters and Workable public endpoints, each "
                                         "with documented public access. Workday has no public API: its careers pages "
                                         "would need scraping and its terms checking first. About 1 hour."],
        ["Step 3: pull and classify", "Pull open roles, run the existing title keywords and the Opus advert check "
                                      "(about $0.005 per advert). Expect a few thousand adverts: about $10-15."],
        ["Coverage", "Likely 30-50% of these groups use a board with a public API; the rest (Workday, Taleo, own sites) "
                     "stay uncovered unless scraping is approved."],
        ["Build time", "About a day of building and testing, then about 2 hours per refresh."],
        ["Status", "Not built. Waiting for Tom."],
    ], columns=["Item", "Detail"])

    summary = pd.DataFrame([
        ["What this is", "Stage 2 pilots on the 334 pilot groups. Nothing has run on the full universe."],
        ["Slice A", f"{nscope} groups; {nsec} sections read; all 'no' under the listed-company app's rules; "
                    f"{int(((A.verdict == 'no') & (A.supply_chain == 'True')).sum())} name supply chain risk (a yes under the "
                    f"Slice A wording); 215 scans and 48 without full accounts are 'couldn't check'."],
        ["Slice B", f"GDELT throttled and held only ~4 days of UK/Irish news; pilot on {nst} stories, {matched} matched a group."],
        ["Slice C", "Stopped: ransomware.live's terms prohibit commercial use without written approval."],
        ["Slice D", f"{len(r.drop_duplicates('item_id'))} items; "
                    f"{int((r.drop_duplicates('item_id').verdict != 'not relevant').sum())} enforcement or downgrade; "
                    f"{int((r.group_id != '').sum())} matched a group; 4 regulators not on GOV.UK."],
        ["Pilot bands", ", ".join(f"{b}: {bands.loc[b, 'before']} -> {bands.loc[b, 'after']}" for b in bands.index)],
        ["Groups that changed band", f"{int((x.changed == 'band changed').sum())} (Tesco's score rose 8.25 -> 11.25; already Act now)"],
        ["Spend", f"${acost + bcost + dcost:.2f} of $40"],
        ["Decisions for Tom", "1) Slice A: count supply chain risk (your wording) or keep the app's rules? Allow text "
                              "recognition or Opus reading the scans (~$0.50 each)? 2) Slice B: another news source "
                              "(GDELT raw files, a paid news API) or drop it? 3) Slice C: ask ransomware.live for written "
                              "approval? 4) Slice D: add Ofgem, Ofwat, TPR and OfS from their own websites? "
                              "5) Careers sites (tab 'Careers sites')."],
    ], columns=["Item", "Value"])

    write(FILE, [("Summary", summary), ("A - 50 companies", a50), ("A - counts and projection", a_counts),
                 ("B - 100 stories", b100), ("B - counts and projection", b_counts), ("C - ransomware.live", c),
                 ("D - every item", d_all), ("D - regulators", d_read), ("Pilot before and after", x),
                 ("Pilot bands", bands.reset_index().rename(columns={"index": "band"})),
                 ("Briefs (band changes)", pd.DataFrame([["None: no pilot group changed band, so no briefs were written."]],
                                                        columns=["Note"])),
                 ("Run log", rl), ("Cost report", cost), ("Careers sites", careers),
                 ("Review (unmatched)", pd.read_csv(INTERIM / "stage2_review.csv", dtype=str).fillna(""))])
    to_uploads(FILE)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
