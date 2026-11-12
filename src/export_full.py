"""Full run spreadsheet for reps (full run review point 7, Tom 11 Nov 2026). Reads finished outputs only.

  python src/export_full.py   -> full_run_review/GTM full run ranked v2 <date>.xlsx (+ copy in Uploads)

Tabs, each sorted by band then score: How to read this | All | Act now (with briefs) | Act now, outside financial
services | Size unconfirmed. v6 (Tom, 13 Nov 2026): groups whose size is unconfirmed are left out of the first three
ranked tabs (not hidden) and appear only in "Size unconfirmed", with their briefs; plain column headings; no hidden
rows anywhere."""
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font

from common import ROOT, paths, settings, to_uploads

ST = settings()
P = paths()
OUT = ROOT / "full_run_review"
# stage 2 (Tom, 12 Nov 2026): the rescored list with the new signals is v3; v2 stays as it was
VERSION = ST["run"].get("export_version", "v3" if ST["stage2"].get("include_in_scoring") else "v2")
FILE = OUT / f"GTM full run ranked {VERSION} {date.today().isoformat()}.xlsx"
BRIEF = ["what_changed", "why_it_matters", "angle", "who_to_contact", "brief_date"]
COLS = ["rank", "known_as", "group_name", "band", "total", "need", "trigger_after_decay", "country", "sector",
        "size_band"] + BRIEF + ["signal 1", "signal 1 date", "signal 1 entity", "signal 1 source", "signal 2",
        "signal 2 date", "signal 2 entity", "signal 2 source", "signal 3", "signal 3 date", "signal 3 entity",
        "signal 3 source", "next_accounts_due", "flags", "entities", "entity_list", "group_id"]
# v6 item 5: plain headings, in this order
HEAD = dict(zip(COLS, ["Rank", "Known as", "Legal name", "Band", "Score", "Need score", "Timing score", "Country",
                       "Sector", "Size", "What changed", "Why it matters", "Angle to open on", "Who to contact",
                       "Brief written", "Signal 1", "Signal 1 date", "Signal 1 company", "Signal 1 link", "Signal 2",
                       "Signal 2 date", "Signal 2 company", "Signal 2 link", "Signal 3", "Signal 3 date",
                       "Signal 3 company", "Signal 3 link", "Next accounts due", "Notes", "Companies in group",
                       "Company list", "ID"]))

