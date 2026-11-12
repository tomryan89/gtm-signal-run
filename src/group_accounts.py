"""Step 2: group entities into account groups (one per corporate family).

  python src/group_accounts.py fetch   # download ownership (PSC) records, resumable, ~2/s
  python src/group_accounts.py build   # build output/step2/groups.csv from the cached records

Rules (build instructions, Step 2):
  UK company  -> follow the controlling UK corporate owner upward until there is none; that top names the group.
  Top has a controlling foreign corporate owner -> group by the foreign owner's normalised name.
  No ownership record (e.g. listed company, society, overseas branch) -> its own top.
  Irish entities -> grouped by shared name stem, every Irish group flagged for review.
  Housing providers, universities, credit unions etc. without records -> group of one.
Never guess: when two owners have equal top-level control (a joint venture), we do not climb; we flag it."""
import json
import re
import sys
import time

import pandas as pd

import companies_house as ch
from common import OUTPUT, RAW, log, settings
from names import norm, norm_ch_number

OUT = OUTPUT / "step2"
G = settings()["grouping"]

MAJORITY = re.compile(G["majority_pattern"])


def majority(natures):
    """True if the owner holds more than 50% of shares, votes or (LLP) surplus assets (point 1)."""
    return any(MAJORITY.match(n or "") for n in natures or [])


def brand_word(name):
    toks = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    toks = [t for t in toks if t not in G["brand_skip_words"]]
    return toks[0] if toks else ""


def investor_reason(name, reg="", child=""):
    """Point 2: why this owner counts as an investor, or '' if it does not. Not an investor when the owner
    shares its first distinctive word with the company it owns (point 1, 11 Nov)."""
    if child and brand_word(name) and brand_word(name) == brand_word(child):
        return ""
    low = f" {(name or '').lower()} "
    company_form = re.search(r"(?<![a-z])(limited|ltd|plc|llp|llc|inc|gmbh|ag|s\.a\.|bv|b\.v\.)(?![a-z])", low)
    for w in G.get("state_owner_words", []):          # v4 item 6: governments and state bodies (not companies)
        if w in low and not company_form:
            return f"government or state body ('{w}')"
    lead = re.sub(r"^\s*(the\s+)?", "", low)
    for w in G["investor_sponsors"]:
        # a sponsor must START the owner's name ("Partners Group AG", not "Health Partners Group Limited")
        if re.match(rf"{re.escape(w)}(?![a-z0-9])", lead):
            return f"known financial sponsor ({w})"
    for w in G["investor_name_words"]:
        if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low):
            return f"name contains '{w}'"
    if reg:
        prof = ch.profile(reg) or {}
        codes = [c for c in prof.get("sic_codes") or [] if c in G["investor_codes"]]
        if codes:
            return f"industry code {codes[0]}"
    return ""


def psc(num):
    return ch.get(f"/company/{num}/persons-with-significant-control", "psc", num, params={"items_per_page": 100})


def resolve_by_name(name):
    """Exact-name lookup at Companies House. Returns a company number only if exactly one company
    has exactly this normalised name; otherwise None (never guess)."""
    target = norm(name)
    if not target:
        return None
    key = re.sub(r"[^a-z0-9]+", "_", target)[:120]
    d = ch.get("/search/companies", "search", key, params={"q": name, "items_per_page": 20})
    exact = [x for x in (d or {}).get("items", []) if norm(x.get("title")) == target]
    nums = {x["company_number"] for x in exact}
    if len(nums) == 1:
        return nums.pop()
    live = {x["company_number"] for x in exact if x.get("company_status") in ("active", "open", "registered")}
    return live.pop() if len(live) == 1 else None    # several exact names, but only one still active


def is_uk(ident):
    txt = " ".join(str(ident.get(k, "")) for k in ("country_registered", "place_registered", "legal_authority")).lower()
    return any(re.search(rf"\b{re.escape(w)}\b", txt) for w in G["uk_place_words"])


