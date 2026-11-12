"""Stage 2, Slice A: principal risks in private-company annual reports (Tom, 12 Nov 2026).

  python src/slice_a.py fetch      # pick each group's company, download its latest full accounts, find the section
  python src/slice_a.py estimate   # exact input tokens (free count endpoint), cost and time; nothing sent
  python src/slice_a.py send       # one Opus batch (id saved, never sent twice)
  python src/slice_a.py collect    # wait, check every quote word for word, write data/interim/slice_a_results.csv

Scope: groups with no result from the listed-company app (pilot groups only until Tom approves the full run).
Company: the group's top UK company; if its latest accounts are not full accounts, the member with the largest staff
band. Accounts: latest accounts filing from Companies House (filing history, document metadata, then the document;
the structured XHTML when offered, else the PDF). A PDF with almost no text layer is a scan -> "couldn't check" (no
text recognition). The section finder and the prompt are the listed-company app's (scanner_text.py, its labelling
guide), so verdicts are consistent. Every download is saved under data/raw/ch/; nothing is fetched twice."""
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

import companies_house as ch
import scanner_text as st
from common import INTERIM, OUTPUT, RAW, log, pace, settings

ST = settings()
A = ST["stage2"]["slice_a"]
M = ST["stage2"]["model"]
OUT = INTERIM / "slice_a"
TABLE = OUT / "documents.csv"
RESULTS = INTERIM / "slice_a_results.csv"
BATCH = OUT / "batch.json"
DOCS = RAW / "ch" / "documents"
SCANNER = Path(os.environ.get("RISK_SCANNER_DIR") or Path.home() / "projects" / "risk-scanner")   # the listed-company app
PUBLIC = "https://find-and-update.company-information.service.gov.uk"


# ------------------------------------------------------------------ scope and company choice
def scope():
    """(group_id, group_name) of pilot groups with no listed-company app result."""
    pg = pd.read_csv(OUTPUT / "step3" / "pilot_groups.csv", dtype=str).fillna("")
    s = pd.read_csv(INTERIM / "scanner_matches.csv", dtype=str).fillna("")
    return pg[~pg.group_id.isin(set(s.group_id))][["group_id", "group_name"]]


def band_rank(b):
    b = (b or "").replace(" staff", "")
    bl = ST["universe"]["min_staff_bands"]
    return bl.index(b) + 1 if b in bl else 0


def accounts(num):
    """The latest accounts filing with a document (the one with most pages within the newest year), or None."""
    d = ch.get(f"/company/{num}/filing-history", "filing", f"{num}_accounts_0",
               params={"category": "accounts", "items_per_page": 100})
    items = [i for i in (d or {}).get("items", []) if (i.get("links") or {}).get("document_metadata")
             and i.get("type") in A["accounts_filing_types"]]
    if not items:
        return None
    newest = max(date.fromisoformat(i["date"]) for i in items)
    same = [i for i in items if (newest - date.fromisoformat(i["date"])).days <= A["same_filing_days"]]
    return max(same, key=lambda i: i.get("pages") or 0)


def is_full(item):
    return bool(item) and any(w in (item.get("description") or "") for w in A["full_accounts_words"])


# ------------------------------------------------------------------ document download (cached)
def _doc_get(url, accept=None):
    """Companies House document API with the key, paced on the shared Companies House limit, no redirects."""
    for attempt in range(6):
        pace("companies_house", ch.MIN_GAP)
        r = requests.get(url, auth=(os.environ["COMPANIES_HOUSE_API_KEY"], ""), allow_redirects=False, timeout=120,
                         headers={"Accept": accept} if accept else {})
        if r.status_code == 429:
            log("companies_house", "rate_limit_pause", path=url[-60:], wait_s=60); time.sleep(60); continue
        if r.status_code >= 500:
            log("companies_house", "server_error", path=url[-60:], status=r.status_code); time.sleep(15 * (attempt + 1)); continue
        log("companies_house", "request", path=url[-80:], status=r.status_code)
        return r
    log("companies_house", "gave_up", path=url[-80:])
    raise RuntimeError(f"Companies House documents: gave up on {url}")


def document(num, item):
    """Path of the saved document (XHTML preferred, else PDF). Metadata and file are both saved."""
    tid = item["transaction_id"]
    mpath = DOCS / f"{num}_{tid}.meta.json"
    DOCS.mkdir(parents=True, exist_ok=True)
    if mpath.exists():
        meta = json.loads(mpath.read_text())
    else:
        r = _doc_get(item["links"]["document_metadata"])
        r.raise_for_status()
        meta = r.json()
        mpath.write_text(json.dumps(meta))
    kinds = meta.get("resources") or {}
    ctype = "application/xhtml+xml" if "application/xhtml+xml" in kinds else "application/pdf"
    path = DOCS / f"{num}_{tid}.{'xhtml' if ctype.endswith('xml') else 'pdf'}"
    if path.exists():
        return path
    r = _doc_get(meta["links"]["document"], accept=ctype)
    if r.status_code in (301, 302, 303, 307, 308):
        r2 = None
        for attempt in range(4):          # pre-signed storage link: fetched WITHOUT the Companies House key
            try:
                r2 = requests.get(r.headers["Location"], timeout=300)
                break
            except requests.RequestException as e:
                log("ch_documents", "error", error=str(e)[:200]); time.sleep(10 * (attempt + 1))
        if r2 is None:
            raise RuntimeError("document storage download failed")
        r2.raise_for_status()
        body = r2.content
        log("ch_documents", "download", bytes=len(body))
    else:
        r.raise_for_status()
        body = r.content
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.rename(path)
    return path


