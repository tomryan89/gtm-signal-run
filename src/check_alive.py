"""Fetch the Companies House profile for every UK entity in the provisional universe that passed size and
private-sector. Cached per company, so it resumes where it stopped. ~2 requests/second (the API limit)."""
import time

import pandas as pd

import companies_house as ch
from common import OUTPUT, RAW, log


def main():
    u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str)
    nums = u[(u.country == "UK") & (u.id_type == "Companies House")].entity_id.tolist()
    todo = [n for n in nums if not (RAW / "ch" / "profile" / f"{n}.json").exists()]
    print(f"{len(nums)} UK companies, {len(nums) - len(todo)} already cached, {len(todo)} to fetch "
          f"(~{len(todo) / 1.9 / 3600:.1f} h)")
    t0 = time.time()
    for i, n in enumerate(todo, 1):
        ch.profile(n)
        if i % 500 == 0:
            rate = i / (time.time() - t0)
            print(f"  {i}/{len(todo)}  {rate:.2f}/s  ~{(len(todo) - i) / rate / 60:.0f} min left", flush=True)
    log("companies_house", "alive_check_done", fetched=len(todo), secs=round(time.time() - t0))
    print("done - now rerun: python src/build_universe.py")


if __name__ == "__main__":
    main()
