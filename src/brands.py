"""Brand-to-group lookup (point 5): names on job adverts, CMA cases and the listed-company file that do not
match a company name exactly (e.g. "Amazon", "JPMorganChase", "Santander UK").

  python src/brands.py candidates   # Python proposes up to 8 candidate groups per name -> brand_candidates.json
  python src/brands.py estimate     # token count and cost of ONE Opus batch, before anything is sent
  python src/brands.py send         # send the batch (only after Tom's go-ahead)
  python src/brands.py collect      # fetch results -> data/interim/brand_lookup.csv

brand_lookup.csv is the table Tom reviews and corrects. Columns: name, sources, adverts, context, model_answer
(a group id, "none", "unsure" or "recruiter"), group_name, confidence, model_reason, tom_override.
tom_override wins when filled in (a group id, "none" or "recruiter"). "unsure" is never applied."""
import json
import re
import sys

import pandas as pd

from common import INTERIM, OUTPUT, RAW, ROOT, log, settings
from names import norm

LOOKUP = INTERIM / "brand_lookup.csv"
# Step 7 (point 14): "--full" extends the lookup to every unmatched employer with 2+ adverts not already in it.
# Those new rows are marked batch=step7 and only their high-confidence answers are applied.
FULL = "--full" in sys.argv
# Stage 2 item 4 (Tom, 12 Nov 2026): "--stage2" adds organisation names from 2+ news stories that matched no group;
# rows marked batch=stage2, high-confidence answers only (as Step 7).
STAGE2 = "--stage2" in sys.argv
FULL = FULL or STAGE2
TAG = "stage2" if STAGE2 else "step7" if FULL else "step3"
CANDS = INTERIM / ("brand_candidates_stage2.json" if STAGE2 else "brand_candidates_full.json" if FULL else "brand_candidates.json")
BATCH = INTERIM / ("brand_batch_stage2.json" if STAGE2 else "brand_batch_full.json" if FULL else "brand_batch.json")
MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 2.0, 10.0          # $ per million tokens, Batch API (Reference E)


OVERRIDES = ROOT / "corrections" / "brand_overrides.csv"     # Tom's corrections, kept in git


def table():
    """The lookup with Tom's corrections applied: column 'final' = what is used."""
    # a fresh copy of the project has no data/interim yet: start from the shared table in reference/ (names and
    # the group each maps to; the advert and news text behind each answer is not shared)
    src = LOOKUP if LOOKUP.exists() else ROOT / "reference" / "brand_lookup.csv"
    if not src.exists():
        return pd.DataFrame(columns=["name", "final"])
    t = pd.read_csv(src, dtype=str).fillna("")
    ov = pd.read_csv(OVERRIDES, dtype=str, keep_default_na=False) if OVERRIDES.exists() else pd.DataFrame(columns=["name", "override", "note"])
    o = dict(zip(ov.name, ov.override)); notes = dict(zip(ov.name, ov.note))
    extra = [n for n in ov.name if n not in set(t.name)]          # override names that were never lookup rows
    if extra:
        t = pd.concat([t, pd.DataFrame({"name": extra, "sources": "Tom's correction", "model_answer": ""})]).fillna("")
    t["tom_override"] = [o.get(n, x) for n, x in zip(t.name, t.tom_override)]
    t["override_note"] = t.name.map(notes).fillna("")
    if "batch" not in t:
        t["batch"] = ""
    t["batch"] = t.batch.fillna("")
    # point 14: a Step 7 model answer is applied only at high confidence (medium / low are listed for Tom)
    t["final"] = [(x.strip() or ("" if b == "step7" and c != "high" else m.strip()))
                  for x, m, b, c in zip(t.tom_override, t.model_answer, t.batch.replace("stage2", "step7"), t.confidence)]
    return t


def lookup():
    """normalised name -> group id (Tom's override first, then the model's pick; never 'unsure')."""
    t = table()
    canon = {i: ids[0] for ids in settings()["grouping"].get("merges", []) for i in ids}   # merged ids -> kept id
    return {norm(n): canon.get(f, f) for n, f in zip(t.name, t.final) if f and f.lower() not in ("none", "unsure", "recruiter")}


