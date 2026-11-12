"""Stage 2 run report (Tom, 12 Nov 2026 decisions): one spreadsheet, then stop.

  python src/review_stage2_run.py   -> output/stage2/GTM Stage 2 run report <date>.xlsx (+ copy in Uploads)"""
import json
import shutil
from datetime import date

import pandas as pd
from openpyxl.styles import Alignment, Font

from common import INTERIM, OUTPUT, ROOT, RUN_LOG, paths, settings, to_uploads

ST = settings()
P = paths()
BASE = OUTPUT / "before_changes" / "stage2_full_base"
FILE = OUTPUT / "stage2" / f"GTM Stage 2 run report {date.today().isoformat()}.xlsx"

ORDER = ST["sector_label"]["band_order"]
START = "2026-11-12T05:00"          # this run's first log line (relevance re-read estimate)


def rd(p):
    return pd.read_csv(p, dtype=str).fillna("") if p.exists() else pd.DataFrame()


def kv(rows):
    return pd.DataFrame(rows, columns=["Item", "Value"])


def write(path, sheets):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path) as w:
        for name, df in sheets:
            df.to_excel(w, sheet_name=name[:31], index=False)
            ws = w.sheets[name[:31]]
            for c in ws[1]:
                c.font = Font(bold=True)
            for col in ws.columns:
                width = min(80, max(10, max(len(str(c.value or "")) for c in col[:200]) + 2))
                ws.column_dimensions[col[0].column_letter].width = width
                if width >= 60:
                    for c in col[1:]:
                        c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.freeze_panes = "A2"


