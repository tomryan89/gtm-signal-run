"""v4 report (Tom, 13 Nov 2026): one spreadsheet, then stop.

  python src/review_v4.py   -> output/stage2/GTM v4 report <date>.xlsx (+ copy in Uploads)"""
import json
import shutil
from datetime import date

import pandas as pd

from common import INTERIM, OUTPUT, RUN_LOG, paths, settings, to_uploads
from review_stage2_run import kv, rd, write

ST = settings()
P = paths()
V2 = OUTPUT / "before_changes" / "stage2_full_base"
V3 = OUTPUT / "before_changes" / "v3_full"
FILE = OUTPUT / "stage2" / f"GTM v4 report {date.today().isoformat()}.xlsx"
ORDER = ST["sector_label"]["band_order"]
START = "2026-11-12T06:50"          # this round starts after the v3 briefs (06:48)


def main():
    L = pd.DataFrame([json.loads(x) for x in RUN_LOG.read_text().splitlines() if x.strip()])
    L = L[L.ts >= START]
    T2, T3, T4 = rd(V2 / "ranked.csv"), rd(V3 / "ranked.csv"), rd(P["ranked"])
    S4 = rd(P["scored"])
    bands = pd.DataFrame([[b, int((T2.band == b).sum()), int((T3.band == b).sum()), int((T4.band == b).sum())] for b in ORDER],
                         columns=["Band", "v2 (release)", "v3 (not approved)", "v4"])
    bands.loc[len(bands)] = ["Groups", len(T2), len(T3), len(T4)]
    sec = pd.DataFrame([[s, int((T2.sector == s).sum()), int((T3.sector == s).sum()), int((T4.sector == s).sum())]
                        for s in ["Financial services"]], columns=["Sector label", "v2", "v3", "v4"])

    # ---------------- news signals before and after
    s3, s4 = rd(V3 / "stage2_signals.csv"), rd(INTERIM / "stage2_signals.csv")
    nb = s3[s3.slice == "B"].signal_type.value_counts()
    na = s4[s4.slice == "B"].signal_type.value_counts()
    types = sorted(set(nb.index) | set(na.index))
    ntypes = pd.DataFrame([[t, int(nb.get(t, 0)), int(na.get(t, 0))] for t in types], columns=["News signal type", "v3", "v4"])
    ntypes.loc[len(ntypes)] = ["TOTAL", int(nb.sum()), int(na.sum())]
    NM3, NM4 = rd(V3 / "news_matched.csv"), rd(INTERIM / "news_matched.csv")
    cols = ["title", "domain", "seendate", "organisation", "event_type", "credited_correctly", "uk_or_ireland", "deal_role",
            "deal_value_gbp_m", "regulator", "area", "event_date", "confidence", "model_reason", "points", "signal_type",
            "scores_0_because", "group_id", "url"]
    gname = dict(zip(T4.group_id, T4.group_name))
    still = NM4[(NM4.group_id != "") & (NM4.points != "0")].copy()
    still = pd.concat([still[still.event_type == t].head(n) for t, n in [
        ("cyber attack, data breach or ransomware", 4), ("technology or systems outage", 3),
        ("supplier or service provider failure", 3), ("merger, acquisition or separation", 7), ("regulatory enforcement", 3)]])
    was = NM3[(NM3.group_id != "") & (NM3.points != "0")][["story_id", "organisation", "event_type", "points"]].rename(
        columns={"event_type": "v3 event type", "points": "v3 points"})
    gone = NM4[NM4.points == "0"].merge(was, on=["story_id", "organisation"])
    gone = gone.groupby("scores_0_because", group_keys=False).apply(lambda g: g.head(4)).head(20)
    for d in (still, gone):
        d["group"] = d.group_id.map(gname).fillna("")
    s40 = pd.concat([still.assign(**{"still scores": "yes", "v3 event type": "", "v3 points": ""}),
                     gone.assign(**{"still scores": "no"})])[["still scores", "v3 event type", "v3 points", "group"] + cols]
    lost = NM4.merge(was, on=["story_id", "organisation"])
    lost = lost[lost.points == "0"].scores_0_because.value_counts().reset_index()
    lost.columns = ["Why a v3 news signal now scores 0", "Organisation mentions"]

    # ---------------- newly Act now (v4, not v2)
    a2 = set(T2[T2.band == "Act now"].group_id)
    new = T4[(T4.band == "Act now") & ~T4.group_id.isin(a2)].copy()
    new["n"] = pd.to_numeric(new.total)
    new = new.sort_values("n", ascending=False)
    cnt = S4[(S4.counted == "True") & (pd.to_numeric(S4.value) > 0)]
    new["signals"] = [" | ".join(f"{x.signal_type} ({x.date or 'standing'}; {x.source}; {x.value} pts): {x.detail[:140]}"
                                 for x in cnt[cnt.group_id == g].sort_values("value", ascending=False).itertuples())
                      for g in new.group_id]
    new["band v2"] = new.group_id.map(dict(zip(T2.group_id, T2.band))).fillna("(new group)")
    top30 = new.head(30)[["group_name", "band v2", "total", "need", "trigger_after_decay", "sector", "country", "size_band",
                          "signals", "group_id"]]

    # ---------------- peers
    PI = rd(INTERIM / "peer_incidents.csv")
    held = s4[s4.signal_type == "peer incident"].group_id.nunique()
    peer = kv([
        ["Groups holding a peer signal (v4)", held],
        ["Groups holding a peer signal (v3)", s3[s3.signal_type == "peer incident"].group_id.nunique()],
        ["Source incidents (victim groups)", len(PI)],
        ["  applied", int((PI.applied == "True").sum())],
        ["  over the 150-group limit (not applied)", int(PI.reason.str.startswith("over").sum())],
        ["  no industry group / no other group in it", int(PI.reason.str.startswith("no ").sum())],
        ["Rules", "Ransomware claims and news cyber or data events or supplier failures (high confidence, UK or Irish "
                  "business), last 6 months; peers share the victim's 3-digit industry group and country"],
    ])
    over = PI[PI.reason.str.startswith("over")][["victim_group_name", "victim", "date", "how", "division", "country", "peers",
                                                  "confirmed_by_news", "link"]].rename(columns={"division": "industry group"})
    applied = PI[PI.applied == "True"][["victim_group_name", "victim", "date", "how", "division", "country", "peers",
                                         "confirmed_by_news"]].rename(columns={"division": "industry group"})

    # ---------------- item 7
    D = rd(INTERIM / "item7" / "documents.csv")
    R7 = rd(INTERIM / "item7_results.csv")
    c7 = sum(pd.to_numeric(L[(L.source == "item7") & L.event.isin(["find_done", "transcribe_done", "verdict_done"])].cost_usd).fillna(0))
    seven = kv([
        ["Groups in scope (1,000+ staff, no listed-company result)", len(D)],
        *[[f"  {k}", int(v)] for k, v in D.status.value_counts().items()],
        *[[f"Verdict: {k}", int(v)] for k, v in R7.verdict.value_counts().items()],
        ["Groups gaining a principal-risk need signal", int(s4[s4.slice == "A"].group_id.nunique())],
        ["Cost", f"${c7:.2f} (Batch API: Haiku find and transcribe, Opus verdict); the 30 tested scans and 28 text "
                 f"sections from the pilot were reused"],
        ["Documents", "Each downloaded document deleted after its section was extracted"],
    ])
    reasons = D[D.status == "couldn't check"].reason.str[:80].value_counts().reset_index()
    reasons.columns = ["Couldn't check: reason", "Groups"]
    res7 = R7[[c for c in ["group_name", "size_band", "company_name", "status", "format", "verdict", "risk_title", "quote",
                           "quote_check", "supply_chain", "reason_model", "source_link"] if c in R7]] if len(R7) else R7

    # ---------------- briefs
    B = rd(P["briefs"]); B = B[B.version.isin(["v4", "v4fix"])]     # current text, incl. the 5 evidence fixes
    nb_ = B[~B.group_id.isin(a2)] if len(B) else B
    briefs = nb_.head(15)[["group_name", "rank", "total", "stage2", "model", "what_changed", "why_it_matters", "angle",
                           "who_to_contact", "evidence"]].rename(columns={"stage2": "new or rewrite"}) if len(nb_) else nb_

    # ---------------- cost
    costs = [["News re-read (Opus, 3,177 stories)", float(L[(L.source == "stage2_model") & (L.event == "done") & (L.job == "news2")].cost_usd.astype(float).sum())]]
    for ev, lab in [("find_done", "Item 7: Haiku find pages"), ("transcribe_done", "Item 7: Haiku transcribe"), ("verdict_done", "Item 7: Opus verdicts")]:
        costs.append([lab, float(pd.to_numeric(L[(L.source == "item7") & (L.event == ev)].cost_usd).sum())])
    costs.append(["Briefs (v4: 175 + 5 evidence fixes)", float(pd.to_numeric(L[(L.source == "briefs_stage2") & (L.event == "done")].cost_usd).sum())])
    c = pd.DataFrame(costs, columns=["Step", "Cost (USD)"])
    c.loc[len(c)] = ["TOTAL this round", c["Cost (USD)"].sum()]
    c.loc[len(c)] = ["Pre-approved this round", 80.0]
    c.loc[len(c)] = ["Stage 2 before this round (v3)", 29.86]
    c["Cost (USD)"] = c["Cost (USD)"].round(2)

    regroup = rd(INTERIM / "v4_regrouped.csv")
    m3 = T4.merge(T3[["group_id", "sector"]], on="group_id", how="left", suffixes=("", "_v3")).fillna("")
    fs_gained_df = m3[(m3.sector == "Financial services") & (m3.sector_v3 != "Financial services")]
    fs_gained, fs_gained_ie = len(fs_gained_df), int((fs_gained_df.country == "IE").sum())
    fs_lost = int(((m3.sector != "Financial services") & (m3.sector_v3 == "Financial services")).sum())
    summary = kv([
        ["What this is", "v4: tightened news rules (saved stories re-read by Opus), new peer rules, sector label and "
                         "government ownership stop, annual reports for groups with 1,000+ staff. v2 stays the release version."],
        ["Spreadsheet", f"GTM full run ranked v4 {date.today().isoformat()}.xlsx (same tabs), in Uploads - not for release until approved"],
        ["Bands v2 / v3 / v4", "; ".join(f"{r.Band} {r._2} / {r._3} / {r.v4}" for r in bands.itertuples())],
        ["Financial services label v2 / v3 / v4", f"{sec.iloc[0, 1]} / {sec.iloc[0, 2]} / {sec.iloc[0, 3]}"],
        ["Financial services label: what changed", f"{fs_lost} groups lost it (an authorised firm is not their largest "
                                                   f"member or top company; need points kept); {fs_gained} gained it, of which "
                                                   f"{fs_gained_ie} are Irish firms on the Central Bank register whose sector was "
                                                   f"blank in v3"],
        ["Groups newly Act now (v4 vs v2)", len(new)],
        ["Peer signal holders v3 -> v4", f"{s3[s3.signal_type == 'peer incident'].group_id.nunique()} -> {held}"],
        ["Entities moved out of government-named groups", len(regroup)],
        ["Model spend this round", f"${c.iloc[len(costs), 1]:.2f} of $80"],
    ])
    write(FILE, [("Summary", summary), ("Bands v2 v3 v4", bands), ("News signals by type", ntypes),
                 ("News - why v3 signals lost", lost), ("News - 40 stories", s40),
                 ("Top 30 newly Act now", top30), ("Peer incidents", peer), ("Peers - over 150 limit", over),
                 ("Peers - applied", applied), ("Item 7 - annual reports", seven), ("Item 7 - couldn't check", reasons),
                 ("Item 7 - results", res7), ("Briefs (15)", briefs), ("Regrouped (state owners)", regroup), ("Cost report", c)])
    to_uploads(FILE)
    print(FILE); print(summary.to_string())


if __name__ == "__main__":
    main()
