# GTM Signal Run

Builds a ranked list of large UK and Irish private-sector organisations ("groups"), scored on public signals that
suggest they may need third-party risk management software now. The output is one spreadsheet for sales reps: every
group in a band (Act now, Warming, Strong fit, Fit only), a score, the three strongest signals with links, and a
four-line brief for every Act now group.

- **`settings.toml`**: every weight, threshold, keyword list, investor and recruiter list, and the run date. Change the
  scoring here, not in the code.
- **`GTM Signal Run Build Instructions.md`**: the full specification and the record of every decision and result,
  run by run (v2 to v6).
- **`reference/brand_lookup.csv`**: brand or trading names mapped to groups (e.g. "Amazon" -> the Amazon group).
  It holds names and answers only; the advert and news text behind each answer is not shared.
- **`corrections/`**: hand corrections (brand overrides, CMA case matches, entities moved between groups).
- **`src/`**: the code. Each script's first lines say what it does and how to run it.

**Not in this repository, and why:**

| Left out | Why |
|---|---|
| `.env` (API keys) | Secret. Copy `.env.example` to `.env` and fill it in instead. |
| `data/` (every download and working file) | Large. Some sources license the data for the key holder's own use only, not republishing: job adverts (Reed, Adzuna), news (NewsAPI.ai) and ransomware claims (ransomware.live). |
| `output/`, `full_run_review/`, `pilot_review/`, `logs/` | Spreadsheets and review packs name individuals (e.g. FCA Senior Managers). |

A fresh copy therefore starts from nothing and downloads everything on its first full run.

## Setting up

1. Install Python 3.12 or newer.
2. In the project folder, create a virtual environment and install the packages:
   ```
   python -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env`. Fill in each key; the comments in `.env.example` say where to get each one.
4. Optional: the listed-company principal-risk verdicts come from a separate project (the "Principal Risks Scanner").
   - Set `RISK_SCANNER_DIR` in `.env` to that project's folder.
   - Put its results workbook (named in `settings.toml` `[scanner] file`) in `UPLOADS_DIR`.
   - Without it, the annual-report step still runs on the private-company accounts.

Run every script from the project folder as `.venv/bin/python src/<script>.py ...`.

**Ground rules built into the code:**
- **Downloads:** every download is saved under `data/raw/` and never fetched twice, and every rate limit is respected (the code pauses and retries).
- **Model calls:** every model step goes through the Anthropic Batch API, with an `estimate` command that prints the cost before anything is sent. Its batch id is saved in `data/interim/*_batch.json`, so it is never sent twice.
- **Run log:** `data/run_log.jsonl` records every request, failure, pause and model cost.

## What each step produces

| Step | Scripts | Produces |
|---|---|---|
| 1. Universe | `download_cbi`, `parse_cbi`, `build_universe`, `check_alive`, `build_universe` again, `fca_additions pra` | `output/step1/universe.csv`: every live private-sector UK or Irish entity above the size line, from the UK gender pay gap service, the modern slavery registry, the Irish CRO and Central Bank registers, and the PRA lists |
| 2. Groups | `group_accounts fetch`, `group_accounts build`, `pilot` (with `[run] scope = "full"`) | `output/full/groups.csv`, `entities.csv`: entities joined into corporate groups by ownership (Companies House owners), stopping below investors and state bodies; `merges` and `corrections/` applied |
| 3. Stage 1 signals | `fca match`, `fca smf`, `jobs pull`, `jobs match`, `ch_signals`, `headcount`, `cma`, `scanner`, `brands candidates/send/collect`, `classify select/send/collect` | FCA-authorised firms and new Senior Managers; job adverts (Reed, Adzuna) classified by Opus; Companies House filings (directors, charges, share allotments, re-registration); pay gap headcount growth; CMA merger cases; listed-company principal risks |
| 4. Stage 2 signals | `slice_a fetch/send/collect` and `scans_full fetch ... verdict-collect` (annual reports); `newsapi pull/stories` and `stage2_model send/collect news, news2, internal, internal2` (news); `regulators pull/items` and `stage2_model ... reg, reg_rel, ofgem_rel` (regulators); `ch_acquisitions` and `stage2_model ... acq` (ownership changes); `ransomware pull/victims`; `careers find-send ... classify-collect` (Irish careers sites); then `stage2_signals` | `data/interim/stage2_signals.csv`: annual-report verdicts, news events, regulatory actions, ownership changes, ransomware claims, peer incidents |
| 5. Score | `signals`, then `score` | `output/full/signals_scored.csv` and `ranked.csv`: need + timing (with decay), band and rank |
| 6. Names and sectors | `names_sectors send/collect`, then `score` again | the name a salesperson would search for, and the main-business sector, for every Act now, Warming and Strong fit group |
| 7. Briefs | `briefs estimate/send/collect` (first time), then `peer_kind send/collect` and `briefs_stage2 select/estimate/send/collect --base=<snapshot> --tag=<version>` | four-line briefs for Act now groups (what changed, why it matters, angle, who to contact) |
| 8. Export | `export_full` (set `[run] export_version`) | `full_run_review/GTM full run ranked <version> <date>.xlsx`, copied to `UPLOADS_DIR` |

