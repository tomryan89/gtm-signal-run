"""Stage 2, Slice D: regulatory enforcement items (Tom, 12 Nov 2026). No model here.

  python src/regulators.py pull    # every source saved under data/raw/regulators/; resumable
  python src/regulators.py items   # one row per item -> data/interim/reg_items.csv (title, date, link, text)

Sources: GOV.UK Search (last 12 months) for Ofgem, Ofwat, the Pensions Regulator, the Regulator of Social Housing,
the Office for Students and the CMA (case type not mergers); the Bank of England news and PRA publications RSS
feeds; FCA final notices listed in the FCA sitemap (which robots.txt allows; the search pages are disallowed);
ICO enforcement pages listed in the ICO sitemap (6 s between requests, its robots.txt crawl delay)."""
import html
import json
import re
import sys
import time
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

from common import INTERIM, RAW, log, settings

ST = settings()
D = ST["stage2"]["slice_d"]
DIR = RAW / "regulators"
RUN = date.fromisoformat(ST["run"]["run_date"])
SINCE = (RUN - timedelta(days=round(D["months"] * 30.44))).isoformat()
_last = {}


def fetch(url, dest, source, gap, params=None):
    if dest.exists():
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(5):
        w = gap - (time.time() - _last.get(source, 0))
        if w > 0:
            time.sleep(w)
        _last[source] = time.time()
        try:
            r = requests.get(url, params=params, timeout=120)
        except requests.RequestException as e:
            log(source, "error", url=url[:120], error=str(e)[:200]); time.sleep(30); continue
        if r.status_code == 429 or r.status_code >= 500:
            log(source, "rate_limit_pause" if r.status_code == 429 else "server_error", url=url[:120]); time.sleep(60 * (attempt + 1)); continue
        log(source, "request", url=url[:120], status=r.status_code)
        if r.status_code != 200:
            dest.write_bytes(b""); return b""
        dest.write_bytes(r.content)
        return r.content
    log(source, "gave_up", url=url[:120])
    return b""


