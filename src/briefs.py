"""Step 5b / Step 7: why-now briefs (Reference D) for the top Act now groups, written by Fable from each group's
matched, dated evidence. One Batch API call; its id is saved so it is never sent twice.

  python src/briefs.py estimate   # exact input tokens, projected cost; nothing sent
  python src/briefs.py send
  python src/briefs.py collect    # waits, then writes the briefs file (common.paths: briefs.csv / briefs_full.csv)

Format (Tom, 11 Nov 2026): four lines - what changed (date and source), why it matters (supplier visibility or
regulatory and audit exposure), angle to open on (a plain topic sentence, no citations), who to contact.
Reasons: need signals and triggers worth 2+ points only; share allotments, charges, board turnover and headcount
growth only when they are the group's only signals."""
import json
import sys
import time
from datetime import date

import pandas as pd

from common import INTERIM, log, paths, settings

ST = settings()
M = ST["models"]
P = paths()
BATCH = INTERIM / f"briefs_{P['scope']}_batch.json"

SYSTEM = """You write short why-now briefs for a sales team that sells third-party risk management (TPRM) software \
to large UK and Irish organisations. Each brief has exactly four parts, written only from the evidence given:

1. what_changed: the change, with its date and source.
2. why_it_matters: why it matters for third-party risk, framed around one of two things: not having a current view \
of suppliers, or regulatory and audit exposure.
3. angle: the angle to open on. One plain sentence describing the topic to raise with the account. It is not an \
email line: no greeting, no "I saw", no congratulations, no citations and no source names.
4. who_to_contact: where the signal is a new Senior Manager appointment on the FCA Register, the named person and \
their function. Otherwise the role most likely to own the issue (for example head of third-party risk, head of \
procurement, chief risk officer, CISO). Never invent a person's name.

Rules:
- Never open on saving time, replacing spreadsheets or consolidating tools.
- Cite a source for every claim in what_changed and why_it_matters only: put the source name and date in \
brackets, e.g. (FCA Register, 22 Oct 2026) or (Tesco PLC annual report 2025). Cite an annual report by company \
and year exactly as the evidence names it. Use only facts in the evidence. Do not add facts about the company \
from memory.
- No hype, and no claim the evidence does not support. Do not pretend to know why the change happened.
- A job advert is evidence that the organisation is hiring for that role, nothing more.
- Plain British English. what_changed and why_it_matters: one or two sentences each."""

SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["what_changed", "why_it_matters", "angle", "who_to_contact"],
          "properties": {k: {"type": "string"} for k in ["what_changed", "why_it_matters", "angle", "who_to_contact"]}}

MINOR = ("new funding", "new charge", "board turnover", "headcount growth")


def evidence(group_id, S):
    """Point 6: need signals and counted triggers worth 2+ points before decay. Minor triggers (allotments,
    charges, board turnover, headcount) only when nothing else is left."""
    sg = S[(S.group_id == group_id) & (S.counted == "True") & (S.value.astype(float) > 0)]
    keep = sg[(sg.kind == "need") | ((sg.points.astype(float) >= M["brief_min_trigger_points"])
                                     & ~sg.signal_type.str.startswith(MINOR))]
    sg = keep if len(keep) else sg
    sg = sg.sort_values(["kind", "value"], ascending=[False, False])
    lines = []
    for x in sg.itertuples():
        when = f"dated {x.date}" if x.date else "no date (standing status)"
        lines.append(f"- {x.signal_type} | {when} | source: {x.source} | entity: {x.entity_name} | {x.detail[:400]}")
    return "\n".join(lines)


def top_groups():
    T = pd.read_csv(P["ranked"], dtype=str).fillna("")
    return T[T.band == "Act now"].head(M["briefs_top_n"])


