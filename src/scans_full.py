"""Stage 2 v4 item 7 (Tom, 13 Nov 2026): annual-report principal risks for every group with 1,000+ staff that has no
listed-company result. The tested method, through the Batch API.

  python src/scans_full.py fetch            # choose the company, download its latest full accounts (resumable).
                                            #   Text accounts: the section is extracted now and the document deleted.
                                            #   Scans: kept until transcribed.        -> data/interim/item7/documents.csv
  python src/scans_full.py find-send | find-collect             # Haiku: page numbers of the principal risks section
  python src/scans_full.py transcribe-send | transcribe-collect # Haiku: word-for-word section; documents deleted
  python src/scans_full.py verdict-send | verdict-collect       # Opus (Slice A prompt and the supply chain rule)
                                                                #   -> data/interim/item7_results.csv

Pilot outcomes are reused (the 30 tested scans and the 28 text sections) so nothing is fetched twice for them.
Score: "yes" need 3, "passing mention" need 1, same family as the listed-company results."""
import base64
import json
import sys
import time

import pandas as pd

import companies_house as ch
import scanner_text as st
from common import INTERIM, OUTPUT, RAW, log, settings
from slice_a import (A, PUBLIC, choose, document, schema, system_prompt)
from slice_a_scans import FIND, TRANSCRIBE

ST = settings()
HAIKU = "claude-haiku-5-5"
OPUS = ST["stage2"]["model"]
OUT = INTERIM / "item7"
TABLE = OUT / "documents.csv"
SEC = OUT / "sections"
DOCS = RAW / "ch" / "documents"
PRICE = ST["models"]["price"]
BATCH_BYTES = 180_000_000          # stay well under the Batch API's 256 MB per batch
MAX_TOK = ST["stage2"]["max_prompt_tokens"]


def scope():
    return pd.read_csv(INTERIM / "item7_scope.csv", dtype=str).fillna("")