# ------------------------------------------------------------------ fetch + section
def choose(gid, members, band):
    """(company number, latest accounts item, how chosen) or (None, None, reason)."""
    uk = members[members.entity_id.str.match(r"^[0-9A-Z]{8}$") & (members.country == "UK")]
    if gid.startswith("UK:"):
        top = gid[3:]
    else:
        tops = [t for t in uk.top_company_number if t]
        top = max(tops, key=lambda t: band_rank(band.get(t, ""))) if tops else ""
    if not top and not len(uk):
        return None, None, "no UK company in the group (Irish or not a company): no Companies House accounts"
    if top:
        item = accounts(top)
        if is_full(item):
            return top, item, "top UK company"
    alt = sorted(uk.entity_id, key=lambda e: -band_rank(band.get(e, "")))
    alt = [e for e in alt if e != top]
    if alt:
        item = accounts(alt[0])
        if is_full(item):
            return alt[0], item, "member with the largest staff band (top company files no full accounts)"
    return None, None, "no full accounts filed by the top company or the largest member"


def fetch():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sections").mkdir(exist_ok=True)
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
    band = dict(zip(u.entity_id, u.size_band))
    sc = scope()
    rows, t0 = [], time.time()
    print(f"{len(sc)} pilot groups with no listed-company result", flush=True)
    for k, x in enumerate(sc.itertuples(), 1):
        m = g[g.group_id == x.group_id]
        row = dict(group_id=x.group_id, group_name=x.group_name, company="", company_name="", chosen="", filed="",
                   made_up_to="", accounts_type="", pages="", format="", status="", reason="", words=0,
                   section_path="", source_link="")
        if not len(m):
            rows.append({**row, "status": "couldn't check", "reason": "group no longer in the universe"}); continue
        num, item, how = choose(x.group_id, m, band)
        if not num:
            rows.append({**row, "status": "couldn't check", "reason": how}); continue
        name = (ch.profile(num) or {}).get("company_name", "")
        row.update(company=num, company_name=name, chosen=how, filed=item["date"],
                   made_up_to=(item.get("description_values") or {}).get("made_up_date", ""),
                   accounts_type=item.get("description", ""), pages=item.get("pages") or "",
                   source_link=f"{PUBLIC}/company/{num}/filing-history/{item['transaction_id']}/document?format=pdf&download=0")
        try:
            path = document(num, item)
        except Exception as e:
            rows.append({**row, "status": "couldn't check", "reason": f"download failed: {type(e).__name__}: {e}"[:200]})
            continue
        row["format"] = "structured (XHTML)" if path.suffix == ".xhtml" else "PDF"
        if path.suffix == ".pdf" and st.pdf_text_density(path) < A["min_text_per_page"]:
            rows.append({**row, "status": "couldn't check", "reason": "scanned PDF with no text (no text recognition)"})
            continue
        lines = st.report_to_lines(path)
        sec = st.find_section(lines)
        if not sec.found:
            rows.append({**row, "status": "no section found", "reason": sec.reason}); continue
        sp = OUT / "sections" / f"{num}.txt"
        sp.write_text("\n".join(sec.lines) + "\n", encoding="utf-8")
        rows.append({**row, "status": "section found", "reason": " | ".join(sec.headings),
                     "words": sum(len(l.split()) for l in sec.lines), "section_path": str(sp.relative_to(OUT.parent.parent.parent))})
        if k % 25 == 0:
            print(f"  {k}/{len(sc)}  {(time.time() - t0) / 60:.0f} min", flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(TABLE, index=False)
    log("slice_a", "fetch_done", groups=len(t), **{k.replace("'", ""): int(v) for k, v in t.status.value_counts().items()},
        secs=round(time.time() - t0))
    print(t.status.value_counts().to_string())
    print(t[t.status != "section found"].reason.str[:70].value_counts().to_string())


# ------------------------------------------------------------------ model (the listed-company app's prompt)
SYS_ADD = """
NOTE FOR THIS RUN: the text is from a UK company's annual report and accounts filed at Companies House. Many are
private companies: their principal risks usually sit in the strategic report under "Principal risks and
uncertainties", often short. Apply the same guide.
RULE CHANGE FOR THIS RUN (Tom, 12 Nov 2026): keep the guide's rules for "yes". If supply chain risk is one of the
principal risks (named as a risk in its own right) but third-party, supplier-assurance or outsourcing risk is not,
return "passing mention" instead of "no", quoting the supply chain risk.
"""


def _scanner():
    """The listed-company app's classify module (its prompt, schema and quote check). Importing it loads the app's
    .env without overriding this project's keys (already loaded by common)."""
    if str(SCANNER) not in sys.path:
        sys.path.insert(0, str(SCANNER))
    from scanner import classify
    return classify


def system_prompt():
    return _scanner().system_prompt().replace("UK listed company's", "UK company's") + SYS_ADD


def schema():
    return _scanner().SCHEMA


def requests_list():
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    t = t[t.status == "section found"].reset_index(drop=True)
    sysp = system_prompt()
    sch = schema()
    reqs = []
    for i, x in enumerate(t.itertuples()):
        sec = (OUT.parent.parent.parent / x.section_path).read_text()
        reqs.append(dict(custom_id=f"s{i:05d}", params=dict(
            model=M, max_tokens=20000,
            system=[{"type": "text", "text": sysp, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"Company: {x.company_name}\n\n==== RISK CHAPTER (extracted from "
                                                  f"the annual report) ====\n{sec}"}],
            output_config={"effort": A["effort"], "format": {"type": "json_schema", "schema": sch}})))
    return t, reqs


def cost(tin, tout):
    pi, po = ST["models"]["price"][M]
    return tin / 1e6 * pi + tout / 1e6 * po


def estimate():
    import anthropic
    client = anthropic.Anthropic()
    t, reqs = requests_list()
    toks = []
    for r in reqs:
        p = r["params"]
        toks.append(client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                                 output_config={"format": p["output_config"]["format"]}).input_tokens)
    over = sum(1 for n in toks if n > ST["stage2"]["max_prompt_tokens"])
    tin, tout = sum(toks), A["assumed_output_tokens"] * len(reqs)
    est = dict(sections=len(reqs), input_tokens=tin, max_prompt=max(toks or [0]), over_limit=over,
               output_tokens_assumed=tout, cost_usd=round(cost(tin, tout), 2),
               cost_per_section_usd=round(cost(tin, tout) / max(1, len(reqs)), 4),
               cost_if_output_doubles_usd=round(cost(tin, 2 * tout), 2))
    log("slice_a", "estimate", **est)
    print(json.dumps(est, indent=1))
    return est


