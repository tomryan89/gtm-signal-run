"""Job adverts from Reed and Adzuna, matched by title keyword (Reference B) and employer name.

  python src/jobs.py pull     # download every advert whose title could match; dated the day pulled
  python src/jobs.py match    # classify titles, drop recruiter adverts to review, attach to universe entities

Raw pages: data/raw/jobs/<pull date>/<source>/<query>_<page>.json  (never fetched twice; resumable)
Output: data/interim/job_adverts.csv (every keyword-matching advert, with its match) + job_review.csv"""
import json
import os
import re
import sys
import time
from datetime import date

import pandas as pd
import requests

from common import INTERIM, OUTPUT, RAW, log, settings
from names import norm

ST = settings()
J, K = ST["jobs"], ST["keywords"]
E = os.environ


def queries():
    terms = all_terms()
    out = []
    for t in terms:   # "third-party" ~ "third party"; skip terms already covered by a shorter term (e.g. "security risk" by "risk")
        t = t.replace("-", " ") if t == "third-party" else t
        if t not in out:
            out.append(t)
    # a term containing another whole term is already covered by that term's search (supplier risk -> risk)
    return [t for t in out if not any(o != t and has(t, o) for o in out)]


def pull_dir():
    d = RAW / "jobs"
    days = sorted(p.name for p in d.glob("20*")) if d.exists() else []
    return d / (days[-1] if days and "--new" not in sys.argv else date.today().isoformat())


def slug(q):
    return re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")


class Paced:
    def __init__(self, gap, cap, name):
        self.gap, self.cap, self.name, self.last, self.n = gap, cap, name, 0.0, 0

    def get(self, url, **kw):
        if self.n >= self.cap:
            raise SystemExit(f"{self.name}: reached the call cap ({self.cap}) set in settings.toml - stopping, rerun resumes")
        for attempt in range(5):
            w = self.gap - (time.time() - self.last)
            if w > 0:
                time.sleep(w)
            self.last = time.time()
            self.n += 1
            r = requests.get(url, timeout=60, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                log(self.name, "rate_limit_pause" if r.status_code == 429 else "server_error", status=r.status_code)
                time.sleep(60 * (attempt + 1)); continue
            if r.status_code in (401, 403):
                raise SystemExit(f"{self.name} rejected the key ({r.status_code}); check .env")
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"{self.name}: gave up on {url}")


def pull():
    base = pull_dir()
    az = Paced(J["adzuna_min_gap_seconds"], J["adzuna_max_calls"], "adzuna")
    rd = Paced(J["reed_min_gap_seconds"], J["reed_max_calls"], "reed")
    for q in queries():
        # Adzuna: title-only search, 50 a page
        page = 1
        while True:
            f = base / "adzuna" / f"{slug(q)}_{page}.json"
            if f.exists():
                d = json.loads(f.read_text())
            else:
                d = az.get(f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}",
                           params={"app_id": E["ADZUNA_APPLICATION_KEY"], "app_key": E["ADZUNA_API_KEY"],
                                   "title_only": q, "results_per_page": 50})
                f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d))
                log("adzuna", "page", q=q, page=page, n=len(d.get("results", [])), count=d.get("count"))
            if len(d.get("results", [])) < 50:
                break
            page += 1
        reed_pages(base, rd, q)
        print(f"  {q:35s} adzuna calls {az.n:4d}  reed calls {rd.n:4d}", flush=True)
    log("jobs", "pull_done", dir=str(base), adzuna_calls=az.n, reed_calls=rd.n)


def all_terms():
    return (K["tprm"] + K["security_leader_exact"] + K["security_leader_area"] + K["wider_area"] + K["operating_change"]
            + K["senior_leader_exact"] + K["senior_leader_area"])


def reed_pages(base, rd, q, depth=0):
    """Reed: whole-text search, 100 a page. Reed stops at reed_max_results, so a bigger search is split into
    q + each seniority word, plus every keyword phrase containing q. A scoring title with q must contain one
    of those (Reference B), so nothing that could score is lost."""
    q = J["reed_query_overrides"].get(q, q)
    first = base / "reed" / f"{slug(q)}_1.json"
    if first.exists():
        total = json.loads(first.read_text()).get("totalResults", 0)
    else:
        total = None
    if total is None:
        d = rd.get("https://www.reed.co.uk/api/1.0/search", auth=(E["REED_API_KEY"], ""),
                   params={"keywords": q, "resultsToTake": 100, "resultsToSkip": 0})
        first.parent.mkdir(parents=True, exist_ok=True); first.write_text(json.dumps(d))
        total = d.get("totalResults", 0)
    if total > J["reed_max_results"] and depth == 0:
        subs = [f"{q} {w}" for w in dict.fromkeys(K["wider_seniority"] + K["security_leader_seniority"])]
        subs += [t for t in all_terms() if t != q and has(t, q)]
        log("reed", "split_search", q=q, total=total, into=subs)
        for sq in subs:
            reed_pages(base, rd, sq, 1)
        return
    if True:
        skip = 0
        while True:
            f = base / "reed" / f"{slug(q)}_{skip // 100 + 1}.json"
            if f.exists():
                d = json.loads(f.read_text())
            else:
                d = rd.get("https://www.reed.co.uk/api/1.0/search", auth=(E["REED_API_KEY"], ""),
                           params={"keywords": q, "resultsToTake": 100, "resultsToSkip": skip})
                f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d))
                log("reed", "page", q=q, skip=skip, n=len(d.get("results", [])), total=d.get("totalResults"))
            if len(d.get("results", [])) < 100:
                break
            skip += 100
            if skip >= J["reed_max_results"]:
                log("reed", "truncated", q=q, total=total)   # a split search still over the cap: keep the first 10,000
                break


