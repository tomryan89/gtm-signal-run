"""Pinned copy of the Principal Risks Scanner text and section-finder code (~/projects/risk-scanner, commit 760baae:
scanner/textify.py and scanner/sections.py find_section), so Stage 2 Slice A extracts sections exactly as the
listed-company app does. Do not edit here; change the scanner and re-copy."""
import html
from dataclasses import dataclass, field
import re
import zipfile
from pathlib import Path

_BLOCK = re.compile(r"</?(?:div|p|br|tr|li|h[1-6]|table|section|article|td|th)\b[^>]*>", re.I)
_DROP = re.compile(r"<(script|style|head)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_HIDDEN = re.compile(r"<ix:header\b.*?</ix:header\s*>", re.S | re.I)  # XBRL metadata, not report text
_TAG = re.compile(r"<[^>]+>")


def report_files(zip_path: Path) -> list[str]:
    """The human-readable report document(s) inside an ESEF package."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist()
                 if "/reports/" in n and n.lower().endswith((".xhtml", ".html", ".htm")) and "viewer" not in n.lower()]
    return sorted(names)


def zip_to_lines(zip_path: Path) -> list[str]:
    lines: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        for name in report_files(zip_path):
            lines.extend(xhtml_to_lines(z.read(name).decode("utf-8", "replace")))
    return lines


def xhtml_to_lines(doc: str) -> list[str]:
    doc = _HIDDEN.sub(" ", _DROP.sub(" ", doc))
    doc = _BLOCK.sub("\n", doc)
    text = html.unescape(_TAG.sub("", doc)).replace(" ", " ")
    out = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if line:
            out.append(line)
    return out


def report_to_lines(path: Path) -> list[str]:
    """Any downloaded report: ESEF zip, PDF or a bare XHTML file."""
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return zip_to_lines(path)
    if suffix == ".pdf":
        return pdf_to_lines(path)
    return xhtml_to_lines(path.read_text(encoding="utf-8", errors="replace"))


def pdf_to_lines(path: Path) -> list[str]:
    import pymupdf

    out = []
    with pymupdf.open(path) as doc:
        for page in doc:
            for raw in page.get_text("text").split("\n"):
                line = " ".join(raw.split())
                if line:
                    out.append(line)
    return out


def pdf_text_density(path: Path) -> float:
    """Average characters of text per page; scanned image PDFs come out near 0."""
    import pymupdf

    with pymupdf.open(path) as doc:
        return sum(len(p.get_text("text")) for p in doc) / max(len(doc), 1)


_CONT = r"(?:\s*[:\-–—]?\s*\(?continued\)?)?"
HEADING = re.compile(
    r"^(?:our |group |the group.s |how we manage (?:our )?)?"
    r"(?:"
    r"(?:principal(?: (?:and|&) emerging)?|key|significant|main) risks?(?: (?:and|&) uncertainties)?"
    r"(?: \(risk factors\))?"
    r"|risk management(?: (?:and|&) principal risks?(?: factors)?)?"
    r"|managing (?:our )?risks?|our approach to risk(?: management)?|risk review|risk report"
    r"|(?:assessment|management|summary) of (?:our )?principal risks(?: (?:and|&) uncertainties)?"
    r"|risks? (?:and|&) uncertainties|risk factors(?: (?:and|&) uncertainties)?|risk overview"
    r"|top (?:and emerging )?risks"
    r")"
    r"(?:\s*[–—-]\s*(?:financial|non-financial|strategic|operational|business|group))?"  # "Principal risks – financial"
    + _CONT + r"\.?$",
    re.I,
)
# Headings that start a different part of the report. Deliberately excludes words that reports repeat as page
# navigation tabs on every page ("Governance", "Sustainability", "Strategic report", "Financial statements").
STOP = re.compile(
    r"^(?:(?:our |the |group.s |group )?(?:longer[- ]term |long[- ]term )?viability statement"
    r"|(?:statement of )?going concern(?: and viability)?(?: statement)?$"
    r"|(?:directors.? duties under )?section 172(?:\(1\))?(?: statement)?|s172 statement"
    r"|non-financial and sustainability information(?: statement)?"
    r"|corporate governance report|chair.?s (?:introduction|letter)"
    r"|directors.? report$|independent auditor)",
    re.I,
)
EMERGING = re.compile(r"^(?:spotlight: )?emerging (?:and [a-z]+ )?risks?\b", re.I)
PR_MENTION = re.compile(r"principal\s+risk", re.I)
PR_HEADING = re.compile(
    r"(?:principal|key|significant|main|top) risks?|risks? (?:and|&) uncertainties|risk factors", re.I)

MAX_GAP = 800  # lines between headings of the same chapter
MIN_TAIL = 450  # always keep at least this many lines after the last heading (unless a stop heading comes first)
MAX_QUIET = 250  # beyond that, stop once this many lines in a row don't mention risk
RISK_WORD = re.compile(r"\brisk", re.I)
MAX_LINES = 4000  # sanity cap for one chapter
MIN_PR_MENTIONS = 3
RISK_STRUCT = re.compile(
    r"^(?:description of (?:the )?risk|how we (?:mitigate|manage) (?:this|the) risk|risk owners?|mitigations?|"
    r"mitigating actions|key mitigations?|risk trend|change in (?:the )?year|link to strategy|potential impact)\b",
    re.I)
MIN_STRUCT = 8


@dataclass
class Section:
    found: bool
    reason: str = ""
    start: int = 0
    end: int = 0
    lines: list[str] = field(default_factory=list)
    has_emerging: bool = False
    pr_mentions: int = 0
    headings: list[str] = field(default_factory=list)


def _is_heading(line: str) -> bool:
    return len(line) <= 90 and line[:1].isupper() and not re.search(r"\d\s*$", line) and bool(HEADING.match(line))


def _is_stop(line: str) -> bool:
    return len(line) <= 80 and line[:1].isupper() and not re.search(r"\d\s*$", line) and bool(STOP.match(line))


POINTER = re.compile(r"set out (?:in|on)|(?:are|is) described (?:in|on)|can be found (?:in|on)|see pages? \d", re.I)


def _heading_at(lines: list[str], i: int) -> str | None:
    """The heading starting at line i, also when it wraps onto a second line ("PRINCIPAL AND EMERGING RISKS AND" /
    "UNCERTAINTIES")."""
    line = lines[i]
    if _is_heading(line):
        return line
    if i + 1 < len(lines) and len(line) <= 50 and len(lines[i + 1]) <= 40:
        joined = f"{line} {lines[i + 1]}"
        if _is_heading(joined):
            return joined
    return None


def find_section(lines: list[str]) -> Section:
    heads = {i: h for i in range(len(lines)) if (h := _heading_at(lines, i))}
    # skip the second line of a wrapped heading we already matched on the line before
    hits = [i for i in heads if not (i - 1 in heads and heads[i - 1].endswith(lines[i]) and heads[i - 1] != lines[i - 1])]
    if not hits:
        return Section(False, "no risk chapter heading found")

    stops = [i for i, l in enumerate(lines) if _is_stop(l)]
    clusters: list[list[int]] = [[hits[0]]]
    for i in hits[1:]:
        prev = clusters[-1][-1]
        if i - prev <= MAX_GAP and not any(prev < s < i for s in stops):
            clusters[-1].append(i)
        else:
            clusters.append([i])

    def span(c: list[int]) -> tuple[int, int]:
        """From the first heading to a stop heading; otherwise at least MIN_TAIL lines past the last heading, and
        further while the text keeps talking about risk. Erring long is deliberate: extra text costs a little
        Haiku time, a cut-off section loses risks."""
        start, last = c[0], c[-1]
        limit = min(len(lines), start + MAX_LINES)
        end, quiet = limit, 0
        for j in range(last + 1, limit):
            if _is_stop(lines[j]):
                end = j
                break
            quiet = 0 if RISK_WORD.search(lines[j]) else quiet + 1
            if quiet >= MAX_QUIET and j >= last + MIN_TAIL:
                end = max(j - quiet + 1, last + MIN_TAIL)
                break
        return start, end

    def score(c: list[int]) -> int:
        s, e = span(c)
        return sum(1 for l in lines[s:e] if PR_MENTION.search(l))

    def pointer(c: list[int]) -> bool:  # a lone heading over "…are set out in the Principal Risks section…"
        return len(c) == 1 and any(POINTER.search(l) for l in lines[c[0] + 1: c[0] + 8])

    def named(c: list[int]) -> bool:  # has a heading that actually says "principal/key risks"
        return not pointer(c) and any(PR_HEADING.search(heads[i]) for i in c)

    if not any(PR_MENTION.search(l) for l in lines) and not any(named(c) for c in clusters):
        return Section(False, "report never mentions principal risks (financial statements only, or not in English?)")
    def structure(c: list[int]) -> int:  # lines that only appear in risk-by-risk write-ups
        s_, e_ = span(c)
        return sum(1 for l in lines[s_:e_] if len(l) <= 60 and RISK_STRUCT.match(l))

    # Prefer a chapter with a "principal risks" heading, or one laid out risk by risk ("Description of risk",
    # "Risk owner", "How we mitigate"): Airtel Africa's real chapter is headed "Managing our risk", while a committee
    # report elsewhere has a "Principal risks" sub-heading that only points to it.
    best = max(clusters, key=lambda c: (named(c) or structure(c) >= MIN_STRUCT, score(c) + structure(c), len(c)))
    pr = score(best)
    # A chapter headed "Principal risks…" counts even if small companies rarely repeat the phrase.
    if pr < MIN_PR_MENTIONS and not named(best):
        return Section(False, f"risk headings found, but none near enough mentions of principal risks ({pr})")
    s, e = span(best)
    body = lines[s:e]
    return Section(
        True, start=s, end=e, lines=body, pr_mentions=pr,
        has_emerging=any(EMERGING.match(l) for l in body) or any(re.search(r"emerging\s+risk", l, re.I) for l in body),
        headings=sorted({heads[i] for i in best}),
    )


