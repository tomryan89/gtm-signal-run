"""Read firm names from the Central Bank of Ireland register PDFs (converted to text) and tie each to a CRO
company by exact normalised name. Output: data/interim/cbi_firms.csv (matched) and cbi_review.csv (not tied).

How a firm is read: only the first column of each register (the name column) is used, so addresses,
passporting countries, agents and branches (all further right) are ignored. A name may wrap over up to
three lines; we try 1, 2 and 3 joined lines and keep whichever exactly equals a CRO company name."""
import re

import pandas as pd

from common import INTERIM, RAW, log
from names import norm

CBI = RAW / "cbi"
NAME_COL_MAX_INDENT = 22       # name column starts at or before this character position
DATE = re.compile(r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b")
REF = re.compile(r"^\s{0,4}(C\d{3,7}|\d{1,4}CU)\s+")
SUFFIX = re.compile(r"\b(ltd|limited|dac|plc|uc|teo|teoranta|clg|company|society|unlimited|"
                    r"designated activity company|credit union limited)\.?\s*$", re.I)
COMPANY_END = re.compile(r"\b(ltd|dac|plc|uc|teo|clg)$")
SKIP = re.compile(r"^(run date|page \d|ref\.? no|name|section|register|undertakings|solvency|insurance business|"
                  r"\(?[a-z]\)|\(?[ivx]+\)|t/a|c/o|registered number|applicant name)", re.I)


def first_cell(line: str):
    """Return (indent, text) of the first column cell, or None."""
    m = REF.match(line)
    ref = m.group(1) if m else None
    body = line[m.end():] if m else line
    offset = m.end() if m else 0
    stripped = body.lstrip()
    if not stripped:
        return None
    indent = offset + len(body) - len(stripped)
    cell = re.split(r"\s{2,}", stripped)[0].strip()
    return indent, cell, ref


def parse_register(txt_path, cro_index):
    label = txt_path.with_suffix(".label").read_text().strip()
    text = txt_path.read_text()
    has_withdrawn_col = bool(re.search(r"Authorisation\s*\n?.*Withdrawn|Date\s+Withdrawn", text, re.I)) or \
        "Withdrawn" in text[:3000]
    lines = text.splitlines()
    # name column position: most common indent of the name on reference-number lines, if any
    ref_ind = [first_cell(ln)[0] for ln in lines if REF.match(ln) and first_cell(ln)]
    col = max(set(ref_ind), key=ref_ind.count) if ref_ind else None

    def in_name_col(ind):
        return abs(ind - col) <= 2 if col is not None else ind <= NAME_COL_MAX_INDENT

    if "credit_unions" in txt_path.stem:
        cus = [dict(register=label, ref=fc[2], name=fc[1], withdrawn=False, cro_num="")
               for ln in lines if (fc := first_cell(ln)) and fc[2] and fc[2].endswith("CU")]
        return cus, []
    cells = []
    for i, ln in enumerate(lines):
        fc = first_cell(ln)
        if fc and in_name_col(fc[0]) and not SKIP.match(fc[1]):
            cells.append((i, fc[1], fc[2], ln))
        else:
            cells.append((i, None, None, ln))
    matched, review, used = [], [], set()
    for k, (i, cell, ref, ln) in enumerate(cells):
        if cell is None or i in used:
            continue
        found = None
        parts = [cell]
        for extra in range(3):
            if extra:
                j = k + extra
                if j >= len(cells) or cells[j][1] is None or cells[j][2]:
                    break
                parts.append(cells[j][1])
            joined = norm(" ".join(parts))
            # a name can run into the next column with a single space: also try dropping up to 2 end words,
            # but only when what is left still ends in a company suffix
            toks = joined.split()
            cands = [joined] + [" ".join(toks[:-d]) for d in (1, 2) if len(toks) > d + 1]
            cands = [c for c in cands if c == joined or COMPANY_END.search(c)]
            hit = next((c for c in cands if c in cro_index), None)
            if hit:
                found = (hit, extra)
                break
        withdrawn = has_withdrawn_col and len(DATE.findall(ln)) >= 2
        if found:
            nums = cro_index[found[0]]
            for e in range(found[1] + 1):
                used.add(cells[k + e][0])
            # Section 10 register: the Institution Type column says "Investment Intermediary" (retail adviser)
            # or "Section 10 Investment Firm" (e.g. fund administrators), over the name line and the next one
            itype = ""
            if "Section 10" in label:
                j = next((q for q in range(k, -1, -1) if cells[q][2]), k)     # the firm's reference-number line
                txt = cells[j][3] + " " + (cells[j + 1][3] if j + 1 < len(cells) else "")
                itype = "Investment Intermediary" if "Intermediary" in txt else \
                        "Section 10 Investment Firm" if "Section 10" in txt else "unknown"
            row = dict(register=label, ref=ref or "", name=" ".join(parts), withdrawn=withdrawn, institution_type=itype)
            if len(nums) == 1:
                matched.append({**row, "cro_num": nums[0]})
            else:
                review.append({**row, "reason": f"name matches {len(nums)} CRO companies: {', '.join(map(str, nums[:5]))}"})
        elif (ref or SUFFIX.search(cell)) and len(norm(cell).split()) >= 3 and not (k and cells[k-1][0] in used):
            # looks like a firm (has a reference number or ends in a company suffix) but no exact CRO name
            if not withdrawn:
                review.append(dict(register=label, ref=ref or "", name=cell, withdrawn=withdrawn,
                                   reason="no exact CRO name match (name may wrap or differ)"))
    return matched, review


def main():
    cro = pd.read_csv(RAW / "cro" / "companies.csv", dtype=str, usecols=["company_num", "company_name", "company_status"])
    cro["n"] = cro.company_name.map(norm)
    # prefer live companies when a name is shared by a dissolved and a live company
    live = cro[cro.company_status.str.strip() == "Normal"]
    idx = live.groupby("n").company_num.apply(list).to_dict()
    for n, g in cro.groupby("n").company_num:
        idx.setdefault(n, list(g))
    all_m, all_r = [], []
    for p in sorted(CBI.glob("*.txt")):
        m, r = parse_register(p, idx)
        print(f"{p.stem[:55]:55s} matched={len(m):4d} review={len(r):4d}")
        log("cbi", "parsed", register=p.stem, matched=len(m), review=len(r))
        all_m += m
        all_r += r
    m = pd.DataFrame(all_m)
    m = m[~m.withdrawn]
    m["cro_num"] = m.cro_num.fillna("")
    m.to_csv(INTERIM / "cbi_firms.csv", index=False)
    pd.DataFrame(all_r).to_csv(INTERIM / "cbi_review.csv", index=False)
    print("authorised firms tied to CRO:", m[m.cro_num != ""].cro_num.nunique(), " credit unions:", (m.cro_num == "").sum(), " review rows:", len(all_r))


if __name__ == "__main__":
    INTERIM.mkdir(parents=True, exist_ok=True)
    main()