# ------------------------------------------------------------------ classify (Reference B)
def has(title, term):
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", title) is not None


def classify(title):
    t = re.sub(r"\s+", " ", (title or "").lower())
    t2 = t.replace("-", " ")
    if any(has(t, k) or has(t2, k.replace("-", " ")) for k in K["tprm"]):
        return "third-party risk role", 4
    lead = any(has(t, k) for k in K["security_leader_seniority"])
    if any(has(t, k) for k in K["security_leader_exact"]) or (lead and any(has(t, a) for a in K["security_leader_area"])):
        return "security leader", 4
    if any(has(t, k) for k in K["senior_leader_exact"]) or (
            any(has(t, s) for s in K["senior_leader_seniority"]) and any(has(t, a) for a in K["senior_leader_area"])):
        return "senior leader (procurement, risk, compliance)", 3
    if any(has(t, a) for a in K["wider_area"]) and any(has(t, s) for s in K["wider_seniority"]):
        return "wider risk/compliance/procurement role", 2
    if any(has(t, k) for k in K["operating_change"]):
        return "operating change role", 2
    return None, 0


def core(name):
    stop = set(J["employer_suffix_words"])
    toks = [t for t in norm(name).split() if t not in stop]
    return " ".join(toks)


def is_recruiter(employer, text):
    e, x = (employer or "").lower(), (text or "").lower()
    if not e.strip():
        return "no employer name"
    if any(has(e, w) for w in J["job_boards"]):
        return "job board or recruiter"
    if any(has(e, w) for w in J["recruiter_name_words"]):
        return "employer name looks like a recruiter"
    if any(p in x for p in J["recruiter_text_phrases"]):
        return "advert text says it is placed for a client"
    return None


def reed_date(d):
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else (d or "")


def load_adverts(base):
    pulled = base.name
    rows = []
    for f in sorted((base / "adzuna").glob("*.json")):
        for a in json.loads(f.read_text()).get("results", []):
            rows.append(dict(source="Adzuna", advert_id=f"AZ{a.get('id')}", title=a.get("title", ""),
                             employer=(a.get("company") or {}).get("display_name", ""), text=a.get("description", ""),
                             location=(a.get("location") or {}).get("display_name", ""), posted=a.get("created", "")[:10],
                             link=a.get("redirect_url", ""), pulled_on=pulled))
    for f in sorted((base / "reed").glob("*.json")):
        for a in json.loads(f.read_text()).get("results", []):
            rows.append(dict(source="Reed", advert_id=f"RD{a.get('jobId')}", title=a.get("jobTitle", ""),
                             employer=a.get("employerName", ""), text=a.get("jobDescription", ""),
                             location=a.get("locationName", ""), posted=reed_date(a.get("date", "")),
                             link=a.get("jobUrl", ""), pulled_on=pulled))
    return pd.DataFrame(rows).drop_duplicates("advert_id")


