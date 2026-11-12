"""Step 7: build the full_run_review folder (Tom, 11 Nov 2026, point 15). Reads only finished outputs; no downloads.

  python src/review_full.py

Writes to full_run_review/ (project folder) and copies the two workbooks to Uploads:
  - GTM full run ranked <date>.xlsx : every group, sorted by band then score, with briefs; plus the scored signals
  - GTM full run review <date>.xlsx : Summary, bands by country and sector, top 50, 20 random groups outside the top
    300, review summary, new medium/low brand lookup rows, run log, cost report, answers to points 8-10."""
import json
import random
import shutil
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from common import INTERIM, OUTPUT, ROOT, paths, settings, to_uploads

ST = settings()
M = ST["models"]
P = paths()
assert P["scope"] == "full", "set [run] scope = \"full\""
OUT = ROOT / "full_run_review"

TODAY = date.today().isoformat()
STEP7_START = ST["run"].get("step7_started", "2026-11-11T16:00")
BRIEF_COLS = ["what_changed", "why_it_matters", "angle", "who_to_contact"]


def write(path, sheets):
    with pd.ExcelWriter(path) as w:
        for name, df in sheets:
            df.to_excel(w, sheet_name=name[:31], index=False)
            ws = w.sheets[name[:31]]
            ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    60, max(9, max(len(str(c.value or "")) for c in col[:200]) + 2))


def signals_text(S, gid, n=6):
    sg = S[(S.group_id == gid) & (S.value.astype(float) > 0)].sort_values("value", ascending=False).head(n)
    return "; ".join(f"{x.signal_type} ({x.date or 'standing'}, {float(x.value):g} pts{'' if x.counted == 'True' else ', not counted'})"
                     for x in sg.itertuples())


def first(d, *keys):
    """The first of these fields that is present and not empty in a run-log row."""
    for k in keys:
        v = d.get(k)
        if v is not None and not (isinstance(v, float) and pd.isna(v)) and v != "":
            return v
    return None


def run_log():
    """Per source since Step 7 began: requests made, failures, active time (gaps over 5 minutes left out) and span."""
    rows = []
    for line in open(ROOT / "data" / "run_log.jsonl"):
        d = json.loads(line)
        if d["ts"] >= STEP7_START:
            rows.append(d)
    L = pd.DataFrame(rows)
    L["t"] = pd.to_datetime(L.ts)
    fail_ev = {"error", "server_error", "gave_up", "rate_limit_pause"}
    out = []
    for src, g in L.groupby("source"):
        g = g.sort_values("t")
        gaps = g.t.diff().dt.total_seconds().fillna(0)
        active = gaps[gaps <= 300].sum()
        req = int(g.event.isin(["request", "page", "job_details", "download"]).sum())
        bad_status = int((pd.to_numeric(g.get("status"), errors="coerce").fillna(200) >= 400).sum()) if "status" in g else 0
        out.append(dict(source=src, requests=req, not_found=int((g.event == "not_found").sum()),
                        failures=int(g.event.isin(["error", "server_error", "gave_up"]).sum()) + bad_status,
                        rate_limit_pauses=int((g.event == "rate_limit_pause").sum()),
                        active_minutes=round(active / 60, 1),
                        first=g.ts.iloc[0][:16].replace("T", " "), last=g.ts.iloc[-1][:16].replace("T", " "),
                        other_events="; ".join(f"{k} {v}" for k, v in g.event.value_counts().items()
                                               if k not in {"request", "page", "job_details", "download", "not_found"} | fail_ev)))
    return pd.DataFrame(out), L


