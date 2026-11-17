#!/usr/bin/env python3
"""
Stage 8 - Auction availability, and role-matched alternatives.

A pressure ranking is only an auction strategy if the players can actually be
bought. This joins the published IPL 2027 retention and release lists onto the
model's eligible pool, then, for every ranked player who is locked up, finds
the closest AVAILABLE player by role.

Role similarity is deliberately simple and inspectable: a small feature vector
of where a player does their pressure work (phase mix, chasing share) and how
(pace/spin split for batters, bowling type for bowlers), z-scored across the
pool and compared by euclidean distance. Candidates are then ordered by model
rating among the reasonably-similar ones, because the point is the best
available player who does a similar job - not the nearest twin.

Usage: python3 availability.py <out_dir> <pack_dir> <retention_json> <json_out>
"""
import sys, os, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from player_cards import bat_card, bowl_card           # noqa: E402

ALIAS = {"Lokesh Rahul": "KL Rahul", "Namboori Tilak Varma": "Tilak Varma",
         "Varun Chakravarthy": "Varun Chakaravarthy",
         "Blessing Muzarbani": "Blessing Muzarabani"}
N_ALT = 3


def main(out_dir, pack_dir, ret_json, json_out):
    R = json.load(open(ret_json))
    retained, released = {}, {}
    for t, xs in R["retained"].items():
        for p in xs:
            retained[p] = t
    for t, xs in R["released"].items():
        for p in xs:
            released[p] = t

    def status(n):
        k = ALIAS.get(n, n)
        if k in retained:
            return "retained", retained[k]
        if k in released:
            return "released", released[k]
        return "unlisted", None

    b = pd.read_csv(os.path.join(out_dir, "balls_pressure.csv"), low_memory=False)
    s = pd.read_csv(os.path.join(out_dir, "state.csv"), low_memory=False,
                    usecols=["ball_uid", "pace_or_spin", "batting_order", "bowling_type"])
    lg = b.merge(s, on="ball_uid", how="left")
    lg = lg[lg["is_legal"] == 1]

    out = {"as_of": R["_as_of"], "source": R["_source"], "caveat": R["_caveat"],
           "purse": R["purse_cr"], "slots": R["slots"],
           "overseas_slots": R["overseas_slots"], "disputed": R["disputed"]}

    # Feature weights matter more than the feature list. Bowling type dominates
    # role for a bowler - a legspinner is not replaced by a fast bowler who
    # happens to bowl in the same overs - so is_spin is weighted heavily.
    # For batters, where in the innings they bat is the dominant role signal.
    for side, idc, ratef, builder, feats, wts in (
            ("bat", "striker_id", "ratings_bat.csv", bat_card,
             ["death_share", "pp_share", "chase_share", "spin_bias", "position"],
             [2.0, 1.0, 0.6, 0.8, 2.0]),
            ("bowl", "bowler_id", "ratings_bowl.csv", bowl_card,
             ["death_share", "pp_share", "mid_share", "chase_share", "is_spin"],
             [1.4, 1.4, 1.0, 0.6, 3.5])):
        r = pd.read_csv(os.path.join(out_dir, ratef))
        rows = []
        for _, x in r.iterrows():
            c = builder(lg[lg[idc] == x[idc]])
            st, team = status(x["name"])
            c.update({"name": x["name"], "rank": int(x["rank"]),
                      "rating": round(float(x["rating"]), 3),
                      "press_value": round(float(x["press_value"]), 4),
                      "resilience": round(float(x["resilience"]), 4),
                      "p_top10": round(float(x["p_top10"]), 3),
                      "status": st, "team": team if team else None,
                      "available": st in ("released", "unlisted")})
            if side == "bat":
                c["spin_bias"] = (c["sr_spin"] or 0) - (c["sr_pace"] or 0)
            else:
                c["is_spin"] = 1.0 if c["type"] and (
                    "break" in c["type"].lower() or "orthodox" in c["type"].lower()
                    or "spin" in c["type"].lower()) else 0.0
            rows.append(c)
        df = pd.DataFrame(rows)

        # z-scored role vector -> euclidean distance
        F = df[feats].astype(float).fillna(df[feats].astype(float).mean())
        Z = (F - F.mean()) / F.std(ddof=0).replace(0, 1)
        Zv = Z.values * np.array(wts)
        avail_mask = df["available"].values

        alts = {}
        for i, row in df.iterrows():
            if row["rank"] > 10:
                continue
            d = np.sqrt(((Zv - Zv[i]) ** 2).sum(axis=1))
            cand = np.where(avail_mask & (np.arange(len(df)) != i))[0]
            if len(cand) == 0:
                alts[row["name"]] = []
                continue
            # keep the closest half on role, then order those by model rating
            near = cand[np.argsort(d[cand])][:max(3, len(cand) // 2)]
            near = sorted(near, key=lambda j: -df.iloc[j]["rating"])
            alts[row["name"]] = [{
                "name": df.iloc[j]["name"], "rank": int(df.iloc[j]["rank"]),
                "status": df.iloc[j]["status"],
                "team": df.iloc[j]["team"] if pd.notna(df.iloc[j]["team"]) else None,
                "press_value": float(df.iloc[j]["press_value"]),
                "p_top10": float(df.iloc[j]["p_top10"]),
                "role_distance": round(float(d[j]), 2),
                "role_match": ("close" if d[j] < 2.5 else
                               "partial" if d[j] < 4.5 else "loose"),
                "press_balls": int(df.iloc[j]["press_balls"]),
            } for j in near[:N_ALT]]

        keep = ["name", "rank", "status", "team", "available", "rating", "press_value",
                "resilience", "p_top10", "press_balls", "ipl_press_balls",
                "death_share", "pp_share", "chase_share"]
        if side == "bat":
            keep += ["sr_press", "sr_base", "bpd_press", "bpd_base", "position"]
        else:
            keep += ["econ_press", "econ_base", "bpw_press", "bpw_base", "type"]

        board = (df[df["available"]].sort_values("rating", ascending=False)
                 .to_dict(orient="records"))
        for rec in board:                      # numpy types are not JSON-safe
            for k, v in list(rec.items()):
                if isinstance(v, (np.integer,)):
                    rec[k] = int(v)
                elif isinstance(v, (np.floating,)):
                    rec[k] = None if np.isnan(v) else round(float(v), 4)
                elif isinstance(v, (np.bool_,)):
                    rec[k] = bool(v)
                elif v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
                    rec[k] = str(v)
        out[side] = {
            "all": df[keep].to_dict(orient="records"),
            "board": board,
            "alternatives": alts,
            "n_eligible": int(len(df)),
            "n_available": int(df["available"].sum()),
        }
        print(f"{side}: {df['available'].sum()} of {len(df)} eligible players available")
        print(f"  best available: " + ", ".join(
            f"{x['name']} (pool rank {x['rank']})" for x in board[:5]))

    json.dump(out, open(json_out, "w"), indent=1, default=str)
    print(f"\nwrote {json_out}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
