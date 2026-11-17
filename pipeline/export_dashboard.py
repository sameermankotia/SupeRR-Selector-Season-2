#!/usr/bin/env python3
"""
Stage 7 - Export a single JSON payload for the dashboard.

Usage: python3 export_dashboard.py <out_dir> <json_out>
"""
import sys, os, json
import numpy as np
import pandas as pd


def main(out_dir, json_out):
    md = json.load(open(os.path.join(out_dir, "model_diagnostics.json")))
    pdg = json.load(open(os.path.join(out_dir, "pressure_diagnostics.json")))
    rd = json.load(open(os.path.join(out_dir, "rating_diagnostics.json")))
    cards = json.load(open(os.path.join(out_dir, "player_cards.json")))
    avail = json.load(open(os.path.join(out_dir, "availability.json")))
    bat = pd.read_csv(os.path.join(out_dir, "ratings_bat.csv"))
    bowl = pd.read_csv(os.path.join(out_dir, "ratings_bowl.csv"))
    b = pd.read_csv(os.path.join(out_dir, "balls_pressure.csv"), low_memory=False)

    def pool(df):
        return [{"name": r["name"], "rank": int(r["rank"]),
                 "rating": round(float(r["rating"]), 3),
                 "press": round(float(r["press_value"]), 4),
                 "res": round(float(r["resilience"]), 4),
                 "lo": round(float(r["rating_lo"]), 3),
                 "hi": round(float(r["rating_hi"]), 3),
                 "p10": round(float(r["p_top10"]), 3),
                 "balls": int(r["press_balls"]), "matches": int(r["matches"])}
                for _, r in df.iterrows()]

    def deciles(key):
        d = pd.DataFrame(pdg[key]).T.reset_index(drop=True)
        return [{"decile": i + 1,
                 "runs_per_wkt": round(float(r["runs_per_wkt"]), 1),
                 "wkt_pct": round(float(r["wkt_pct"]), 2),
                 "runs_per_ball": round(float(r["runs_per_ball"]), 3),
                 "balls_per_wkt": round(float(r["balls_per_wkt"]), 1),
                 "strike_rate": round(float(r["strike_rate"]), 1)}
                for i, r in d.iterrows()]

    lev = (b.pivot_table(index="phase", columns="innings", values="leverage",
                         aggfunc="mean").reindex(["powerplay", "middle", "death"]))
    share = (b.groupby("phase")[["press_bat", "press_bowl"]].mean() * 100
             ).reindex(["powerplay", "middle", "death"])

    payload = {
        "meta": {
            "deliveries": int(len(b)), "matches": int(b["match_id"].nunique()),
            "seasons": "IPL 2022-2026 + T20I",
            "ipl_matches": int(b[b.is_ipl == 1]["match_id"].nunique()),
            "t20i_matches": int(b[b.is_ipl == 0]["match_id"].nunique()),
            "state_accuracy": 98.91,
            "press_share_bat": round(100 * pdg["share_bat"], 0),
            "press_share_bowl": round(100 * pdg["share_bowl"], 0),
            "corr_pi": round(pdg["corr_pi"], 2),
            "both_flagged": round(100 * pdg["both_flagged"], 0),
            "wp_auc_chase": round(md["innings2"]["oof_auc"], 3),
            "wp_auc_set": round(md["innings1"]["oof_auc"], 3),
            "wp_forward": round(md["innings2"]["forward_auc"], 3),
            "pool_bat": int(rd["bat"]["eligible"]), "pool_bowl": int(rd["bowl"]["eligible"]),
        },
        "reliability": {
            "bat": {k: round(float(v), 3) for k, v in rd["bat"]["reliability"].items()
                    if isinstance(v, (int, float))},
            "bowl": {k: round(float(v), 3) for k, v in rd["bowl"]["reliability"].items()
                     if isinstance(v, (int, float))},
            "weights": {"bat": [rd["bat"]["w_abs"], rd["bat"]["w_res"]],
                        "bowl": [rd["bowl"]["w_abs"], rd["bowl"]["w_res"]]},
            "wpa_bat": round(rd["bat"]["wpa_spearman"], 3),
            "wpa_bowl": round(rd["bowl"]["wpa_spearman"], 3),
        },
        "calibration": {
            "chase": [{"p": round(x["pred"], 3), "a": round(x["actual"], 3), "n": x["n"]}
                      for x in md["innings2"]["reliability"]],
            "set": [{"p": round(x["pred"], 3), "a": round(x["actual"], 3), "n": x["n"]}
                    for x in md["innings1"]["reliability"]],
        },
        "validation": {"bat": deciles("validation_bat"), "bowl": deciles("validation_bowl")},
        "leverage": [{"phase": p.title(), "set": round(float(lev.loc[p, 1]), 3),
                      "chase": round(float(lev.loc[p, 2]), 3)} for p in lev.index],
        "share": [{"phase": p.title(), "bat": round(float(share.loc[p, "press_bat"]), 1),
                   "bowl": round(float(share.loc[p, "press_bowl"]), 1)} for p in share.index],
        "batters": cards["batters"], "bowlers": cards["bowlers"],
        "pool": {"bat": pool(bat), "bowl": pool(bowl)},
        "avail": {
            "as_of": avail["as_of"], "source": avail["source"], "caveat": avail["caveat"],
            "purse": avail["purse"], "slots": avail["slots"],
            "overseas_slots": avail["overseas_slots"],
            "bat": {"board": avail["bat"]["board"], "alternatives": avail["bat"]["alternatives"],
                    "n_available": avail["bat"]["n_available"],
                    "n_eligible": avail["bat"]["n_eligible"],
                    "status": {x["name"]: {"status": x["status"], "team": x["team"]}
                               for x in avail["bat"]["all"]}},
            "bowl": {"board": avail["bowl"]["board"], "alternatives": avail["bowl"]["alternatives"],
                     "n_available": avail["bowl"]["n_available"],
                     "n_eligible": avail["bowl"]["n_eligible"],
                     "status": {x["name"]: {"status": x["status"], "team": x["team"]}
                                for x in avail["bowl"]["all"]}},
        },
        "rr": {"squad": cards["rr_squad_2026"],
               "batters": cards["rr_batters"], "bowlers": cards["rr_bowlers"],
               "pool_bat": cards["batters_pool"], "pool_bowl": cards["bowlers_pool"]},
    }
    json.dump(payload, open(json_out, "w"), separators=(",", ":"))
    print(f"wrote {json_out} ({os.path.getsize(json_out)/1024:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