def fetch():
    OUT.mkdir(parents=True, exist_ok=True)
    SEC.mkdir(exist_ok=True)
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    by = dict(tuple(g.groupby("group_id")))
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    band = dict(zip(u.entity_id, u.size_band))
    pilot = pd.read_csv(INTERIM / "slice_a" / "documents.csv", dtype=str).fillna("")
    pscan = pd.read_csv(INTERIM / "slice_a_scans.csv", dtype=str).fillna("")
    done = pd.read_csv(TABLE, dtype=str).fillna("") if TABLE.exists() else pd.DataFrame(columns=["group_id"])
    rows = done.to_dict("records")
    have = set(done.group_id)
    t0 = time.time()
    sc = scope()
    for k, x in enumerate(sc.itertuples(), 1):
        if x.group_id in have:
            continue
        row = dict(group_id=x.group_id, group_name=x.group_name, size_band=x.size_band, company="", company_name="",
                   chosen="", made_up_to="", pages="", format="", status="", reason="", section_path="", doc_path="",
                   source_link="")
        p = pilot[pilot.group_id == x.group_id]
        if len(p) and (p.status.iloc[0] == "section found" or p.company.iloc[0] in set(pscan.company)
                       or not p.company.iloc[0]):
            q = p.iloc[0]
            row.update(company=q.company, company_name=q.company_name, chosen=q.chosen, made_up_to=q.made_up_to,
                       pages=q.pages, format=q.format, source_link=q.source_link, reason=q.reason,
                       status=("text section" if q.status == "section found" else "scan (pilot test)" if q.company in set(pscan.company)
                               else "couldn't check"), section_path=q.section_path)
            rows.append(row); continue
        m = by.get(x.group_id)
        if m is None:
            rows.append({**row, "status": "couldn't check", "reason": "group no longer in the universe"}); continue
        try:
            num, item, how = choose(x.group_id, m, band)
        except Exception as e:
            rows.append({**row, "status": "couldn't check", "reason": f"filing history failed: {e}"[:200]}); continue
        if not num:
            rows.append({**row, "status": "couldn't check", "reason": how}); continue
        row.update(company=num, company_name=(ch.profile(num) or {}).get("company_name", ""), chosen=how,
                   made_up_to=(item.get("description_values") or {}).get("made_up_date", ""), pages=item.get("pages") or "",
                   source_link=f"{PUBLIC}/company/{num}/filing-history/{item['transaction_id']}/document?format=pdf&download=0")
        try:
            path = document(num, item)
        except Exception as e:
            rows.append({**row, "status": "couldn't check", "reason": f"download failed: {type(e).__name__}: {e}"[:200]}); continue
        row["format"] = "structured (XHTML)" if path.suffix == ".xhtml" else "PDF"
        if path.suffix == ".pdf" and st.pdf_text_density(path) < A["min_text_per_page"]:
            row.update(status="scan", doc_path=str(path))
        else:
            sec = st.find_section(st.report_to_lines(path))
            if sec.found:
                sp = SEC / f"{num}.txt"
                sp.write_text("\n".join(sec.lines) + "\n", encoding="utf-8")
                row.update(status="text section", reason=" | ".join(sec.headings), section_path=str(sp))
            else:
                row.update(status="no section found", reason=sec.reason)
            path.unlink(missing_ok=True)                        # Tom: no documents kept after extraction
        rows.append(row)
        if k % 25 == 0:
            pd.DataFrame(rows).to_csv(TABLE, index=False)
            print(f"  {k}/{len(sc)}  {(time.time() - t0) / 60:.0f} min", flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(TABLE, index=False)
    log("item7", "fetch_done", groups=len(t), **{s.replace("'", ""): int(v) for s, v in t.status.value_counts().items()})
    print(t.status.value_counts().to_string())


# ------------------------------------------------------------------ batch helpers
def jpeg_pages(path, pages, px, q):
    import pymupdf
    out = []
    with pymupdf.open(path) as d:
        for n in pages:
            if 1 <= n <= len(d):
                p = d[n - 1]
                z = px / max(p.rect.width, p.rect.height)
                pix = p.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY)
                out.append((n, base64.standard_b64encode(pix.tobytes("jpg", jpg_quality=q)).decode()))
    return out