def match():
    base = pull_dir()
    ads = load_adverts(base)
    ads[["category", "points"]] = ads.title.apply(lambda t: pd.Series(classify(t)))
    ads = ads[ads.category.notna()].copy()
    # the same advert on both boards: keep one (same employer + title + location)
    ads["dupkey"] = ads.employer.map(norm) + "|" + ads.title.str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    ads = ads.sort_values("source", ascending=False).drop_duplicates("dupkey")    # Reed first: it has full text
    ads["recruiter"] = [is_recruiter(e, x) or "" for e, x in zip(ads.employer, ads.text)]

    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    grp = dict(zip(g.entity_id, g.group_id))
    sic = {e: [x.strip() for x in re.split(r"[,;]", str(c)) if x.strip()] for e, c in zip(u.entity_id, u.industry_code)}
    exact, by_core = {}, {}
    for e in u.itertuples():
        exact.setdefault(norm(e.name), set()).add(e.entity_id)
        c = core(e.name)
        if c:
            by_core.setdefault(c, set()).add(e.entity_id)
    # group names also identify an account (e.g. advert "Amazon" -> group Amazon.com Inc)
    for gid, gname in g[["group_id", "group_name"]].drop_duplicates().itertuples(index=False):
        c = core(gname)
        if c and gid.startswith("FP:"):
            by_core.setdefault(c, set()).add(gid)

    from brands import lookup as brand_lookup, recruiters as brand_recruiters
    brand_map, brand_rec = brand_lookup(), brand_recruiters()
    out = []
    for a in ads.itertuples():
        r = a._asdict(); r.pop("Index"); r.pop("dupkey"); r.pop("text")
        if a.recruiter:
            out.append({**r, "match": "", "entity_id": "", "group_id": "", "review_reason": a.recruiter}); continue
        if any(has(a.employer.lower(), w) for w in ST["universe"]["public_name_flags"]):
            out.append({**r, "match": "", "entity_id": "", "group_id": "",
                        "review_reason": "employer looks like a public body"}); continue
        n = norm(a.employer)
        if n in brand_rec:
            out.append({**r, "recruiter": "recruiter (brand lookup)", "match": "", "entity_id": "", "group_id": "",
                        "review_reason": "recruiter or job board (brand lookup)"}); continue
        ids, how = exact.get(n), "exact name"
        if not ids:
            ids, how = by_core.get(core(a.employer)), "name without legal-form words"
        if (not ids or len({grp.get(i, i) for i in ids}) > 1) and n in brand_map:
            ids, how = {brand_map[n]}, "brand lookup"
        if not ids:
            out.append({**r, "match": "", "entity_id": "", "group_id": "", "review_reason": "employer not in the universe"}); continue
        groups = {grp.get(i, i) for i in ids}
        if len(groups) > 1:
            out.append({**r, "match": "", "entity_id": "", "group_id": "",
                        "review_reason": f"employer name matches {len(groups)} different groups"}); continue
        ent = sorted(i for i in ids if not i.startswith(("FP:", "UK:", "IE:", "SOLO:", "LISTED:")))
        if any(c.startswith(tuple(J["recruiter_industry_prefixes"])) for i in ids for c in sic.get(i, [])):
            out.append({**r, "recruiter": "employer is a recruitment company (industry code 78)", "match": "",
                        "entity_id": "", "group_id": "", "review_reason": "employer is a recruitment company (industry code 78)"})
            continue
        out.append({**r, "match": how, "entity_id": ent[0] if len(ent) == 1 else "", "group_id": groups.pop(), "review_reason": ""})
    o = pd.DataFrame(out)
    # point 4 (Tom, 11 Nov): duplicates again after matching - an employer name repeated at the end of the title
    # ("... - London Stock Exchange Group") is ignored, and brand variants mapped to one group (Citi, Citigroup)
    # are one employer
    gnames = dict(zip(g.group_id, g.group_name))

    def same_org(tail, employer, gid):
        c = core(tail)
        if not c:
            return False
        if c == core(employer) or (gid and c == core(gnames.get(gid, ""))):
            return True
        n = norm(tail)
        hit = exact.get(n) or by_core.get(c) or ({brand_map[n]} if n in brand_map else None)
        return bool(gid and hit and {grp.get(i, i) for i in hit} == {gid})

    def clean_title(t, employer, gid):
        t = re.sub(r"\s+", " ", (t or "").strip())
        m = re.match(r"^(.*\S)\s*(?:\s[-\u2013\u2014|]\s|\sat\s)\s*(\S.*)$", t)
        if m and same_org(m.group(2), employer, gid):
            t = m.group(1)
        return t.lower()

    o["title_clean"] = [clean_title(t, e, gid) for t, e, gid in zip(o.title, o.employer, o.group_id)]
    o["dupkey2"] = [(gid or norm(e)) + "|" + tc for gid, e, tc in zip(o.group_id, o.employer, o.title_clean)]
    before = len(o)
    o = o.sort_values("source", ascending=False).drop_duplicates("dupkey2").drop(columns=["dupkey2"])
    print(f"{before - len(o)} more duplicates removed after matching (employer name in title, brand variants)")
    o.to_csv(INTERIM / "job_adverts.csv", index=False)
    stats = dict(adverts_pulled=int(len(load_adverts(base))), keyword_matches=int(len(o)),
                 recruiter_or_no_employer=int((o.recruiter != "").sum()),
                 matched_to_group=int((o.group_id != "").sum()),
                 employer_not_in_universe=int((o.review_reason == "employer not in the universe").sum()),
                 ambiguous=int(o.review_reason.str.startswith("employer name matches").sum()))
    stats["share_no_named_employer"] = f"{stats['recruiter_or_no_employer'] / max(1, len(o)):.1%}"
    log("jobs", "match_done", **stats)
    print(json.dumps(stats, indent=1))
    print(o.category.value_counts().to_string())


if __name__ == "__main__":
    {"pull": pull, "match": match}[sys.argv[1]]()