def main():
    L = pd.DataFrame([json.loads(x) for x in RUN_LOG.read_text().splitlines() if x.strip()])
    L = L[L.ts >= START]
    T0, T1 = rd(BASE / "ranked.csv"), rd(P["ranked"])
    S1 = rd(P["scored"])
    s2 = rd(INTERIM / "stage2_signals.csv")

    # ------------------------------------------------ bands before and after
    b0, b1 = T0.band.value_counts(), T1.band.value_counts()
    bands = pd.DataFrame([[b, int(b0.get(b, 0)), int(b1.get(b, 0)), int(b1.get(b, 0)) - int(b0.get(b, 0))] for b in ORDER],
                         columns=["Band", "Before (v2)", "After (stage 2)", "Change"])
    old = dict(zip(T0.group_id, T0.band))
    oldt = dict(zip(T0.group_id, T0.total))
    T1["band_before"] = T1.group_id.map(old).fillna("")
    T1["total_before"] = T1.group_id.map(oldt).fillna("")
    mv = pd.crosstab(T1.band_before, T1.band).reindex(index=ORDER, columns=ORDER, fill_value=0)
    mv.insert(0, "Before \\ After", mv.index)
    ch = T1[T1.band != T1.band_before].copy()
    ch["_b"] = ch.band.map({b: i for i, b in enumerate(ORDER)})
    ch["total_n"] = pd.to_numeric(ch.total)
    ch = ch.sort_values(["_b", "total_n"], ascending=[True, False]).head(30)
    cnt = S1[(S1.counted == "True") & (pd.to_numeric(S1.value) > 0)]
    new_types = set(s2.signal_type)
    ch["new signals"] = [" | ".join(f"{x.signal_type} ({x.date}; {x.source}): {x.detail[:160]}"
                                    for x in cnt[(cnt.group_id == g) & cnt.signal_type.isin(new_types)].itertuples())
                         for g in ch.group_id]
    top30 = ch[["group_name", "band_before", "band", "total_before", "total", "need", "trigger_after_decay", "sector",
                "country", "size_band", "new signals", "group_id"]].rename(columns={"band": "band_after", "total": "total_after"})

    # ------------------------------------------------ item 1: regulators
    R = rd(INTERIM / "reg_matched.csv")
    items = R.drop_duplicates("item_id")
    enf = items[items.verdict == "enforcement"]
    zero = enf[enf.points.astype(str) == "0"][["source", "title", "published", "date", "area", "relevance_reason", "organisation", "link"]]
    zero = zero.sort_values(["area", "source", "date"])
    relevant = enf[enf.points.astype(str) == "4"]
    mrel = R[(R.points.astype(str) != "0") & (R.group_id != "")]
    one = kv([
        ["Items read (12 months)", len(items)],
        ["  of which Ofgem (new, own website)", int((items.source == "Ofgem").sum())],
        ["Marked enforcement (first read)", len(enf)],
        ["  relevant (4 points)", len(relevant)], ["  scored 0", len(zero)],
        *[[f"    scored 0: {k}", int(v)] for k, v in zero.area.value_counts().items()],
        *[[f"    relevant: {k}", int(v)] for k, v in relevant.area.value_counts().items()],
        ["Governance downgrades (3 points)", int((items.verdict == "governance downgrade").sum())],
        ["Signals given to groups (relevant enforcement or downgrade matched to a group)", int(mrel.group_id.nunique())],
        ["Dates", "Every action date parsed to a real date: " + "; ".join(f"{k}: {v}" for k, v in
                                                                        R[R.verdict != "not relevant"].drop_duplicates("item_id").date_precision.value_counts().items())],
        ["Re-read cost", f"${pd.to_numeric(L[(L.source == 'stage2_model') & (L.event == 'done') & L.job.isin(['reg_rel', 'ofgem', 'ofgem_rel'])].cost_usd).sum():.2f}"],
    ])
    matched_reg = R[(R.group_id != "") & (R.verdict != "not relevant")][["source", "title", "date", "verdict", "area", "points",
                                                                          "organisation", "group_id", "match", "relevance_reason", "link"]]
    notread = pd.DataFrame([
        ["Ofwat", "Not read", "Its website refuses our script (HTTP 403 for every page, robots.txt included); not worked around. "
                              "GOV.UK has no Ofwat enforcement items."],
        ["The Pensions Regulator", "Not added (your decision)", "Its 7 GOV.UK items were read; its own website was not."],
        ["Office for Students", "Not added (your decision)", "Its 2 GOV.UK items were read; its own website was not."],
        ["Ofgem", "Read (partly)", "Own website via its sitemap (robots.txt allows it): 251 enforcement pages changed in 12 months, "
                                   "6 first published in 12 months were kept (older pages updated since are not re-dated). "
                                   "Plus 16 GOV.UK items."],
        ["Bank of England / PRA", "Read (partly)", "RSS feeds hold only their newest 50 items (news back to Jul 2026, PRA "
                                                   "publications back to Mar 2026); not 12 months."],
        ["FCA, ICO", "Read", "Via their sitemaps (allowed by robots.txt)."],
        ["CMA, Regulator of Social Housing", "Read", "GOV.UK search and content API."],
    ], columns=["Regulator", "Status", "Detail"])

    # ------------------------------------------------ item 2: Companies House acquisitions
    A = rd(INTERIM / "ch_acquisitions.csv")
    acq = rd(INTERIM / "stage2_acq_model_raw.csv")
    Ac = A[A.counts == "True"].copy()
    Ac["cid"] = [f"a{i:04d}" for i in Ac.index]
    ans = {x.id: json.loads(x.answer) for x in acq.itertuples() if x.answer}
    Ac["model_verdict"] = Ac.cid.map(lambda c: ans.get(c, {}).get("verdict", ""))
    Ac["model_reason"] = Ac.cid.map(lambda c: ans.get(c, {}).get("reason", ""))
    ext = Ac[Ac.model_verdict == "external change of control"]
    two = kv([
        ["Groups with a top UK company (ownership records saved in Step 2; no new requests)", 10003],
        ["Corporate owner with control notified in the last 12 months", len(A)],
        ["  not a replacement (no other owner ceased within 90 days)", int(A.reason.str.startswith("no different").sum())],
        ["  internal reorganisation by rule (same group, same name, same first word)", int(A.reason.str.startswith("internal").sum())],
        ["  read by Opus", len(Ac)],
        ["    external change of control (signal, 3 points)", len(ext)],
        ["    internal reorganisation", int((Ac.model_verdict == "internal reorganisation").sum())],
        ["    unclear (no signal)", int((Ac.model_verdict == "unclear").sum())],
        ["Groups with the signal", int(ext.group_id.nunique())],
    ])
    ex20 = ext.sort_values("notified_on", ascending=False).head(20)[[
        "group_name", "company_name", "company_number", "new_owner", "new_owner_country", "notified_on", "control",
        "previous_owner", "previous_ceased_on", "model_reason", "source_link"]]
    other = Ac[Ac.model_verdict != "external change of control"].head(10)[[
        "group_name", "company_name", "new_owner", "notified_on", "previous_owner", "model_verdict", "model_reason"]]

    # ------------------------------------------------ item 3: ransomware.live
    V = rd(INTERIM / "ransomware_matched.csv")
    PI = rd(INTERIM / "peer_incidents.csv")
    u = rd(OUTPUT / "step1" / "universe.csv")
    from slice_a import band_rank
    gsize = {}
    E = rd(P["entities"])
    sb = dict(zip(u.entity_id, u.size_band))
    for gid, m in E.groupby("group_id"):
        gsize[gid] = max((band_rank(sb.get(e, "")) for e in m.entity_id), default=0)
    vm = V[V.group_id != ""].copy()
    vm["size_rank"] = vm.group_id.map(gsize)
    vm["group_name"] = vm.group_id.map(dict(zip(T1.group_id, T1.group_name)))
    vm["size_band"] = vm.group_id.map(dict(zip(T1.group_id, T1.size_band)))
    PIr = PI[PI.how.str.contains("ransomware")]
    peers = dict(zip(PIr.victim_group, zip(PIr.peers, PIr.applied, PIr.reason, PIr.division, PIr.country, PIr.confirmed_by_news)))
    top10 = vm.sort_values(["size_rank"], ascending=False).drop_duplicates("group_id").head(10)
    top10 = top10.assign(**{
        "industry division": [peers.get(g, ("",) * 6)[3] for g in top10.group_id],
        "country": [peers.get(g, ("",) * 6)[4] for g in top10.group_id],
        "groups in the same division and country": [peers.get(g, ("",) * 6)[0] for g in top10.group_id],
        "peer signal applied": [peers.get(g, ("",) * 6)[1] for g in top10.group_id],
        "why not": [peers.get(g, ("",) * 6)[2] for g in top10.group_id],
        "confirmed by news": [peers.get(g, ("",) * 6)[5] for g in top10.group_id]})[[
        "victim", "group_name", "size_band", "date", "ransomware_group", "industry division", "country",
        "groups in the same division and country", "peer signal applied", "why not", "confirmed by news", "permalink"]]
    calls = L[(L.source == "ransomware_live") & (L.event == "request")]
    three = kv([
        ["Calls made", f"{len(calls)} victim searches (UK and Ireland x 13 months) + 1 key check + 1 test (2 x 13 = 26 planned)"],
        ["Claimed victims found (last 12 months)", f"{len(V)} (UK {int((V.country == 'UK').sum())}, Ireland {int((V.country == 'IE').sum())})"],
        ["Matched to a group", f"{(V.group_id != '').sum()} ({(V.group_id != '').mean():.1%})"],
        ["Not matched: named only by a web address", int((V.review == "victim named only by a web address").sum())],
        ["Not matched: not in the universe", int((V.review == "not in the universe").sum())],
        ["Not matched: name matches several groups", int(V.review.str.startswith("name matches").sum())],
        ["Peer incidents from ransomware claims", f"{len(PIr)} victims; applied for {int((PIr.applied == 'True').sum())}; "
                                                 f"over the 300-group limit {int(PIr.reason.str.startswith('over').sum())}; "
                                                 f"no industry division {int((PIr.reason == 'no industry division').sum())}"],
        ["Peer incidents from news (high-confidence incident at a universe group)",
         f"{int(PI.how.str.contains('news').sum())} victims (some also have a ransomware claim)"],
        ["Groups given a peer signal (all incidents)", int(s2[s2.signal_type == "peer incident"].group_id.nunique())],
    ])
    over = PI[PI.reason.str.startswith("over")][["victim_group_name", "victim", "date", "how", "division", "country", "peers",
                                                  "confirmed_by_news", "link"]]
    peer_all = PI[["victim_group_name", "victim", "date", "how", "division", "country", "peers", "applied", "reason",
                   "confirmed_by_news", "link"]]

    # ------------------------------------------------ item 4: news
    NS = rd(INTERIM / "news_stories.csv")
    NM = rd(INTERIM / "news_matched.csv")
    srch = L[(L.source == "newsapi") & (L.event == "search")]
    use = json.loads((ROOT / "data" / "raw" / "stage2_tests" / "newsapi" / "usage_final.json").read_text()) \
        if (ROOT / "data" / "raw" / "stage2_tests" / "newsapi" / "usage_final.json").exists() else {}
    st_m = NM[NM.group_id != ""].story_id.nunique()
    four = kv([
        ["Service", "NewsAPI.ai (Event Registry): https://newsapi.ai - API at https://eventregistry.org/api/v1/article/getArticles"],
        ["How far back", "Free tier: recent articles only. Documented as the last 30 days; on 12 Nov 2026 the earliest article "
                         "it returned was 20 Sep 2026 (searches for 1-19 Sep and earlier returned nothing). Archive back to "
                         "2014 needs a paid plan (5 tokens per searched year). So the pull covers ~7.5 weeks, not 6 months."],
        ["Article text or headlines", "Full article text (body) plus headline, source, date and URL. Opus read the headline "
                                      "and the first 500 characters."],
        ["What counts as one search", "One API call returning one page of up to 100 articles = 1 token (recent data). "
                                      "200,000 articles = 2,000 searches x 100."],
        ["Searches used", f"{use.get('usedTokens', 0)} of 2,000 (the service's own counter): {len(srch)} for the pull "
                          f"(including 3 re-runs of empty queries from 15 Sep) and {use.get('usedTokens', 0) - len(srch)} "
                          f"for the source test and topic counts. Limit set in the code: 1,000."],
        ["Articles pulled", int(L[(L.source == "newsapi") & (L.event == "stories")].articles.dropna().iloc[-1])],
        ["Stories after removing duplicates", len(NS)],
        ["Stories naming at least one organisation with a counted event", int(NM[NM.event_type.isin([
            "incident at this organisation", "failure or breach at one of its suppliers", "merger, acquisition or separation",
            "regulatory enforcement"])].story_id.nunique())],
        ["Stories matched to a group", f"{st_m} ({st_m / max(1, len(NS)):.1%} of stories)"],
        ["Organisation mentions matched / sent to review", f"{(NM.group_id != '').sum()} / {(NM.review != '').sum()}"],
        ["Brand lookup extended", "Unmatched names in 2+ stories -> one Opus batch; high-confidence answers applied"],
        ["News enforcement relevance (item 1 rule)", f"{int((NM.event_type == 'regulatory enforcement') & (NM.group_id != '')).__int__() if False else int(((NM.event_type == 'regulatory enforcement') & (NM.group_id != '')).sum())} matched; "
                                                     f"relevant {int(((NM.event_type == 'regulatory enforcement') & (NM.relevant == 'True')).sum())}"],
        ["Signals by type", "; ".join(f"{k}: {v}" for k, v in s2[s2.slice == "B"].signal_type.value_counts().items())],
        ["Topics", "; ".join(f"{k}: {v}" for k, v in NS.topic.value_counts().items())],
    ])
    m30 = NM[NM.group_id != ""].copy()
    m30["group_name"] = m30.group_id.map(dict(zip(T1.group_id, T1.group_name)))
    m30 = pd.concat([m30[m30.event_type == t].head(n) for t, n in [("incident at this organisation", 9),
                     ("failure or breach at one of its suppliers", 5), ("merger, acquisition or separation", 9),
                     ("regulatory enforcement", 7)]])[[
        "title", "domain", "seendate", "organisation", "event_type", "confidence", "event_date", "relevant", "area",
        "relevance_reason", "points", "group_name", "match", "url"]]

    # ------------------------------------------------ item 5: scans
    SC = rd(INTERIM / "slice_a_scans.csv")
    ok = SC[SC.status == "section transcribed"]
    cost_doc = pd.to_numeric(SC.cost_usd).mean()
    full_scans = round(10836 * 215 / 317)
    five = kv([
        ["Scanned accounts tested (largest pilot groups by staff band)", len(SC)],
        ["Usable section (transcribed)", f"{len(ok)} of {len(SC)}"],
        *[[f"  {k}", int(v)] for k, v in SC.status.value_counts().items()],
        *[[f"Verdict: {k}", int(v)] for k, v in SC.verdict.value_counts().items()],
        ["Cost", f"${pd.to_numeric(SC.cost_usd).sum():.2f} in total; ${cost_doc:.3f} per document "
                 f"(Haiku find + transcribe, Opus verdict; live calls at standard prices)"],
        ["Projection: every scanned document in the universe",
         f"about {full_scans:,} scans (10,836 groups in scope x 215 scans per 317 pilot groups): about ${full_scans * cost_doc:,.0f} "
         f"at live prices, about ${full_scans * cost_doc / 2:,.0f} through the Batch API (half price). Plus the downloads: about "
         f"{full_scans:,} documents (~2 GB at a time if each is deleted after extraction), ~6-7 hours of Companies House requests."],
        ["Quotes", "Marked 'from scan, not word-checked'."],
        ["Documents", "All downloaded accounts documents deleted after extraction (sections kept)."],
        ["Slice A supply chain rule, the 28 text sections re-read", "; ".join(
            f"{k}: {v}" for k, v in rd(INTERIM / "slice_a_results.csv").query("status == 'section found'").verdict.value_counts().items())],
    ])
    side = ok.head(5)[["company_name", "size_band", "pdf_pages", "pages_found", "heading", "pages_sent", "transcript",
                       "verdict", "risk_title", "quote", "quote_check", "source_link"]].rename(
        columns={"pages_found": "page reference (PDF page numbers of the section)"})
    scans = SC[[c for c in ["company_name", "size_band", "pdf_pages", "status", "pages_found", "heading", "transcript_chars",
                            "verdict", "risk_title", "quote", "quote_check", "supply_chain", "reason", "find_tokens",
                            "transcribe_tokens", "cost_usd", "source_link"] if c in SC]]

    # ------------------------------------------------ item 6: careers
    F = rd(INTERIM / "careers_find.csv")
    B = rd(INTERIM / "careers_boards.csv")
    J = rd(INTERIM / "careers_roles.csv")
    C = rd(INTERIM / "careers_classified.csv")
    sigc = s2[s2.slice == "careers"]
    six = kv([
        ["Irish groups", len(F)],
        ["Website found by the web search", int((F.website != "").sum()) if len(F) else 0],
        ["Careers page found", int((F.careers_url != "").sum()) if len(F) else 0],
        ["Any job board detected", int((B.boards != "").sum()) if len(B) else 0],
        *([[f"  {k}", int(v)] for k, v in B[B.boards != ""].boards.str.split(":").str[0].value_counts().items()] if len(B) else []),
        ["Readable board (Greenhouse, Lever, Ashby, SmartRecruiters, Workable public feed)", int((B.readable_board != "").sum()) if len(B) else 0],
        ["Open roles read", len(J)],
        ["Roles matching the keywords (UK/Ireland or no location)", len(C)],
        *([[f"  Opus: {k}", int(v)] for k, v in C.model_category.value_counts().items()] if len(C) else []),
        ["Groups that gained a hiring signal", int(sigc.group_id.nunique())],
        ["Cost", f"web search ${pd.to_numeric(F.cost_usd).sum():.2f}" if len(F) else ""],
    ])
    boards = B.merge(F[["group_id", "confidence", "note"]], on="group_id", how="left") if len(B) else B

    # ------------------------------------------------ briefs
    BR = rd(INTERIM / "briefs_stage2.csv")
    if len(BR):
        BR["uses ransomware or peer evidence"] = BR.evidence.str.contains("claimed ransomware victim|peer incident")
        pick = pd.concat([BR[BR["uses ransomware or peer evidence"]].head(7), BR[~BR["uses ransomware or peer evidence"]]]).head(15)
        briefs = pick[["group_name", "rank", "total", "stage2", "model", "uses ransomware or peer evidence", "what_changed",
                       "why_it_matters", "angle", "who_to_contact", "evidence"]].rename(columns={"stage2": "new or rewrite"})
    else:
        briefs = pd.DataFrame()

    # ------------------------------------------------ run log and cost
    log = L[["ts", "source", "event"] + [c for c in L.columns if c not in ("ts", "source", "event")]]
    log = log.dropna(axis=1, how="all")
    costs = []
    for (src, job), g in L[pd.to_numeric(L.get("cost_usd"), errors="coerce").notna()].groupby(
            [L.source, L.get("job", pd.Series("", index=L.index)).fillna("")]):
        if src in ("slice_a_scans",) and g.event.iloc[0] == "document":
            costs.append([f"{src}", "30 scan documents", pd.to_numeric(g.cost_usd).sum()])
        elif g.event.isin(["done", "find_done", "classify_done", "batch_collected"]).any():
            costs.append([src, job, pd.to_numeric(g[g.event.isin(["done", "find_done", "classify_done", "batch_collected"])].cost_usd).sum()])
    c = pd.DataFrame(costs, columns=["Step", "Job", "Cost (USD)"])
    for x in L[(L.source == "slice_a") & (L.event == "done")].itertuples():
        c.loc[len(c)] = ["slice_a", "28 sections re-read (supply chain rule)", float(x.cost)]
    earlier = 2.30
    c.loc[len(c)] = ["Stage 2 pilots (earlier today)", "", earlier]
    total = c["Cost (USD)"].sum()
    c.loc[len(c)] = ["TOTAL stage 2", "pre-approved up to $60", total]
    c["Cost (USD)"] = c["Cost (USD)"].astype(float).round(4)

    summary = kv([
        ["What this is", "Stage 2 decisions run on the full list (items 1-4 and 6 switched on), rescored and re-exported. "
                         "Slice A (annual reports) is not switched on: scan test only."],
        ["Spreadsheet for reps", f"GTM full run ranked v3 {date.today().isoformat()}.xlsx (same tabs as stage 1), in Uploads"],
        ["Bands before -> after", "; ".join(f"{r.Band} {r._2} -> {r._3}" for r in bands.itertuples())],
        ["Groups whose band changed", int((T1.band != T1.band_before).sum())],
        ["New or rewritten briefs", len(BR)],
        ["Model spend, all of stage 2", f"${total:.2f} of $60"],
        ["Approval files", "ransomware_live_approval / newsapi_approval: " + ("found in the project folder" if
                           list(ROOT.glob("ransomware_live_approval*")) and list(ROOT.glob("newsapi_approval*")) else
                           "not yet in the project folder when this report was built")],
    ])
    write(FILE, [("Summary", summary), ("Bands before and after", bands), ("Band moves", mv),
                 ("Top 30 band changes", top30),
                 ("1 - counts", one), ("1 - scored 0", zero), ("1 - matched items", matched_reg), ("1 - regulators not read", notread),
                 ("2 - counts", two), ("2 - 20 ownership changes", ex20), ("2 - not counted (examples)", other),
                 ("3 - ransomware.live", three), ("3 - 10 largest victims", top10), ("3 - over 300 limit", over),
                 ("3 - all incidents", peer_all),
                 ("4 - NewsAPI", four), ("4 - 30 matched stories", m30),
                 ("5 - scan test", five), ("5 - side by side", side), ("5 - all 30 scans", scans),
                 ("6 - careers sites", six), ("6 - boards by group", boards),
                 ("Briefs (15)", briefs), ("Run log", log), ("Cost report", c)])
    to_uploads(FILE)
    print(FILE)
    print(summary.to_string())


if __name__ == "__main__":
    main()
