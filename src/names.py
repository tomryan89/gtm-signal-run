"""Name normalisation used for every exact-name match. Deliberately conservative: no fuzzy matching."""
import re
import unicodedata

_SUFFIXES = [
    (r"\bpublic limited company\b", "plc"),
    (r"\bdesignated activity company\b", "dac"),
    (r"\bunlimited company\b", "uc"),
    (r"\bcompany limited by guarantee\b", "clg"),
    (r"\bprivate limited company\b", "ltd"),
    (r"\blimited\b", "ltd"),
    (r"\bteoranta\b", "teo"),
    (r"\bcuideachta ghníomhaíochta ainmnithe\b", "dac"),
    (r"\bu\s?c\b", "uc"),
    (r"\bd\s?a\s?c\b", "dac"),
    (r"\bp\s?l\s?c\b", "plc"),
    (r"\bco\b", "company"),
]


def norm(name: str | None) -> str:
    if not name or not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"^the\s+", "", s.strip())
    for pat, rep in _SUFFIXES:
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


def norm_ch_number(n) -> str:
    """Companies House numbers are 8 characters; pay gap files sometimes drop leading zeros."""
    if n is None or (isinstance(n, float)) or str(n).strip() == "":
        return ""
    s = str(n).strip().upper().replace(" ", "")
    if s.isdigit():
        s = s.zfill(8)
    elif re.fullmatch(r"[A-Z]{2}\d{1,6}", s):
        s = s[:2] + s[2:].zfill(6)
    return s if re.fullmatch(r"[A-Z0-9]{8}", s) else ""
