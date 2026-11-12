"""Stage 2 item 4 (Tom, 12 Nov 2026): Slice B news from NewsAPI.ai (Event Registry), replacing GDELT.

  python src/newsapi.py pull     # topic searches x UK / Ireland sources, every page saved in data/raw/newsapi/
  python src/newsapi.py stories  # remove duplicates -> data/interim/news_stories.csv (GDELT's are kept as news_stories_gdelt.csv)

Service: https://newsapi.ai (API at eventregistry.org/api/v1/article/getArticles, key NEWSAPI_KEY in .env only;
written approval held by Tom - "newsapi_approval" in the project folder). One search = one page of up to 100
articles = 1 token. The free tier holds recent articles only (documented as the last 30 days; on 12 Nov 2026 it
returned articles back to 20 Sep 2026); archive searches need a paid plan. Articles come with full text.
Searches: the Slice B terms in the headline (keywordLoc=title), English, publisher located in the UK or Ireland,
Event Registry's duplicate filter on. A query may hold at most 15 words on this tier, so the incident terms are
split into two queries."""
import json
import os
import re
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

from common import INTERIM, RAW, log, settings

ST = settings()
B = ST["stage2"]["slice_b"]
RUN = date.fromisoformat(ST["run"]["run_date"])
DIR = RAW / "newsapi"
URL = "https://eventregistry.org/api/v1/article/getArticles"
LOC = {"UK": "http://en.wikipedia.org/wiki/United_Kingdom", "IE": "http://en.wikipedia.org/wiki/Republic_of_Ireland"}
MAX_SEARCHES = 1000


def queries():
    out = []
    for t, terms in B["topics"].items():
        parts, cur = [], []
        for x in terms:                                     # at most 15 words per query
            if sum(len(y.split()) for y in cur + [x]) > 15:
                parts.append(cur); cur = []
            cur.append(x)
        parts.append(cur)
        for i, p in enumerate(parts, 1):
            out.append((t if len(parts) == 1 else f"{t}{i}", p))
    return out


def search(c, name, terms, page, used):
    f = DIR / f"{c}_{name}_p{page:03d}.json"
    if f.exists():
        return json.loads(f.read_text())
    if used[0] >= MAX_SEARCHES:
        raise SystemExit("search limit reached")
    f.parent.mkdir(parents=True, exist_ok=True)
    body = {"action": "getArticles", "keyword": terms, "keywordOper": "or", "keywordLoc": "title",
            "sourceLocationUri": [LOC[c]], "dateStart": (RUN - timedelta(days=round(B["months"] * 30.44))).isoformat(),
            "dateEnd": RUN.isoformat(), "lang": "eng", "isDuplicateFilter": "skipDuplicates", "articlesPage": page,
            "articlesCount": 100, "articlesSortBy": "date", "resultType": "articles", "dataType": ["news"],
            "apiKey": os.environ["NEWSAPI_KEY"]}
    for attempt in range(5):
        time.sleep(2)
        r = requests.post(URL, json=body, timeout=120)
        if r.status_code == 429 or r.status_code >= 500:
            log("newsapi", "rate_limit_pause", status=r.status_code); time.sleep(60 * (attempt + 1)); continue
        break
    used[0] += 1
    d = r.json()
    log("newsapi", "search", country=c, query=name, page=page, status=r.status_code,
        n=len(d.get("articles", {}).get("results", [])))
    if "error" in d:
        raise SystemExit(f"NewsAPI error: {d['error']}")
    f.write_text(json.dumps(d))
    return d


def pull():
    used = [0]
    for c in LOC:
        for name, terms in queries():
            d = search(c, name, terms, 1, used)
            pages = d.get("articles", {}).get("pages", 0) or 0
            for p in range(2, pages + 1):
                search(c, name, terms, p, used)
    print(f"{used[0]} searches made this run")
    log("newsapi", "pull_done", searches=used[0])


def stories():
    rows = []
    for f in sorted(DIR.glob("*_p*.json")):
        c, name = f.stem.split("_")[:2]
        for a in json.loads(f.read_text()).get("articles", {}).get("results", []):
            rows.append(dict(uri=a.get("uri", ""), title=re.sub(r"\s+", " ", a.get("title") or "").strip(),
                             domain=(a.get("source") or {}).get("uri", ""), sourcecountry=c, seendate=a.get("date", ""),
                             url=a.get("url", ""), topic=re.sub(r"\d*b?$", "", name), duplicate=a.get("isDuplicate", False),
                             body=re.sub(r"\s+", " ", a.get("body") or "")[:1200]))
    S = pd.DataFrame(rows)
    n0 = len(S)
    S = S.drop_duplicates("uri")
    S["key"] = S.title.str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.strip()
    S = S.sort_values("seendate").drop_duplicates("key").drop(columns=["key"])
    S = S[S.duplicate.astype(str) != "True"]
    S.insert(0, "story_id", [f"a{i:05d}" for i in range(len(S))])
    S.to_csv(INTERIM / "news_stories.csv", index=False)
    log("newsapi", "stories", articles=n0, stories=len(S))
    print(f"{n0} articles -> {len(S)} stories after removing duplicates")
    print(S.groupby(["sourcecountry", "topic"]).size().to_string())


if __name__ == "__main__":
    {"pull": pull, "stories": stories}[sys.argv[1]]()
