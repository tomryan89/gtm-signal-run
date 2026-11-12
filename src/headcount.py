"""Point 18: headcount growth. An entity moved up at least one pay gap staff band between the last two pay gap
years. Dated from when the latest report was submitted (DateSubmitted).

  python src/headcount.py  -> data/interim/headcount_growth.csv (every UK universe company that moved up)"""
import pandas as pd

from common import INTERIM, OUTPUT, RAW, settings
from names import norm_ch_number

ST = settings()


def main():
    bands = ["Less than 250", "250 to 499", "500 to 999", "1000 to 4999", "5000 to 19,999", "20,000 or more"]
    files = sorted((RAW / "gpg").glob("gpg_*.csv"))
    frames = []
    for f in files:
        d = pd.read_csv(f, dtype=str).fillna("")
        d["year"] = int(f.stem.split("_")[1])
        d["num"] = d.CompanyNumber.map(norm_ch_number)
        frames.append(d[d.num != ""][["num", "EmployerName", "EmployerSize", "DateSubmitted", "year"]])
    allf = pd.concat(frames).drop_duplicates(["num", "year"], keep="last").sort_values(["num", "year"])
    allf["rank"] = allf.EmployerSize.map(lambda x: bands.index(x) if x in bands else -1)
    last2 = allf.groupby("num").tail(2)
    prev = last2.groupby("num").head(1).set_index("num")
    last = last2.groupby("num").tail(1).set_index("num")
    both = prev.join(last, lsuffix="_prev", rsuffix="_last", how="inner")
    both = both[both.year_prev != both.year_last]
    up = both[(both.rank_prev >= 0) & (both.rank_last > both.rank_prev)].reset_index()
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str)
    up = up[up.num.isin(u.entity_id)]
    up["date"] = up.DateSubmitted_last.str[:10].str.replace("/", "-")
    out = up.rename(columns={"num": "entity_id", "EmployerName_last": "employer"})[
        ["entity_id", "employer", "EmployerSize_prev", "EmployerSize_last", "date", "year_prev", "year_last"]]
    out.to_csv(INTERIM / "headcount_growth.csv", index=False)
    print(f"{len(both)} companies with two filings; {len(out)} universe companies moved up a band")
    print(out.year_last.value_counts().to_string())
    print(out.head(5).to_string())


if __name__ == "__main__":
    main()