def requests_list():
    S = pd.read_csv(P["scored"], dtype=str).fillna("")
    top = top_groups()
    today = date.today().isoformat()
    reqs, ev = [], {}
    for i, g in enumerate(top.itertuples()):
        ev[g.group_id] = evidence(g.group_id, S)
        msg = (f"Account: {g.group_name} (sector: {g.sector or 'unknown'}, country: {g.country})\n"
               f"Today's date: {today}\nEvidence (each line is one signal, with its source and date):\n{ev[g.group_id]}")
        reqs.append(dict(custom_id=f"g{i:04d}", params=dict(
            model=M["briefs"], max_tokens=8000, system=SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": msg}])))
    return top, reqs, ev


def cost(tin, tout):
    pi, po = M["price"][M["briefs"]]
    return tin / 1e6 * pi + tout / 1e6 * po


def estimate():
    import anthropic
    client = anthropic.Anthropic()
    top, reqs, _ = requests_list()
    sample = reqs[:: max(1, len(reqs) // 15)][:15]
    tok = chars = 0
    for r in sample:
        p = r["params"]
        tok += client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                            output_config={"format": p["output_config"]["format"]}).input_tokens
        chars += len(p["system"]) + len(p["messages"][0]["content"])
    tin = sum(tok / chars * (len(r["params"]["system"]) + len(r["params"]["messages"][0]["content"])) for r in reqs)
    tout = M["briefs_assumed_output_tokens"] * len(reqs)
    est = dict(briefs=len(reqs), input_tokens=round(tin), output_tokens_assumed=tout, cost_usd=round(cost(tin, tout), 2),
               cost_per_brief_usd=round(cost(tin, tout) / max(1, len(reqs)), 4),
               cost_if_output_doubles_usd=round(cost(tin, 2 * tout), 2))
    log("briefs", "estimate", **est)
    print(json.dumps(est, indent=1))
    return est


def send():
    import anthropic
    if BATCH.exists():
        raise SystemExit(f"already sent: {json.loads(BATCH.read_text())['id']} - run collect")
    top, reqs, _ = requests_list()
    b = anthropic.Anthropic().messages.batches.create(requests=reqs)
    BATCH.write_text(json.dumps({"id": b.id, "requests": len(reqs), "groups": list(top.group_id),
                                 "date": date.today().isoformat()}))
    log("briefs", "batch_sent", id=b.id, n=len(reqs))
    print("sent", b.id, len(reqs))


def collect():
    import anthropic
    client = anthropic.Anthropic()
    meta = json.loads(BATCH.read_text())
    while (b := client.messages.batches.retrieve(meta["id"])).processing_status != "ended":
        print("waiting:", b.request_counts, flush=True)
        time.sleep(60)
    res = {r.custom_id: r for r in client.messages.batches.results(meta["id"])}
    top, _, ev = requests_list()
    if list(top.group_id) != meta["groups"]:
        print("note: the ranking changed since the batch was sent; briefs are kept for the groups they were written for")
    T = pd.read_csv(P["ranked"], dtype=str).fillna("").set_index("group_id")
    S = pd.read_csv(P["scored"], dtype=str).fillna("")
    rows = []
    for i, gid in enumerate(meta["groups"]):
        r = res[f"g{i:04d}"]
        g = T.loc[gid] if gid in T.index else None
        row = dict(rank=g["rank"] if g is not None else "", group_id=gid, group_name=g["group_name"] if g is not None else "",
                   band=g["band"] if g is not None else "", total=g["total"] if g is not None else "",
                   brief_date=meta.get("date", date.today().isoformat()), evidence=ev.get(gid) or evidence(gid, S))
        if r.result.type == "succeeded" and r.result.message.stop_reason != "refusal":
            m = r.result.message
            row.update(json.loads(next(x.text for x in m.content if x.type == "text")),
                       input_tokens=m.usage.input_tokens, output_tokens=m.usage.output_tokens,
                       cost_usd=cost(m.usage.input_tokens, m.usage.output_tokens))
        else:
            row.update(what_changed="", why_it_matters="", angle="", who_to_contact="", input_tokens=0, output_tokens=0,
                       cost_usd=0.0, note=f"no brief: {r.result.type} {getattr(getattr(r.result, 'message', None), 'stop_reason', '')}")
        rows.append(row)
    o = pd.DataFrame(rows)
    o.to_csv(P["briefs"], index=False)
    log("briefs", "done", scope=P["scope"], n=len(o), cost=round(o.cost_usd.sum(), 4),
        input_tokens=int(o.input_tokens.sum()), output_tokens=int(o.output_tokens.sum()))
    print(f"{len(o)} briefs, cost ${o.cost_usd.sum():.4f}")


if __name__ == "__main__":
    {"estimate": estimate, "send": send, "collect": collect}[sys.argv[1]]()
