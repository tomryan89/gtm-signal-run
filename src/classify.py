"""Step 5a / Step 7: classify keyword-matched job adverts with a model (Reference E). Opus only (Tom, 11 Nov 2026:
the Haiku first pass is dropped).

  python src/classify.py select     # every keyword-matched advert tied to a group in scope -> sample file
  python src/classify.py estimate   # exact input tokens (free count endpoint), projected cost; nothing sent
  python src/classify.py send       # one Opus batch (its id is saved, so it is never sent twice)
  python src/classify.py collect    # wait for the batch, then write the classified file

Files follow settings [run] scope (common.paths): pilot -> classify_sample.csv / job_classified.csv,
full -> classify_full_input.csv / job_classified_full.csv."""
import html
import json
import os
import re
import sys
import time

import pandas as pd
import requests

from common import INTERIM, RAW, log, paths, settings

ST = settings()
M = ST["models"]
P = paths()
BATCH = INTERIM / f"classify_{P['scope']}_batch.json"
CATS = ["third-party risk role", "security leader", "senior leader", "wider role", "operating change role", "irrelevant"]
RANK = {"third-party risk role": 4, "security leader": 4, "senior leader": 3, "wider role": 2,
        "operating change role": 2, "irrelevant": 0}
KEYWORD_TO_CAT = {"third-party risk role": "third-party risk role", "security leader": "security leader",
                  "senior leader (procurement, risk, compliance)": "senior leader",
                  "wider risk/compliance/procurement role": "wider role", "operating change role": "operating change role"}

SYSTEM = """You classify UK job adverts for a third-party risk management (TPRM) software sales team. Decide what \
the job really is, from the title and the advert text, using these categories:

- third-party risk role: the job is about managing risk from suppliers, vendors, outsourcing or third parties, \
including supplier assurance and third-party security.
- security leader: the most senior or second most senior information or cyber security role in the organisation.
- senior leader: head, director or chief-level owner of procurement, sourcing, compliance, enterprise or \
operational risk, GRC or operational resilience for the organisation or a major division.
- wider role: manager-level or above in those same functions (procurement, sourcing, compliance, enterprise or \
operational risk, GRC, operational resilience, internal audit, information or cyber security).
- operating change role: leading a procurement transformation or an ERP programme.
- irrelevant: roles where "risk" means credit, market, investment, fraud, pricing, underwriting, insurance loss \
control, clinical, project or health and safety risk; software engineering roles; sales or customer success roles; \
roles at consultancies, analyst firms or outsourcers that deliver risk or procurement work for clients; and anything \
where the function word is incidental to the job.

Rules:
- "Operational resilience" in a title counts as a third-party risk role only if the advert text mentions third \
parties, suppliers or outsourcing. Otherwise treat it as a wider or senior leader role by seniority.
- Supplier quality roles (product, manufacturing or food quality assurance of suppliers) are a wider role, not a \
third-party risk role.
- If the advert text is only company boilerplate and says nothing about the job, classify from the title alone, \
and never place it in a higher category than the keyword match did (the keyword match is given with each advert). \
Say whether the text describes the job in the field text_describes_job.
- Fixed-term and interim roles count the same as permanent ones.
- If the advert text is only a short snippet, judge from what is there; lower your confidence if it is not enough.

Return the category, your confidence (high, medium or low), whether the text describes the job, and one sentence \
of reason."""

SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["category", "confidence", "text_describes_job", "reason"],
          "properties": {"category": {"type": "string", "enum": CATS},
                         "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                         "text_describes_job": {"type": "boolean"},
                         "reason": {"type": "string"}}}


def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()


def reed_full(job_id):
    """Full advert text from Reed's job details endpoint, cached in data/raw/jobs/details/."""
    f = RAW / "jobs" / "details" / f"{job_id}.json"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            time.sleep(ST["jobs"]["reed_min_gap_seconds"])
            try:
                r = requests.get(f"https://www.reed.co.uk/api/1.0/jobs/{job_id}", auth=(os.environ["REED_API_KEY"], ""),
                                 timeout=60)
            except requests.RequestException as e:
                log("reed", "error", job=job_id, error=str(e)[:200]); time.sleep(10); continue
            if r.status_code == 429 or r.status_code >= 500:
                log("reed", "rate_limit_pause" if r.status_code == 429 else "server_error", status=r.status_code)
                time.sleep(60 * (attempt + 1)); continue
            f.write_text(r.text if r.ok else json.dumps({"_status": r.status_code}))
            log("reed", "job_details", job=job_id, status=r.status_code)
            break
        else:
            return ""
    d = json.loads(f.read_text())
    return clean(d.get("jobDescription", ""))


def select():
    from jobs import load_adverts, pull_dir
    G = pd.read_csv(P["groups"], dtype=str).fillna("")
    j = pd.read_csv(INTERIM / "job_adverts.csv", dtype=str).fillna("")
    pick = j[j.group_id.isin(G.group_id) & (j.review_reason == "")].copy()
    text = load_adverts(pull_dir()).set_index("advert_id").text.to_dict()
    full = []
    reed = pick.source.eq("Reed").sum()
    print(f"{len(pick)} adverts tied to a group; fetching full text for {reed} Reed adverts (cached)", flush=True)
    for k, a in enumerate(pick.itertuples(), 1):
        if a.source == "Reed":
            t = reed_full(a.advert_id[2:])
            full.append((t or clean(text.get(a.advert_id, "")), "Reed full advert" if t else "Reed snippet"))
        else:
            full.append((clean(text.get(a.advert_id, "")), "Adzuna snippet (no full-text API)"))
        if k % 200 == 0:
            print(f"  {k}/{len(pick)}", flush=True)
    pick["advert_text"] = [t[:3500] for t, _ in full]
    pick["text_source"] = [s for _, s in full]
    pick["group_name"] = pick.group_id.map(dict(zip(G.group_id, G.group_name)))
    pick.to_csv(P["sample"], index=False)
    log("classify", "selected", scope=P["scope"], adverts=len(pick))
    print(pick.text_source.value_counts().to_string())


