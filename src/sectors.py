"""The group's largest member and its industry codes (full run review points 2 and 3, Tom 11 Nov 2026).

The largest member is the one with the largest pay gap staff band whose industry codes are not only holding or
head-office codes (settings [sector_label] ignore_code_prefixes). Used for the sector label and for the critical
infrastructure / pharmaceuticals need signals, which count only when they are the largest member's sector."""
import re

from common import settings

ST = settings()


def band_rank(size_band):
    b = (size_band or "").replace(" staff", "")
    bl = ST["universe"]["min_staff_bands"]
    return bl.index(b) + 1 if b in bl else 0


def codes_of(industry_code):
    """Real industry codes (digits only), holding and head-office codes removed."""
    ign = tuple(ST["sector_label"]["ignore_code_prefixes"])
    out = []
    for c in re.split(r"[,;]", industry_code or ""):
        c = c.strip()
        d = re.sub(r"\D", "", c[:-2] if c.endswith(".0") else c)
        if d and d != ST["universe"]["gpg_public_sector_code"] and not d.startswith(ign):
            out.append(d)
    return out


def lead_member(entity_ids, size_band, industry_code):
    """(entity_id, codes) of the largest member with real industry codes; ('', []) if none has any.
    size_band / industry_code: dicts entity_id -> value. Ties keep the order given."""
    for e in sorted(entity_ids, key=lambda e: -band_rank(size_band.get(e, ""))):
        cs = codes_of(industry_code.get(e, ""))
        if cs:
            return e, cs
    return "", []