def recruiters():
    """normalised names the lookup marks as recruiters / job boards."""
    t = table()
    return {norm(n) for n, f in zip(t.name, t.final) if f.lower() == "recruiter"}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s)


def names_to_resolve():
    from jobs import core   # noqa
    rows = {}
    if STAGE2:
        n = pd.read_csv(INTERIM / "news_matched.csv", dtype=str).fillna("")
        n = n[n.review.isin(["not in the universe"]) | n.review.str.startswith("name matches")]
        for name, ex in n.groupby(n.organisation.map(norm)):
            if ex.story_id.nunique() >= 2 and name:
                rows[name] = dict(name=ex.organisation.iloc[0], sources={"news stories"}, adverts=int(ex.story_id.nunique()),
                                  context=[f"{t} ({e})" for t, e in zip(ex.title[:3], ex.event_type[:3])])
        return list(rows.values())

    def add(name, source, context, n=0):
        k = norm(name)
        if not k:
            return
        r = rows.setdefault(k, dict(name=name, sources=set(), context=[], adverts=0))
        r["sources"].add(source)
        r["adverts"] += n
        if context and len(r["context"]) < 4:
            r["context"].append(context)

    j = pd.read_csv(INTERIM / "job_adverts.csv", dtype=str).fillna("")
    ni = j[j.review_reason == "employer not in the universe"]
    counts = ni.employer.value_counts()
    for emp in counts[counts >= 2].index:
        ex = ni[ni.employer == emp].head(3)
        add(emp, "job adverts (employer not in list)", "; ".join(f"'{t}' ({loc})" for t, loc in zip(ex.title, ex.location)),
            int(counts[emp]))
    amb = j[j.review_reason.str.startswith("employer name matches")]
    for emp, ex in amb.groupby("employer"):
        add(emp, "job adverts (name matches 2 groups)", "; ".join(f"'{t}' ({loc})" for t, loc in zip(ex.title[:3], ex.location[:3])),
            len(ex))
    c = pd.read_csv(INTERIM / "cma_review.csv", dtype=str).fillna("")
    for r in c.itertuples():
        add(r.party, "CMA case party", f"{r.role} in CMA case '{r.case}'")
    s = pd.read_csv(INTERIM / "scanner_review.csv", dtype=str).fillna("")
    raw = pd.read_excel(RAW / "scanner" / settings()["scanner"]["file"].split("/")[-1], sheet_name="Results", dtype=str).fillna("")
    ind = dict(zip(raw.company, raw.industry))
    for r in s[s.verdict.isin(["yes", "passing mention"]) & s.reason.str.startswith(("no company", "name matches"))].itertuples():
        add(r.company, "listed company", f"UK-listed company, ticker {r.ticker}, industry {ind.get(r.company, '')}")
    return list(rows.values())


def candidates():
    from jobs import core
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    texts = []          # (core, squashed, group_id)
    for r in g.itertuples():
        for t in (r.entity_name, r.parent_name):
            c = core(re.sub(r"\(.*?\)", "", t))
            if c:
                texts.append((c, squash(c), r.group_id))
    info = g.groupby("group_id").agg(group_name=("group_name", "first"), size=("entity_id", "size"),
                                     parent=("parent_name", "first"),
                                     members=("entity_name", lambda s: list(s)[:4]))
    out = []
    known = set(pd.read_csv(LOOKUP, dtype=str).fillna("").name.map(norm)) if FULL and LOOKUP.exists() else set()
    for n in names_to_resolve():
        if norm(n["name"]) in known:
            continue
        qc = core(n["name"]); qs = squash(qc); qt = set(qc.split())
        if not qc:
            continue
        best = {}
        for c, sq, gid in texts:
            if c == qc:
                sc = 3
            elif c.startswith(qc + " ") or qc.startswith(c + " "):
                sc = 2.5
            elif len(qs) >= 4 and len(sq) >= 4 and (qs in sq or sq in qs):
                sc = 2
            else:
                ct = set(c.split())
                sc = 1 if qt and len(qt & ct) / len(qt | ct) >= 0.5 else 0
            if sc and sc > best.get(gid, 0):
                best[gid] = sc
        top = sorted(best, key=lambda x: (-best[x], -int(info.loc[x, "size"])))[:8]
        n["sources"] = sorted(n["sources"])
        n["candidates"] = [dict(group_id=x, group_name=info.loc[x, "group_name"], parent=info.loc[x, "parent"],
                                members=info.loc[x, "members"], entities=int(info.loc[x, "size"])) for x in top]
        out.append(n)
    CANDS.write_text(json.dumps(out, indent=1))
    withc = sum(1 for n in out if n["candidates"])
    print(f"{len(out)} names; {withc} have at least one candidate group; {len(out) - withc} have none (no model call)")
    for k in ("job adverts (employer not in list)", "job adverts (name matches 2 groups)", "CMA case party", "listed company"):
        print(f"  {k}: {sum(1 for n in out if k in n['sources'])}")