HOW = [
    ("What this is", "Every organisation group in the UK and Irish universe, scored for why it may need third-party "
                     "risk software now. Score = need + timing. Run date " + ST["run"]["run_date"] + "."),
    ("Every signal is a lead to verify", "No signal is a confirmed fact about the account. Before you use one, open "
                                         "its link (Signal 1-3 link columns) and check what it actually says."),
    ("How often", "The list is rescored monthly: new data is pulled, every group is rescored and the briefs of Act now "
                  "groups whose signals changed are rewritten."),
    ("", ""),
    ("TABS", ""),
    ("All", "Every group whose staff size is confirmed, ranked."),
    ("Act now", "Act now groups whose staff size is confirmed, with their briefs."),
    ("Act now, outside fin. services", "The Act now tab without groups whose sector is Financial services."),
    ("Size unconfirmed", "Groups whose staff size is not known (they came in from the PRA lists or the FCA Register). "
                         "They appear only in this tab, ranked among themselves, with briefs where they are Act now."),
    ("", ""),
    ("COLUMNS", ""),
    ("Rank", "Position within the tab, by band then score."),
    ("Known as", "The name a salesperson would search for (e.g. Bupa, OVO, Santander UK). For Act now, Warming and "
                 "Strong fit groups this was chosen by a model from the group's name, its companies and the brand "
                 "names seen in adverts and news; for the rest it is the legal name in normal capitalisation."),
    ("Legal name", "The group's registered name (its foreign parent, its top UK company, or its largest member)."),
    ("Band", "Act now, Warming, Strong fit or Fit only (see BANDS)."),
    ("Score / Need score / Timing score", "Score = need + timing (see NEED SIGNALS and TIMING SIGNALS)."),
    ("Country", "UK or Irish group."),
    ("Sector", "The group's main business. For Act now, Warming and Strong fit groups it was chosen by a model from "
               "the group's name, companies and brands (a bank, insurer, asset manager or payments company is Financial "
               "services; a group that only owns a small financial subsidiary keeps its main sector). For the rest it "
               "comes from the industry code of the largest member or the FCA, Central Bank of Ireland, housing and "
               "university registers."),
    ("Size", "The largest staff band of any member (UK gender pay gap service or Irish equivalent)."),
    ("What changed / Why it matters / Angle to open on / Who to contact / Brief written", "The brief (Act now groups "
     "only) and the date it was written."),
    ("Signal 1-3 / date / company / link", "The three highest-scoring signals, the date of each, the member company it "
                                           "belongs to, and the link to its source."),
    ("Next accounts due", "When the top UK company's next accounts are due at Companies House."),
    ("Notes", "Flags such as 'owned by an investor', 'grouping unchecked' or unmatched signals held for review."),
    ("Companies in group / Company list / ID", "How many member companies, their names and numbers, and the group's ID."),
    ("", ""),
    ("BANDS", ""),
    ("Act now", "Timing score 3 or more AND at least one recent trigger worth 3+ points on its own (third-party "
                "risk or security leader advert, senior leader advert, new Senior Manager, merger or acquisition, "
                "relevant regulatory enforcement, regulatory governance downgrade). A peer incident never counts "
                "towards this. Has a brief."),
    ("Warming", "Timing score 2 or more, but not Act now."),
    ("Strong fit", "Little or no recent timing, but need score 3 or more (e.g. names third-party risk as a principal risk)."),
    ("Fit only", "In the target universe; nothing current points to now."),
    ("", ""),
    ("NEED SIGNALS (no expiry)", ""),
    ("principal risk named / passing mention", "The latest annual report names third-party, supplier or outsourcing "
                                               "risk as a principal risk (3 points), or mentions it in passing (1). "
                                               "See 'Annual report verdicts' below."),
    ("authorised financial firm", "A member is authorised by the FCA (bank, building society, insurer, investment "
                                  "firm, payment or e-money institution) or the Central Bank of Ireland (2). "
                                  "Insurance intermediaries and investment advisers 1."),
    ("critical infrastructure / pharmaceuticals", "The group's largest member is in energy, water, telecoms, rail, "
                                                  "air transport or hospitals (2), or pharmaceuticals (1)."),
    ("other regulated sector", "Registered social housing provider or university on the OfS register (1)."),
    ("", ""),
    ("TIMING SIGNALS (full value under 3 months old, half 3-6, quarter 6-12, nothing older)", ""),
    ("hiring", "A job advert at the group (Reed, Adzuna, and for Irish groups their own careers site where it uses "
               "Greenhouse, Lever, Ashby, SmartRecruiters or Workable): third-party risk role or security leader 4, "
               "senior leader in procurement, risk or compliance 3, wider or operating change role 2. Checked by a "
               "model, not just the title."),
    ("new senior manager (SMF4/SMF5)", "Someone newly approved on the FCA Register as Chief Risk (SMF4) or Head of "
                                       "Internal Audit (SMF5) at a member firm (4)."),
    ("pre-IPO", "A private company re-registered as a plc in the last 12 months (2)."),
    ("board turnover", "Three or more director changes at the top company (1)."),
    ("new funding / new charge", "New shares allotted or a new charge registered at Companies House (1)."),
    ("headcount growth", "Moved up a pay gap staff band between the last two years (1)."),
    ("", ""),
    ("STAGE 2 SIGNALS (news, regulators, ownership, annual reports, ransomware, peers)", ""),
    ("News events", "UK and Irish news stories (NewsAPI.ai, roughly the last two months) read by a model. A story "
                    "counts only if it is about the group's UK or Irish business, a UK or Irish regulator, or a change "
                    "of control of the whole group, and only if the event happened to the organisation credited. "
                    "Readings made with low confidence score 0. Each event is dated from when it happened or was "
                    "announced, never from a planned future date. The types are: a merger, acquisition or separation "
                    "(below); an incident at the account (below); regulatory enforcement (below). Commentary, "
                    "rumours, anniversaries and stories that only mention the group score 0."),
    ("  merger, acquisition or separation", "From the news, a CMA merger case, or Companies House. 3 points when the "
                                            "group is being acquired, merging, demerging, selling a major division or "
                                            "buying a large business (GBP 100m+ or a whole branded company); 1 point for "
                                            "a smaller bolt-on (never makes a group Act now). 0 for rumours, talks, "
                                            "unagreed bids, single sites, brands or assets, the group acting only as "
                                            "adviser, lender, minority investor or former owner, and any deal between "
                                            "units of the same group. Counted once across sources."),
    ("  incident at the account", "News in the last 6 months of a cyber attack, data breach or ransomware event at the "
                                  "group, a technology or systems outage at the group, or a failure, breach or outage at "
                                  "one of its suppliers that affected it (2). Not utility supply cuts, pollution, weather, "
                                  "strikes, recalls, accidents or legal settlements."),
    ("Regulatory actions", "Enforcement by a UK or Irish regulator (FCA, ICO, CMA, Ofgem, Bank of England / PRA, "
                           "housing regulator, or reported in the news) against the group's UK or Irish business, only "
                           "when it concerns systems and controls, operational resilience, outsourcing or third parties, "
                           "data protection or security, financial crime controls, governance or regulatory reporting "
                           "(4). Environmental, health and safety, consumer and sporting sanctions score 0. A housing "
                           "governance downgrade 3. Counted once."),
    ("Ownership changes", "Companies House shows a new controlling corporate owner of a UK company in the last 12 "
                          "months, replacing the previous owner. Counted as a merger or acquisition (3) only when a "
                          "model judged it an external change of control, not an internal reorganisation. Groups are "
                          "traced to their ultimate owner, stopping below investors and governments or state bodies."),
    ("Annual report verdicts", "For listed groups and for groups with 1,000+ staff, the principal risks section of the "
                               "latest annual report (from Companies House; scanned reports transcribed by a model) was "
                               "read by a model. 'yes' (need 3): third-party, supplier or outsourcing risk is a "
                               "principal risk in its own right. 'passing mention' (need 1): it is mentioned within "
                               "another risk, supply chain risk is named on its own, or the only such risk is about "
                               "modern slavery, labour rights or supplier ethics. Quotes from scans are not "
                               "word-checked against the document: check the report before quoting."),
    ("Ransomware claims", "The group appears as a claimed victim on a ransomware gang's leak site (via ransomware.live) "
                          "(2). THIS IS AN ATTACKER'S CLAIM, NOT A CONFIRMED BREACH. Do not quote it or raise it with "
                          "the account. It never appears in a brief's angle."),
    ("Peer incidents", "Another UK or Irish group in the same 3-digit industry group and country had a ransomware claim, "
                       "or a cyber, data or supplier-failure event in the news, in the last 6 months (2). Not applied "
                       "when it would reach more than 150 groups, and never makes a group Act now on its own. Briefs "
                       "mention a peer incident only when the two are plainly the same kind of business, and name the "
                       "peer only when news confirms the incident."),
    ("", ""),
    ("HOW TO USE IT", ""),
    ("Signals are leads to verify", "Each signal is a lead, not a fact about the account's plans. Open the source "
                                    "link and check it before you use it."),
    ("New Senior Manager", "This signal belongs to the named firm and person shown, not the whole group. In a large "
                           "group it may be a subsidiary: speak to that entity and that person."),

    ("Briefs", "Act now groups have a four-line brief: what changed, why it matters, the angle to open on, who to "
               "contact. Written by a model from the counted signals; check the sources."),
    ("Ransomware claims (again)", "A ransomware entry is an attacker's claim, not a confirmed breach. Never quote it "
                                  "to the account."),
    ("", ""),
    ("DATA PULLED (run date " + ST["run"]["run_date"] + ")", ""),
    ("Companies House", "Company profiles, officers, owners (persons with significant control), filings and annual "
                        "reports: 10-12 Nov 2026."),
    ("UK gender pay gap service", "Employer sizes, 10 Nov 2026."),
    ("Irish Companies Registration Office (CRO)", "10 Nov 2026."),
    ("Central Bank of Ireland registers", "10-11 Nov 2026."),
    ("FCA Register (firms and Senior Managers)", "11 Nov 2026."),
    ("PRA lists of banks, building societies and insurers", "11 Nov 2026."),
    ("Housing and university registers (RSH, OfS)", "10 Nov 2026."),
    ("Job adverts (Reed, Adzuna)", "11 Nov 2026 (adverts live on that day)."),
    ("Irish careers sites", "12 Nov 2026."),
    ("CMA merger cases", "11 Nov 2026."),
    ("Regulator enforcement (FCA, ICO, CMA, Bank of England / PRA, Ofgem, housing regulator, GOV.UK)",
     "11-12 Nov 2026, covering actions from Nov 2025."),
    ("News (NewsAPI.ai)", "12 Nov 2026, stories published 19 Aug - 10 Nov 2026."),
    ("Ransomware claims (ransomware.live)", "12 Nov 2026, claims from Nov 2025."),
    ("Annual report principal risks", "Latest reports at Companies House, read 11-12 Nov 2026."),
]