def controller(num):
    """Return (kind, info) for the majority (>50%) owner of a UK company:
       ('none', reason) | ('uk', (number, name)) | ('foreign', name) | ('other', name) | ('tie', names) |
       ('tie_uk', (names, regs))"""
    d = psc(num)
    if d is None:
        return "none", "no ownership record"
    items = [i for i in d.get("items", []) if not i.get("ceased_on") and not i.get("ceased")]
    if not items:
        return "none", "no current owner listed"
    leaders = [i for i in items if majority(i.get("natures_of_control"))]
    if not leaders:
        return "none", "no owner holds more than 50%"
    if len(leaders) > 1:
        if all(i.get("kind", "").startswith("individual") for i in leaders):
            return "none", "controlled by individuals"
        names = " / ".join(i.get("name", "?") for i in leaders)
        regs = []
        for i in leaders:
            ident = i.get("identification") or {}
            reg = norm_ch_number(ident.get("registration_number")) if i.get("kind", "").startswith("corporate") else ""
            if not (reg and is_uk(ident)):
                return "tie", names
            regs.append(reg)
        return "tie_uk", (names, sorted(set(regs)))
    i = leaders[0]
    kind = i.get("kind", "")
    if kind.startswith("corporate-entity"):
        ident = i.get("identification") or {}
        reg = norm_ch_number(ident.get("registration_number"))
        if is_uk(ident) and reg:
            return "uk", (reg, i.get("name", ""))
        if is_uk(ident):
            found = resolve_by_name(i.get("name", ""))
            if found:
                return "uk", (found, i.get("name", ""))
            return "other", f"{i.get('name')} (UK owner without a usable company number)"
        return "foreign", i.get("name", "")
    if kind.startswith("legal-person"):
        return "other", i.get("name", "")
    return "none", "controlled by an individual"


def climb(num, cache, depth=0):
    """Follow controlling UK corporate owners upward. Returns dict describing the group top."""
    path, seen = [num], {num}
    while True:
        cur = path[-1]
        if cur not in cache:
            cache[cur] = controller(cur)
        kind, info = cache[cur]
        # point 2: an investor owner ends the walk; the group is the company below it
        owner_names = ([info[1]] if kind == "uk" else [info] if kind in ("foreign", "other")
                       else info.split(" / ") if kind == "tie" else info[0].split(" / ") if kind == "tie_uk" else [])
        owner_regs = [info[0]] if kind == "uk" else []
        child = (ch.profile(cur) or {}).get("company_name", "")
        reasons = [investor_reason(n, owner_regs[0] if owner_regs else "", child) for n in owner_names]
        if owner_names and all(reasons):
            return dict(top=cur, path=path, end="", owner_kind="investor",
                        investor="; ".join(f"{n} ({r})" for n, r in zip(owner_names, reasons)))
        if kind == "tie_uk":
            # several UK companies share top control. If they all lead to the same top company, it is one
            # family holding through two vehicles - follow it. Otherwise it is a real joint venture.
            names, regs = info
            if any(r in seen for r in regs) or len(path) > G["max_chain"]:
                return dict(top=cur, path=path, end=names, owner_kind="tie")
            ends = {}
            for r in regs:
                c = climb(r, cache, depth + 1) if depth < 5 else None
                ends[r] = (c["top"], c["owner_kind"], c["end"]) if c else None
            if None not in ends.values() and len(set(ends.values())) == 1:
                nxt = regs[0]
                seen.add(nxt)
                path.append(nxt)
                continue
            return dict(top=cur, path=path, end=names, owner_kind="tie")
        if kind == "uk":
            nxt = info[0]
            if ch.profile(nxt) is None:
                # the owner's company number does not exist (a typo in the filing): use the exact name instead
                fixed = resolve_by_name(info[1])
                log("companies_house", "owner_number_invalid", child=cur, number=nxt, name=info[1], resolved=fixed)
                if not fixed:
                    return dict(top=cur, path=path, end=f"owner {info[1]} has an invalid company number {nxt}",
                                owner_kind="other")
                nxt = fixed
            if nxt in seen or len(path) > G["max_chain"]:
                return dict(top=cur, path=path, end="loop or chain too long", owner_kind="uk")
            seen.add(nxt)
            path.append(nxt)
            continue
        return dict(top=cur, path=path, end=info if isinstance(info, str) else "", owner_kind=kind)


# ------------------------------------------------------------------ fetch
def fetch():
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str)
    nums = u[(u.country == "UK") & (u.id_type == "Companies House")].entity_id.tolist()
    cache, t0, n_req = {}, time.time(), 0
    print(f"{len(nums)} UK companies to climb")
    for k, n in enumerate(nums, 1):
        climb(n, cache)
        if k % 500 == 0:
            el = time.time() - t0
            print(f"  {k}/{len(nums)} entities, {len(cache)} companies looked up, {el / 60:.0f} min", flush=True)
    log("companies_house", "psc_fetch_done", entities=len(nums), companies=len(cache), secs=round(time.time() - t0))
    print("done - now run: python src/group_accounts.py build")