SYSTEM = """You match an organisation name, as it appears on a UK job advert, a CMA merger case, a news story or a \
stock-exchange listing, to the corporate group it belongs to, from a short list of candidate groups built from Companies House \
records. Answer with one candidate group_id only when you are confident the name refers to that group (the same \
business or brand, e.g. "Amazon" -> the Amazon.com group, "Santander UK" -> the Banco Santander group). \
Answer "recruiter" when the name is a recruitment agency, staffing firm, job board or headhunter advertising for \
clients. Answer "none" when it is a real employer but none of the candidates is it. Answer "unsure" when it could \
be a candidate but you cannot tell. A similar-looking name is not enough: shared words like "Capital", "Group" or \
a surname do not make a match."""


def prompt(n):
    lines = [f"Name: {n['name']}", f"Where seen: {', '.join(n['sources'])}"]
    if n["context"]:
        lines.append("Context: " + " | ".join(n["context"]))
    lines.append("Candidate groups:")
    for c in n["candidates"]:
        par = f"; owned by {c['parent']}" if c["parent"] else ""
        lines.append(f"- {c['group_id']}: {c['group_name']} ({c['entities']} entities{par}; members include "
                     f"{', '.join(c['members'])})")
    return "\n".join(lines)


def schema(n):
    return {"type": "object", "additionalProperties": False, "required": ["answer", "confidence", "reason"],
            "properties": {"answer": {"type": "string", "enum": [c["group_id"] for c in n["candidates"]] +
                                      ["none", "unsure", "recruiter"]},
                           "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                           "reason": {"type": "string"}}}


def requests_list():
    names = [n for n in json.loads(CANDS.read_text()) if n["candidates"]]
    reqs = []
    for i, n in enumerate(names):
        reqs.append(dict(custom_id=f"b{i:04d}", params=dict(
            model=MODEL, max_tokens=4000, system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema(n)}},
            messages=[{"role": "user", "content": prompt(n)}])))
    return names, reqs


