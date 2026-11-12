"""Rule 3: one small request to each Step 3 source; saves the raw reply to data/raw/source_tests/."""
import json, os, sys
import requests
from common import RAW, log

D = RAW / "source_tests"
D.mkdir(parents=True, exist_ok=True)
E = os.environ


def save(name, r):
    (D / f"{name}.json").write_text(r.text)
    print(f"{name}: HTTP {r.status_code}, {len(r.text)} bytes, rate headers:",
          {k: v for k, v in r.headers.items() if "limit" in k.lower() or "remaining" in k.lower()})
    log("source_test", name, status=r.status_code)
    try:
        return r.json()
    except Exception:
        print("   not JSON:", r.text[:200]); return None


def fca():
    h = {"X-Auth-Email": E["FCA_EMAIL"], "X-Auth-Key": E["FCA_API_KEY"], "Content-Type": "application/json"}
    base = "https://register.fca.org.uk/services/V0.1"
    j = save("fca_search", requests.get(f"{base}/Search", params={"q": "Barclays Bank UK PLC", "type": "firm"}, headers=h, timeout=30))
    print("   ", json.dumps(j)[:600])
    j = save("fca_firm", requests.get(f"{base}/Firm/759676", headers=h, timeout=30))
    print("   ", json.dumps(j)[:900])
    j = save("fca_individuals", requests.get(f"{base}/Firm/759676/Individuals", headers=h, timeout=30))
    print("   ", json.dumps(j)[:700])


def reed():
    r = requests.get("https://www.reed.co.uk/api/1.0/search", params={"keywords": "third party risk", "resultsToTake": 5},
                     auth=(E["REED_API_KEY"], ""), timeout=30)
    j = save("reed_search", r)
    if j:
        print("    total:", j.get("totalResults"), "| first:", json.dumps((j.get("results") or [{}])[0])[:600])


def adzuna():
    r = requests.get("https://api.adzuna.com/v1/api/jobs/gb/search/1",
                     params={"app_id": E["ADZUNA_APPLICATION_KEY"], "app_key": E["ADZUNA_API_KEY"],
                             "what_phrase": "third party risk", "results_per_page": 5}, timeout=30)
    j = save("adzuna_search", r)
    if j:
        print("    count:", j.get("count"), "| first:", json.dumps((j.get("results") or [{}])[0])[:700])


def govuk():
    r = requests.get("https://www.gov.uk/api/search.json",
                     params={"filter_format": "cma_case", "filter_case_type": "mergers", "count": 3,
                             "order": "-opened_date", "fields[]": ["title", "link", "opened_date", "case_state", "public_timestamp"]},
                     timeout=30)
    j = save("govuk_cma", r)
    if j:
        print("    total:", j.get("total"), "|", json.dumps(j.get("results"))[:800])


def ch():
    import companies_house as c
    fh = c.get("/company/00048839/filing-history", "filing_test", "00048839", params={"items_per_page": 5})
    print("ch filing history: items", fh.get("total_count"), "|", json.dumps(fh.get("items", [])[:1])[:500])
    of = c.get("/company/00048839/officers", "officers_test", "00048839", params={"items_per_page": 3})
    print("ch officers: total", of.get("total_results"), "|", json.dumps(of.get("items", [])[:1])[:400])


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print("=" * 10, name)
        try:
            globals()[name]()
        except Exception as ex:
            print("   FAILED:", type(ex).__name__, str(ex)[:300])