def main():
    OUT.mkdir(exist_ok=True)
    T = pd.read_csv(P["ranked"], dtype=str).fillna("")
    S = pd.read_csv(P["scored"], dtype=str).fillna("")
    b = pd.read_csv(P["briefs"], dtype=str).fillna("") if P["briefs"].exists() else pd.DataFrame(columns=["group_id"])
    for c in BRIEF_COLS:
        T[c] = T.group_id.map(dict(zip(b.group_id, b[c]))).fillna("") if len(b) else ""
    T["brief_date"] = T.group_id.map(dict(zip(b.group_id, b.brief_date))).fillna("") if len(b) else ""
    T = T.drop(columns=[c for c in ("brief", "pilot_stratum") if c in T])
    for c in ("total", "need", "trigger_after_decay", "hiring_points"):
        T[c] = pd.to_numeric(T[c])
    T["rank"] = pd.to_numeric(T["rank"])
    # ---- 1. ranked workbook
    Ssig = S[S.value.astype(float) > 0].copy()
    write(OUT / f"GTM full run ranked {TODAY}.xlsx",
          [("Ranked list", T), ("Signals scored", Ssig)])

    # ---- 2. summary tables
    bands = ST["sector_label"]["band_order"]
    bc = T.band.value_counts().reindex(bands).fillna(0).astype(int)
    by_country = pd.crosstab(T.country, T.band).reindex(columns=bands, fill_value=0)
    by_country["all"] = by_country.sum(axis=1)
    by_country = by_country.sort_values("all", ascending=False).reset_index()
    by_sector = pd.crosstab(T.sector.replace("", "unknown"), T.band).reindex(columns=bands, fill_value=0)
    by_sector["all"] = by_sector.sum(axis=1)
    by_sector = by_sector.sort_values(bands[0], ascending=False).reset_index()
    keep = ["rank", "group_name", "band", "total", "need", "trigger_after_decay", "country", "sector", "size_band"]
    top50 = T.head(50)[keep].copy()
    top50["signals"] = [signals_text(S, g) for g in T.head(50).group_id]
    top50["brief: angle"] = T.head(50).angle.values
    rest = T.iloc[300:]
    rnd = rest.sample(n=min(20, len(rest)), random_state=ST["run"].get("review_seed", 7)).sort_values("rank")
    rand20 = rnd[keep].copy()
    rand20["signals"] = [signals_text(S, g) for g in rnd.group_id]

    # ---- review file summary
    R = pd.read_csv(P["review"], dtype=str).fillna("")
    src_col = "source" if "source" in R else R.columns[0]
    why_col = next((c for c in ("reason", "review_reason", "why") if c in R), R.columns[-1])
    R[why_col] = R[why_col].str.replace(r"number is \S+, not \S+", "number is different", regex=True)
    rev = R.groupby([src_col, why_col]).size().reset_index(name="items").sort_values([src_col, "items"], ascending=[True, False])
    j = pd.read_csv(INTERIM / "job_adverts.csv", dtype=str).fillna("")
    jrev = j[j.review_reason != ""].groupby("review_reason").size().reset_index(name="adverts")
    jrev.insert(0, "source", "job adverts (whole pull)")
    jrev = jrev.rename(columns={"review_reason": why_col})

    # ---- brand rows needing a look (Step 7 batch, medium/low)
    bl = pd.read_csv(INTERIM / "brand_lookup.csv", dtype=str).fillna("")
    new_brand = bl[(bl.get("batch", "") == "step7") & bl.confidence.isin(["medium", "low"])] if "batch" in bl else bl.iloc[0:0]
    brand_stats = (bl[bl.get("batch", "") == "step7"].confidence.replace("", "no candidate group").value_counts().to_dict() if "batch" in bl else {})

    # ---- run log and cost
    rl, L = run_log()
    ev = lambda src, e: L[(L.source == src) & (L.event == e)]
    cost_rows = []
    total = 0.0
    for label, src, e in [("Brand lookup (Opus batch)", "brands", "batch_collected"),
                          ("Advert classification (Opus batch)", "classify", "done"),
                          ("Why-now briefs (Fable batch)", "briefs", "done")]:
        x = ev(src, e)
        if len(x):
            d = x.iloc[-1]
            c = float(first(d, "cost_usd", "cost") or 0)
            total += c
            n = first(d, "n", "requests")
            cost_rows.append([label, f"{int(d.input_tokens):,} in / {int(d.output_tokens):,} out",
                              "" if n is None else int(n), f"${c:.2f}"])
        else:
            cost_rows.append([label, "not run", "", ""])
    est = [f"{r.source} {r.event}: ${float(r.cost_usd):.2f}" for r in L[L.event == "estimate"].itertuples()
           if "cost_usd" in L and not pd.isna(r.cost_usd)]
    cost_rows += [["Total model spend, Step 7", "", "", f"${total:.2f}"],
                  ["Approved ceiling", "", "", f"${M['budget_full_run_usd']:.2f}"],
                  ["Estimates made before sending", "; ".join(est), "", ""]]
    cost = pd.DataFrame(cost_rows, columns=["item", "tokens", "requests", "cost"])

    # ---- answers to points 8, 9, 10
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    gpg = u[u.entity_id.str.startswith("GPG-")].copy()
    order = {b: i for i, b in enumerate(ST["universe"]["min_staff_bands"])}
    gpg["_s"] = gpg.size_band.str.replace(" staff", "").map(order).fillna(-1)
    p8top = gpg.sort_values(["_s", "name"], ascending=[False, True]).head(50)[
        [c for c in ("name", "size_band", "industry_code", "sources", "flag") if c in gpg]]
    add = pd.read_csv(INTERIM / "fca_additions.csv", dtype=str).fillna("")
    addrev = pd.read_csv(INTERIM / "fca_additions_review.csv", dtype=str).fillna("")
    pra = add[add.added_by == "PRA list"]
    adv = add[add.added_by == "advert employer"]
    inuni = lambda df: int(df.entity_id.isin(u.entity_id).sum())
    newly = lambda df: int((u.entity_id.isin(df.entity_id) & u.size_test.str.contains("size unconfirmed")
                            & u.sources.str.match(r"(PRA list|advert employer on FCA Register)")).sum())
    answers = pd.DataFrame([
        ["8", "Pay gap entries with no company number",
         f"{len(gpg)} kept (rule: not public-sector code '1' and no public-body name word; universities only via the "
         f"universities register). The 50 largest are in 'Point 8 largest 50'."],
        ["9", "PRA banks, building societies and insurers",
         f"{len(pra)} firms added to the FCA table from the PRA lists ({(pra.fca_type == 'insurer').sum()} insurers, "
         f"{(pra.fca_type != 'insurer').sum()} banks and building societies); {inuni(pra)} are in the universe "
         f"({newly(pra)} of them new, the rest were already there). {(pra.entity_id.str.startswith('FRN-')).sum()} have no "
         f"Companies House number on the FCA Register (overseas branches, Gibraltar and EEA run-off firms, friendly societies, building societies not in the pay gap file) and stand as their own group. "
         f"{(addrev.added_by == 'PRA list').sum()} not added (see 'Additions review')."],
        ["10", "Advert employers on the FCA Register",
         f"{len(adv)} employers added (exact name match to an FCA investment firm or payment / e-money institution): "
         + ", ".join(adv.name) + f". {(addrev.added_by == 'advert employer').sum()} in review."],
    ], columns=["point", "item", "answer"])

    rep = json.loads(P["score_report"].read_text()) if P["score_report"].exists() else {}
    summary = pd.DataFrame([
        ["What this is", "Step 7: the full run. Every group scored; briefs for the top Act now groups."],
        ["Groups", f"{len(T):,}"],
        ["Bands", ", ".join(f"{k} {v:,}" for k, v in bc.items())],
        ["Act now on a job advert alone", rep.get("Act now on a job advert alone", "")],
        ["Groups with no signal at all", rep.get("groups with no signal at all", "")],
        ["Briefs written", f"{int((T.angle != '').sum())}"],
        ["Model spend", f"${total:.2f} of ${M['budget_full_run_usd']} approved"],
        ["Brand lookup, Step 7 rows", ", ".join(f"{k} {v}" for k, v in brand_stats.items()) + " (high applied; medium/low listed)"],
        ["Tabs", "Bands | By country | By sector | Top 50 | Random 20 outside top 300 | Review summary | "
                 "Brand rows to review | Run log | Cost report | Answers 8-10 | Point 8 largest 50 | Additions | Additions review"],
    ], columns=["Item", "Value"])
    sheets = [("Summary", summary), ("Bands", bc.reset_index().rename(columns={"index": "band", "band": "band", "count": "groups"})),
              ("By country", by_country), ("By sector", by_sector), ("Top 50", top50),
              ("Random 20 outside top 300", rand20), ("Review summary", pd.concat([rev, jrev])),
              ("Brand rows to review", new_brand), ("Run log", rl), ("Cost report", cost), ("Answers 8-10", answers),
              ("Point 8 largest 50", p8top), ("Additions", add), ("Additions review", addrev)]
    write(OUT / f"GTM full run review {TODAY}.xlsx", sheets)
    for name, df in [("summary", summary), ("bands_by_country", by_country), ("bands_by_sector", by_sector),
                     ("top50", top50), ("random20_outside_top300", rand20), ("review_summary", pd.concat([rev, jrev])),
                     ("brand_rows_medium_low", new_brand), ("run_log", rl), ("cost_report", cost),
                     ("answers_points_8_9_10", answers), ("point8_largest50", p8top)]:
        df.to_csv(OUT / f"{name}.csv", index=False)
    for f in OUT.glob(f"GTM full run * {TODAY}.xlsx"):
        to_uploads(f)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
