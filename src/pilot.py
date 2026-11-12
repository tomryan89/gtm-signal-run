"""Pick the pilot sample at random (fixed seed in settings.toml, so it can be repeated).

  python src/pilot.py

100 UK groups containing an FCA-authorised entity, 150 other UK groups, 50 Irish groups.
Output: output/step3/pilot_groups.csv and pilot_entities.csv (every entity of each picked group)."""
import pandas as pd

from common import INTERIM, OUTPUT, log, paths, settings

P = settings()["pilot"]
OUT = OUTPUT / "step3"


def full():
    """Step 7: every group in the universe (settings [run] scope = "full")."""
    P_ = paths()
    P_["groups"].parent.mkdir(parents=True, exist_ok=True)
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    per = g.groupby("group_id").agg(group_name=("group_name", "first"), entities=("entity_id", "size"),
                                    countries=("country", lambda s: "/".join(sorted(set(s))))).reset_index()
    per["stratum"] = per.countries.map(lambda c: "Irish" if c == "IE" else "UK" if c == "UK" else "UK and Irish")
    per.to_csv(P_["groups"], index=False)
    g.merge(per[["group_id", "stratum"]], on="group_id").to_csv(P_["entities"], index=False)
    log("scope", "full", groups=len(per), entities=len(g))
    print(f"full run: {len(per)} groups, {len(g)} entities")


def main():
    if paths()["scope"] == "full":
        return full()
    OUT.mkdir(parents=True, exist_ok=True)
    g = pd.read_csv(OUTPUT / "step2" / "groups.csv", dtype=str).fillna("")
    f = pd.read_csv(INTERIM / "fca_firms.csv", dtype=str).fillna("")
    fca_auth = set(f[f.authorised == "True"].entity_id)
    g["fca_authorised"] = g.entity_id.isin(fca_auth)
    fca_auth = set(f[f.counts_as_financial.astype(str) == "True"].entity_id) if "counts_as_financial" in f else fca_auth
    g["fca_authorised"] = g.entity_id.isin(fca_auth)
    per = g.groupby("group_id").agg(group_name=("group_name", "first"), entities=("entity_id", "size"),
                                    countries=("country", lambda s: "/".join(sorted(set(s)))),
                                    fca=("fca_authorised", "any")).reset_index()
    ie = per[per.countries == "IE"]
    uk = per[per.countries != "IE"]
    if P.get("mode") == "keep":
        from common import ROOT
        old = pd.read_csv(ROOT / P["keep_from"], dtype=str)
        kept = old[old.entity_id.isin(g.entity_id)]
        gids = set(g[g.entity_id.isin(kept.entity_id)].group_id)
        pick = per[per.group_id.isin(gids)].copy()
        pick["stratum"] = ["Irish" if c == "IE" else "UK, FCA-authorised firm" if f_ else "UK, other"
                           for c, f_ in zip(pick.countries, pick.fca)]
        ents = g[g.group_id.isin(pick.group_id)].merge(pick[["group_id", "stratum"]], on="group_id")
        pick.to_csv(OUT / "pilot_groups.csv", index=False)
        ents.to_csv(OUT / "pilot_entities.csv", index=False)
        dropped = old[~old.entity_id.isin(g.entity_id)]
        dropped.to_csv(OUT / "pilot_dropped_entities.csv", index=False)
        log("pilot", "kept", groups=len(pick), entities=len(ents), original_entities=len(old), dropped=len(dropped))
        print(f"kept {len(old) - len(dropped)} of {len(old)} original pilot entities ({len(dropped)} removed from the universe)")
        print(f"-> {len(pick)} groups, {len(ents)} entities in those groups")
        print(pick.stratum.value_counts().to_string())
        return
    pick = pd.concat([
        uk[uk.fca].sample(P["financial_groups"], random_state=P["seed"]).assign(stratum="UK, FCA-authorised firm"),
        uk[~uk.fca].sample(P["other_uk_groups"], random_state=P["seed"]).assign(stratum="UK, other"),
        ie.sample(P["irish_groups"], random_state=P["seed"]).assign(stratum="Irish"),
    ])
    pick.to_csv(OUT / "pilot_groups.csv", index=False)
    ents = g[g.group_id.isin(pick.group_id)].merge(pick[["group_id", "stratum"]], on="group_id")
    ents.to_csv(OUT / "pilot_entities.csv", index=False)
    log("pilot", "sample", seed=P["seed"], groups=len(pick), entities=len(ents),
        pool_fca=int(uk.fca.sum()), pool_other=int((~uk.fca).sum()), pool_ie=len(ie))
    print(f"picked {len(pick)} groups ({len(ents)} entities) from pools: FCA {int(uk.fca.sum())}, "
          f"other UK {int((~uk.fca).sum())}, Irish {len(ie)}")
    print(pick.stratum.value_counts().to_string())


if __name__ == "__main__":
    main()