def ranked(df):
    """Rank 1..n within the tab; plain headings."""
    df = df.copy()
    df["rank"] = list(range(1, len(df) + 1))
    return df[COLS].rename(columns=HEAD)


def write_sheet(w, name, df):
    df.to_excel(w, sheet_name=name, index=False)
    ws = w.sheets[name]
    ws.freeze_panes = "D2"
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(50, max(9, max(len(str(c.value or "")) for c in col[:200]) + 2))
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.auto_filter.ref = ws.dimensions           # filter buttons only; nothing is filtered or hidden
    for c in ["What changed", "Why it matters", "Angle to open on", "Who to contact"]:
        if c in df:
            L = ws.cell(row=1, column=list(df.columns).index(c) + 1).column_letter
            ws.column_dimensions[L].width = 60
            for cell in ws[L][1:]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")


def main():
    T = pd.read_csv(P["ranked"], dtype=str).fillna("")
    for c in ("total", "need", "trigger_after_decay"):
        T[c] = pd.to_numeric(T[c])
    order = {b: i for i, b in enumerate(ST["sector_label"]["band_order"])}
    T = T.assign(_b=T.band.map(order)).sort_values(["_b", "total", "trigger_after_decay", "need", "group_name"],
                                                  ascending=[True, False, False, False, True]).drop(columns="_b")
    T["sector"] = T.sector.replace("", "unknown")
    b = pd.read_csv(P["briefs"], dtype=str).fillna("")
    act_ids = set(T[T.band == "Act now"].group_id)
    b = b[b.group_id.isin(act_ids)]                # briefs belong to Act now groups only (older briefs are not shown)
    for c in BRIEF:
        T[c] = T.group_id.map(dict(zip(b.group_id, b[c]))).fillna("")
    conf = T[T.size_confirmed == "yes"]
    allt = ranked(conf)
    act = conf[conf.band == "Act now"]
    act_t = ranked(act)
    nfs = act[act.sector != "Financial services"]
    nfs_t = ranked(nfs)
    unc = ranked(T[T.size_confirmed == "no"])
    how = pd.DataFrame(HOW, columns=["Item", "What it means"])
    OUT.mkdir(exist_ok=True)
    with pd.ExcelWriter(FILE) as w:
        how.to_excel(w, sheet_name="How to read this", index=False)
        ws = w.sheets["How to read this"]
        ws.column_dimensions["A"].width = 42
        ws.column_dimensions["B"].width = 110
        for row in ws.iter_rows():
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
                if c.column == 1 and c.value and not ws.cell(row=c.row, column=2).value:
                    c.font = Font(bold=True)
        write_sheet(w, "All", allt)
        write_sheet(w, "Act now", act_t)
        write_sheet(w, "Act now, outside fin. services", nfs_t)
        write_sheet(w, "Size unconfirmed", unc)
    to_uploads(FILE)
    print(f"All {len(allt)} | Act now {len(act_t)} | outside FS {len(nfs_t)} | size unconfirmed {len(unc)} "
          f"(of which Act now {int((unc.Band == 'Act now').sum())}, with a brief {int((unc['What changed'] != '').sum())})")
    return T, nfs


if __name__ == "__main__":
    main()