def estimate():
    import anthropic
    client = anthropic.Anthropic()
    names, reqs = requests_list()
    # count input tokens exactly on a sample of 20 (free endpoint), scale by characters for the rest
    sample = reqs[:: max(1, len(reqs) // 20)][:20]
    tok = chars = 0
    for r in sample:
        p = r["params"]
        c = client.messages.count_tokens(model=MODEL, system=p["system"], messages=p["messages"])
        tok += c.input_tokens
        chars += len(p["system"]) + len(p["messages"][0]["content"])
    per_char = tok / chars
    total_in = sum(per_char * (len(r["params"]["system"]) + len(r["params"]["messages"][0]["content"])) for r in reqs)
    out_per = 350           # answer JSON (~60 tokens) + thinking at low effort (assumed ~300)
    total_out = out_per * len(reqs)
    cost = total_in / 1e6 * PRICE_IN + total_out / 1e6 * PRICE_OUT
    est = dict(requests=len(reqs), input_tokens=round(total_in), avg_input_per_request=round(total_in / len(reqs)),
               assumed_output_per_request=out_per, cost_usd=round(cost, 2), cost_per_item_usd=round(cost / len(reqs), 4),
               cost_if_output_doubles_usd=round(total_in / 1e6 * PRICE_IN + 2 * total_out / 1e6 * PRICE_OUT, 2))
    log("brands", "estimate", **est)
    print(json.dumps(est, indent=1))


def send():
    import anthropic
    client = anthropic.Anthropic()
    names, reqs = requests_list()
    if BATCH.exists():
        raise SystemExit(f"a batch was already sent: {json.loads(BATCH.read_text())['id']} - run collect")
    b = client.messages.batches.create(requests=reqs)
    BATCH.write_text(json.dumps({"id": b.id, "requests": len(reqs)}))
    log("brands", "batch_sent", id=b.id, requests=len(reqs))
    print("sent batch", b.id, len(reqs), "requests")


def collect():
    import anthropic
    client = anthropic.Anthropic()
    bid = json.loads(BATCH.read_text())["id"]
    b = client.messages.batches.retrieve(bid)
    if b.processing_status != "ended":
        print("still", b.processing_status, b.request_counts); return
    names, reqs = requests_list()
    by_id = {f"b{i:04d}": n for i, n in enumerate(names)}
    rows, tin, tout = {}, 0, 0
    for res in client.messages.batches.results(bid):
        n = by_id[res.custom_id]
        row = dict(name=n["name"], sources="; ".join(n["sources"]), adverts=n["adverts"], context=" | ".join(n["context"]),
                   candidates="; ".join(f"{c['group_id']} {c['group_name']}" for c in n["candidates"]))
        if res.result.type == "succeeded":
            m = res.result.message
            tin += m.usage.input_tokens; tout += m.usage.output_tokens
            if m.stop_reason == "refusal":
                row.update(model_answer="unsure", confidence="", model_reason="model declined")
            else:
                d = json.loads(next(x.text for x in m.content if x.type == "text"))
                row.update(model_answer=d["answer"], confidence=d["confidence"], model_reason=d["reason"])
        else:
            row.update(model_answer="unsure", confidence="", model_reason=f"batch result {res.result.type}")
        rows[res.custom_id] = row
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    gname = dict(zip(g.group_id, g.group_name))
    no_cand = [dict(name=n["name"], sources="; ".join(n["sources"]), adverts=n["adverts"], context=" | ".join(n["context"]),
                    candidates="", model_answer="none", confidence="", model_reason="no candidate group found by Python")
               for n in json.loads(CANDS.read_text()) if not n["candidates"]]
    t = pd.DataFrame(list(rows.values()) + no_cand)
    t["group_name"] = t.model_answer.map(gname).fillna("")
    t["tom_override"] = ""
    t["batch"] = TAG
    t = t[["name", "sources", "adverts", "model_answer", "group_name", "confidence", "model_reason", "context",
           "candidates", "tom_override", "batch"]].sort_values(["model_answer", "name"])
    if FULL:                 # append to the reviewed Step 3 table; never overwrite it
        old = pd.read_csv(LOOKUP, dtype=str).fillna("")
        old["batch"] = old.get("batch", pd.Series("", index=old.index)).replace("", "step3")
        old = old[old.batch != TAG]
        t = pd.concat([old, t]).fillna("")
    elif LOOKUP.exists():    # keep any corrections Tom already made
        old = pd.read_csv(LOOKUP, dtype=str).fillna("")
        t["tom_override"] = t.name.map(dict(zip(old.name, old.tom_override))).fillna("")
    t.to_csv(LOOKUP, index=False)
    cost = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
    log("brands", "batch_collected", id=bid, input_tokens=tin, output_tokens=tout, cost_usd=round(cost, 2))
    print(f"input {tin}, output {tout} tokens, cost ${cost:.2f}")
    print(t.model_answer.where(t.model_answer.isin(["none", "unsure", "recruiter"]), "matched a group").value_counts().to_string())


if __name__ == "__main__":
    {"candidates": candidates, "estimate": estimate, "send": send, "collect": collect}[sys.argv[1]]()
