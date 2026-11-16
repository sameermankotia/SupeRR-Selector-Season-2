#!/usr/bin/env python3
"""
Stage 6 - Per-player pressure evidence, and Rajasthan Royals squad gaps.

For each ranked player this computes what they actually do under pressure
versus their own non-pressure baseline, plus the role signals an auction room
needs: which phase their pressure work comes from, how they fare against pace
and spin, and how much of the evidence is from the IPL itself.

It also profiles RR's current squad against the same pressure measures, so
"this player fills a gap" points at a measured gap rather than an assertion.

Usage: python3 player_cards.py <out_dir> <pack_dir> <json_out>
"""
import sys, os, json
import numpy as np
import pandas as pd

TOP_N = 10


def pct(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 1)


def bat_card(d, flag="press_bat"):
    p, n = d[d[flag] == 1], d[d[flag] == 0]
    sp = p.groupby("pace_or_spin")["bat_runs"].mean() * 100
    return {
        "press_balls": int(len(p)), "base_balls": int(len(n)),
        "ipl_press_balls": int(p["is_ipl"].sum()),
        "ipl_share": pct(100 * p["is_ipl"].mean()),
        "sr_press": pct(100 * p["bat_runs"].mean()),
        "sr_base": pct(100 * n["bat_runs"].mean()),
        "bdry_press": pct(100 * (p["bat_runs"] >= 4).mean()),
        "bdry_base": pct(100 * (n["bat_runs"] >= 4).mean()),
        "dot_press": pct(100 * (p["team_runs"] == 0).mean()),
        "bpd_press": pct(len(p) / max(p["is_wicket"].sum(), 1)),
        "bpd_base": pct(len(n) / max(n["is_wicket"].sum(), 1)),
        "death_share": pct(100 * (p["phase"] == "death").mean()),
        "pp_share": pct(100 * (p["phase"] == "powerplay").mean()),
        "sr_pace": pct(sp.get("Pace")), "sr_spin": pct(sp.get("Spin")),
        "chase_share": pct(100 * (p["innings"] == 2).mean()),
        "position": None if d["batting_order"].isna().all() else int(d["batting_order"].median()),
    }


def bowl_card(d, flag="press_bowl"):
    p, n = d[d[flag] == 1], d[d[flag] == 0]
    bt = d["bowling_type"].mode()
    return {
        "press_balls": int(len(p)), "base_balls": int(len(n)),
        "ipl_press_balls": int(p["is_ipl"].sum()),
        "ipl_share": pct(100 * p["is_ipl"].mean()),
        "econ_press": pct(6 * p["team_runs"].mean()),
        "econ_base": pct(6 * n["team_runs"].mean()),
        "dot_press": pct(100 * (p["team_runs"] == 0).mean()),
        "dot_base": pct(100 * (n["team_runs"] == 0).mean()),
        "bpw_press": pct(len(p) / max(p["bowler_wicket"].sum(), 1)),
        "bpw_base": pct(len(n) / max(n["bowler_wicket"].sum(), 1)),
        "bdry_conceded_press": pct(100 * (p["bat_runs"] >= 4).mean()),
        "death_share": pct(100 * (p["phase"] == "death").mean()),
        "pp_share": pct(100 * (p["phase"] == "powerplay").mean()),
        "mid_share": pct(100 * (p["phase"] == "middle").mean()),
        "type": None if bt.empty else str(bt.iat[0]),
        "chase_share": pct(100 * (p["innings"] == 2).mean()),
    }


def main(out_dir, pack_dir, json_out):
    b = pd.read_csv(os.path.join(out_dir, "balls_pressure.csv"), low_memory=False)
    s = pd.read_csv(os.path.join(out_dir, "state.csv"), low_memory=False,
                    usecols=["ball_uid", "pace_or_spin", "batting_order", "bowling_type"])
    b = b.merge(s, on="ball_uid", how="left")
    lg = b[b["is_legal"] == 1]

    mp = pd.read_csv(os.path.join(pack_dir, "competition_team_player_mapping.csv"))
    cp = pd.read_csv(os.path.join(pack_dir, "competitions.csv"))
    t20i = set(cp[cp["match_format"] == "T20I"]["comp_id"])
    nat = (mp[mp["comp_id"].isin(t20i)].groupby("player_id")["team_name"]
           .agg(lambda x: x.mode().iat[0]))
    rr = set(mp[(mp["team_name"].str.contains("Rajasthan", case=False, na=False))
                & (mp["comp_name"] == "IPL 2026")]["player_name"])

    out = {"rr_squad_2026": sorted(rr), "batters": [], "bowlers": []}

    for side, idc, ratef, builder in (
            ("batters", "striker_id", "ratings_bat.csv", bat_card),
            ("bowlers", "bowler_id", "ratings_bowl.csv", bowl_card)):
        r = pd.read_csv(os.path.join(out_dir, ratef))
        for _, row in r.head(TOP_N).iterrows():
            d = lg[lg[idc] == row[idc]]
            card = builder(d)
            card.update({
                "rank": int(row["rank"]), "name": row["name"],
                "nation": str(nat.get(row[idc], "unknown")),
                "at_rr": row["name"] in rr,
                "rating": round(float(row["rating"]), 3),
                "lo": round(float(row["rating_lo"]), 3),
                "hi": round(float(row["rating_hi"]), 3),
                "p_top10": round(float(row["p_top10"]), 3),
                "press_value": round(float(row["press_value"]), 4),
                "resilience": round(float(row["resilience"]), 4),
                "matches": int(row["matches"]),
            })
            out[side].append(card)

        # ---- RR squad profile on the same measure ----
        rr_rows = r[r["name"].isin(rr)]
        out[f"rr_{side}"] = [{
            "name": x["name"], "rank": int(x["rank"]), "of": int(len(r)),
            "percentile": round(100 * (1 - (x["rank"] - 1) / len(r)), 0),
            "press_value": round(float(x["press_value"]), 4),
            "press_balls": int(x["press_balls"]),
        } for _, x in rr_rows.iterrows()]
        out[f"{side}_pool"] = int(len(r))

    # ---- where RR's pressure coverage is thin, by phase ----
    rr_ids = lg[lg["striker_name"].isin(rr)]["striker_id"].unique()
    rrb = lg[lg["bowler_name"].isin(rr)]["bowler_id"].unique()
    out["rr_phase_cover"] = {}
    for lbl, ids, idc, flag in (("batting", rr_ids, "striker_id", "press_bat"),
                                ("bowling", rrb, "bowler_id", "press_bowl")):
        d = lg[lg[idc].isin(ids) & (lg[flag] == 1) & (lg["is_ipl"] == 1)]
        out["rr_phase_cover"][lbl] = {
            k: int(v) for k, v in d["phase"].value_counts().items()}

    json.dump(out, open(json_out, "w"), indent=2)
    print(f"wrote {json_out}")
    print(f"  RR 2026 squad: {len(rr)} players")
    for side in ("batters", "bowlers"):
        print(f"\n  RR players in the eligible {side} pool "
              f"(of {out[f'{side}_pool']}):")
        for x in out[f"rr_{side}"]:
            print(f"    {x['name']:<22} rank {x['rank']:>3}/{x['of']}  "
                  f"top {100-x['percentile']:.0f}%  value {x['press_value']:+.3f}")
    print(f"\n  RR IPL pressure deliveries by phase: {out['rr_phase_cover']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
