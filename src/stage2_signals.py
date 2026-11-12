"""Stage 2: turn the new sources into signals for every group (Tom, 12 Nov 2026, decisions on the pilots).

  python src/stage2_signals.py   -> data/interim/stage2_signals.csv (+ stage2_review.csv, news_matched.csv,
                                    reg_matched.csv, ransomware_matched.csv, peer_incidents.csv)

Item 1 (regulators): enforcement scores 4 only when Opus marks it relevant (systems and controls, operational
  resilience, outsourcing or third parties, data protection or security, financial crime controls, governance,
  regulatory reporting); housing governance downgrades score 3; everything else 0 (listed, no signal).
Item 2 (Companies House): new controlling owner that Opus reads as an external change of control -> merger family, 3.
Item 3 (ransomware.live): claimed victim matched to a group -> 2; peers (same industry division and country) -> 2,
  not applied for an incident that would reach more than 300 groups.
Item 4 (news, NewsAPI.ai): incident or supplier failure 2; enforcement 4 only if relevant (item 1 rule); merger 3;
  a high-confidence incident at a universe group also gives its peers the peer signal (same 300 limit).
Item 6 (careers sites, Irish groups): open roles classified by Opus -> the hiring signals.
Slice A: v4 item 7 results (groups with 1,000+ staff), need 3 / 1.
Matching: orgmatch.Matcher (exact name, name without legal-form words, then the brand lookup); anything else goes to
review. Dates: every action date parsed to a real date; month-only dates take the publication date when it falls in
that month, else the 1st; items with no date take the publication date."""
import json
import re
from datetime import date, datetime, timedelta

import pandas as pd

from common import INTERIM, OUTPUT, log, paths, settings
from orgmatch import Matcher

ST = settings()
P = paths()
RUN = date.fromisoformat(ST["run"]["run_date"])
PEER_LIMIT = ST["stage2"].get("peer_limit", 150)
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def real_date(s, pub=""):
    """(YYYY-MM-DD, precision) from '2026-05-20', '20260520', '27 July 2026', 'October 2026', '2026-10'."""
    s = (s or "").strip()
    pub = (pub or "").strip()[:10]
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    if m:
        try:
            return date(*map(int, m.groups())).isoformat(), "day"
        except ValueError:
            pass
    m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)? ({MONTHS}),? (\d{{4}})", s, re.I)
    if m:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date().isoformat(), "day"
    m = re.search(rf"({MONTHS}) (\d{{4}})", s, re.I) or re.match(r"(\d{4})-(\d{2})$", s)
    if m:
        y, mo = (int(m.group(2)), datetime.strptime(m.group(1), "%B").month) if not m.group(1).isdigit() else (int(m.group(1)), int(m.group(2)))
        if pub[:7] == f"{y:04d}-{mo:02d}":
            return pub, "month (publication date used)"
        return date(y, mo, 1).isoformat(), "month (1st used)"
    m = re.fullmatch(r"(\d{4})", s)
    if pub:
        p = real_date(pub)[0] if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", pub) else pub
        return p, "publication date"
    return "", "none"


def answers(*jobs):
    out = []
    for j in jobs:
        f = INTERIM / f"stage2_{j}_model_raw.csv"
        if f.exists():
            out.append(pd.read_csv(f, dtype=str).fillna(""))
    if not out:
        return pd.DataFrame(columns=["id", "answer"])
    return pd.concat(out).drop_duplicates("id", keep="last")


def group_info():
    """group -> (industry division, country, name) from the largest member (the Step 7 sector rule)."""
    from sectors import lead_member
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    e = pd.read_csv(P["entities"], dtype=str).fillna("")
    g = pd.read_csv(P["groups"], dtype=str).fillna("")
    sb, ic, cc = dict(zip(u.entity_id, u.size_band)), dict(zip(u.entity_id, u.industry_code)), dict(zip(u.entity_id, u.country))
    info = {}
    by = dict(tuple(e.groupby("group_id")))
    for x in g.itertuples():
        ids = list(by.get(x.group_id, e.iloc[0:0]).entity_id)
        lead, codes = lead_member(ids, sb, ic)
        div = next((re.sub(r"\D", "", c)[:3] for c in codes if len(re.sub(r"\D", "", c)) >= 3), "")   # v4: 3-digit industry group
        country = x.countries if x.countries in ("UK", "IE") else cc.get(lead, "UK")
        info[x.group_id] = (div, "IE" if country in ("IE", "Ireland") else "UK", x.group_name)
    return info


