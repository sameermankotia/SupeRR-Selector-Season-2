#!/usr/bin/env python3
"""
Stage 3 - Pressure Index, defined separately for batting and bowling.

    PI_side = L_norm  x  U_side

L_norm   normalised Leverage from the validated win-probability model: how much
         this single delivery can swing the match result. Shared by both sides,
         and it is what stops a dead-rubber death over counting as "pressure".
U_side   a transparent composite of match-situation squeeze signals, combined
         with a probabilistic OR so that simultaneous squeezes compound.

Why the two sides need different definitions: when a chase needs 15 an over the
BATTER is under pressure and the bowler is comfortable; when the same chase is
cruising at 6 required the pressure has flipped to the BOWLER. A single
symmetric pressure flag - which is the obvious approach - gets one of the two
groups exactly backwards.

Usage: python3 pressure.py <balls_enriched_csv> <out_dir>
"""
import sys, os, json
import numpy as np
import pandas as pd

TARGET_SHARE = 0.27     # fraction of deliveries designated "pressure"


def por(*cs):
    """Probabilistic OR: 1 - prod(1 - c). Compounds independent squeezes."""
    out = np.zeros_like(cs[0], dtype=float)
    acc = np.ones_like(cs[0], dtype=float)
    for c in cs:
        acc = acc * (1.0 - np.clip(c, 0, 1))
    return 1.0 - acc


