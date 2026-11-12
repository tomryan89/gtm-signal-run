"""Stage 2, Slice B: news from GDELT's DOC 2.0 API, searched by topic (Tom, 12 Nov 2026).

  python src/news.py pull     # weekly windows x 3 topic queries; every reply saved in data/raw/gdelt/; resumable
  python src/news.py stories  # remove duplicate stories -> data/interim/news_stories.csv

A week whose combined query hits the result cap is re-queried term by term, so nothing is cut off. GDELT refuses
fast callers (429); we wait settings gap_seconds between requests and back off longer on every refusal."""
import json
import re
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from common import INTERIM, RAW, log, settings

ST = settings()
B = ST["stage2"]["slice_b"]
URL = "https://api.gdeltproject.org/api/v2/doc/doc"
DIR = RAW / "gdelt"
RUN = date.fromisoformat(ST["run"]["run_date"])
_last = [0.0]


def q(terms):
    t = " OR ".join(f'"{x}"' if " " in x else x for x in terms)
    c = " OR ".join(f"sourcecountry:{x}" for x in B["countries"])
    return f"({t}) ({c})" if len(terms) > 1 else f"{t} ({c})"


def get(name, terms, start, end):
    f = DIR / "weeks" / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    f.parent.mkdir(parents=True, exist_ok=True)
    p = dict(query=q(terms), mode="artlist", format="json", maxrecords=B["max_records"], sort="datedesc",
             startdatetime=start.strftime("%Y%m%d%H%M%S"), enddatetime=end.strftime("%Y%m%d%H%M%S"))
    for attempt in range(10):
        wait = B["gap_seconds"] - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = requests.get(URL, params=p, timeout=120)
        except requests.RequestException as e:
            log("gdelt", "error", query=name, error=str(e)[:200]); time.sleep(60); continue
        if r.status_code == 429:
            log("gdelt", "rate_limit_pause", query=name, attempt=attempt)
            time.sleep(60 * (attempt + 1)); continue
        if r.status_code >= 500:
            log("gdelt", "server_error", query=name, status=r.status_code); time.sleep(60); continue
        try:
            d = r.json() if r.text.strip() else {"articles": []}
        except ValueError:
            d = {"articles": [], "_message": r.text[:300]}
        d["_query"] = p
        f.write_text(json.dumps(d))
        log("gdelt", "request", query=name, status=r.status_code, n=len(d.get("articles", [])))
        return d
    log("gdelt", "gave_up", query=name)
    raise SystemExit(f"GDELT kept refusing ({name}); rerun later - saved weeks are kept")


def weeks():
    end = datetime(RUN.year, RUN.month, RUN.day)
    start = end - timedelta(days=round(B["months"] * 30.44))
    w = []
    while end > start:
        s = max(start, end - timedelta(days=7))
        w.append((s, end))
        end = s
    return w


def pull():
    W = weeks()
    t0 = time.time()
    for k, (s, e) in enumerate(W, 1):
        for topic, terms in B["topics"].items():
            name = f"{s:%Y%m%d}_{topic}"
            d = get(name, terms, s, e)
            if len(d.get("articles", [])) >= B["max_records"]:
                for term in terms:
                    get(f"{s:%Y%m%d}_{topic}_{re.sub(r'[^a-z0-9]+', '_', term.lower())}", [term], s, e)
        print(f"  week {k}/{len(W)} ({s:%d %b}) {(time.time() - t0) / 60:.0f} min", flush=True)
    log("gdelt", "pull_done", weeks=len(W), secs=round(time.time() - t0))


def stories():
    rows = []
    for f in sorted((DIR / "weeks").glob("*.json")):
        d = json.loads(f.read_text())
        parts = f.stem.split("_")
        for a in d.get("articles", []):
            rows.append(dict(week=parts[0], topic=parts[1], term="_".join(parts[2:]), title=a.get("title", ""),
                             url=a.get("url", ""), domain=a.get("domain", ""), seendate=a.get("seendate", ""),
                             language=a.get("language", ""), sourcecountry=a.get("sourcecountry", ""),
                             note=d.get("_message", "")))
    S = pd.DataFrame(rows)
    n0 = len(S)
    S = S[S.language.eq("English") | S.language.eq("")]
    S["key"] = S.title.str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    topics = S.groupby("key").topic.apply(lambda s: "; ".join(sorted(set(s))))
    S = S.sort_values("seendate").drop_duplicates("url").drop_duplicates("key")   # same story: same URL or same headline
    S["topics"] = S.key.map(topics)
    S = S.drop(columns=["topic", "term"]).reset_index(drop=True)
    S.insert(0, "story_id", [f"n{i:05d}" for i in range(len(S))])
    S.to_csv(INTERIM / "news_stories.csv", index=False)
    log("gdelt", "stories", articles=n0, stories=len(S))
    print(f"{n0} articles -> {len(S)} stories after removing duplicates")
    print(S.topics.value_counts().to_string())


if __name__ == "__main__":
    {"pull": pull, "stories": stories}[sys.argv[1]]()