def main():
    mt = Matcher()
    sig, rev, zero = [], [], []
    GI = group_info()
    peers_by = {}
    for gid, (div, c, _) in GI.items():
        if div:
            peers_by.setdefault((div, c), []).append(gid)
    incidents = []          # (victim group, date, how, victim name, confirmed by news, link, source)

    # ---------------------------------------------------------------- Item 1: regulators (Slice D + Ofgem)
    R = pd.read_csv(INTERIM / "reg_items.csv", dtype=str).fillna("").set_index("item_id")
    ans = answers("reg", "reg_rsh", "ofgem")
    rel = {x.id: json.loads(x.answer) for x in answers("reg_rel", "ofgem_rel").itertuples() if x.answer}
    out = []
    for x in ans.itertuples():
        if x.id not in R.index:
            continue
        it = R.loc[x.id]
        d = json.loads(x.answer) if x.answer else {"verdict": "", "organisations": [], "action_date": "", "confidence": "", "reason": getattr(x, "error", "")}
        v = d["verdict"]
        rl = rel.get(x.id, {})
        if v == "enforcement":
            pts, why = (4, f"relevant: {rl.get('area', '')}") if rl.get("relevant") else (0, f"scored 0: {rl.get('area', 'not re-read')}")
        elif v == "governance downgrade":
            pts, why = 3, "housing governance downgrade" if "Social Housing" in it.source else "governance downgrade"
        else:
            pts, why = 0, ""
        dt, prec = real_date(rl.get("action_date") or d["action_date"], it.date)
        orgs = d["organisations"] if v in ("enforcement", "governance downgrade") else [""]
        for o in orgs or [""]:
            gid, eid, how = mt.match(o) if o else ("", "", "")
            out.append(dict(item_id=x.id, source=it.source, title=it.title, published=it.date, link=it.link, verdict=v,
                            relevant=rl.get("relevant", ""), area=rl.get("area", ""), relevance_reason=rl.get("reason", ""),
                            points=pts, organisation=o, action_date_text=rl.get("action_date") or d["action_date"],
                            date=dt, date_precision=prec, confidence=d["confidence"], reason=d["reason"],
                            group_id=gid, entity_id=eid, match=how if gid else "", review=how if (o and not gid) else ""))
            if gid and pts:
                st = (f"regulatory enforcement ({rl.get('area', '')})" if v == "enforcement"
                      else "regulatory governance downgrade")
                sig.append(dict(group_id=gid, entity_id=eid, signal_type=st, kind="trigger", date=dt, source=it.source,
                                source_link=it.link, detail=f"{it.title}: {rl.get('reason') or d['reason']}"[:400], slice="D"))
            elif o and not gid and pts:
                rev.append(dict(source=f"Slice D: {it.source}", item=o, reason=how, source_link=it.link))
    RM = pd.DataFrame(out)
    RM.to_csv(INTERIM / "reg_matched.csv", index=False)

    # ---------------------------------------------------------------- Item 2: Companies House new controlling owner
    f = INTERIM / "ch_acquisitions.csv"
    if f.exists():
        A = pd.read_csv(f, dtype=str).fillna("")
        A = A[A.counts == "True"].copy()
        A["cid"] = [f"a{i:04d}" for i in A.index]
        acq = {x.id: json.loads(x.answer) for x in answers("acq").itertuples() if x.answer}
        for x in A.itertuples():
            a = acq.get(x.cid, {})
            if a.get("verdict") == "external change of control":
                sig.append(dict(group_id=x.group_id, entity_id=f"UK:{x.company_number}" if not x.company_number.startswith(("UK:", "IE:")) else x.company_number,
                                signal_type="merger, acquisition or separation (Companies House: new controlling owner)",
                                kind="trigger", date=x.notified_on, source="Companies House (persons with significant control)",
                                source_link=x.source_link,
                                detail=f"{x.company_name}: new controlling owner {x.new_owner} notified {x.notified_on}, replacing "
                                       f"{x.previous_owner} ({a.get('reason', '')})"[:400], slice="CH"))

    # ---------------------------------------------------------------- Item 4: news (NewsAPI.ai), v4 reading
    # Tom, 13 Nov 2026: UK and Ireland test; correct organisation; deal role and scale; narrower incidents (event
    # in the last 6 months); enforcement by a UK or Irish regulator, relevant areas only.
    N = pd.read_csv(INTERIM / "news_stories.csv", dtype=str).fillna("").set_index("story_id")
    SIX = (RUN - timedelta(days=183)).isoformat()
    INC = {"cyber attack, data breach or ransomware": "operational incident or supplier failure (news: cyber attack or data breach)",
           "technology or systems outage": "operational incident or supplier failure (news: technology outage)",
           "supplier or service provider failure": "operational incident or supplier failure (news: supplier failure)"}
    BIG = {"being acquired", "merging", "demerging or being broken up", "selling a major division", "acquiring a large business"}
    RELEVANT = {"systems and controls", "operational resilience", "outsourcing or third parties", "data protection or security",
                "financial crime controls", "governance", "regulatory reporting"}
    internal = {x.id: json.loads(x.answer)["verdict"] for x in answers("internal").itertuples() if x.answer}
    internal2 = {x.id: json.loads(x.answer)["verdict"] for x in answers("internal2").itertuples() if x.answer}
    out = []
    for x in answers("news2").itertuples():
        if x.id not in N.index or not x.answer:
            continue
        st = N.loc[x.id]
        for k, o in enumerate(json.loads(x.answer)["organisations"]):
            et = o["event_type"]
            dt, prec = real_date(o["event_date"], st.seendate)
            # v5 item 4 (Tom, 13 Nov 2026): dated from when the event happened or was announced, never a planned
            # future date; if the only date is after publication, the publication date is used
            if dt and dt > st.seendate[:10]:
                dt, prec = st.seendate[:10], "publication date (event date given was in the future)"
            pts, stype, why = 0, "", ""
            if et == "none":
                why = "no counted event"
            elif o["confidence"] == "low":                       # v5 item 3: low-confidence readings score 0
                why = "read with low confidence"
            elif not o["credited_correctly"]:
                why = "event happened to a different organisation"
            elif not o["uk_or_ireland"]:
                why = "not about the UK or Irish business (UK and Ireland test)"
            elif et in INC:
                if dt and dt < SIX:
                    why = "event older than 6 months"
                else:
                    pts, stype = 2, INC[et]
            elif et == "merger, acquisition or separation":
                # v5 item 1: a deal between units of the same group scores 0 (a demerger splits the group, so it keeps
                # its v4 score of 3)
                # v6 item 3: integrating or legally transferring a business acquired in the last 24 months is a merger
                # signal (3); reorganisations between long-standing units still score 0
                if (internal.get(f"{x.id}_{k}") == "internal (same group)" and o["deal_role"] != "demerging or being broken up"
                        and internal2.get(f"{x.id}_{k}") == "integration of a recent acquisition"):
                    pts, stype = 3, "merger, acquisition or separation (news: integrating a recent acquisition)"
                elif internal.get(f"{x.id}_{k}") == "internal (same group)" and o["deal_role"] != "demerging or being broken up":
                    why = "deal scores 0: between long-standing units of the same group"
                elif o["deal_role"] in BIG:
                    pts, stype = 3, f"merger, acquisition or separation (news: {o['deal_role']})"
                elif o["deal_role"] == "acquiring a smaller bolt-on":
                    pts, stype = 1, "merger, acquisition or separation (news: smaller bolt-on)"
                else:
                    why = f"deal scores 0: {o['deal_role']}"
            elif et == "regulatory enforcement":
                if not o["regulator_uk_or_ireland"]:
                    why = f"regulator not UK or Irish ({o['regulator']})"
                elif o["area"] not in RELEVANT:
                    why = f"enforcement scores 0: {o['area']}"
                else:
                    pts, stype = 4, f"regulatory enforcement (news: {o['area']})"
            gid, eid, how = mt.match(o["name"]) if (o["name"] and et != "none") else ("", "", "")
            out.append(dict(story_id=x.id, org_key=f"{x.id}_{k}", title=st.title, domain=st.domain, seendate=st.seendate[:10],
                            url=st.url, body=st.body[:600], organisation=o["name"], event_type=et,
                            credited_correctly=o["credited_correctly"], uk_or_ireland=o["uk_or_ireland"],
                            deal_role=o["deal_role"], deal_value_gbp_m=o["deal_value_gbp_m"], regulator=o["regulator"],
                            regulator_uk_or_ireland=o["regulator_uk_or_ireland"], area=o["area"], confidence=o["confidence"],
                            event_date=dt, date_precision=prec, model_reason=o["reason"], points=pts, signal_type=stype,
                            scores_0_because=why, group_id=gid, entity_id=eid, match=how if gid else "",
                            review=how if (pts and o["name"] and not gid) else ""))
            if gid and pts:
                sig.append(dict(group_id=gid, entity_id=eid, signal_type=stype, kind="trigger", date=dt,
                                source=f"{st.domain} (news)", source_link=st.url,
                                detail=f"{st.title} [{o['confidence']} confidence; {o['reason']}]"[:400], slice="B"))
                # peer source events: cyber or data events and supplier failures (not outages), high confidence
                if et in ("cyber attack, data breach or ransomware", "supplier or service provider failure") and o["confidence"] == "high":
                    incidents.append(dict(victim_group=gid, date=dt, victim=o["name"], confirmed_by_news=st.url,
                                          link=st.url, how=f"news: {et} (high confidence)"))
            elif pts and o["name"]:
                rev.append(dict(source="Slice B: news", item=o["name"], reason=how, source_link=st.url))
    NM = pd.DataFrame(out)
    NM.to_csv(INTERIM / "news_matched.csv", index=False)
    news_incident = {}
    for i in incidents:
        news_incident.setdefault(i["victim_group"], i["link"])

    # ---------------------------------------------------------------- Item 3: ransomware.live
    f = INTERIM / "ransomware_victims.csv"
    if f.exists():
        V = pd.read_csv(f, dtype=str).fillna("")
        out = []
        for x in V.itertuples():
            name = re.sub(r"\s*\(.*?\)\s*", " ", x.victim).strip()
            if re.fullmatch(r"[\w.-]+\.[a-z]{2,}(\.[a-z]{2})?", name.lower()):
                gid, eid, how = "", "", "victim named only by a web address"
            else:
                gid, eid, how = mt.match(name)
            out.append(dict(victim_id=x.victim_id, victim=x.victim, website=x.website, country=x.country, sector=x.sector,
                            ransomware_group=x.ransomware_group, date=x.date, attack_date=x.attack_date,
                            discovered=x.discovered, press=x.press, permalink=x.permalink,
                            group_id=gid, entity_id=eid, match=how if gid else "", review="" if gid else how))
            if gid:
                sig.append(dict(group_id=gid, entity_id=eid, signal_type="claimed ransomware victim", kind="trigger",
                                date=x.date, source="ransomware.live (claim on a ransomware group's leak site)",
                                source_link=x.permalink,
                                detail=f"{x.victim} listed by {x.ransomware_group} on {x.date} (a claim, not confirmed)"
                                       + (f"; press: {x.press}" if x.press else ""), slice="C"))
                conf = news_incident.get(gid, "") or x.press
                if x.date >= SIX:                      # v4: peer source events within the last 6 months
                        incidents.append(dict(victim_group=gid, date=x.date, victim=x.victim, confirmed_by_news=conf,
                                          link=x.permalink, how="ransomware.live claim"))
            else:
                rev.append(dict(source="ransomware.live", item=x.victim, reason=how, source_link=x.permalink))
        pd.DataFrame(out).to_csv(INTERIM / "ransomware_matched.csv", index=False)

    # ---------------------------------------------------------------- peers (items 3 and 4)
    prow = []
    # one incident per victim group: its earliest date; named when any source is confirmed by news
    inc = {}
    for i in sorted(incidents, key=lambda i: i["date"] or "9999"):
        j = inc.setdefault(i["victim_group"], dict(i, how=set()))
        j["how"].add(i["how"])
        j["confirmed_by_news"] = j["confirmed_by_news"] or i["confirmed_by_news"]
    for i in inc.values():
        i["how"] = " + ".join(sorted(i["how"]))
        div, c, vname = GI.get(i["victim_group"], ("", "", ""))
        peers = [g for g in peers_by.get((div, c), []) if g != i["victim_group"]] if div else []
        applied = bool(peers) and len(peers) <= PEER_LIMIT
        prow.append(dict(victim_group=i["victim_group"], victim_group_name=vname, victim=i["victim"], date=i["date"],
                         how=i["how"], division=div, country=c, peers=len(peers), applied=applied,
                         reason="" if applied else ("no industry group" if not div else "no other group in the industry group"
                                                    if not peers else f"over the {PEER_LIMIT}-group limit"),
                         confirmed_by_news=i["confirmed_by_news"], link=i["link"]))
        if applied:
            named = bool(i["confirmed_by_news"])
            for g in peers:
                sig.append(dict(group_id=g, entity_id="", signal_type="peer incident", kind="trigger", date=i["date"],
                                source=i["how"], source_link=i["confirmed_by_news"] or i["link"],
                                detail=(f"peer: {vname} ({i['victim']}); confirmed by news: {i['confirmed_by_news']}" if named
                                        else f"a reported incident in your sector (industry group {div}, {c}); peer not confirmed by news")
                                       + f"; source: {i['how']}", slice="peer"))
    pd.DataFrame(prow).to_csv(INTERIM / "peer_incidents.csv", index=False)

    # ---------------------------------------------------------------- Item 6: careers sites (Irish groups)
    f = INTERIM / "careers_classified.csv"
    if f.exists():
        C = pd.read_csv(f, dtype=str).fillna("")
        to_type = {"third-party risk role": "third-party risk role", "security leader": "security leader",
                   "senior leader": "senior leader (procurement, risk, compliance)",
                   "wider role": "wider risk/compliance/procurement role", "operating change role": "operating change role"}
        for x in C.itertuples():
            mc = x.model_category or ""
            if mc in ("", "irrelevant"):
                continue
            sig.append(dict(group_id=x.group_id, entity_id="", signal_type=f"hiring: {to_type[mc]}", kind="trigger",
                            date=x.posted, source=f"careers site ({x.board})", source_link=x.link,
                            detail=f"\"{x.title}\" ({x.location}; {x.board} job feed; model: {mc} ({x.model_confidence}) - {x.model_reason})"[:400],
                            slice="careers"))

    # ---------------------------------------------------------------- v4 item 7: annual reports (1,000+ staff)
    f = INTERIM / "item7_results.csv"
    if f.exists():
        e = pd.read_csv(P["entities"], dtype=str).fillna("")
        egroup = dict(zip(e.entity_id, e.group_id))
        for x in pd.read_csv(f, dtype=str).fillna("").itertuples():
            if x.verdict in ("yes", "passing mention"):
                scan = x.quote_check.startswith("from scan")
                sig.append(dict(group_id=egroup.get(x.company, x.group_id), entity_id=x.company,
                                signal_type="principal risk named" if x.verdict == "yes" else "principal risk passing mention",
                                kind="need", date=x.made_up_to, source=f"{x.company_name} annual report {x.made_up_to[:4]}",
                                source_link=x.source_link,
                                detail=f"{x.risk_title}: \"{x.quote[:300]}\"" + (" (quote from scan, not word-checked)" if scan else ""),
                                slice="A"))

    S = pd.DataFrame(sig, columns=["group_id", "entity_id", "signal_type", "kind", "date", "source", "source_link",
                                   "detail", "slice"])
    S = S.drop_duplicates(["group_id", "signal_type", "date", "source_link"])
    S.to_csv(INTERIM / "stage2_signals.csv", index=False)
    pd.DataFrame(rev).to_csv(INTERIM / "stage2_review.csv", index=False)
    log("stage2", "signals", n=len(S), review=len(rev), **{f"slice_{k}": int(v) for k, v in S.slice.value_counts().items()})
    print(f"{len(S)} stage 2 signals, {len(rev)} to review")
    print(S.groupby(["slice", "signal_type"]).size().to_string() if len(S) else "")


if __name__ == "__main__":
    main()