def main(balls_csv, out_dir):
    df = pd.read_csv(balls_csv, low_memory=False)
    print(f"loaded {len(df):,} deliveries")

    sched = 120.0
    df["par_rate"] = df["par_score"] * 6.0 / sched
    legal_done = sched - df["balls_rem"]

    # league-average wickets lost by this point of an innings -> collapse signal
    wk_curve = (df.assign(b=legal_done.astype(int))
                  .groupby("b")
                  .apply(lambda g: (10 - g["wkts_in_hand"]).mean(), include_groups=False))
    exp_wkts = legal_done.astype(int).map(wk_curve).fillna(0).values
    wkts_lost = (10 - df["wkts_in_hand"]).values

    chase = (df["innings"] == 2).values
    rrr = df["rrr"].fillna(0).values
    par_rate = df["par_rate"].values
    crr = df["crr"].fillna(0).values
    over = df["over_no"].values

    # ---------------- batting-side squeeze ----------------
    # needing well above par rate
    chase_squeeze = np.where(chase, np.clip((rrr - par_rate) / (0.6 * par_rate), 0, 1), 0.0)
    # more wickets down than the league norm at this stage
    collapse = np.clip((wkts_lost - exp_wkts) / 3.0, 0, 1)
    # setting a total while behind par pace
    behind_par = np.where(~chase,
                          np.clip(-df["score_vs_par"].values / (0.12 * df["par_score"].values), 0, 1),
                          0.0)
    # innings endgame: every ball must be converted
    death_accel = np.clip((over - 15) / 5.0, 0, 1)
    U_bat = por(chase_squeeze, collapse, behind_par, death_accel)

    # ---------------- bowling-side threat ----------------
    # chase cruising, with wickets in the bank
    on_track = np.where(chase & (rrr > 0),
                        np.clip((par_rate - rrr) / (0.5 * par_rate), 0, 1)
                        * (df["wkts_in_hand"].values / 10.0), 0.0)
    # being taken apart relative to par
    being_hit = np.clip((crr - par_rate) / (0.5 * par_rate), 0, 1)
    # defending at the death
    death_def = np.clip((over - 15) / 5.0, 0, 1)
    # a small total to defend leaves no margin
    small_total = np.where(chase, np.clip((par_rate * sched / 6 - df["target"].fillna(0).values)
                                          / (0.25 * df["par_score"].values), 0, 1), 0.0)
    U_bowl = por(on_track, being_hit, death_def, small_total)

    # ---------------- leverage gate ----------------
    lev_ref = df["leverage"].quantile(0.90)
    L = np.clip(df["leverage"].values / lev_ref, 0, 1)

    df["U_bat"], df["U_bowl"], df["L_norm"] = U_bat, U_bowl, L
    df["PI_bat"] = L * U_bat
    df["PI_bowl"] = L * U_bowl

    thr_bat = df["PI_bat"].quantile(1 - TARGET_SHARE)
    thr_bowl = df["PI_bowl"].quantile(1 - TARGET_SHARE)
    df["press_bat"] = (df["PI_bat"] >= thr_bat).astype(int)
    df["press_bowl"] = (df["PI_bowl"] >= thr_bowl).astype(int)
    print(f"\nthresholds: PI_bat>={thr_bat:.4f}  PI_bowl>={thr_bowl:.4f}")
    print(f"pressure share: batting {df['press_bat'].mean():.1%}  "
          f"bowling {df['press_bowl'].mean():.1%}")

    # =====================================================================
    # VALIDATION - does the index actually isolate harder cricket?
    # =====================================================================
    legal = df["is_legal"] == 1

    def curve(flagcol, label, side):
        """Outcome profile across the pressure distribution.

        NOTE on metrics: raw strike rate is the WRONG lens for batting
        pressure. Under a squeeze T20 batters *attempt* more, so SR rises even
        as the situation gets harder. The honest degradation signals are
        runs-per-dismissal (risk-adjusted output) and runs scored versus the
        model's expectation for that exact state.
        """
        d = df[legal].copy()
        d["dec"] = pd.qcut(d[flagcol].rank(method="first"), 10,
                           labels=False, duplicates="drop")
        g = d.groupby("dec").apply(lambda x: pd.Series({
            "balls": len(x),
            "mean_PI": x[flagcol].mean(),
            "runs_per_ball": x["team_runs"].mean(),
            "strike_rate": 100 * x["bat_runs"].mean(),
            "dot_pct": 100 * (x["team_runs"] == 0).mean(),
            "wkt_pct": 100 * x["is_wicket"].mean(),
            "balls_per_wkt": len(x) / max(x["is_wicket"].sum(), 1),
            "runs_per_wkt": x["team_runs"].sum() / max(x["is_wicket"].sum(), 1),
            "runs_vs_exp": x["team_runs"].mean() - x["exp_runs"].mean(),
        }), include_groups=False)
        print(f"\n--- {label}: league outcomes by {flagcol} decile ---")
        print(g.to_string(float_format=lambda v: f"{v:9.2f}"))
        lo, hi = g.iloc[0], g.iloc[-1]
        print(f"    decile 1 -> 10:  runs/wkt {lo['runs_per_wkt']:.1f} -> "
              f"{hi['runs_per_wkt']:.1f}   balls/wkt {lo['balls_per_wkt']:.1f} -> "
              f"{hi['balls_per_wkt']:.1f}   wkt% {lo['wkt_pct']:.2f} -> {hi['wkt_pct']:.2f}")
        return g

    g_bat = curve("PI_bat", "BATTING pressure", "bat")
    g_bowl = curve("PI_bowl", "BOWLING pressure", "bowl")

    # ---------------------------------------------------------------
    # WITHIN-PLAYER paired test: the strongest validation available.
    # Comparing the SAME player against himself removes every
    # player-quality confound. If pressure is real, the paired
    # differences should lean clearly negative for batters.
    # ---------------------------------------------------------------
    print("\n=== within-player paired test (same player, pressure vs normal) ===")
    for side, idcol, flag in (("BATTERS", "striker_id", "press_bat"),
                              ("BOWLERS", "bowler_id", "press_bowl")):
        d = df[legal].copy()
        agg = d.groupby([idcol, flag]).apply(lambda x: pd.Series({
            "balls": len(x),
            "sr": 100 * x["bat_runs"].mean(),
            "rpb": x["team_runs"].mean(),
            "bpw": len(x) / max(x["is_wicket"].sum(), 1),
        }), include_groups=False).unstack(flag)
        ok = (agg[("balls", 0)] >= 120) & (agg[("balls", 1)] >= 120)
        a = agg[ok]
        n = len(a)
        d_rpb = (a[("rpb", 1)] - a[("rpb", 0)])
        d_bpw = (a[("bpw", 1)] - a[("bpw", 0)])
        from scipy import stats as st
        t1 = st.wilcoxon(d_rpb)
        t2 = st.wilcoxon(d_bpw)
        print(f"\n  {side}  (n={n} players with >=120 balls in both buckets)")
        print(f"    runs/ball   pressure - normal : median {d_rpb.median():+.3f}  "
              f"mean {d_rpb.mean():+.3f}  share worse {100*(d_rpb<0).mean():.0f}%  "
              f"Wilcoxon p={t1.pvalue:.2e}")
        print(f"    balls/wicket pressure - normal: median {d_bpw.median():+.2f}  "
              f"mean {d_bpw.mean():+.2f}  share worse {100*(d_bpw<0).mean():.0f}%  "
              f"Wilcoxon p={t2.pvalue:.2e}")

    # the two definitions must not be the same thing wearing two hats
    r = np.corrcoef(df["PI_bat"], df["PI_bowl"])[0, 1]
    both = ((df["press_bat"] == 1) & (df["press_bowl"] == 1)).mean()
    print(f"\ncorr(PI_bat, PI_bowl) = {r:+.3f}   "
          f"share of balls flagged pressure for BOTH sides = {both:.1%}")
    print("(low/negative correlation is the point: the two sides are squeezed "
          "in different situations)")

    print("\npressure share by phase:")
    print(df.groupby("phase")[["press_bat", "press_bowl"]].mean().to_string())
    print("\npressure share by innings:")
    print(df.groupby("innings")[["press_bat", "press_bowl"]].mean().to_string())

    df.to_csv(os.path.join(out_dir, "balls_pressure.csv"), index=False)
    json.dump({"thr_bat": float(thr_bat), "thr_bowl": float(thr_bowl),
               "share_bat": float(df["press_bat"].mean()),
               "share_bowl": float(df["press_bowl"].mean()),
               "corr_pi": float(r), "both_flagged": float(both),
               "validation_bat": g_bat.to_dict(orient="index"),
               "validation_bowl": g_bowl.to_dict(orient="index")},
              open(os.path.join(out_dir, "pressure_diagnostics.json"), "w"),
              indent=2, default=float)
    print(f"\nwrote {out_dir}/balls_pressure.csv")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
