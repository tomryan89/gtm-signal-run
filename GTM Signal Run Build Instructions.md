# GTM Signal Run: Build Instructions

Nov 10, 2026 · @Tom Ryan · Updated 11 Nov 2026 after the Step 3 pilot reviews (grouping, matching, universe and signal-rule changes; Steps 2-4 approved with corrections; Step 5 changed by Tom); pilot approved 11 Nov 2026 with the Step 7 changes (Act now rule, Opus-only classification, four-line briefs, universe additions)

## What this builds

One ranked spreadsheet of large private-sector organisations in the UK and Ireland, scored on public signals that third-party risk is worth raising now. The team works from it for three months.

- **In scope:** any private-sector organisation with 250+ staff or £36m+ turnover, regulated or not.
- **Out of scope:** public sector, tender data, competitor wins, CRM data, backtesting, and modern slavery as a signal.
- **One row per account group**, not per legal entity. Signals from a group's entities are added together.
- **Free sources only**, and a model budget of $100.
- **Built in two stages.** These instructions cover stage 1. Stage 2 is outlined at the end and starts only after the stage 1 list is in use.

Steps 1 to 6 end in a pilot that is reviewed before anything runs at full size.

## Before you start (Tom)

Do these once, before opening Claude Code.

- [x] **Companies House key.** Register at the [developer hub](https://developer.company-information.service.gov.uk), create a **live** application, and copy the REST key (not the streaming key).
- [x] **FCA Register key.** Sign up on the [developer portal](https://register.fca.org.uk/Developer/s/). Calls need your email address and the key.
- [x] **Reed key.** Free from [Reed's developer page](https://www.reed.co.uk/developers/jobseeker).
- [x] **Adzuna app ID and key.** Free from the [Adzuna developer portal](https://developer.adzuna.com).
- [x] **Claude API key.** Create a new key in the Claude Console for this project only, so its spend shows separately and the key can be switched off without affecting the risk-scanner.
- [x] **Spend limit.** Set $100 a month in the Claude Console.
- [ ] **Project folder.** Create an empty folder for this build and save this document into it as a Markdown file.
- [ ] **Keys file.** Claude Code will create a `.env` file in that folder (a private settings file that holds keys) and tell you where to paste each key. Never paste keys into the chat.
- [ ] **Listed-company app results.** Find the results file from the existing app and note where it is. Step 3 needs it.

### Handing over to Claude Code

Open Claude Code in the project folder and send this:

```
Read the build instructions file in this folder. Follow the "Rules for Claude Code" section throughout. Do Step 1 only, then stop and show me what you produced and what I need to check.
```

After you have checked a step, send: `Step N is approved. Do the next step only, then stop.`

## Rules for Claude Code

These apply to every step.

1. **One step at a time.** Finish the step, show the output and the checks, then stop and wait for Tom's approval.
2. **Explain in plain English.** Tom is new to app building. Say what each step does and what he needs to do, without assuming developer knowledge.
3. **Test every source before building on it.** Make one small request, show the fields that came back, and stop if the access, limits or fields differ from these instructions. The source details were not re-checked when this was written.
4. **Save every raw download to `data/raw` and never fetch the same thing twice.** Every step must be able to resume where it stopped.
5. **Respect rate limits.** Pause and retry. Never work around a limit.
6. **Keys live only in the `.env` file.** Never print them or include them in saved code history.
7. **Keep all weights, thresholds and keyword lists in one settings file**, so rescoring never needs a code change or a new download. The run date is fixed there too; age decay is calculated from it.
8. **Never guess a match.** Anything that cannot be tied to an organisation with confidence goes to a review file with the reason.
9. **No model call at full size without Tom's go-ahead.** Report cost per item and the projected total first.
10. **Do not start stage 2.**

## Step 1: Build the universe

Produces the list of every legal entity that passes the fit filter. Runs on the whole of the UK and Ireland; the downloads are free.

**Claude Code:**

1. Create the project structure, the `.env` file and the settings file. Tell Tom where to paste each key.
2. Download the latest UK gender pay gap file and the modern slavery registry file.
3. Download the CRO daily company file for Ireland, and the Central Bank of Ireland registers.
4. Download the housing provider and universities registers.
5. Apply the fit filter in Reference A: size, private sector, alive. Check "alive" against Companies House and CRO status.
6. For Ireland, apply the Irish size rule in Reference C. Keep only firms on these Central Bank registers: credit institutions, insurers and reinsurers, investment firms, fund administrators (in the Section 10 register, only firms whose Institution Type is "Section 10 Investment Firm"), fund managers (AIFMs and UCITS management companies), and payment and e-money institutions. Remove credit unions, retail investment intermediaries, retail credit, high-cost credit, credit servicing and crypto-asset firms. Size stays "unconfirmed".
7. **Add regulated firms the size files miss** (11 Nov 2026, size "unconfirmed"): every bank, building society and insurer on the PRA's published lists (banks, building societies and insurers CSVs; the Bank of England refuses scripted downloads, so Tom downloads them into Uploads), with their FCA record and Companies House number; and job-advert employers whose name (without legal-form words) exactly matches an FCA firm that is an investment firm or a payment or e-money institution. Insurance special purpose vehicles are not added. A firm whose FCA record has no Companies House number is first matched to a universe entry that has no company number (pay gap entry or Irish company) with exactly the same name, e.g. Nationwide Building Society; otherwise it is added as `FRN-<number>`, its own group. Any file name containing "Banks List 2611" (or the website's "banks-list-2611") is read.
8. Remove academy trusts and schools: entities whose industry codes are all primary or secondary education (85100, 85200, 85310, 85320), or whose name contains "academy trust", "academies trust", "multi-academy", "learning trust" or "schools trust". A name that only contains academy, academies or schools is not enough. Charities stay.

**Output:** a universe file with one row per entity (name, identifier, country, industry code, size band, which size test it passed), and a removed file listing every entity dropped and the test that dropped it.

**Tom checks:**

- [ ] The row count is plausible (expect tens of thousands of UK entities).
- [ ] 20 random rows are real, large, private-sector organisations.
- [ ] The removed file contains councils, NHS bodies and government departments, and no obvious companies.

## Step 2: Group entities into accounts

Produces one account group per corporate family, so that a bank's several legal entities score as one account.

**Claude Code:**

1. For each UK entity, read its ownership records at Companies House ("persons with significant control"). Where the owner is a UK company holding **more than 50%** (the 50-75% or 75-100% bands of shares, votes or, for LLPs, surplus assets), follow it upward until there is no such owner. That top entity is the group. The right to appoint directors alone is not enough.
2. **Stop the walk below investors.** An investor is an owner with industry code 64301-64306, 66300 or 65300; or whose name contains L.P., LP, Fund, Capital Partners, Private Equity, Pension or Superannuation; or a known financial sponsor (KKR, BGF, Blackstone, CVC, Carlyle, Advent, Apollo, Bain Capital, Cinven, Permira, EQT, TDR, Macquarie, LDC; the list is in the settings file). The group is the highest company below the investor. Record the investor in its own column; never group by it. A sponsor's name must start the owner's name ("Partners Group AG", not "Health Partners Group Limited"). An owner is **not** an investor when it shares a brand with the company it owns: the same first distinctive word (Jupiter / Jupiter, GAM / GAM, Lloyds / Lloyds). Sponsors added 11 Nov 2026: Brookfield, CK Hutchison, CK Infrastructure, Global Infrastructure Partners, BlackRock, OMERS, CPP Investments, Ontario Teachers, Antin, Ardian, 3i, Bridgepoint, Hg, Warburg Pincus, Clayton Dubilier & Rice, PAI Partners, BC Partners, Apax, Inflexion, Stonepeak, I Squared, IFM Investors, Partners Group, Temasek, GIC, DBAY.
   - *Not done:* grouping single-company groups that sit under the same investor through a shared intermediate holding company. The ownership records name the investor directly (e.g. KKR & Co. Inc. for each KKR solar company), so the intermediate company is not in the data. A stand-in (same investor and same registered office) is listed in `output/step2/investor_sibling_proposals.csv` but not applied: it would also join unrelated portfolio companies that use the investor's office address.
3. Group entities whose top UK company has a more-than-50% foreign corporate parent (that is not an investor) by the parent's normalised name.
4. Treat a listed company, which has no owner record, as its own top.
5. Group Irish entities by shared name stem, and flag every Irish group for review. Ireland has no free ownership data.
6. Treat housing providers, universities and anything else without ownership records as a group of one.
7. **Name each group** after its foreign parent where there is one (unless that name is mostly numbers, e.g. "2283485 Alberta Ltd"); otherwise after the top UK company. Fall back to the member with the largest staff band in the pay gap file only when that name contains Bidco, Topco, Midco, Holdco, Finco or Borrower, or is mostly numbers (fallback ties: the top company, then the member nearest the top, then the shortest name). Never use a lower-cased name stem. A group made up only of firms added from the PRA lists or as advert employers is named after its regulated firm, not a holding company above it (full run review, 11 Nov 2026). Tom's single-entity moves live in `corrections/entity_moves.csv` (e.g. J.P. Morgan Personal Investing into the JPMorgan Chase group).
8. **Merge groups Tom has confirmed are one business** (listed in the settings file, `grouping.merges`, e.g. Deutsche Bank's foreign-parent, UK and Irish groups). Single entities Tom has approved moving are listed in `corrections/entity_moves.csv` (the 30 merge proposals of 11 Nov 2026 and Citibank UK into Citigroup). The general rule behind those proposals (a UK branch record, BR or FC number, joins the group whose foreign parent has the same name; an Irish entity joins a UK or foreign-parent group when the brand lookup maps the same brand to both) still only proposes: new proposals go to `output/step2/merge_proposals.csv` for Tom.
9. List every group with more than 10 entities for Tom to check.

**Output:** a group file listing each group, its member entities, and how each member was linked (ownership record, foreign parent name, name stem, or single entity).

**Tom checks:**

- [ ] Ten well-known groups each appear once, with their entities together.
- [ ] The share of entities with no ownership record is reported and looks tolerable.
- [ ] No obviously unrelated companies have been merged because of a similar name.
- [ ] The list of groups with more than 10 entities looks right, and the investor column is sensible.

## Step 3: Pull signals for the pilot sample

Produces every stage 1 signal for 300 groups. From here until Step 7, everything runs on this pilot sample only.

**Claude Code:**

1. Pick the pilot sample at random: 100 groups containing an authorised financial firm, 150 other UK groups, and 50 Irish groups. Save the list so the pilot can be repeated. (After the 11 Nov 2026 regrouping, the pilot keeps the same entities as the first draw, mapped to their new groups, with removed entities dropped.)
2. Ask Tom where the listed-company app's results file is, and import it using the rule in Reference C.
3. Pull each signal in Reference A that is marked stage 1:
   - FCA Register: authorised status and firm type (Reference C), and the start dates of SMF4 and SMF5 holders, firm by firm.
   - Reed and Adzuna: adverts whose titles match the keywords in Reference B. Dated from the posted date. Remove duplicate adverts (same employer and title, ignoring an employer name repeated at the end of the title, e.g. "- London Stock Exchange Group", and treating brand variants mapped to the same group, e.g. Citi and Citigroup, as one employer).
   - CMA merger cases from GOV.UK Search, for the last 12 months.
   - Companies House filing history: director appointments and resignations (group top company only), share allotments (SH01, not on plcs) and new charges (MR01), for the last 12 months. Company profiles: re-registration from private to public (pre-IPO).
   - UK gender pay gap files: headcount growth (moved up a staff band between the entity's last two reports).
   - Central Bank of Ireland registers, housing and universities registers: regulated status. Industry codes: critical infrastructure and pharmaceuticals.
4. Attach each signal to an entity, then to that entity's group.
5. Build a **brand-to-group lookup** for names that do not match a company name exactly: every unmatched employer with 2 or more adverts, every name that matched 2 groups, unmatched CMA parties and unmatched listed companies. Python proposes up to 8 candidate groups per name; one Opus batch picks a group or answers recruiter, none or unsure (cost shown to Tom before sending). The result is a table Tom can correct, applied to job adverts, CMA parties and listed-company names. Tom's corrections live in `corrections/brand_overrides.csv` (kept in the code history) and win over the model; "unsure" is never applied. Step 7 extends the lookup to every unmatched employer with 2 or more adverts in the full pull that is not already in it, in one Opus batch; only its high-confidence answers are applied, and its medium and low answers are listed for Tom. The Step 3 rows stay as Tom reviewed them.
6. Produce a table of CMA cases, their parties (buyer, target, alias, title name) and matched groups for Tom to confirm. Tom's case-level corrections live in `corrections/cma_overrides.csv`.
7. Send anything that cannot be matched to the review file.

**Output:** a signal file with one row per signal: group, entity, signal type, date, and a source link.

**Tom checks:**

- [ ] 20 random signals are true when the source link is opened, and the date is right.
- [ ] The review file is a sensible size, and the reasons make sense.
- [ ] The share of job adverts with no named employer is reported.

## Step 4: Score, band and export

Produces the ranked spreadsheet for the pilot sample.

**Claude Code:**

1. Score each group using the points and rules in Reference A. Job adverts are scored on keywords alone at this step.
2. Apply age decay to triggers, counted from the run date in the settings file.
3. Assign each group a band.
4. Rank by band first (Act now, Warming, Strong fit, Fit only), then by total score, and export the spreadsheet with the columns in Reference F. Show for each signal which entity in the group it came from.
5. The sector label: "Financial services" if the group contains an FCA-authorised bank, building society, insurer, investment firm or payment or e-money institution; "Education" for providers on the universities register; "Housing" for registered housing providers; otherwise the industry code of the group's largest member (largest pay gap staff band, ignoring holding-company and head-office codes 642xx, 70100, 82990, and the public sector marker "1"). Groups with no usable code are "unknown".

**Output:** the pilot spreadsheet.

**Tom checks:**

- [ ] The top of the list reads sensibly, and each row's signals explain its score.
- [ ] Changing one weight in the settings file and rescoring takes under a minute, with no new downloads.

## Step 5: Model steps on the pilot

Adds the two places a model is used in stage 1: classifying job adverts, and writing why-now briefs.

**Claude Code:**

1. Tom does not label adverts. Classify keyword-matched adverts with the model in Reference E. (The pilot used Haiku first with unsure answers to Opus, on all 108 pilot adverts; from Step 7 every advert goes to Opus.) Send the full advert text where the source gives it (Reed's job details endpoint, cached); Adzuna gives only a snippet.
2. Classification guidance (in the prompt): third-party risk role = managing risk from suppliers, vendors, outsourcing or third parties, including supplier assurance and third-party security; security leader = the most senior or second most senior information or cyber security role; senior leader = head, director or chief-level owner of procurement, sourcing, compliance, enterprise or operational risk, GRC or operational resilience for the organisation or a major division; wider role = manager-level or above in those functions; operating change role = leading a procurement transformation or an ERP programme; irrelevant = credit, market, investment, fraud, pricing, underwriting, insurance loss control, clinical, project or health and safety risk, software engineering, sales or customer success, roles at consultancies, analyst firms or outsourcers delivering risk or procurement work for clients, and anything where the function word is incidental. "Operational resilience" is a third-party risk role only if the advert mentions third parties, suppliers or outsourcing. Supplier quality roles (product, manufacturing or food quality assurance of suppliers) are a wider role, not a third-party risk role. If the advert text is only company boilerplate and says nothing about the job, classify from the title alone and never place it in a higher category than the keyword match did (the keyword match is given to the model, and the cap is also enforced in code). Fixed-term and interim roles count the same. The model returns a category, a confidence, whether the text describes the job, and one sentence of reason.
3. Replace the keyword-only job scores with the model's verdicts and rescore (an "irrelevant" advert scores nothing).
4. Write why-now briefs for the top 10 Act now groups in the pilot, following Reference D (top 300 in Step 7).
5. Report tokens used, cost per item, the share of adverts that went up to Opus, and the projected cost of the full run.

**Output:** the pilot spreadsheet with model verdicts and 10 briefs, and a cost report.

**Tom checks:**

- [ ] The model verdicts read sensibly against the advert text (Tom reviews them; no labelling).
- [ ] The share of adverts that went up to Opus is reported, with the cost.
- [ ] The 10 briefs are accurate against their sources and follow the framing rule.

## Step 6: Review pack, then stop

The full run does not start until the pilot's output has been reviewed by Claude in the 3rdRisk Agent project.

**Claude Code:** put these nine files in one `pilot_review` folder, then stop.

| File | What it shows |
| --- | --- |
| Pilot spreadsheet | The ranked output for the 300 groups, in the final layout |
| Signal file | Every signal found, with group, entity, type, date and source link |
| Group file | The 300 groups with their member entities and how each was linked |
| Review file | Everything that could not be matched, with the reason |
| Removed file | Entities dropped by the size, private-sector and alive tests, with the test that dropped each |
| Model log | For each of the 50 adverts and 10 briefs: what the model was given, what it returned, and whether it went up to Opus |
| Run log | Per source: requests made, failures, rate-limit pauses, time taken, and anything that differed from these instructions |
| Cost report | Tokens and cost per step, and the projected cost and running time of the full run |
| Settings file | The weights, thresholds and keyword lists used |

**Tom:**

- [ ] Attach the nine files and this document to a new chat in the 3rdRisk Agent project and ask for the pilot review.
- [ ] Give Claude Code any changes the review asks for, and have it rerun the affected pilot steps.

The review judges four things: whether the matching and grouping are right, whether the signals are true and correctly dated, whether the ranking and briefs make sense, and whether the projected time and cost fit the budget.

## Step 7: Full run and release

Runs Steps 3 to 5 on every group, after the pilot review has passed. `settings.toml` `[run] scope = "full"` points Steps 3 to 5 at every group (`output/full/`); `"pilot"` reruns the pilot unchanged.

**Claude Code:**

1. Pull stage 1 signals for all groups. Expect hours because of rate limits (Companies House and the FCA run side by side, each under its own limit, shared across processes); report progress and resume from saved downloads if interrupted. Tell Tom the expected running time first, and whether the computer must stay awake. Companies House filing history is read with one uncategorised listing per company (officers, capital and charges together).
2. Extend the brand lookup (Step 3 point 5) to every unmatched employer with 2 or more adverts, in one Opus batch. Apply high-confidence rows only; list medium and low rows for review.
3. Classify every keyword-matched advert tied to a group with Opus. Model spend for the full run is pre-approved up to $25 (classification and the top 300 briefs); if the projection is higher, stop and tell Tom before sending.
4. Score, band and rank.
5. Write briefs for the top 300 Act now groups.
6. Put these in a `full_run_review` folder (and a copy in Uploads), then stop: the final ranked spreadsheet (sorted by band then score, with briefs); a summary (groups per band, by country and by sector; the top 50 with scores and signals); 20 random groups from outside the top 300 with their signals; the review file summary (unmatched items by source and reason) and the new medium and low brand lookup rows; the run log (per source: requests, failures, time taken); the cost report; and the answers to Tom's points 8, 9 and 10 of 11 Nov 2026.

7. **Rep spreadsheet** (`python src/export_full.py`, full run review 11 Nov 2026), tabs each sorted by band then score: "How to read this" (bands, what each signal means, signals are leads to verify via the source link, a new Senior Manager signal belongs to the named entity and person, not the group); "All"; "Act now" (with the four-line briefs); "Act now, outside fin. services"; "Size unconfirmed". A "size_confirmed" column (yes / no): in the first three ranked tabs, unconfirmed groups get no rank number and are hidden by a filter on that column. Briefs are written for any group that becomes Act now without one.

**Tom checks, before the team sees it:**

- [ ] Read the top 30 rows: are these accounts worth chasing, and is each reason true when the link is opened?
- [ ] Read 20 random rows from lower down: is anything good buried?
- [ ] Check the grouping by eye for the top 300.
- [ ] If the order is wrong, change the weights or the Act now threshold in the settings file and rescore. No new downloads are needed.
- [ ] Release the spreadsheet to the team.

## Step 8: Keep the list fresh

The list is used for three months, so older triggers have to lose weight as time passes.

| When | Claude Code does | New downloads? |
| --- | --- | --- |
| Start of month 2 and month 3 | Set the run date to today and rescore, so triggers decay and bands update | No |
| Month 3 | Pull job adverts again, classify them, rescore, and rewrite briefs only for accounts whose signals changed | Job adverts only |

Any account outside the top 300 can have a brief written on demand from the evidence already stored.

## Reference A: Fit filter, points and bands

### Fit filter

A group is on the list if at least one of its entities passes all three tests. There are no points for passing.

| Test | UK | Ireland |
| --- | --- | --- |
| **Size** | 250+ staff (gender pay gap file) or £36m+ turnover (modern slavery registry, used for size only) | See the Irish size rule in Reference C |
| **Private sector** | See the public sector rule in Reference C | Same rule, using the CRO number |
| **Alive** | Companies House status is active, with no insolvency record | CRO status is normal |

### Points

Score = need points + trigger points.

| Type | Signal | Source | Points |
| --- | --- | --- | --- |
| Need | Third-party or supply chain risk named as a principal risk | Listed-company app results | 3 (passing mention: 1) |
| Need | Authorised financial firm: bank, building society, insurer, investment firm, or payment or e-money institution (FCA, PRA or Central Bank of Ireland). Consumer credit alone does not count | FCA Register, Central Bank registers | 2 |
| Need | Critical infrastructure: energy, water and waste water, telecoms, rail and air transport, hospitals | Industry codes | 2 |
| Need | FCA-authorised insurance intermediary or investment adviser | FCA Register | 1 |
| Need | Other regulated sector (housing, universities) | Housing and universities registers | 1 |
| Need | Pharmaceuticals | Industry codes | 1 |
| Trigger | Hiring for a third-party, vendor or supplier risk role | Reed, Adzuna | 4 |
| Trigger | Hiring for a security leader | Reed, Adzuna | 4 |
| Trigger | New Senior Manager in risk or internal audit (SMF4, SMF5) | FCA Register | 4 |
| Trigger | Hiring a senior leader in procurement, sourcing, compliance, risk, GRC or operational resilience | Reed, Adzuna | 3 |
| Trigger | Merger, acquisition or separation | CMA merger cases | 3 |
| Trigger | Hiring for a wider risk, security, compliance or procurement role, or an operating change role | Reed, Adzuna | 2 |
| Trigger | Board turnover | Companies House, CRO | 1 |
| Trigger | Pre-IPO: private company re-registered as a public company | Companies House | 2 |
| Trigger | New funding (SH01, not on plcs) or new secured borrowing (MR01) | Companies House | 1 |
| Trigger | Headcount growth: moved up a pay gap staff band | UK gender pay gap files | 1 |

**Scoring rules:**

- Each row counts **once per group**, however many entities or adverts show it.
- **Hiring signals do not stack:** a group takes its highest hiring row (4, 3 or 2), not the sum.
- **Sector need points do not add up:** authorised financial firm (2, or 1 for an intermediary or adviser), critical infrastructure, other regulated sector and pharmaceuticals are one choice; a group takes its highest one. Principal risk adds on top.
- **Job adverts are scored on title keywords only** until the model check in Step 5.
- **Triggers decay with age:** full points under 3 months old, half for 3 to 6 months, a quarter for 6 to 12 months, nothing after 12. Age is counted from the run date.
- **Need points do not decay.**
- Job adverts are dated from the day they were pulled.

### Bands

"Timing" means trigger points after decay.

| Band | Rule |
| --- | --- |
| **Act now** | Timing of 3 or more AND at least one counted trigger worth 3 or more before decay (third-party risk role, security leader, senior leader advert, new Senior Manager, merger), with or without need points |
| **Warming** | Timing 2 or more that is not Act now (below 2: Strong fit or Fit only by need) |
| **Strong fit** | Need of 3 or more, no timing |
| **Fit only** | Everything else that passes the filter |

Rank by total score within the whole list, with no cut-off.

## Reference B: Job advert keywords

Match on the advert's title, ignoring capitals. Keywords only narrow the pile; from Step 5 the model makes the final call on each match.

| Category | Points | Title contains |
| --- | --- | --- |
| Third-party risk role | 4 | third party, third-party, TPRM, vendor risk, supplier risk, supplier assurance, supply chain risk, vendor management, supplier management, supplier security, vendor security, outsourcing, operational resilience, third party transformation |
| Security leader | 4 | CISO, chief information security officer, chief security officer; or one of head, director, VP together with one of information security, cyber security, cybersecurity, IT security |
| Senior leader | 3 | One of head, director, chief, VP, global head together with one of procurement, sourcing, compliance, risk, GRC, operational resilience (so "Chief Procurement Officer" matches; the bare acronyms CPO, CRO and CCO do not) |
| Wider role | 2 | One of risk, compliance, procurement, internal audit, GRC, information security, cyber security, cybersecurity, IT security, security risk, security assurance, sourcing, governance, resilience, resiliency, together with one of head, director, manager, lead, chief |
| Operating change role | 2 | procurement transformation, source-to-pay, ERP programme, ERP implementation, S/4HANA |

- A title that matches more than one category takes the highest.
- Wider and operating change roles are one signal: a group with both scores 2, not 4.
- An advert with no named employer (placed by a recruiter or a job board such as eFinancialCareers) goes to the review file and scores nothing. Recruiters are spotted by name words, a job-board and recruiter list, recruitment industry codes (78), "our client" wording, and the brand lookup.
- Duplicate adverts (same employer and title, on either board) count once.

## Reference C: Other rules

| Rule | Definition |
| --- | --- |
| **Public sector** | Remove entities with a public administration industry code. A pay gap entry with no company number stays in only if its industry codes do not include the public sector marker "1" AND its name contains none of: council, NHS (also "N H S"), health board, hospital, ambulance, police, constabulary, authority, department, ministry, office, government, parliament, fire and rescue, combined authority, borough, crown, agency, armed forces; it is flagged "no company number: alive not checked". Universities come in through the universities register only (an entry tied to the universities or housing register skips the code "1" test but not the name words). (Tom, 11 Nov 2026.) Remove academy trusts and schools (Step 1). Also flag names containing council, NHS, police, authority or department. Housing providers, universities and charities stay in. Also remove further education and sixth-form colleges (codes 85310, 85320, 85410 with the public sector marker "1"), any name containing "education trust", "educational trust", "catholic education" or "education partnership", and Northern Trains Limited; universities stay (full run review, 11 Nov 2026). List everything removed. |
| **Irish size** | Test whether the Irish Gender Pay Gap Portal offers a bulk export, and if so keep employers in the 250+ band. If it does not, keep Central Bank-authorised firms only, mark their size as "unconfirmed", and tell Tom. |
| **Board turnover** | Three or more director appointments or resignations on the group's top company within 12 months of the run date. Dated from the most recent change. UK only: the CRO publishes no free director data. |
| **Authorised financial firm** | FCA: a current firm whose Permissions include Accepting Deposits (bank, building society), Effecting or Carrying out contracts of insurance (insurer), or Dealing in investments as principal, Managing investments, Safeguarding and administration of assets, Managing a UCITS or Managing an AIF (investment firm); Managing the underwriting capacity of a Lloyd's syndicate as a managing agent (insurer); or whose PSD / EMD Status is Authorised Payment Institution or Authorised Electronic Money Institution: 2 points. Assisting in the administration and performance of a contract of insurance (insurance intermediary), or Advising on investments / on Pension Transfers (investment adviser): 1 point. Consumer credit or mortgage permissions alone earn nothing. Ireland: the Central Bank registers kept in Step 1. |
| **Critical infrastructure / pharmaceuticals** | From industry codes (UK SIC / Irish NACE): energy 35, 0610, 0620, 1920, 4950; water and waste water 36, 37; telecoms 61100, 61200, 61300 (Irish 6110-6130); rail 4910, 4920; air transport 51, 5223; hospitals 86101 (Irish 8610); pharmaceuticals 21. Counts only when it is the sector of the group's largest member (largest staff band, holding codes ignored), not when a small subsidiary has the code. Data hosting is not a signal. |
| **New funding** | SH01 share allotments on private companies only; allotments by plcs are ignored. |
| **Headcount growth** | The entity's pay gap staff band in its latest report is higher than in its previous report. Dated from when the latest report was submitted. |
| **Pre-IPO** | A company that is now a plc and whose previous name ending Limited or Ltd ceased in the last 12 months (read from the company profile). Dated from that change. |
| **Merger, acquisition or separation** | A CMA merger case opened in the last 12 months that names a group entity as a party. Dated from the case opening. Parties are matched on exact or near-exact name; the rest go to review. |
| **Senior Manager** | An SMF4 or SMF5 approval at any FCA-authorised entity in the group, with a start date in the last 12 months. |
| **Listed-company app results** | The file needs the company number, the verdict (yes, passing mention or no), the quote and the report date. Match on company number where the file has one. Otherwise match on exact name after tidying listing-style names ("Barr (A.G.) Plc" -> "A.G. Barr Plc", "(The)" removed, "Ld" -> "Limited"), then the brand lookup. A listed company with a yes or passing-mention verdict that is not in the universe is attached to its group if it is the parent of a universe entity; otherwise it becomes its own group, flagged "size from listing". If no UK company can be found at all, it is still added as its own group by name, flagged "size from listing, no UK company record". The rest go to review. |
| **Modern slavery registry** | Used only for the £36m turnover test. Nothing from it is scored, shown as evidence or mentioned in a brief. |

## Reference D: Why-now briefs

Each brief is four lines, written from that group's matched and dated evidence (Tom, 11 Nov 2026).

1. **What changed**, with the date and source.
2. **Why it matters**, framed around supplier visibility or regulatory and audit exposure.
3. **Angle to open on:** one plain sentence describing the topic to raise, not written as an email line. No citations, no source names, no "I saw", no congratulations.
4. **Who to contact:** the named Senior Manager where the signal is an FCA appointment; otherwise the role most likely to own the issue (for example head of third-party risk, head of procurement, CISO).

Rules:

- **Frame around risk to the business.** Never open on saving time, replacing spreadsheets or consolidating tools.
- **Reasons:** only signals worth 2 or more points, plus need signals. Share allotments, new charges, board turnover and headcount growth are not mentioned unless they are the group's only signals.
- **Cite a source for every claim**, in the "what changed" and "why it matters" lines only. Cite an annual report by company and year (e.g. "Tesco PLC annual report 2025"), not the listed-company app. Keep the evidence attached to the row.
- **No hype**, and no claim the evidence does not support.
- **Date every brief.**

## Reference E: Models and cost

Python does everything that can be decided by rule: downloads, filters, grouping, matching on identifiers and names, scoring, decay, banding and export. A model is used in two places, both through the Batch API (half price, results within a day).

| Step | Python narrows it first | Model decides | Model |
| --- | --- | --- | --- |
| Job advert classification | Keyword match on titles | Third-party risk role, security leader, senior leader, wider role, operating change role, or irrelevant; plus a confidence | `claude-opus-5-5` for every advert (Tom, 11 Nov 2026; the pilot used Haiku first) |
| Why-now briefs | Gathers the group's evidence | The four lines in Reference D | `claude-fable-5-2` |
| Brand lookup | Up to 8 candidate groups per name | A group, recruiter, none or unsure | `claude-opus-5-5` |

- Job classification returns fixed fields, not free text.
- Keep every Haiku prompt under 100,000 tokens; above that the price is five times higher.

### Cost estimate for stage 1

Batch prices per million tokens, from the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing.md) on 10 November 2026: Fable 5.2 $4 in and $20 out; Opus 5.5 $2 and $10; Haiku 5.5 $0.05 and $0.25.

| Step | Assumed volume | Estimate |
| --- | --- | --- |
| Job adverts, Haiku first pass | 20,000 adverts | $2 |
| Job adverts, unsure cases on Opus | 10% of them | $12 |
| Briefs on Fable | 300 | $14 |
| **Stage 1 full run** |  | **About $28** |
| Pilot (Steps 3 to 5) | 50 adverts, 10 briefs | Under $2 |
| Month 3 refresh | Adverts again, changed briefs | $15 to $25 |

The volumes are assumptions. The pilot measured about $0.004 per advert on Opus and $0.013 per brief on Fable; Step 7 is pre-approved up to $25 (classification and 300 briefs) and stops for Tom above that.

## Reference F: Output columns

One spreadsheet, one row per group, sorted by rank.

| Column group | Columns |
| --- | --- |
| Identity | Rank, band, group name, country, sector, size band, entities in the group with their identifiers |
| Score | Total, need, trigger (after decay) |
| Evidence | Top three signals, each with its date, source link and the entity it came from |
| Timing | Next accounts due date |
| Brief | Why-now brief and the date it was written |
| Flags | Grouping unchecked, size unconfirmed, unmatched signals waiting in review |

## Reference G: Sources for stage 1

Access details and limits were not re-checked when this was written. Rule 3 applies: test each one first.

| Source | Used for | Access |
| --- | --- | --- |
| [UK gender pay gap service](https://gender-pay-gap.service.gov.uk/viewing/download) | Universe, 250+ staff test, size bands | Free yearly CSV |
| [Modern slavery statement registry](https://modern-slavery-statement-registry.service.gov.uk/download) | £36m turnover test only | Free CSV |
| [Companies House API](https://developer.company-information.service.gov.uk) | Status, ownership, filing history, officers, accounts due date | Free key; 600 requests per 5 minutes |
| [FCA Register API](https://register.fca.org.uk/Developer/s/) | Authorised firms; Senior Manager start dates | Free key plus email; about 100 requests a minute |
| [Reed Jobseeker API](https://www.reed.co.uk/developers/jobseeker) | UK job adverts | Free key |
| [Adzuna API](https://developer.adzuna.com) | UK job adverts | Free app ID and key; about 1,000 calls a month |
| GOV.UK Search API | CMA merger cases | No key |
| Listed-company app results | Principal risk verdicts for UK listed companies | Tom's existing file |
| [Regulator of Social Housing register](https://www.gov.uk/government/publications/registered-providers-of-social-housing) | Housing providers | Free spreadsheet |
| [Office for Students register](https://www.officeforstudents.org.uk/for-providers/regulatory-resources/guide-to-the-ofs-register/) | Universities | Free spreadsheet |
| [CRO Open Data Portal](https://opendata.cro.ie) | Irish companies and status | Free daily file |
| [Central Bank of Ireland registers](https://registers.centralbank.ie/) | Irish authorised firms | Free downloads |
| Irish Gender Pay Gap Portal | Irish size test | Public; bulk export not confirmed |

## Stage 2: new signals (approved 12 Nov 2026)

Adds new signals to the existing list; stage 1 is not rebuilt. The stage 1 rules for Claude Code still apply. Four slices, built one at a time; for each: count the items and project cost and time before any model call, run on the pilot groups only, then move on. After the four pilots, a review pack, then stop. Nothing runs on the full universe until Tom approves. Model spend for all of stage 2 is pre-approved up to $40; if the count-based projection for the full run is higher, stop and tell Tom. Settings: `[stage2]` in `settings.toml`.

### Slice A: principal risks in private-company annual reports (`src/slice_a.py`)

1. Scope: every group with no result from the listed-company app (the Principal Risks Scanner, `~/projects/risk-scanner`). Company: the group's top UK company (for a foreign-parent group, its UK top company with the largest staff band); if its latest accounts are not full or group accounts, the member with the largest staff band.
2. Latest accounts from Companies House: accounts filing history, then the document metadata, then the document (structured XHTML when offered, else PDF). Every reply and file is saved under `data/raw/ch/` (`filing/<n>_accounts_0.json`, `documents/`).
3. A PDF with under 300 characters of text per page is a scan: "couldn't check" (no text recognition in this build).
4. Section: the scanner's own finder (pinned copy in `src/scanner_text.py`, scanner commit 760baae), which looks for "principal risks", "principal risks and uncertainties", "risk management" and similar headings. None: "no section found".
5. Opus reads the section only (every prompt under 100,000 tokens) with the scanner's prompt and labelling guide, and returns yes / passing mention / no with an exact quote; each quote is checked word for word with the scanner's check.
6. Signal: need, 3 points (passing mention 1), the same family as the listed-company result.

### Slice B: news (GDELT)

Search GDELT by topic (UK and Irish sources, last 6 months, weekly windows) for: data breach, cyber attack, ransomware, cyber incident, third party breach, supplier failure, supplier collapse, outage, operational disruption, acquisition, acquires, merger, takeover, demerger, fined, enforcement action, regulator fines, DORA, NIS2, outsourcing regulation, PRA guidance, sanctions. No ESG or labour-practice terms. Remove duplicate stories. Opus reads each headline (and first paragraph where it can be fetched within the site's terms) and returns the organisations, the event type for each (incident at this organisation; failure or breach at one of its suppliers; merger, acquisition or separation; regulatory enforcement; none), the event date and a confidence. Match by exact name, then the brand lookup (extended in one Opus batch for unmatched names in 2+ stories); the rest to review. Signals: merger, acquisition or separation 3 (same family as the CMA signal); regulatory enforcement 4; operational incident or supplier failure at the account 2. Dated from the event date.

### Slice C: ransomware claims and peer incidents

Only if ransomware.live's terms clearly allow a one-off commercial pull. Then: claimed victims in the UK and Ireland, last 12 months, matched as in Slice B. Signals: claimed victim 2; peer incident 2 (a universe group with a ransomware claim, or a high-confidence Slice B incident, gives every other group whose largest member is in the same industry division and country the signal, dated from the incident). Each counts once. A peer incident does not count towards the Act now "trigger worth 3+" test.

### Slice D: regulatory enforcement

GOV.UK Search, last 12 months: Ofgem, Ofwat, the Pensions Regulator, the Regulator of Social Housing (regulatory judgements and notices), the Office for Students, the CMA (consumer and competition enforcement, not mergers). Bank of England and PRA news feeds. FCA final notices and ICO enforcement only if readable without scraping a page that forbids it. Opus decides: enforcement or governance downgrade against a named organisation, or not relevant. Match as in Slice B. Signal: regulatory enforcement or governance downgrade, 4 (same family as the news enforcement signal).

### Scoring and briefs

New signals join the existing scoring; all other rules stay (decay, Act now). A ransomware claim against the account never appears in "angle to open on"; it may appear in "why it matters" as a reported claim. A peer incident may be the angle; name the peer only when a news story confirms it, otherwise "a reported incident in your sector". Briefs using ransomware evidence are written by Opus, not Fable.

### Review pack (after the four pilots, then stop)

One spreadsheet: Slice A (50 pilot companies with section, verdict and quote; counts of couldn't check and no section found; full-run projection); Slice B (100 stories with headline, source, model output and matched group; share matched; projection); Slice C (terms reading, matched victims, peer lists for 5 victims); Slice D (every item, verdict, matched group; regulators that could not be read); the pilot ranked list before and after with band changes; 10 briefs for groups whose band changed; run log and cost report.

Not in this build: website changes (Wayback Machine) and company careers sites (list what careers sites would involve for the Irish groups and the top 300, with a time estimate, and wait).

### Source tests (12 Nov 2026)

- **Companies House accounts documents:** the route works, but the large companies' latest full accounts so far are all PDF only and image scans with no text layer (the listed-company app found the same). Under "no text recognition" they are "couldn't check".
- **ransomware.live:** its terms prohibit commercial use without the owner's prior written approval, and its free API "is not intended for corporate or business use". Slice C stopped pending Tom.
- **GDELT:** the DOC API refused most requests with 429 ("one request every 5 seconds") even 30 s to 7 min apart (5 of 81 searches in about 2 hours; not worked around), and returned UK/Irish articles only for 6-9 Nov 2026: the week before was empty. It does not give 6 months. Pull stopped; the pilot used the 116 stories saved.
- **GOV.UK Search:** works. Covers the Regulator of Social Housing (250 decision notices in 12 months) and the CMA (149 cases). Ofgem (15 items, none enforcement), Ofwat (0), the Pensions Regulator (7) and the Office for Students (1) publish enforcement on their own websites, not GOV.UK.
- **Bank of England feeds (RSS):** readable with curl's default client; Python's default client is refused (403), not worked around (the source-test copies are used). Each feed holds only its 50 newest items (news back to Jul 2026, PRA publications back to Mar 2026).
- **Regulator of Social Housing:** the GOV.UK search entry carries no grade; the judgement (grades and whether each changed) is on the attached GOV.UK page, read through the GOV.UK content API (two calls per judgement, saved).
- **FCA final notices:** readable without scraping: the FCA's sitemap (offered to crawlers, allowed by robots.txt) lists each final notice PDF with a date (107 changed in the last 12 months).
- **ICO enforcement:** readable the same way: its sitemap lists 41 enforcement pages from the last 12 months; robots.txt asks for 6 seconds between requests.

### Pilot results (12 Nov 2026)

- Slice A: 317 groups; 28 sections read (all from structured XHTML accounts); all "no" under the app's rules (12 name supply chain risk, which the app excludes); 215 scans, 48 without full or medium accounts, 22 with no UK company, 3 no section. $0.30.
- Slice B: 116 stories (one week), 5 matched a group. $0.07.
- Slice C: not pulled (terms).
- Slice D: 619 items; 121 enforcement and 47 downgrades (housing judgements re-read with their full text); 17 matched a group. $1.93.
- Pilot: no group changed band (Tesco 8.25 -> 11.25, already Act now). Review pack: `output/stage2/GTM Stage 2 pilot review <date>.xlsx` (`src/review_stage2.py`). Settings left at scope "full" with `include_in_scoring = false` until Tom approves.

### Decisions on the pilots (Tom, 12 Nov 2026) - stage 2 run

Model spend for all of stage 2 is now pre-approved up to $60. ransomware.live and NewsAPI have approved this project's use of their data (written approvals: "ransomware_live_approval" and "newsapi_approval" in the project folder). Keys `RANSOMWARE_LIVE_API_KEY` and `NEWSAPI_KEY` live in `.env` only.

1. **Slice D (regulators), every group** (`src/regulators.py`, `src/stage2_model.py` jobs `reg_rel`, `ofgem`, `ofgem_rel`, `src/stage2_signals.py`). Opus re-reads every item it marked enforcement (FCA notices from their first 8 pages; ICO and Ofgem pages; up to 8,000 characters) and marks it relevant or not with the area and a one-line reason. Enforcement scores 4 only when it concerns systems and controls, operational resilience, outsourcing or third parties, data protection or security, financial crime controls, governance or regulatory reporting. Score 0: consumer protection, pricing, advertising and sales practices (including PECR marketing); FCA notices that only cancel or vary a permission for unpaid fees, missing returns or a firm ceasing business; competition law; actions against an individual only. Housing governance downgrades score 3 (`governance_downgrade`), same family. Every action date is parsed to a real date (month-only: the publication date when in that month, else the 1st; no date: the publication date). FCA notices are dated from the FCA sitemap; ICO pages from the page's own date. Ofgem added from its own website (robots.txt allows it; its sitemap, 10 pages, lists 251 press-release, publication and decision pages whose addresses name enforcement and that changed in the last 12 months; each fetched 5 s apart; kept when first published in the last 12 months). Ofwat not added: its website refuses our script (403, robots.txt included) and that is not worked around. The Pensions Regulator and the Office for Students: not added (Tom).
2. **Acquisitions from Companies House** (`src/ch_acquisitions.py`, job `acq`). From the ownership records saved in Step 2 (no new requests): the top UK company's corporate owner (corporate entity or legal person) with more than 50% of shares or votes or the right to appoint the board, notified in the last 12 months, replacing a different owner that ceased within 90 days either side. Rule-based removals: the new owner is a member of the same group; old and new names the same, or starting with the same word. Opus then reads each remaining change and says external change of control, internal reorganisation or unclear; only external changes count. Signal: "merger, acquisition or separation (Companies House: new controlling owner)", 3 points, dated from the notified date, same family as the CMA and news merger signals (counts once).
3. **ransomware.live** (`src/ransomware.py`). Pro API `api-pro.ransomware.live/victims/?country=GB|IE&year=&month=` with the `X-API-KEY` header (limit 60 requests a minute; we wait 3 s): 2 countries x 13 calendar months = 26 calls. The month filter is the month ransomware.live discovered the listing; the signal date is the earlier of the attack and discovery dates; listings older than 12 months dropped. Victim names matched as in Slice B (a name in brackets removed; a victim named only by a web address goes to review). Claimed victim 2 points. Peer incident 2 points to every other group whose largest member is in the same 2-digit industry division and the same country (UK or IE), where the victim is a universe group; one incident per victim group (its earliest date). An incident that would reach more than 300 groups (`peer_limit`) is not applied and is listed. A peer incident never counts towards the Act now "trigger worth 3+" test.
4. **News: NewsAPI.ai** (`src/newsapi.py`, replacing GDELT). Service: https://newsapi.ai (Event Registry; API `eventregistry.org/api/v1/article/getArticles`). One search = one page of up to 100 articles = 1 token; the free tier (2,000 searches, 200,000 articles) holds recent articles only (documented as the last 30 days; on 12 Nov 2026 the earliest article returned was 20 Sep 2026); archive search needs a paid plan. Articles come with full text. Searches: the Slice B terms in the headline, English, publishers in the UK or Ireland, Event Registry's duplicate filter on; at most 15 words per query on this tier (so the incident terms are two queries); every page saved under `data/raw/newsapi/`; hard stop at 1,000 searches. Then the Slice B steps: remove duplicates (same article, same headline), Opus reads the headline and the first 500 characters of each story (organisations, event types, date, confidence), match to groups, extend the brand lookup for unmatched names in 2+ stories (`src/brands.py candidates|send|collect --stage2`, high-confidence answers only). Scores: incident or supplier failure at the account 2; regulatory enforcement 4 only if relevant under item 1 (job `news_rel`, same family as Slice D); merger or acquisition 3 (same family as CMA and Companies House). A high-confidence incident at a universe group also raises the peer signal (item 3 rules, 300 limit).
5. **Slice A rule change and scan test, no full run** (`src/slice_a.py`, `src/slice_a_scans.py`). Verdicts: the listed-company app's rules for "yes"; supply chain risk named as a principal risk without third-party, supplier-assurance or outsourcing risk = "passing mention". Scan test: 30 scanned accounts from the pilot groups with the largest staff bands. Haiku sees the first 40 pages as small images and gives the page numbers of the principal risks section; Haiku then transcribes that section word for word from those pages (and the next) at higher resolution; Opus gives the verdict from the transcript; the quote is marked "from scan, not word-checked". Every request under 100,000 tokens. Downloaded documents are deleted after the sections are extracted (metadata and section text kept). Slice A signals stay out of scoring until a full run is approved.
6. **Careers sites, the 554 Irish groups** (`src/careers.py`). Haiku with Anthropic's web search tool (at most 2 searches per group) finds the website, careers page and any job-board links it sees. The job board is detected from links on the organisation's own careers page or homepage (robots.txt checked; at most 3 pages per site; 5 s apart per site), else from links the search saw. Open roles are read only from public job feeds: Greenhouse, Lever, Ashby, SmartRecruiters, Workable. Workday and every other system: recorded, not read; no scraping. Roles in the UK or Ireland (or no location given) pass the existing title keywords, then the Step 5 Opus prompt; signals as the existing hiring signals.
7. **Score and export.** `include_in_scoring = true`: signals from items 1 to 4 and 6 join the full run; rescored; spreadsheet re-exported with the stage 1 tabs as `GTM full run ranked v3 <date>.xlsx`. Briefs (`src/briefs_stage2.py`): every group that is Act now after rescoring and whose counted signals changed gets a new or rewritten brief, with the ransomware and peer rules above; Opus writes any brief using ransomware evidence, Fable the rest. The state before this run is kept in `output/before_changes/stage2_full_base/`.

### Stage 2 run results (12 Nov 2026)

- Item 1: 625 regulator items (6 from Ofgem's own site); 124 enforcement, of which 31 relevant (4 points) and 93 scored 0 (63 FCA permission cancellations, 30 consumer protection); 47 housing governance downgrades (3 points). Ofwat not read (403). Re-read cost $0.62.
- Item 2: 202 new corporate controlling owners in 12 months; 102 read by Opus; 47 external changes of control (46 groups) score 3. No new requests.
- Item 3: 26 calls; 447 claimed victims (UK 421, Ireland 26); 15 matched (3.4%; 97 named only by a web address, 335 not in the universe).
- Peer incidents (items 3 and 4): 56 victim groups; applied for 32; 17 over the 300-group limit (listed, not applied); 1,578 groups got a peer signal.
- Item 4: NewsAPI.ai: 78 of 2,000 searches used (63 for the pull); 5,296 articles from 20 Sep to 12 Nov 2026, 5,159 stories after removing duplicates; 1,278 stories matched a group. Brand lookup: 724 names in 2+ stories, 90 high-confidence matches applied. Opus $8.07, relevance $0.33, brand batch $0.97.
- Item 5: the 28 text sections re-read under the supply chain rule: 5 passing mention, 23 no. Scan test: 30 of 30 gave a transcribed section (2 yes, 14 passing mention, 12 no, 2 couldn't check); $1.52 ($0.05 a document); about 7,350 scans in the universe, about $190 by batch. One transcript checked by eye against the page image: word for word. All 248 downloaded documents deleted.
- Item 6: 554 Irish groups; 468 websites; 102 with a job board detected (42 Workday, not read); 24 readable boards, 1,063 open roles, 11 keyword matches, 4 groups gained a hiring signal. Web search $11.66.
- Rescore: Act now 155 -> 462, Warming 259 -> 1,243, Strong fit 55 -> 39, Fit only 10,664 -> 9,389. 351 briefs (307 new, 44 rewritten; 35 by Opus) $3.75. Spreadsheet `full_run_review/GTM full run ranked v3 2026-11-12.xlsx`; report `output/stage2/GTM Stage 2 run report 2026-11-12.xlsx` (both in Uploads). Stage 2 model spend in total: $29.86 of $60.

### v4: tightened rules (Tom, 13 Nov 2026)

v3 is not approved for release; v2 stays the release version until Tom approves v4 (`[run] export_version = "v4"`; v3 kept in `output/before_changes/v3_full/`). No new downloads except item 7. Additional model spend pre-approved up to $80 (up to $60 for item 7).

1. **UK and Ireland test, every news signal.** A news event counts only if the story is about the group's UK or Irish business, a UK or Irish regulator, or a whole-company change of control at the group's ultimate parent (being acquired, merged or broken up). Events at a foreign parent's overseas operations do not count. The organisation credited must be the one the event happened to.
2. **News mergers and acquisitions** (Opus returns the role and the scale): 3 points, counts towards Act now: being acquired, merging, demerging, selling a major division, or acquiring a large business (a stated value of GBP 100m or more, or a whole operating company with a known brand). 1 point (`merger_bolt_on`), never towards Act now: a smaller bolt-on. 0: rumours, speculation, talks, bids not agreed, share-price commentary, adviser / lender / minority investor / former owner, single sites, brands or assets. Same family as the CMA and Companies House signals: the highest counts.
3. **News incidents (2 points):** a cyber attack, data breach or ransomware event at the group; a technology or systems outage at the group; a failure, breach or outage at a supplier or service provider that affected it. Not: utility supply interruptions to customers, pollution, weather, strikes, recalls, accidents, legal settlements, anniversaries of older events, commentary. The event itself within the last 6 months.
4. **News enforcement (4 points):** the item 1 relevance rule, and 0 for environmental or pollution fines, health and safety fines and sporting sanctions. The regulator must be UK or Irish, or the action against the group's UK or Irish entity.
5. **Peer incidents (2 points):** source events are ransomware claims and news cyber or data events or supplier failures (high confidence, passing the UK and Ireland test), in the last 6 months, at a universe group. Peers share the victim's largest member's 3-digit industry group (not the 2-digit division) and country. Not applied when it would reach more than 150 groups (`peer_limit`); listed.
6. **Sector label and owners.** "Financial services" only when the group's largest member (by staff band) or its top company is a financial firm (FCA bank, building society, insurer, investment firm or payment institution, or on the Central Bank of Ireland register); otherwise the largest member's sector. The need points are unchanged. The ownership walk stops below governments and state bodies (`[grouping] state_owner_words`; owner names with a company legal form are not state bodies), as it does for investors. After regrouping every signal follows its entity's current group (`signals.py`).
7. **Annual reports, groups with 1,000+ staff and no listed-company result** (`src/scans_full.py`). Count and projection first (1,685 groups; projected about $31-35; stop if over $60). Text accounts: the Slice A section finder and Opus. Scans, through the Batch API: Haiku finds the section's pages from the first 40 pages (900 px greyscale JPEG), Haiku transcribes those pages (1,500 px), Opus gives the verdict under the current rules (quote "from scan, not word-checked"). Batches are split to stay under the size limit. Each document deleted after extraction. Scores: yes need 3, passing mention need 1, same family as the listed-company result. Pilot outcomes reused.
8. Careers sites: no further work.
9. **Briefs** (`src/briefs_stage2.py ... --v4`): rewritten for Act now groups whose counted signals changed since v3. Briefs cite counted signals only, so a news signal that now scores 0 is never cited.

The saved stories are re-read by Opus under items 1 to 4 in one batch (`stage2_model.py` job `news2`: the 3,177 stories whose first reading named a counted event; the rest named none, and the rules only narrow). Signal building: `stage2_signals.py`.

Run order: `stage2_model.py send/collect news2` -> `group_accounts.py build` + `pilot.py` (state-owner stop) -> `scans_full.py fetch`, `find-send`/`find-collect`, `transcribe-send`/`transcribe-collect` (deletes each PDF), `verdict-send`/`verdict-collect` -> `stage2_signals.py` -> `signals.py` -> `score.py` -> `briefs_stage2.py select|estimate|send|collect --v4` -> `briefs_stage2.py select|send|collect --v4 --fix` (Act now briefs whose evidence text no longer matches the current counted signals: same signal types and dates, but a different story behind them) -> `export_full.py` -> `review_v4.py`.

### v4 results (12 Nov 2026)

- Bands v2 / v3 / v4: Act now 155 / 462 / 276; Warming 259 / 1,243 / 781; Strong fit 55 / 39 / 90; Fit only 10,664 / 9,389 / 9,988. 121 groups are Act now in v4 but not in v2.
- News signals 1,410 (v3) -> 781 (v4). Main reasons v3 signals now score 0: not about the UK or Irish business (318 mentions), rumour / talks / bid not agreed (152), no counted event (131).
- Peer incidents: 19 source incidents, 14 applied, 3 over the 150-group limit (named in the v4 report, not here); 669 groups hold a peer signal (v3: 1,578).
- Financial services label: 46 groups lost it; 347 gained it, 346 of them Irish firms on the Central Bank register whose sector was blank before.
- 31 entities moved out of government-named groups (`data/interim/v4_regrouped.csv`).
- Item 7: 1,685 groups; 1,080 scans transcribed, 163 text sections, 30 pilot scans reused; verdicts yes 41, passing mention 329, no 864, couldn't check 451. Cost $14.07. All documents deleted.
- Briefs: 175 rewritten or new + 5 evidence fixes; every Act now group has a brief whose evidence matches its current counted signals.
- Model spend this round $31.18 of $80.
- Known weak point: 2 of the 10 "merging" news signals are internal reorganisations (Playground Games / Turn 10 inside Microsoft; Bray Leino / Krow inside Mission Group), which put Microsoft into Act now. Not changed: Tom to decide whether a merger between units of the same group should score 0.
- Report: `output/stage2/GTM v4 report 2026-11-12.xlsx`; spreadsheet `full_run_review/GTM full run ranked v4 2026-11-12.xlsx` (both in Uploads). Not for release until approved.

### v5: v4 approved with changes (Tom, 13 Nov 2026) - the release version

Tom approved v4 with the changes below; no new downloads; up to $5 of model spend. Rule: if Act now moved by more than 30 groups either way, stop and send the list; otherwise v5 is the release version, replacing v2. Act now moved by 10, so **v5 is the release version** (`full_run_review/GTM full run ranked v5 2026-11-12.xlsx`, in Uploads). v4 kept in `output/before_changes/v4_full/`.

1. **Same-group deals score 0.** A merger, acquisition or reorganisation between units of the same group (`stage2_model.py` job `internal`: Opus reads each news merger signal that scored in v4 - 422 - and answers internal / external / unclear). Only "internal (same group)" scores 0. A demerger splits the group, so it keeps its v4 score (ABF / Primark). 0 now: Microsoft studios (Playground Games / Turn 10), Mission Group agencies (Bray Leino / Krow), Coventry moving Co-op Bank into itself, Rix sister companies.
2. **Annual reports.** A risk only about modern slavery, labour rights, ethical trading or supplier ethics is a "passing mention", not "yes". The 41 item 7 "yes" verdicts re-read by Opus (`scans_full.py recheck-send` / `recheck-collect`, the sections were kept; before: `data/interim/item7/item7_results_before_v5_recheck.csv`): 8 became passing mention, 33 stay yes. Other verdicts untouched.
3. **News signals read with low confidence score 0** ("read with low confidence").
4. **News dates.** Dated from when the event happened or was announced; if the model's date is after publication (a planned future date), the publication date is used (30 mentions).
5. **Peer incidents in briefs** (`src/peer_kind.py send|collect` -> `data/interim/peer_kind.csv`): for each Act now group with a counted peer incident, Opus judges whether account and victim are plainly the same kind of business (two banks, two airports, two fashion retailers); when unsure, "different". Unlike peers are dropped from the brief's evidence (`briefs_stage2.drop_unlike_peers`); the points stay. 53 pairs: 37 same kind, 16 different (corrected 13 Nov; first reported as 38 and 15).
6. **MUFG in Ireland:** `IE:mitsubishi ufj` and `IE:mufg alternative` merged (`[grouping] merges`); `signals.py` moves entity-less signals (e.g. careers adverts) to the kept id.
7. **"How to read this"** rewritten with a stage 2 section: news events, regulatory actions, ownership changes, annual report verdicts, ransomware claims (an attacker's claim, not a confirmed breach; never quote it to the account), peer incidents; and "every signal is a lead to verify by opening its source link" at the top.

Briefs (`briefs_stage2.py select|estimate|send|collect --v5`): rewritten for Act now groups whose counted signals changed since v4 (4), or whose evidence changed because an unlike peer incident is now left out (16) or a different story sits behind a signal (1): 21 briefs. Every Act now group has a brief whose evidence matches its current counted signals.

Run order: `stage2_model.py send/collect internal` -> `scans_full.py recheck-send/recheck-collect` -> `group_accounts.py build` + `pilot.py` -> `stage2_signals.py` -> `signals.py` -> `score.py` -> `peer_kind.py send/collect` -> `briefs_stage2.py select|send|collect --v5` -> `export_full.py`.

Results: Act now 276 -> 266; Warming 781 -> 781; Strong fit 90 -> 84; Fit only 9,988 -> 10,003; groups 11,135 -> 11,134 (MUFG merge). 20 groups changed band (incl. the merged MUFG group). Left Act now (10, none entered): Microsoft, Mission Group, Coventry Building Society, Co-operative Bank, J.R. Rix & Sons (same-group deals); Delek, Intertek, Saipem, FirstGroup (low-confidence readings); MUFG Alternative Fund Services (merged into the other MUFG group, still Act now). Model spend $2.13 of $5 (internal check $0.97, annual report re-read $0.76, peer check $0.10, briefs $0.30).

### v6: presentation fixes and one rule correction (Tom, 13 Nov 2026)

v5 approved as the list. v6 = presentation fixes plus one rule correction; no new downloads; up to $5 model spend. v5 kept in `output/before_changes/v5_full/`.

1. **Known as and sector, top three bands** (`src/names_sectors.py estimate|send|collect` -> `data/interim/names_sectors.csv`): Opus reads each Act now / Warming / Strong fit group's legal name, up to 25 member companies and the high-confidence brand lookup names, and returns `known_as` (the name a UK or Irish salesperson would search for) and `sector` (one label from the existing list; banks, insurers, asset managers and payments companies are Financial services; a group that only owns a small financial subsidiary keeps its main sector). `score.py` uses these for those bands (`sector_source` column; `rule_sector` keeps the old label); every other group keeps the rule-based sector and `known_as` = the group name in normal capitalisation (`names_sectors.nice_case`). If a group enters the top three bands in a later run, rerun names_sectors for it.
2. "Known as" is the first name column, "Legal name" beside it; the "Act now, outside fin. services" tab uses the new sectors.
3. **Same-group correction:** integrating or legally transferring a business the group bought within the last 24 months is a merger signal (3), type "merger, acquisition or separation (news: integrating a recent acquisition)". Only the 19 signals marked internal in v5 were re-read (`stage2_model.py` job `internal2`). Result: Coventry Building Society / Co-operative Bank (bought January 2025) score 3 again; Microsoft, Mission Group and Rix stay 0; the ABF / Primark demerger keeps 3 (v5 exemption).
4. **Size-unconfirmed groups** are left out of "All", "Act now" and "Act now, outside fin. services" (not hidden) and appear only in "Size unconfirmed", with their briefs. No hidden rows or active filters anywhere (filter buttons only). Briefs are shown only for Act now groups (older briefs of groups that left Act now are not shown).
5. Plain column headings in Tom's order (`export_full.HEAD`); rank is 1..n within each tab. "How to read this" is first and explains every column.
6. "How to read this" lists the date each source was pulled and says the list is rescored monthly.

Briefs: rewritten only where counted signals changed since v5 (`briefs_stage2.py ... --v6`): Coventry Building Society and Co-operative Bank. The one new peer pair (Co-operative Bank / Bank of Scotland) was judged with `peer_kind.py send|collect --add`: same kind.

Results: Act now 266 -> 268 (Co-operative Bank from Warming, Coventry from Fit only); Warming 781 -> 780; Strong fit 84; Fit only 10,003 -> 10,002. Sector changed for 287 groups (all in the top three bands); Financial services label 1,659 -> 1,691. Tabs: All 10,063, Act now 223, outside fin. services 121, Size unconfirmed 1,071 (45 Act now, all with briefs). Model spend about $1.50 of $5 (names and sectors $1.43, internal re-read $0.03, briefs $0.04).
