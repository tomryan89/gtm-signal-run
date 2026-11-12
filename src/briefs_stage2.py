"""Stage 2 item 7 (Tom, 12 Nov 2026): write or rewrite a brief for every group that is Act now after rescoring and
whose counted signals changed. Same four-part format and rules as briefs.py, plus:
  - a ransomware claim against the account itself never appears in "angle to open on"; it may appear in "why it
    matters", worded as a reported claim;
  - a peer incident may be the angle; the peer is named only when a news story confirms the incident, otherwise
    "a reported incident in your sector";
  - any brief whose evidence includes ransomware evidence (a claim, or a peer incident from ransomware.live) is
    written by Opus; the others by Fable (as before).

  python src/briefs_stage2.py select     # -> data/interim/briefs_stage2_groups.csv (which groups and why)
  python src/briefs_stage2.py estimate | send | collect   # collect merges into briefs_full.csv (old rows kept in the snapshot)"""
import json
import sys
import time
from datetime import date

import pandas as pd

from briefs import SCHEMA, SYSTEM, evidence
from common import INTERIM, OUTPUT, log, paths, settings

ST = settings()
M = ST["models"]
P = paths()
# v4 (Tom, 13 Nov 2026): "--v4" compares with the v3 snapshot and rewrites briefs whose counted signals changed
V4 = "--v4" in sys.argv
# "--fix": after the v4 rewrite, also rewrite Act now briefs whose evidence text no longer matches the current counted
# signals (same signal types and dates, but a different story behind them), so no brief cites a story that now scores 0
FIX = "--fix" in sys.argv
# v5 (Tom, 13 Nov 2026): compare with the v4 snapshot; rewrite a brief when its counted signals changed, or when the
# evidence it was written from changed (a peer incident now left out under item 5, or a different story behind the
# same signal); a peer incident is left out of the evidence unless the victim is plainly the same kind of business
V6 = "--v6" in sys.argv             # v6 (Tom, 13 Nov 2026): same rules as v5, compared with the v5 snapshot
# later runs: --base=<snapshot folder under output/before_changes> --tag=<version>, e.g. --base=v6_full --tag=v7
ARG = dict(a[2:].split("=", 1) for a in sys.argv if a.startswith("--") and "=" in a)
V5 = "--v5" in sys.argv or V6 or "base" in ARG
BASE = OUTPUT / "before_changes" / (ARG.get("base") or ("v5_full" if V6 else "v4_full" if V5 else "v3_full" if V4 else "stage2_full_base"))
TAG = ARG.get("tag") or ("v6" if V6 else "v5" if V5 else "v4fix" if FIX else "v4" if V4 else "stage2")


def drop_unlike_peers(S):
    """v5 item 5: remove peer incident lines from a group's brief evidence unless the peer is the same kind of
    business (data/interim/peer_kind.csv). The points are unaffected (scoring already happened)."""
    if not V5:
        return S
    K = pd.read_csv(INTERIM / "peer_kind.csv", dtype=str).fillna("")
    bad = set(zip(K[K.same_kind != "same kind"].group_id, K[K.same_kind != "same kind"].detail))
    return S[[not (t == "peer incident" and (g, d) in bad) for g, t, d in zip(S.group_id, S.signal_type, S.detail)]]
SEL = INTERIM / f"briefs_{TAG}_groups.csv"
BATCH = INTERIM / f"briefs_{TAG}_batch.json"
OPUS = ST["stage2"]["model"]

SYSTEM2 = SYSTEM + """
- A "claimed ransomware victim" line is a claim posted by a criminal group on its leak site; it is not confirmed. \
Never mention it, ransomware, an attack on the account or leaked data in the angle. You may mention it in \
why_it_matters only as a reported claim (e.g. "a ransomware group has claimed it as a victim (ransomware.live, \
date); the claim is not confirmed").
- A "peer incident" line may be the angle. Name the peer organisation only when its line says "confirmed by \
news"; otherwise refer to it only as "a reported incident in your sector" and do not name the peer anywhere."""


def counted(S):
    S = S[(S.counted == "True") & (S.value.astype(float) > 0)]
    return S.groupby("group_id").apply(lambda g: tuple(sorted(zip(g.family, g.signal_type, g.date))), include_groups=False).to_dict()