def clean(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def pull():
    # GOV.UK
    for org in D["govuk_orgs"]:
        fetch("https://www.gov.uk/api/search.json", DIR / "govuk" / f"{org}.json", "govuk_search", 2,
              params={"filter_organisations": org, "filter_public_timestamp": f"from:{SINCE}", "count": 1000,
                      "fields": "title,link,public_timestamp,content_store_document_type,description,case_type"})
    # Bank of England
    for u in D["boe_feeds"]:
        fetch(u, DIR / "boe" / (u.rsplit("/", 1)[1] + ".xml"), "bank_of_england", 3)
    # FCA final notices via the sitemap
    urls = []
    for k, u in enumerate(D["fca_sitemaps"], 1):
        x = fetch(u, DIR / "fca" / f"sitemap_{k}.xml", "fca_web", D["fca_gap_seconds"]).decode("utf-8", "replace")
        urls += re.findall(r"<loc>([^<]*/publication/final-notices/[^<]*)</loc><lastmod>([^<]*)", x)
    urls = sorted({u for u, m in urls if m[:10] >= SINCE})
    print(f"FCA final notices changed since {SINCE}: {len(urls)}", flush=True)
    for u in urls:
        fetch(u, DIR / "fca" / "notices" / u.rsplit("/", 1)[1], "fca_web", D["fca_gap_seconds"])
    # ICO enforcement pages via the sitemap
    x = fetch(D["ico_sitemap"], DIR / "ico" / "sitemap.xml", "ico", D["ico_gap_seconds"]).decode("utf-8", "replace")
    pages = sorted(set(re.findall(r"https://ico\.org\.uk/action-weve-taken/enforcement/(\d{4})/(\d{2})/([^<\"/]+)/", x)))
    pages = [p for p in pages if f"{p[0]}-{p[1]}" >= SINCE[:7]]
    print(f"ICO enforcement pages since {SINCE[:7]}: {len(pages)}", flush=True)
    for y, m, slug in pages:
        fetch(f"https://ico.org.uk/action-weve-taken/enforcement/{y}/{m}/{slug}/", DIR / "ico" / "pages" / f"{y}_{m}_{slug}.html",
              "ico", D["ico_gap_seconds"])
    log("regulators", "pull_done")


OFGEM_WORDS = r"penalt|fine|enforce|investigat|redress|breach|sanction|final-order|provisional-order|compliance"


def ofgem_pages():
    """Ofgem pages (press releases, publications, decisions) whose address names enforcement and which changed in the
    window. robots.txt (12 Nov 2026) allows these paths; /search is disallowed and not used."""
    out = []
    for f in sorted((DIR / "ofgem").glob("sitemap_[0-9]*.xml")):
        x = f.read_text(errors="replace")
        for loc, mod in re.findall(r"<loc>https://www\.ofgem\.gov\.uk/([^<]+)</loc>(?:\s*<xhtml:link[^>]*/>)*\s*<lastmod>([^<]+)</lastmod>", x):
            if mod[:10] >= SINCE and re.match(r"(press-release|publications|decision)/", loc) and re.search(OFGEM_WORDS, loc):
                out.append(loc)
    return sorted(set(out))


def ofgem():
    """Ofgem: sitemap (10 pages, saved) -> candidate pages, 5 s apart."""
    for k in range(1, 11):
        fetch(f"https://www.ofgem.gov.uk/sitemap.xml?page={k}", DIR / "ofgem" / f"sitemap_{k}.xml", "ofgem", 5)
    pages = ofgem_pages()
    print(f"Ofgem candidate pages: {len(pages)}", flush=True)
    for k, loc in enumerate(pages, 1):
        fetch(f"https://www.ofgem.gov.uk/{loc}", DIR / "ofgem" / "pages" / (loc.replace("/", "__") + ".html"), "ofgem", 5)
        if k % 25 == 0:
            print(f"  {k}/{len(pages)}", flush=True)
    log("regulators", "ofgem_done", pages=len(pages))


MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def first_date(text):
    from datetime import datetime
    m = re.search(rf"\b(\d{{1,2}}) ({MONTHS}) (20\d\d)\b", text)
    return datetime.strptime(" ".join(m.groups()), "%d %B %Y").date().isoformat() if m else ""


def rsh():
    """Regulator of Social Housing: the GOV.UK search entry only says 'how well X is meeting standards'; the grade
    and whether it changed are in the judgement page attached to it. Two GOV.UK content API calls per item (saved)."""
    d = json.loads((DIR / "govuk" / "regulator-of-social-housing.json").read_text())
    docs = [x for x in d.get("results", []) if x.get("content_store_document_type") == "decision"]
    for k, x in enumerate(docs, 1):
        path = x["link"]
        page = fetch("https://www.gov.uk/api/content" + path, DIR / "govuk_content" / (path.strip("/").replace("/", "_") + ".json"),
                     "govuk_content", 2)
        try:
            det = json.loads(page or b"{}").get("details", {})
        except ValueError:
            continue
        for a in (det.get("attachments") or [])[:1]:
            u = a.get("url", "")
            if u.startswith("/government/"):
                fetch("https://www.gov.uk/api/content" + u, DIR / "govuk_content" / (u.strip("/").replace("/", "_") + ".json"),
                      "govuk_content", 2)
        if k % 50 == 0:
            print(f"  {k}/{len(docs)}", flush=True)


def rsh_text(link, n):
    path = link.replace("https://www.gov.uk", "")
    f = DIR / "govuk_content" / (path.strip("/").replace("/", "_") + ".json")
    if not f.exists() or not f.stat().st_size:
        return ""
    det = json.loads(f.read_text()).get("details", {})
    for a in (det.get("attachments") or [])[:1]:
        g = DIR / "govuk_content" / (a.get("url", "").strip("/").replace("/", "_") + ".json")
        if g.exists() and g.stat().st_size:
            return clean(json.loads(g.read_text()).get("details", {}).get("body", ""))[:n]
    return clean(det.get("body", ""))[:n]


def pdf_text(path, n):
    import pymupdf
    try:
        with pymupdf.open(path) as d:
            return clean(" ".join(p.get_text("text") for p in list(d)[:3]))[:n]
    except Exception as e:
        return f"(could not read PDF: {e})"


def long_text(x, n):
    """Longer text of one item from its saved file (FCA PDF, ICO or Ofgem page); otherwise the item text."""
    if x.source == "FCA final notice":
        f = DIR / "fca" / "notices" / x.link.rsplit("/", 1)[1]
        import pymupdf
        try:
            with pymupdf.open(f) as d:
                return clean(" ".join(p.get_text("text") for p in list(d)[:8]))[:n]
        except Exception:
            return x.text
    if x.source in ("ICO enforcement", "Ofgem"):
        f = (DIR / "ico" / "pages" / ("_".join(x.link.rstrip("/").split("/")[-3:]) + ".html") if x.source == "ICO enforcement"
             else DIR / "ofgem" / "pages" / (x.link.split("ofgem.gov.uk/", 1)[1].replace("/", "__") + ".html"))
        if f.exists():
            h = f.read_text(errors="replace")
            m = re.search(r"<main.*?</main>", h, re.S)
            return clean(re.sub(r"<(script|style|nav|header|footer)\b.*?</\1>", " ", m.group(0) if m else h, flags=re.S))[:n]
    if "Social Housing" in x.source:
        return rsh_text(x.link, n) or x.text
    return x.text


def items():
    n = D["text_chars"]
    rows = []
    names = {"ofgem": "Ofgem", "ofwat": "Ofwat", "the-pensions-regulator": "The Pensions Regulator",
             "regulator-of-social-housing": "Regulator of Social Housing", "office-for-students": "Office for Students",
             "competition-and-markets-authority": "CMA"}
    for org in D["govuk_orgs"]:
        d = json.loads((DIR / "govuk" / f"{org}.json").read_text() or "{}")
        for x in d.get("results", []):
            if org == "competition-and-markets-authority" and (x.get("content_store_document_type") != "cma_case"
                                                                or set(x.get("case_type") or []) & set(D["govuk_skip_cma_case_types"])):
                continue
            if org == "regulator-of-social-housing" and x.get("content_store_document_type") != "decision":
                continue
            link = "https://www.gov.uk" + x.get("link", "")
            text = (rsh_text(link, n) if org == "regulator-of-social-housing" else "") or clean(x.get("description"))[:n]
            rows.append(dict(source=f"GOV.UK: {names[org]}", title=x.get("title", ""), date=(x.get("public_timestamp") or "")[:10],
                             link=link, text=text,
                             doc_type=x.get("content_store_document_type", ""), case_type="; ".join(x.get("case_type") or [])))
    for f in sorted((DIR / "boe").glob("*.xml")):
        x = f.read_text(errors="replace")
        for it in re.findall(r"<item>(.*?)</item>", x, re.S):
            g = lambda t: clean((re.search(rf"<{t}>(.*?)</{t}>", it, re.S) or [None, ""])[1])
            try:
                dt = parsedate_to_datetime(g("pubDate")).date().isoformat()
            except Exception:
                dt = ""
            if dt and dt < SINCE:
                continue
            rows.append(dict(source=f"Bank of England ({f.stem})", title=g("title"), date=dt, link=g("link"),
                             text=g("description")[:n], doc_type="rss", case_type=""))
    lastmod = {}
    for f in sorted((DIR / "fca").glob("sitemap_*.xml")):
        for u, m in re.findall(r"<loc>([^<]*/publication/final-notices/[^<]*)</loc><lastmod>([^<]*)", f.read_text(errors="replace")):
            lastmod[u.rsplit("/", 1)[1]] = m[:10]
    for f in sorted((DIR / "fca" / "notices").glob("*.pdf")):
        if f.stat().st_size:
            rows.append(dict(source="FCA final notice", title=f.stem.replace("-", " "), date=lastmod.get(f.name, ""),
                             link=f"https://www.fca.org.uk/publication/final-notices/{f.name}", text=pdf_text(f, n),
                             doc_type="final notice", case_type=""))
    for f in sorted((DIR / "ico" / "pages").glob("*.html")):
        x = f.read_text(errors="replace")
        title = clean((re.search(r"<h1[^>]*>(.*?)</h1>", x, re.S) or [None, f.stem])[1])
        main = re.search(r"<main.*?</main>", x, re.S)
        body = clean(re.sub(r"<(script|style|nav|header|footer)\b.*?</\1>", " ", main.group(0) if main else x, flags=re.S))
        y, m = f.stem.split("_")[:2]
        rows.append(dict(source="ICO enforcement", title=title, date=first_date(body) or f"{y}-{m}", text=body[:n], doc_type="enforcement",
                         link=f"https://ico.org.uk/action-weve-taken/enforcement/{y}/{m}/{f.stem.split('_', 2)[2]}/", case_type=""))
    R = pd.DataFrame(rows).drop_duplicates("link")
    R.insert(0, "item_id", [f"r{i:04d}" for i in range(len(R))])
    # Ofgem (added 12 Nov 2026) goes after the first sources so their item ids do not change
    old = INTERIM / "reg_items.csv"
    if old.exists():
        O = pd.read_csv(old, dtype=str).fillna("")
        O = O[O.source != "Ofgem"]
        assert list(O.link) == list(R.link[:len(O)]), "existing regulator items changed order"
    of = []
    for f in sorted((DIR / "ofgem" / "pages").glob("*.html")):
        x = f.read_text(errors="replace")
        if not x:
            continue
        title = clean((re.search(r"<h1[^>]*>(.*?)</h1>", x, re.S) or [None, f.stem])[1])
        main = re.search(r"<main.*?</main>", x, re.S)
        body = clean(re.sub(r"<(script|style|nav|header|footer)\b.*?</\1>", " ", main.group(0) if main else x, flags=re.S))
        pub = re.search(r'property="article:published_time" content="([^"]+)"', x) or re.search(r'datetime="(20[^"]{8})', x)
        dt = pub.group(1)[:10] if pub else first_date(body)
        if dt and dt < SINCE:
            continue
        of.append(dict(source="Ofgem", title=title, date=dt, link="https://www.ofgem.gov.uk/" + f.stem.replace("__", "/"),
                       text=body[:n], doc_type=f.stem.split("__")[0], case_type=""))
    if of:
        F = pd.DataFrame(of)
        F.insert(0, "item_id", [f"r{i:04d}" for i in range(len(R), len(R) + len(F))])
        R = pd.concat([R, F], ignore_index=True)
    R.to_csv(INTERIM / "reg_items.csv", index=False)
    log("regulators", "items", n=len(R), **{k: int(v) for k, v in R.source.value_counts().items()})
    print(R.source.value_counts().to_string())


if __name__ == "__main__":
    {"pull": pull, "rsh": rsh, "items": items, "ofgem": ofgem}[sys.argv[1]]()