# ------------------------------------------------------------------ build
def ie_stem(name):
    toks = norm(name).split()
    stop = set(G["ie_stem_stopwords"])
    toks = [t for t in toks if t not in stop]
    return " ".join(toks[:G["ie_stem_words"]])


def band_rank(size_band):
    """Larger pay gap staff band = higher rank; turnover bands and 'unconfirmed' rank 0."""
    bands = settings()["universe"]["min_staff_bands"]
    sb = (size_band or "").replace(" staff", "")
    if sb in bands:
        return bands.index(sb) + 1
    return 1 if sb == "250+" else 0


def is_holdco(name):
    low = (name or "").lower()
    return any(re.search(rf"\b{w}\b", low) for w in G["holdco_words"])


def bad_name(name):
    """Holdco-style or mostly-numbers name (point 1)."""
    n = name or ""
    if is_holdco(n):
        return True
    alnum = re.sub(r"[^A-Za-z0-9]", "", n)
    first = (n.split() or [""])[0]
    return bool(alnum) and (sum(c.isdigit() for c in alnum) / len(alnum) >= 0.4 or (first.isdigit() and len(first) >= 3))


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    cache, rows = {}, []
    names = dict(zip(u.entity_id, u.name))
    for e in u.itertuples():
        base = dict(entity_id=e.entity_id, entity_name=e.name, country=e.country, investor="", parent_name="")
        if e.country == "UK" and e.id_type == "Companies House":
            c = climb(e.entity_id, cache)
            top = c["top"]
            top_name = names.get(top) or next((cache[p][1][1] for p in c["path"][:-1] if cache[p][0] == "uk"
                                               and cache[p][1][0] == top), top)
            hops = len(c["path"]) - 1
            link = "ownership record" if hops else "single entity"
            row = {**base, "group_id": f"UK:{top}", "link": link, "top_uk_entity": f"{top} {top_name}",
                   "top_company_number": top, "hops": hops, "path": " > ".join(c["path"])}
            if c["owner_kind"] == "foreign":
                fp = cache[top][1]
                rows.append({**row, "group_id": f"FP:{norm(fp)}", "parent_name": fp, "link": "foreign parent name",
                             "detail": f"top UK company {top} is more than 50% owned by {fp}"})
            elif c["owner_kind"] == "investor":
                rows.append({**row, "investor": c["investor"],
                             "detail": f"walk stopped below investor: {c['investor']}"})
            elif c["owner_kind"] == "tie":
                rows.append({**row, "detail": f"joint control, not climbed: {c['end']}", "flag": "joint venture - check"})
            elif c["owner_kind"] == "other":
                rows.append({**row, "parent_name": c["end"], "detail": f"top owner is {c['end']}",
                             "flag": "owned by a non-company body - check"})
            else:
                rows.append({**row, "detail": c["end"]})
        elif e.country == "IE" and not e.entity_id.startswith("CU-"):
            st = ie_stem(e.name)
            rows.append({**base, "group_id": f"IE:{st}", "link": "name stem", "detail": f"stem '{st}'",
                         "flag": "Irish grouping unchecked"})
        else:
            rows.append({**base, "group_id": f"SOLO:{e.entity_id}", "link": "single entity",
                         "detail": "no ownership records for this kind of body"})
    g = pd.DataFrame(rows).astype(str).replace("nan", "")
    sizes = g.group_id.map(g.group_id.value_counts())
    ie1 = g.group_id.str.startswith("IE:") & (sizes == 1)
    g.loc[ie1, "link"] = "single entity"
    g.loc[ie1, "flag"] = ""
    # Tom's merges: same business split across groups (first id kept)
    g["merged_from"] = ""
    for ids in G.get("merges", []):
        missing = [i for i in ids if i not in set(g.group_id)]
        if missing:
            log("grouping", "merge_id_missing", ids=missing)
        sel = g.group_id.isin(ids)
        g.loc[sel, "merged_from"] = g.loc[sel, "group_id"]
        g.loc[sel, "group_id"] = ids[0]
    # entity moves Tom approved (merge proposals, Citibank UK): corrections/entity_moves.csv
    from common import ROOT
    mvf = ROOT / "corrections" / "entity_moves.csv"
    if mvf.exists():
        canon = {i: ids[0] for ids in G.get("merges", []) for i in ids}
        mv = pd.read_csv(mvf, dtype=str).fillna("")
        have = set(g.group_id)
        for x in mv.itertuples():
            to = canon.get(x.to_group, x.to_group)
            if to not in have or x.entity_id not in set(g.entity_id):
                log("grouping", "move_not_applied", entity=x.entity_id, to=x.to_group)
                continue
            sel = g.entity_id == x.entity_id
            g.loc[sel, "merged_from"] = g.loc[sel, "group_id"]
            g.loc[sel, "group_id"] = to
    # point 1 (11 Nov): foreign parent's name; else the top UK company's name; fall back to the largest pay gap
    # member when that name has a Bidco/Topco/Midco/Holdco/Finco/Borrower word or is mostly numbers
    band = dict(zip(u.entity_id, u.size_band))
    g["_band"] = g.entity_id.map(lambda x: band_rank(band.get(x, "")))
    g["_hold"] = g.entity_name.map(bad_name)
    g["_top"] = g.entity_id == g.get("top_company_number", "")
    g["_len"] = g.entity_name.str.len()
    g["_hops"] = pd.to_numeric(g.get("hops", 0), errors="coerce").fillna(99)
    fallback = g.sort_values(["group_id", "_band", "_hold", "_top", "_hops", "_len"],
                             ascending=[True, False, True, False, True, True]).drop_duplicates("group_id") \
        .set_index("group_id").entity_name
    names_out, how = {}, {}
    for gid, m in g.groupby("group_id"):
        fp = m[m.link == "foreign parent name"].parent_name
        cand, src = "", ""
        if gid.startswith("FP:") and len(fp):
            cand, src = fp.value_counts().index[0], "foreign parent"
        elif gid.startswith("UK:"):
            top = gid[3:]                      # a UK group's id is its top company
            cand = (ch.profile(top) or {}).get("company_name") or names.get(top) or ""
            src = "top UK company"
        if cand and not bad_name(cand):
            names_out[gid], how[gid] = cand, src
        else:
            names_out[gid] = fallback[gid]
            how[gid] = "largest pay gap member" + (f" ({src} name '{cand}' not used)" if cand else "")
    # full run review point 4: a group made up only of firms added from the PRA lists or as advert employers is
    # named after its regulated firm, not a holding company above it (several such firms: the largest by staff
    # band, then the shortest name)
    added = set(u[u.sources.str.fullmatch(r"(PRA list|advert employer on FCA Register)(; .*)?")].entity_id)
    for gid, m in g.groupby("group_id"):
        if len(m) and m.entity_id.isin(added).all() and names_out[gid] not in set(m.entity_name):
            pick = m.sort_values(["_band", "_len"], ascending=[False, True]).entity_name.iloc[0]
            how[gid] = f"regulated firm (PRA list / advert employer; owner '{names_out[gid]}' not used)"
            names_out[gid] = pick
    g["group_name"] = g.group_id.map(names_out)
    g["group_name_from"] = g.group_id.map(how)
    g = g.drop(columns=["_band", "_hold", "_top", "_len", "_hops"])
    g["group_size"] = g.group_id.map(g.group_id.value_counts())
    cols = ["entity_id", "entity_name", "country", "group_id", "group_name", "group_name_from", "group_size", "link",
            "top_uk_entity", "top_company_number", "hops", "path", "parent_name", "investor", "merged_from", "detail", "flag"]
    g = g.reindex(columns=cols).fillna("").sort_values(["group_size", "group_id", "entity_name"],
                                                         ascending=[False, True, True])
    g.to_csv(OUT / "groups.csv", index=False)
    big = g[g.group_size.astype(int) > G["large_group_check"]]
    big.to_csv(OUT / "large_groups.csv", index=False)

    uk = g[g.entity_id.isin(u[(u.country == "UK") & (u.id_type == "Companies House")].entity_id)]
    no_rec = sum(1 for n in uk.entity_id if cache.get(n, ("", ""))[0] == "none"
                 and cache[n][1] in ("no ownership record", "no current owner listed"))
    stats = {
        "entities": len(g), "groups": g.group_id.nunique(),
        "groups with more than 10 entities": int(big.group_id.nunique()),
        "UK companies": len(uk),
        "UK companies with no ownership record": f"{no_rec} ({no_rec / max(1, len(uk)):.1%})",
        "entities whose walk stopped below an investor": int((g.investor != "").sum()),
        "Irish groups": int(g[g.country == "IE"].group_id.nunique()),
        "linked by": g.link.value_counts().to_dict(),
        "flags": g.flag.value_counts().to_dict(),
        "companies looked up (incl. parents outside universe)": len(cache),
    }
    (OUT / "grouping_report.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1]]()
