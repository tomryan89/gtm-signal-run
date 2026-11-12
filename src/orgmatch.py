"""Match an organisation name to a group, the same way job-advert employers are matched (jobs.match): exact
normalised name, then the name without legal-form words (entity names, and foreign-parent group names), then the
brand lookup. Several groups or none -> review (never guess)."""
import pandas as pd

from common import OUTPUT
from jobs import core
from names import norm


class Matcher:
    def __init__(self):
        u = pd.read_csv(OUTPUT / "step1" / "universe.csv", dtype=str).fillna("")
        g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
        self.grp = dict(zip(g.entity_id, g.group_id))
        self.gname = dict(zip(g.group_id, g.group_name))
        self.exact, self.by_core = {}, {}
        for e in u.itertuples():
            self.exact.setdefault(norm(e.name), set()).add(e.entity_id)
            c = core(e.name)
            if c:
                self.by_core.setdefault(c, set()).add(e.entity_id)
        for gid, gn in g[["group_id", "group_name"]].drop_duplicates().itertuples(index=False):
            c = core(gn)
            if c and gid.startswith("FP:"):
                self.by_core.setdefault(c, set()).add(gid)
        from brands import lookup, recruiters
        self.brand = lookup()

    def match(self, name):
        """(group_id, entity_id, how) or ("", "", review reason)."""
        n = norm(name)
        if not n:
            return "", "", "no name"
        ids, how = self.exact.get(n), "exact name"
        if not ids:
            ids, how = self.by_core.get(core(name)), "name without legal-form words"
        if (not ids or len({self.grp.get(i, i) for i in ids}) > 1) and n in self.brand:
            ids, how = {self.brand[n]}, "brand lookup"
        if not ids:
            return "", "", "not in the universe"
        groups = {self.grp.get(i, i) for i in ids}
        if len(groups) > 1:
            return "", "", f"name matches {len(groups)} different groups"
        ent = sorted(i for i in ids if i in self.grp)
        return groups.pop(), (ent[0] if ent else ""), how