def user_msg(a):
    return (f"Employer: {a.employer}\nTitle: {a.title}\nKeyword match on the title: {KEYWORD_TO_CAT.get(a.category, a.category)}\n"
            f"Location: {a.location}\nPosted: {a.posted}\nAdvert text ({a.text_source}):\n{a.advert_text}")


def requests_list():
    s = pd.read_csv(P["sample"], dtype=str).fillna("")
    return s, [dict(custom_id=f"a{i:05d}", params=dict(
        model=M["classify"], max_tokens=4000, system=SYSTEM,
        output_config={"effort": M["classify_effort"], "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": user_msg(a)}])) for i, a in enumerate(s.itertuples())]


def cost(model, tin, tout):
    pi, po = M["price"][model]
    return tin / 1e6 * pi + tout / 1e6 * po


def estimate():
    import anthropic
    client = anthropic.Anthropic()
    s, reqs = requests_list()
    sample = reqs[:: max(1, len(reqs) // 25)][:25]
    tok = chars = 0
    for r in sample:
        p = r["params"]
        tok += client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                            output_config={"format": p["output_config"]["format"]}).input_tokens
        chars += len(p["system"]) + len(p["messages"][0]["content"])
    tin = sum(tok / chars * (len(r["params"]["system"]) + len(r["params"]["messages"][0]["content"])) for r in reqs)
    tout = M["classify_assumed_output_tokens"] * len(reqs)
    c = cost(M["classify"], tin, tout)
    est = dict(adverts=len(reqs), input_tokens=round(tin), output_tokens_assumed=tout, cost_usd=round(c, 2),
               cost_per_advert_usd=round(c / max(1, len(reqs)), 5),
               cost_if_output_doubles_usd=round(cost(M["classify"], tin, 2 * tout), 2))
    log("classify", "estimate", **est)
    print(json.dumps(est, indent=1))
    return est


def send():
    import anthropic
    if BATCH.exists():
        raise SystemExit(f"already sent: {json.loads(BATCH.read_text())['id']} - run collect")
    s, reqs = requests_list()
    b = anthropic.Anthropic().messages.batches.create(requests=reqs)
    BATCH.write_text(json.dumps({"id": b.id, "requests": len(reqs)}))
    log("classify", "batch_sent", model=M["classify"], id=b.id, n=len(reqs))
    print(f"sent {M['classify']} batch {b.id} ({len(reqs)})")


def collect():
    import anthropic
    client = anthropic.Anthropic()
    bid = json.loads(BATCH.read_text())["id"]
    while (b := client.messages.batches.retrieve(bid)).processing_status != "ended":
        print("waiting:", b.request_counts, flush=True)
        time.sleep(60)
    s, _ = requests_list()
    res = {}
    for r in client.messages.batches.results(bid):
        if r.result.type != "succeeded":
            res[r.custom_id] = dict(category="", confidence="", text_describes_job="", reason=f"batch result {r.result.type}",
                                    tin=0, tout=0)
            continue
        m = r.result.message
        d = (dict(category="", confidence="", text_describes_job="", reason="model declined") if m.stop_reason == "refusal"
             else json.loads(next(x.text for x in m.content if x.type == "text")))
        res[r.custom_id] = {**d, "tin": m.usage.input_tokens, "tout": m.usage.output_tokens}
    rows = [res.get(f"a{i:05d}", dict(category="", confidence="", text_describes_job="", reason="no result", tin=0, tout=0))
            for i in range(len(s))]
    s["opus_category"] = [r["category"] for r in rows]
    s["model_confidence"] = [r["confidence"] for r in rows]
    s["text_describes_job"] = [r["text_describes_job"] for r in rows]
    s["model_reason"] = [r["reason"] for r in rows]
    s["input_tokens"] = [r["tin"] for r in rows]
    s["output_tokens"] = [r["tout"] for r in rows]
    # point 3: boilerplate-only text -> never above the keyword category
    final, capped = [], []
    for cat, desc, kw in zip(s.opus_category, s.text_describes_job, s.category):
        kc = KEYWORD_TO_CAT.get(kw, kw)
        if cat and desc is False and RANK.get(cat, 0) > RANK.get(kc, 0):
            final.append(kc); capped.append(True)
        else:
            final.append(cat); capped.append(False)
    s["model_category"] = final
    s["capped_at_keyword"] = capped
    s["sent_to_opus"] = True
    s["cost_usd"] = [cost(M["classify"], a, b) for a, b in zip(s.input_tokens, s.output_tokens)]
    s.to_csv(P["classified"], index=False)
    log("classify", "done", scope=P["scope"], n=len(s), capped=int(sum(capped)), cost=round(s.cost_usd.sum(), 4),
        input_tokens=int(s.input_tokens.sum()), output_tokens=int(s.output_tokens.sum()))
    print(f"{len(s)} adverts, cost ${s.cost_usd.sum():.4f}, {sum(capped)} capped at the keyword category")
    print(pd.crosstab(s.category, s.model_category).to_string())


if __name__ == "__main__":
    {"select": select, "estimate": estimate, "send": send, "collect": collect}[sys.argv[1]]()