def select():
    T = pd.read_csv(P["ranked"], dtype=str).fillna("")
    S1 = pd.read_csv(P["scored"], dtype=str).fillna("")
    S0 = pd.read_csv(BASE / "signals_scored.csv", dtype=str).fillna("")
    c1, c0 = counted(S1), counted(S0)
    S1 = drop_unlike_peers(S1)
    old = pd.read_csv(BASE / "briefs_full.csv", dtype=str).fillna("")
    has = set(old[old.what_changed != ""].group_id)
    rows = []
    cur = pd.read_csv(P["briefs"], dtype=str).fillna("") if FIX else None
    cur_ev = dict(zip(cur.group_id, cur.evidence)) if FIX else {}
    for g in T[T.band == "Act now"].itertuples():
        ev = evidence(g.group_id, S1)
        if FIX or V5:
            cur_ev = cur_ev or dict(zip(old.group_id, old.evidence))
            if c1.get(g.group_id) == c0.get(g.group_id) and cur_ev.get(g.group_id) == ev:
                continue
            why = ("counted signals changed" if c1.get(g.group_id) != c0.get(g.group_id) else
                   "peer incident left out" if "peer incident" in cur_ev.get(g.group_id, "") and "peer incident" not in ev
                   else "evidence text changed")
        elif c1.get(g.group_id) == c0.get(g.group_id):
            continue
        else:
            why = "counted signals changed"
        ransom = ("claimed ransomware victim" in ev) or ("ransomware.live" in ev and "peer incident" in ev)
        rows.append(dict(group_id=g.group_id, group_name=g.group_name, rank=g.rank, total=g.total,
                         action="rewrite" if g.group_id in has else "new",
                         model=OPUS if ransom else M["briefs"], uses_ransomware=ransom,
                         peer_incident="peer incident" in ev, why=why, evidence=ev))
    D = pd.DataFrame(rows)
    D.to_csv(SEL, index=False)
    log("briefs_stage2", "select", n=len(D), **{k: int(v) for k, v in D.action.value_counts().items()} if len(D) else {})
    if len(D): print(D.why.value_counts().to_string())
    print(f"{len(D)} Act now groups whose signals changed: {D.action.value_counts().to_dict() if len(D) else {}}; "
          f"by Opus (ransomware evidence): {int(D.uses_ransomware.sum()) if len(D) else 0}")


def requests_list():
    D = pd.read_csv(SEL, dtype=str).fillna("")
    T = pd.read_csv(P["ranked"], dtype=str).fillna("").set_index("group_id")
    today = date.today().isoformat()
    R = []
    for i, x in enumerate(D.itertuples()):
        g = T.loc[x.group_id]
        msg = (f"Account: {x.group_name} (sector: {g.sector or 'unknown'}, country: {g.country})\n"
               f"Today's date: {today}\nEvidence (each line is one signal, with its source and date):\n{x.evidence}")
        R.append(dict(custom_id=f"g{i:04d}", params=dict(
            model=x.model, max_tokens=8000, system=[{"type": "text", "text": SYSTEM2, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": msg}])))
    return D, R


def cost(model, tin, tout):
    pi, po = M["price"][model]
    return tin / 1e6 * pi + tout / 1e6 * po


def estimate():
    import anthropic
    client = anthropic.Anthropic()
    D, R = requests_list()
    tot = 0.0
    for r in R:
        p = r["params"]
        n = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                         output_config={"format": p["output_config"]["format"]}).input_tokens
        tot += cost(p["model"], n, M["briefs_assumed_output_tokens"])
    est = dict(briefs=len(R), opus=int((D.model == OPUS).sum()), fable=int((D.model != OPUS).sum()), cost_usd=round(tot, 2))
    log("briefs_stage2", "estimate", **est)
    print(json.dumps(est))


def send():
    import anthropic
    if BATCH.exists():
        raise SystemExit("already sent")
    D, R = requests_list()
    b = anthropic.Anthropic().messages.batches.create(requests=R)
    BATCH.write_text(json.dumps({"id": b.id, "groups": list(D.group_id), "date": date.today().isoformat()}))
    log("briefs_stage2", "batch_sent", id=b.id, n=len(R))
    print("sent", b.id, len(R))


def collect():
    import anthropic
    client = anthropic.Anthropic()
    meta = json.loads(BATCH.read_text())
    while (b := client.messages.batches.retrieve(meta["id"])).processing_status != "ended":
        print("waiting:", b.request_counts, flush=True); time.sleep(60)
    res = {r.custom_id: r for r in client.messages.batches.results(meta["id"])}
    D, _ = requests_list()
    rows = []
    for i, x in enumerate(D.itertuples()):
        r = res[f"g{i:04d}"]
        row = dict(rank=x.rank, group_id=x.group_id, group_name=x.group_name, band="Act now", total=x.total,
                   brief_date=meta["date"], evidence=x.evidence, model=x.model, stage2=x.action, version=TAG)
        if r.result.type == "succeeded" and r.result.message.stop_reason != "refusal":
            m = r.result.message
            u = m.usage
            row.update(json.loads(next(c.text for c in m.content if c.type == "text")),
                       input_tokens=u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
                       output_tokens=u.output_tokens,
                       cost_usd=cost(x.model, u.input_tokens + (u.cache_creation_input_tokens or 0) * 1.25
                                     + (u.cache_read_input_tokens or 0) * 0.1, u.output_tokens))
        else:
            row.update(what_changed="", why_it_matters="", angle="", who_to_contact="", cost_usd=0.0,
                       note=f"no brief: {r.result.type}")
        rows.append(row)
    new = pd.DataFrame(rows)
    new.to_csv(INTERIM / f"briefs_{TAG}.csv", index=False)
    old = pd.read_csv(P["briefs"] if FIX else BASE / "briefs_full.csv", dtype=str).fillna("")
    merged = pd.concat([old[~old.group_id.isin(new.group_id)], new.astype(str)]).fillna("")
    merged.to_csv(P["briefs"], index=False)
    log("briefs_stage2", "done", n=len(new), cost_usd=round(new.cost_usd.astype(float).sum(), 4))
    print(f"{len(new)} briefs, cost ${new.cost_usd.astype(float).sum():.4f}")


if __name__ == "__main__":
    {"select": select, "estimate": estimate, "send": send, "collect": collect}[sys.argv[1]]()