The build instructions give each step in full, with the order used in the last run (see the "Run order" lines under v4, v5 and v6).

## Three ways to run it

Before any run:
- Set `[run] run_date` in `settings.toml` to today. Every look-back window and the decay of old signals count from it.
- Bump `[run] export_version` (e.g. `v7`).
- Copy the current `output/full/` and `data/interim/briefs_full.csv` to `output/before_changes/<version>_full/`, so briefs are rewritten only where signals changed.

Cached downloads are reused. To refresh a source:
- Move its folder out of `data/raw/` (e.g. into `data/archive/<date>/`) so it is downloaded again.
- Move the matching `data/interim/*_batch.json` files aside so the model step can be sent again.

### Monthly rescore (no new downloads): about 15-30 minutes, under $2

- **What it does:** ages every signal by one month, so triggers decay and bands move. Then it writes briefs for groups that became Act now and gets names and sectors for groups that entered the top three bands.
- **Steps:**
  1. `signals`, `score`.
  2. `names_sectors` for new top-band groups.
  3. `peer_kind send --add`.
  4. `briefs_stage2 ... --base=<last version>_full --tag=<new version>`.
  5. `export_full`.
- **Cost:** model spend only for the new briefs and names: typically $0.50-2.

### Light refresh (the fast-moving sources): about half a day, $30-40

- **What it re-pulls:**
  - job adverts: `jobs pull/match`, `classify` (about $4);
  - news: `newsapi pull/stories`, `stage2_model news`, then `news2`, `internal` and `internal2` (about $20-25);
  - regulators: `regulators pull/items`, `stage2_model reg`, `reg_rel`, `ofgem_rel` (about $2);
  - ransomware claims: `ransomware pull/victims` (no model cost);
  - FCA Senior Managers: `fca smf`.
- **Then:** `stage2_signals`, and the monthly rescore steps.
- **Time:** about 4-6 hours, mostly waiting on rate limits and batches.
- **Note:** the NewsAPI.ai free tier only reaches back about a month.

### Full run (everything from scratch): about 2-3 days elapsed, $70-90

- **What it does:** every step in the table above, on every group.
- **Time:** it is long because the free APIs are rate-limited.
  - The last run made about 100,000 Companies House requests at 2 a second (most of a day) and 53,000 FCA Register requests (about 16 hours). The two run side by side.
  - It also read about 1,700 annual reports.
- **Computer:** must stay on. Every step resumes from its saved downloads if interrupted.
- **Model spend, last run (Nov 2026), about $71:**
  - news reading $25;
  - annual reports (find, transcribe, verdicts) $17;
  - Irish careers sites $12;
  - briefs $8;
  - job advert classification $4;
  - brands, names and sectors $3;
  - regulators and ownership changes $3;
  - other small checks under $1.
- **Before sending:** each model step's `estimate` prints its projected cost.

## Before sharing a list

- Every signal is a lead to verify: open its link before using it.
- A ransomware entry is an attacker's claim, not a confirmed breach. It must never be quoted to the account; the briefs already leave it out of the angle.
- The "How to read this" tab in the spreadsheet explains every column, band and signal, and when each source was pulled.