def content(imgs, text):
    c = []
    for n, b in imgs:
        c += [{"type": "text", "text": f"Page {n}:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}]
    return c + [{"type": "text", "text": text}]


def send_chunks(name, reqs):
    """Several batches when needed (request size); ids saved in item7/<name>_batches.json."""
    import anthropic
    f = OUT / f"{name}_batches.json"
    if f.exists():
        raise SystemExit(f"{name}: already sent")
    client = anthropic.Anthropic()
    ids, cur, size = [], [], 0
    for r in reqs + [None]:
        n = len(json.dumps(r)) if r else 0
        if cur and (r is None or size + n > BATCH_BYTES):
            ids.append(client.messages.batches.create(requests=cur).id)
            log("item7", f"{name}_batch_sent", id=ids[-1], n=len(cur))
            cur, size = [], 0
        if r:
            cur.append(r); size += n
    f.write_text(json.dumps(ids))
    print(f"{name}: {len(reqs)} requests in {len(ids)} batches")


def results(name):
    import anthropic
    client = anthropic.Anthropic()
    ids = json.loads((OUT / f"{name}_batches.json").read_text())
    for b in ids:
        while (x := client.messages.batches.retrieve(b)).processing_status != "ended":
            print("waiting:", b[-6:], x.request_counts, flush=True); time.sleep(60)
    out = {}
    for b in ids:
        for r in client.messages.batches.results(b):
            out[r.custom_id] = r
    return out


def usage_cost(m, model):
    u = m.usage
    pi, po = PRICE[model]
    return (u.input_tokens + (u.cache_creation_input_tokens or 0) * 1.25 + (u.cache_read_input_tokens or 0) * 0.1) / 1e6 * pi \
        + u.output_tokens / 1e6 * po


def text_of(m):
    return next((b.text for b in m.content if b.type == "text"), "")


# ------------------------------------------------------------------ find
def find_send():
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    s = t[t.status == "scan"]
    reqs = []
    for x in s.itertuples():
        first = list(range(1, min(int(x.pages or 40), 40) + 1))
        reqs.append(dict(custom_id=f"f{x.Index:05d}", params=dict(
            model=HAIKU, max_tokens=2000, system=[{"type": "text", "text": FIND, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content(jpeg_pages(x.doc_path, first, 900, 60), "Find the principal risks section.")}])))
    send_chunks("find", reqs)


def find_collect():
    import re
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    res = results("find")
    cost = 0.0
    for i, x in t[t.status == "scan"].iterrows():
        r = res.get(f"f{i:05d}")
        if r is None or r.result.type != "succeeded":
            t.loc[i, "find_note"] = f"model: {r.result.type if r else 'no result'}"; continue
        m = r.result.message
        cost += usage_cost(m, HAIKU)
        try:
            j = json.loads(re.search(r"\{.*\}", text_of(m), re.S).group(0))
        except Exception:
            j = {}
        t.loc[i, "pages_found"] = " ".join(str(int(p)) for p in j.get("pages", []) if str(p).isdigit())
        t.loc[i, "heading"] = j.get("heading", "")
        t.loc[i, "find_note"] = j.get("note", "")
        t.loc[i, "find_cost"] = usage_cost(m, HAIKU)
    t.to_csv(TABLE, index=False)
    log("item7", "find_done", cost_usd=round(cost, 4), found=int((t.get("pages_found", pd.Series(dtype=str)).fillna("") != "").sum()))
    print(f"find: ${cost:.4f}; section pages found for {(t.pages_found.fillna('') != '').sum()} of {(t.status == 'scan').sum()}")


# ------------------------------------------------------------------ transcribe
def transcribe_send():
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    reqs = []
    for x in t[(t.status == "scan") & (t.pages_found != "")].itertuples():
        pages = sorted({int(p) for p in x.pages_found.split()})
        want = sorted(set(pages) | {pages[-1] + 1})[:12]
        reqs.append(dict(custom_id=f"t{x.Index:05d}", params=dict(
            model=HAIKU, max_tokens=12000, system=[{"type": "text", "text": TRANSCRIBE, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": content(jpeg_pages(x.doc_path, want, 1500, 75), "Transcribe the principal risks section.")}])))
    send_chunks("transcribe", reqs)


def transcribe_collect():
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    res = results("transcribe")
    cost = 0.0
    for i, x in t[t.status == "scan"].iterrows():
        r = res.get(f"t{i:05d}")
        if x.pages_found == "":
            t.loc[i, "status"] = "scan: no section found on the scanned pages"
        elif r is None or r.result.type != "succeeded":
            t.loc[i, "status"] = f"scan: transcription failed ({r.result.type if r else 'no result'})"
        else:
            m = r.result.message
            cost += usage_cost(m, HAIKU)
            tx = text_of(m)
            t.loc[i, "transcribe_cost"] = usage_cost(m, HAIKU)
            if tx.strip().startswith("NO SECTION") or len(tx.strip()) < 80:
                t.loc[i, "status"] = "scan: transcription found no section"
            else:
                sp = SEC / f"{x.company}.txt"
                sp.write_text(tx)
                t.loc[i, "status"], t.loc[i, "section_path"] = "scan transcribed", str(sp)
        from pathlib import Path
        Path(x.doc_path).unlink(missing_ok=True)                  # deleted after extraction
    t.to_csv(TABLE, index=False)
    log("item7", "transcribe_done", cost_usd=round(cost, 4), transcribed=int((t.status == "scan transcribed").sum()))
    print(f"transcribe: ${cost:.4f}; {(t.status == 'scan transcribed').sum()} transcribed; documents deleted")


# ------------------------------------------------------------------ verdict (Opus)
def verdict_rows():
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    return t[t.status.isin(["text section", "scan transcribed"])]


def verdict_send():
    sysp = system_prompt()
    scan_note = "\nThis risk section was transcribed from a scanned image by another model; judge the text as given.\n"
    reqs = []
    for x in verdict_rows().itertuples():
        sec = open(x.section_path, encoding="utf-8").read()
        scan = x.status == "scan transcribed"
        reqs.append(dict(custom_id=f"v{x.Index:05d}", params=dict(
            model=OPUS, max_tokens=20000, system=[{"type": "text", "text": sysp + (scan_note if scan else ""), "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": A["effort"], "format": {"type": "json_schema", "schema": schema()}},
            messages=[{"role": "user", "content": f"Company: {x.company_name}\n\n==== RISK CHAPTER ({'transcribed from a scan of' if scan else 'extracted from'} "
                                                  f"the annual report) ====\n{sec[:300000]}"}])))
    send_chunks("verdict", reqs)


def verdict_collect():
    from slice_a import _scanner
    quote_found = _scanner().quote_found
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    res = results("verdict")
    rows, cost = [], 0.0
    pscan = pd.read_csv(INTERIM / "slice_a_scans.csv", dtype=str).fillna("")
    for i, x in t.iterrows():
        row = x.to_dict()
        r = res.get(f"v{i:05d}")
        if x.status == "scan (pilot test)":          # tested yesterday: same rules, keep that verdict
            q = pscan[pscan.company == x.company].iloc[0]
            row.update(verdict=q.verdict, quote=q.quote, risk_title=q.risk_title, reason_model=q.reason,
                       quote_check="from scan, not word-checked", supply_chain=q.supply_chain)
        elif r is not None and r.result.type == "succeeded" and r.result.message.stop_reason != "refusal":
            m = r.result.message
            cost += usage_cost(m, OPUS)
            d = json.loads(text_of(m))
            sec = open(x.section_path, encoding="utf-8").read()
            row.update(verdict=d["verdict"], quote=d["quote"], risk_title=d["risk_title"], reason_model=d["reason"],
                       supply_chain=d["supply_chain"], verdict_cost=usage_cost(m, OPUS),
                       quote_check=("from scan, not word-checked" if x.status == "scan transcribed"
                                    else "word-checked: found" if quote_found(d["quote"], sec) else "word-checked: NOT found"))
        else:
            row.update(verdict="couldn't check")
        rows.append(row)
    o = pd.DataFrame(rows)
    o.to_csv(INTERIM / "item7_results.csv", index=False)
    log("item7", "verdict_done", cost_usd=round(cost, 4), **{f"verdict_{k}".replace("'", ""): int(v) for k, v in o.verdict.value_counts().items()})
    print(f"verdict: ${cost:.4f}"); print(o.verdict.value_counts().to_string())


# v5 item 2 (Tom, 13 Nov 2026): a risk only about modern slavery, labour rights, ethical trading or supplier ethics is
# a "passing mention", not "yes". The 41 "yes" verdicts are re-read under this rule; the others are left as they are.
V5_RULE = """
RULE CHANGE FOR THIS RUN (Tom, 13 Nov 2026): if the only third-party or supplier risk that qualifies is about modern
slavery, labour rights, ethical trading or supplier ethics (human rights, ethical sourcing, supplier conduct
standards), return "passing mention", not "yes". Keep "yes" only when a named principal risk covers third-party,
supplier or outsourcing risk more widely (e.g. failure, performance, resilience, security or concentration of
suppliers or outsourced providers).
"""


def _recheck_rows():
    t = pd.read_csv(INTERIM / "item7_results.csv", dtype=str).fillna("")
    return t[t.verdict == "yes"]


def _section(x):
    if x.status == "scan (pilot test)":
        q = pd.read_csv(INTERIM / "slice_a_scans.csv", dtype=str).fillna("")
        return q[q.company == x.company].iloc[0].transcript
    return open(x.section_path, encoding="utf-8").read()


def recheck_send():
    import anthropic
    f = OUT / "recheck_batch.json"
    if f.exists():
        raise SystemExit("already sent")
    sysp = system_prompt() + V5_RULE
    reqs = []
    for x in _recheck_rows().itertuples():
        scan = x.status != "text section"
        note = "\nThis risk section was transcribed from a scanned image by another model; judge the text as given.\n" if scan else ""
        reqs.append(dict(custom_id=f"r{x.Index:05d}", params=dict(
            model=OPUS, max_tokens=20000, system=[{"type": "text", "text": sysp + note, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": A["effort"], "format": {"type": "json_schema", "schema": schema()}},
            messages=[{"role": "user", "content": f"Company: {x.company_name}\n\n==== RISK CHAPTER ({'transcribed from a scan of' if scan else 'extracted from'} "
                                                  f"the annual report) ====\n{_section(x)[:300000]}"}])))
    b = anthropic.Anthropic().messages.batches.create(requests=reqs)
    f.write_text(json.dumps({"id": b.id, "n": len(reqs)}))
    log("item7", "recheck_sent", id=b.id, n=len(reqs))
    print("sent", b.id, len(reqs))


def recheck_collect():
    import anthropic
    from slice_a import _scanner
    quote_found = _scanner().quote_found
    client = anthropic.Anthropic()
    bid = json.loads((OUT / "recheck_batch.json").read_text())["id"]
    while (b := client.messages.batches.retrieve(bid)).processing_status != "ended":
        print("waiting:", b.request_counts, flush=True); time.sleep(60)
    res = {r.custom_id: r for r in client.messages.batches.results(bid)}
    t = pd.read_csv(INTERIM / "item7_results.csv", dtype=str).fillna("")
    t.to_csv(OUT / "item7_results_before_v5_recheck.csv", index=False)
    cost, changed = 0.0, []
    for i in _recheck_rows().index:
        r = res.get(f"r{i:05d}")
        if r is None or r.result.type != "succeeded" or r.result.message.stop_reason == "refusal":
            continue                                   # no answer: the earlier verdict stands
        m = r.result.message
        cost += usage_cost(m, OPUS)
        d = json.loads(text_of(m))
        x = t.loc[i]
        if d["verdict"] != x.verdict:
            changed.append((x.company_name, x.verdict, d["verdict"], d["risk_title"]))
        t.loc[i, ["verdict", "quote", "risk_title", "reason_model", "supply_chain"]] = [str(d[k]) for k in ("verdict", "quote", "risk_title", "reason", "supply_chain")]
        t.loc[i, "v5_recheck"] = f"re-read 13 Nov (was yes)"
        if x.status == "text section":
            t.loc[i, "quote_check"] = "word-checked: found" if quote_found(d["quote"], _section(x)) else "word-checked: NOT found"
    t.fillna("").to_csv(INTERIM / "item7_results.csv", index=False)
    pd.DataFrame(changed, columns=["company", "was", "now", "risk title"]).to_csv(OUT / "v5_recheck_changes.csv", index=False)
    log("item7", "recheck_done", cost_usd=round(cost, 4), n=len(res), changed=len(changed))
    print(f"recheck: ${cost:.4f}; {len(changed)} changed"); print(pd.DataFrame(changed).to_string())


if __name__ == "__main__":
    {"fetch": fetch, "find-send": find_send, "find-collect": find_collect, "transcribe-send": transcribe_send,
     "transcribe-collect": transcribe_collect, "verdict-send": verdict_send, "verdict-collect": verdict_collect,
     "recheck-send": recheck_send, "recheck-collect": recheck_collect}[sys.argv[1]]()