def send():
    import anthropic
    if BATCH.exists():
        raise SystemExit(f"already sent: {json.loads(BATCH.read_text())['id']} - run collect")
    t, reqs = requests_list()
    b = anthropic.Anthropic().messages.batches.create(requests=reqs)
    BATCH.write_text(json.dumps({"id": b.id, "requests": len(reqs), "companies": list(t.company)}))
    log("slice_a", "batch_sent", id=b.id, n=len(reqs))
    print("sent", b.id, len(reqs))


def collect():
    import anthropic
    quote_found = _scanner().quote_found          # the app's word-for-word quote check
    client = anthropic.Anthropic()
    meta = json.loads(BATCH.read_text())
    while (b := client.messages.batches.retrieve(meta["id"])).processing_status != "ended":
        print("waiting:", b.request_counts, flush=True)
        time.sleep(60)
    res = {r.custom_id: r for r in client.messages.batches.results(meta["id"])}
    t, _ = requests_list()
    allt = pd.read_csv(TABLE, dtype=str).fillna("")
    out = []
    for i, x in enumerate(t.itertuples()):
        r = res.get(f"s{i:05d}")
        sec = (OUT.parent.parent.parent / x.section_path).read_text()
        row = dict(company=x.company)
        if r is not None and r.result.type == "succeeded" and r.result.message.stop_reason != "refusal":
            m = r.result.message
            d = json.loads(next(c.text for c in m.content if c.type == "text"))
            row.update(verdict=d["verdict"], quote=d["quote"], risk_title=d["risk_title"], main_theme=d["main_theme"],
                       themes="; ".join(d["themes"]), supply_chain=d["supply_chain"], tprm_programme=d["tprm_programme"],
                       reason=d["reason"], quote_verified=quote_found(d["quote"], sec),
                       findings=json.dumps(d["findings"])[:3000],
                       input_tokens=m.usage.input_tokens + (m.usage.cache_read_input_tokens or 0)
                       + (m.usage.cache_creation_input_tokens or 0),
                       output_tokens=m.usage.output_tokens,
                       cost_usd=cost(m.usage.input_tokens + (m.usage.cache_creation_input_tokens or 0) * 1.25
                                     + (m.usage.cache_read_input_tokens or 0) * 0.1, m.usage.output_tokens))
        else:
            row.update(verdict="couldn't check", reason=f"model: {r.result.type if r else 'no result'}", cost_usd=0.0)
        out.append(row)
    o = allt.merge(pd.DataFrame(out), on="company", how="left", suffixes=("", "_model"))
    o["verdict"] = o.verdict.fillna("").where(o.status == "section found", o.status)
    o.to_csv(RESULTS, index=False)
    log("slice_a", "done", n=len(out), cost=round(sum(r.get("cost_usd", 0) for r in out), 4))
    print(o.verdict.value_counts().to_string())
    print(f"cost ${sum(r.get('cost_usd', 0) for r in out):.4f}")


if __name__ == "__main__":
    {"fetch": fetch, "estimate": estimate, "send": send, "collect": collect}[sys.argv[1]]()
