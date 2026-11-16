#!/usr/bin/env python3
"""
Stage 4 - Player ratings under pressure (reliability-calibrated).

The runs term and the wicket term are kept SEPARATE rather than summed into a
single net-run-value and ranked on. A wicket is worth several runs and
dismissals are rare, so that term carries far more variance per unit of
repeatable signal than the scoring term does; summing them first can produce a
composite less reliable than either part.

So nothing is weighted by taste. Each component is shrunk by its OWN
empirically measured reliability:

  1. split the matches in half at random, 60 times, and correlate each
     component's per-player rate across the two halves  -> r_half
  2. Spearman-Brown up to the full sample                -> r_full = 2r/(1+r)
  3. reliability IS the signal share, so true_var = r_full * observed_var,
     and each player's error variance scales as 1/(their effective sample)
  4. shrink_i = true_var / (true_var + err_var_i)

A component that does not replicate collapses to the league mean on its own
evidence. Split-half is taken at MATCH level, so it also absorbs the
within-match correlation that an independence assumption would miss.

Final rating, per side, from the WEIGHTS table below:
    w_abs * z(shrunk pressure value) + w_res * z(shrunk resilience delta)
where the absolute term is performance in pressure states and the resilience
term is that minus the player's own non-pressure baseline.

Usage: python3 ratings.py <balls_pressure_csv> <state_csv> <out_dir>
"""
import sys, os, json
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from scipy import stats as st

SEED = 17
NSPLIT = 5
RNG = np.random.default_rng(SEED)

# Side-specific rating mix. Set these from the split-half reliability the run
# reports for each side's resilience term: where resilience does not replicate,
# weighting it degrades the composite, so it earns weight only where it holds up.
# Re-measure before changing - do not carry these over to another dataset.
WEIGHTS = {"bat": (0.70, 0.30), "bowl": (1.00, 0.00)}
HALF_LIFE = 2.0
IPL_W, T20I_W = 1.00, 0.75
MIN_PRESS_BALLS = 250          # raised: reliability roughly doubles 150 -> 300
MIN_BASE_BALLS = 250
MIN_MATCHES = 15
RECENT_SEASONS = {2025, 2026}

# --- auction-relevance filters -------------------------------------------
# The task is an IPL auction, so two constraints apply that pure performance
# ranking misses.
#
# 1. Players from these boards cannot be signed at an IPL auction at all, so a
#    ranking that lists them is not actionable however well they rate.
INELIGIBLE_NATIONS = {"Pakistan"}
# 2. A rating whose evidence is almost entirely from T20Is is an extrapolation
#    into the target competition. Require a minimum pressure sample in the IPL
#    itself. The exact floor is not load-bearing: anything from 50 to 150
#    produces the same changes to the top ten, which is why this is a filter
#    and not a tuned parameter.
MIN_IPL_PRESS_BALLS = 100
N_BOOT = 400
N_REL_REP = 60

BALL_FEATURES = ["innings", "balls_rem", "wkts_in_hand", "score_before", "crr",
                 "runs_required", "rrr", "over_no", "is_ipl", "resources"]
BOWLER_CHARGED = {"wide", "Overstep", "other", "Penalty"}


def xfit(model_fn, X, y, groups, proba=False):
    out = np.zeros(len(X))
    for tr, te in GroupKFold(n_splits=NSPLIT).split(X, y, groups):
        m = model_fn().fit(X.iloc[tr], y.iloc[tr])
        out[te] = m.predict_proba(X.iloc[te])[:, 1] if proba else m.predict(X.iloc[te])
    return out


def reg():
    return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06,
                                         min_samples_leaf=200, early_stopping=False,
                                         random_state=SEED)


def clf():
    return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06,
                                          min_samples_leaf=200, early_stopping=False,
                                          l2_regularization=2.0, random_state=SEED)


def split_half_rho(cell, idc, flag, numcol, wcol, players, nrep=N_REL_REP):
    """Mean match-level split-half Spearman for one component."""
    c = cell[(cell[flag] == 1) & cell[idc].isin(players)]
    if len(c) == 0:
        return np.nan
    mids = c["match_id"].unique()
    pid, num, wt = c[idc].values, c[numcol].values, c[wcol].values
    mi = c["match_id"].map({m: i for i, m in enumerate(mids)}).values
    codes, uniq = pd.factorize(pid)
    n = len(uniq)
    rs = []
    for _ in range(nrep):
        h = RNG.integers(0, 2, len(mids))[mi]
        out = []
        for side in (0, 1):
            s = h == side
            w = np.bincount(codes[s], weights=wt[s], minlength=n)
            v = np.bincount(codes[s], weights=num[s], minlength=n)
            out.append(np.divide(v, w, out=np.full(n, np.nan), where=w > 0))
        a, b = out
        ok = ~np.isnan(a) & ~np.isnan(b)
        if ok.sum() > 20:
            rs.append(st.spearmanr(a[ok], b[ok]).statistic)
    return float(np.nanmean(rs)) if rs else np.nan


def calibrated_shrink(rate, w, r_half):
    """Shrink toward the league mean by empirically measured reliability.

    reliability = signal share of observed variance, so true_var = r_full*obs_var
    and each player's error variance scales inversely with their sample weight.
    """
    r_full = np.clip(2 * r_half / (1 + r_half), 0.0, 0.99) if np.isfinite(r_half) else 0.0
    mu = float(np.average(rate, weights=w))
    obs = float(np.average((rate - mu) ** 2, weights=w))
    true_var = max(r_full * obs, 1e-12)
    err_mean = max(obs - true_var, 1e-12)
    err_i = err_mean * (np.mean(w) / np.maximum(w, 1e-9))
    shrink = true_var / (true_var + err_i)
    return mu + shrink * (rate - mu), shrink, r_full


def nationality(pack_dir):
    """Most-represented national side per player, from T20I squads."""
    mp = pd.read_csv(os.path.join(pack_dir, "competition_team_player_mapping.csv"))
    cp = pd.read_csv(os.path.join(pack_dir, "competitions.csv"))
    t20i = set(cp[cp["match_format"] == "T20I"]["comp_id"])
    return (mp[mp["comp_id"].isin(t20i)]
            .groupby("player_id")["team_name"].agg(lambda s: s.mode().iat[0]))


def main(balls_csv, state_csv, out_dir, pack_dir="Data Pack"):
    df = pd.read_csv(balls_csv, low_memory=False)
    print(f"loaded {len(df):,} deliveries")
    assert df["ball_uid"].is_unique
    if "resources" not in df.columns:
        df["resources"] = df["balls_rem"] * df["wkts_in_hand"]

    charged = df["extras_type"].isin(BOWLER_CHARGED)
    df["bowler_runs"] = df["bat_runs"] + np.where(charged, df["extras"], 0)
    df["runs_rest"] = (df["innings_final_score"] - df["score_before"]).clip(lower=0)
    X, g = df[BALL_FEATURES], df["match_id"]

    print("\n=== expectation models (cross-fitted by match) ===")
    df["exp_bat_runs"] = np.clip(xfit(reg, X, df["bat_runs"], g), 0, None)
    df["exp_bowler_runs"] = np.clip(xfit(reg, X, df["bowler_runs"], g), 0, None)
    df["p_bowl_wkt"] = xfit(clf, X, df["bowler_wicket"], g, proba=True)
    for lbl, a, b in (("E[bat_runs]", "exp_bat_runs", "bat_runs"),
                      ("E[bowler_runs]", "exp_bowler_runs", "bowler_runs"),
                      ("P(bowler wkt)", "p_bowl_wkt", "bowler_wicket")):
        print(f"  {lbl:<16} {df[a].mean():.4f} vs actual {df[b].mean():.4f}")

    print("\n=== wicket cost model (state-dependent) ===")
    wf = ["innings", "balls_rem", "wkts_in_hand", "score_before", "runs_required", "is_ipl"]
    wm = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06,
                                       min_samples_leaf=200, early_stopping=False,
                                       monotonic_cst=[0, 1, 1, 0, 0, 0],
                                       random_state=SEED).fit(df[wf], df["runs_rest"])
    lose = df[wf].copy()
    lose["wkts_in_hand"] = (lose["wkts_in_hand"] - 1).clip(lower=0)
    df["wicket_cost"] = np.clip(wm.predict(df[wf]) - wm.predict(lose), 0.5, None)
    print("  mean cost by phase (early wickets cost most - many balls left to lose):")
    print(df.groupby("phase")["wicket_cost"].mean().to_string())

    # ---- the two value components, kept SEPARATE so each can be shrunk on its own evidence
    df["bat_runs_comp"] = df["bat_runs"] - df["exp_bat_runs"]
    df["bat_wkt_comp"] = -df["wicket_cost"] * (df["is_wicket"] - df["p_wicket"])
    df["bowl_runs_comp"] = -(df["bowler_runs"] - df["exp_bowler_runs"])
    df["bowl_wkt_comp"] = df["wicket_cost"] * (df["bowler_wicket"] - df["p_bowl_wkt"])

    df = df.sort_values(["match_id", "innings", "balls_rem"], ascending=[True, True, False])
    df["wpa"] = (df.groupby(["match_id", "innings"])["wp"].shift(-1) - df["wp"]).fillna(0.0)

    team_wins = df.groupby("batting_team_id")["wp"].mean()
    zt = (team_wins - team_wins.mean()) / max(float(team_wins.std()), 1e-9)
    tstr = pd.Series(0.5 + 0.5 * st.norm.cdf(zt.values), index=team_wins.index).clip(0.4, 1.0)
    df["rec_w"] = 0.5 ** ((2026 - df["season_yr"]) / HALF_LIFE)
    df["comp_w"] = np.where(df["is_ipl"] == 1, IPL_W, T20I_W)
    df["w_bat"] = df["rec_w"] * df["comp_w"] * df["bowling_team_id"].map(tstr).fillna(0.75)
    df["w_bowl"] = df["rec_w"] * df["comp_w"] * df["batting_team_id"].map(tstr).fillna(0.75)

    legal = df["is_legal"] == 1
    nat = nationality(pack_dir)
    out, diag = {}, {}

    for side in ("bat", "bowl"):
        idc = "striker_id" if side == "bat" else "bowler_id"
        nmc = "striker_name" if side == "bat" else "bowler_name"
        flag, wcol = f"press_{side}", f"w_{side}"
        rc, kc = f"{side}_runs_comp", f"{side}_wkt_comp"
        sgn = 1.0 if side == "bat" else -1.0
        W_ABS, W_RES = WEIGHTS[side]
        print(f"\n{'='*66}\n{side.upper()}   (rating mix: {W_ABS:.0%} absolute / "
              f"{W_RES:.0%} resilience)\n{'='*66}")

        d = df[legal].copy()
        d["_w"] = d[wcol]
        d["_runs"] = d[wcol] * d[rc]
        d["_wkt"] = d[wcol] * d[kc]
        d["_tot"] = d["_runs"] + d["_wkt"]
        d["_wpa"] = d[wcol] * sgn * d["wpa"]

        cell = (d.groupby([idc, "match_id", flag], as_index=False)
                 .agg(w=("_w", "sum"), runs=("_runs", "sum"), wkt=("_wkt", "sum"),
                      tot=("_tot", "sum"), wpa=("_wpa", "sum"), balls=("_w", "size")))

        piv = cell.pivot_table(index=idc, columns=flag,
                               values=["w", "runs", "wkt", "tot", "wpa", "balls"],
                               aggfunc="sum", fill_value=0.0)
        for c in ["w", "runs", "wkt", "tot", "wpa", "balls"]:
            for b in (0, 1):
                if (c, b) not in piv.columns:
                    piv[(c, b)] = 0.0

        tab = pd.DataFrame({
            "name": d.groupby(idc)[nmc].agg(lambda s: s.mode().iat[0]),
            "matches": d.groupby(idc)["match_id"].nunique(),
            "press_balls": piv[("balls", 1)], "base_balls": piv[("balls", 0)],
            "press_w": piv[("w", 1)], "base_w": piv[("w", 0)],
        })
        for nm, b in (("press", 1), ("base", 0)):
            for c in ("runs", "wkt", "tot", "wpa"):
                tab[f"{nm}_{c}"] = piv[(c, b)] / piv[("w", b)].replace(0, np.nan)
        tab["active"] = (d.groupby(idc)["season_yr"].agg(set)
                          .apply(lambda s: bool(s & RECENT_SEASONS)))
        tab["nation"] = pd.Series(tab.index, index=tab.index).map(nat).fillna("unknown")
        tab["ipl_press_balls"] = (d[d[flag] == 1].groupby(idc)["is_ipl"].sum()
                                  .reindex(tab.index).fillna(0))
        tab["auction_eligible"] = ~tab["nation"].isin(INELIGIBLE_NATIONS)

        base_elig = ((tab["press_balls"] >= MIN_PRESS_BALLS)
                     & (tab["base_balls"] >= MIN_BASE_BALLS)
                     & (tab["matches"] >= MIN_MATCHES) & tab["active"])
        blocked = tab[base_elig & ~tab["auction_eligible"]]
        thin = tab[base_elig & tab["auction_eligible"]
                   & (tab["ipl_press_balls"] < MIN_IPL_PRESS_BALLS)]
        if len(blocked):
            print(f"  excluded, cannot be signed at an IPL auction: "
                  f"{', '.join(blocked['name'].tolist())}")
        if len(thin):
            print(f"  excluded, under {MIN_IPL_PRESS_BALLS} IPL pressure balls: "
                  + ", ".join(f"{r['name']} ({int(r.ipl_press_balls)})"
                              for _, r in thin.sort_values('ipl_press_balls',
                                                           ascending=False).head(8).iterrows())
                  + (f" and {len(thin)-8} more" if len(thin) > 8 else ""))

        elig = (base_elig & tab["auction_eligible"]
                & (tab["ipl_press_balls"] >= MIN_IPL_PRESS_BALLS))
        e = tab[elig].copy()
        print(f"  candidates {len(tab)} -> eligible {len(e)} "
              f"(>={MIN_PRESS_BALLS} pressure balls, >={MIN_MATCHES} matches, active 2025/26)")
        if len(e) < 25:
            raise SystemExit(f"only {len(e)} eligible - loosen thresholds")

        # ---- measure reliability of each component, then shrink by it ----
        print(f"\n  measured split-half reliability ({N_REL_REP} random match splits):")
        rel = {}
        for comp, col in (("runs", "runs"), ("wkt", "wkt"), ("combined", "tot")):
            r = split_half_rho(cell, idc, flag, col, "w", e.index)
            rel[comp] = r
            print(f"    {comp:<9} r_half={r:+.3f}   -> r_full="
                  f"{np.clip(2*r/(1+r),0,.99) if np.isfinite(r) else 0:.3f}")

        sh_runs, k_runs, rf_runs = calibrated_shrink(
            e["press_runs"].values, e["press_w"].values, rel["runs"])
        sh_wkt, k_wkt, rf_wkt = calibrated_shrink(
            e["press_wkt"].values, e["press_w"].values, rel["wkt"])
        e["press_runs_sh"], e["press_wkt_sh"] = sh_runs, sh_wkt
        e["press_value"] = sh_runs + sh_wkt
        print(f"    shrink weights: runs mean={k_runs.mean():.3f}  "
              f"wkt mean={k_wkt.mean():.3f}  (the noisy term self-collapses)")

        rel_b = {c: split_half_rho(
                    cell[cell[flag] == 0].assign(**{flag: 1}), idc, flag, c, "w", e.index)
                 for c in ("runs", "wkt")}
        bs_runs, _, _ = calibrated_shrink(e["base_runs"].values, e["base_w"].values, rel_b["runs"])
        bs_wkt, _, _ = calibrated_shrink(e["base_wkt"].values, e["base_w"].values, rel_b["wkt"])
        e["base_value"] = bs_runs + bs_wkt
        e["resilience"] = e["press_value"] - e["base_value"]

        z = lambda v: (v - np.mean(v)) / max(np.std(v), 1e-12)
        e["z_abs"], e["z_res"] = z(e["press_value"].values), z(e["resilience"].values)
        e["rating"] = W_ABS * e["z_abs"] + W_RES * e["z_res"]

        # ---- cluster bootstrap by match ----
        mids = cell["match_id"].unique()
        rm = cell["match_id"].map({m: i for i, m in enumerate(mids)}).values
        pidx = {p: i for i, p in enumerate(e.index)}
        kp = np.array([p in pidx for p in cell[idc].values])
        rp = np.array([pidx[p] for p in cell[idc].values[kp]])
        rmk, rf = rm[kp], cell[flag].values[kp]
        rw = cell["w"].values[kp]
        rr, rk = cell["runs"].values[kp], cell["wkt"].values[kp]
        nP = len(e)
        boot = np.zeros((N_BOOT, nP))
        for b in range(N_BOOT):
            mult = RNG.multinomial(len(mids), np.full(len(mids), 1.0 / len(mids)))[rmk]
            acc = {}
            for bucket in (0, 1):
                m_ = rf == bucket
                w_ = np.bincount(rp[m_], weights=(mult * rw)[m_], minlength=nP)
                r_ = np.bincount(rp[m_], weights=(mult * rr)[m_], minlength=nP)
                k_ = np.bincount(rp[m_], weights=(mult * rk)[m_], minlength=nP)
                sw = np.maximum(w_, 1e-9)
                acc[bucket] = (np.divide(r_, sw), np.divide(k_, sw), w_)
            pr, pk, pw = acc[1]
            br, bk, bw = acc[0]
            pv = (calibrated_shrink(pr, np.maximum(pw, 1e-9), rel["runs"])[0]
                  + calibrated_shrink(pk, np.maximum(pw, 1e-9), rel["wkt"])[0])
            bv = (calibrated_shrink(br, np.maximum(bw, 1e-9), rel_b["runs"])[0]
                  + calibrated_shrink(bk, np.maximum(bw, 1e-9), rel_b["wkt"])[0])
            boot[b] = W_ABS * z(pv) + W_RES * z(pv - bv)
        e["rating_lo"] = np.percentile(boot, 5, axis=0)
        e["rating_hi"] = np.percentile(boot, 95, axis=0)
        ranks = (-boot).argsort(axis=1).argsort(axis=1) + 1
        e["rank_med"] = np.median(ranks, axis=0)
        e["p_top10"] = (ranks <= 10).mean(axis=0)

        # ---- reliability of the FINAL composite and of the resilience term ----
        fin_r, res_r, abs_r = [], [], []
        for _ in range(60):
            hh = RNG.integers(0, 2, len(mids))[rmk]
            got = []
            for hside in (0, 1):
                sel = hh == hside
                a = {}
                for bucket in (0, 1):
                    m_ = sel & (rf == bucket)
                    w_ = np.bincount(rp[m_], weights=rw[m_], minlength=nP)
                    r_ = np.bincount(rp[m_], weights=rr[m_], minlength=nP)
                    k_ = np.bincount(rp[m_], weights=rk[m_], minlength=nP)
                    a[bucket] = (r_, k_, w_)
                pr_, pk_, pw_ = a[1]
                br_, bk_, bw_ = a[0]
                ok = (pw_ > 0) & (bw_ > 0)
                sp = np.maximum(pw_, 1e-9); sb = np.maximum(bw_, 1e-9)
                pv = (calibrated_shrink(pr_ / sp, sp, rel["runs"])[0]
                      + calibrated_shrink(pk_ / sp, sp, rel["wkt"])[0])
                bv = (calibrated_shrink(br_ / sb, sb, rel_b["runs"])[0]
                      + calibrated_shrink(bk_ / sb, sb, rel_b["wkt"])[0])
                got.append((W_ABS * z(pv) + W_RES * z(pv - bv), pv - bv, pv, ok))
            m_ok = got[0][3] & got[1][3]
            if m_ok.sum() > 20:
                fin_r.append(st.spearmanr(got[0][0][m_ok], got[1][0][m_ok]).statistic)
                res_r.append(st.spearmanr(got[0][1][m_ok], got[1][1][m_ok]).statistic)
                abs_r.append(st.spearmanr(got[0][2][m_ok], got[1][2][m_ok]).statistic)
        sb_ = lambda r: np.clip(2 * r / (1 + r), 0, 0.99)
        r_fin, r_res, r_abs = np.mean(fin_r), np.mean(res_r), np.mean(abs_r)
        print(f"\n  RELIABILITY OF THE RANKING ITSELF (60 match-level split-halves):")
        print(f"    absolute pressure value  r_half={r_abs:+.3f}  r_full={sb_(r_abs):.3f}")
        print(f"    resilience delta         r_half={r_res:+.3f}  r_full={sb_(r_res):.3f}")
        print(f"    final composite rating   r_half={r_fin:+.3f}  r_full={sb_(r_fin):.3f}")
        rel.update({"final_rating": float(r_fin), "resilience": float(r_res),
                    "absolute": float(r_abs),
                    "final_rating_full": float(sb_(r_fin)),
                    "resilience_full": float(sb_(r_res)),
                    "absolute_full": float(sb_(r_abs))})

        wpa_rho = st.spearmanr(e["rating"], e["press_wpa"]).statistic
        print(f"\n  independent-currency cross-check: corr(rating, pressure WPA/ball) "
              f"= {wpa_rho:+.3f}")
        print(f"  bootstrap: {N_BOOT} match-level resamples")

        e = e.sort_values("rating", ascending=False)
        e["rank"] = range(1, len(e) + 1)
        e.to_csv(os.path.join(out_dir, f"ratings_{side}.csv"))
        out[side] = e
        diag[side] = {"eligible": int(len(e)), "w_abs": W_ABS, "w_res": W_RES,
                      "reliability": rel,
                      "reliability_base": rel_b,
                      "r_full_runs": float(rf_runs), "r_full_wkt": float(rf_wkt),
                      "shrink_runs": float(k_runs.mean()), "shrink_wkt": float(k_wkt.mean()),
                      "wpa_spearman": float(wpa_rho)}

        print(f"\n  --- TOP 12 {side.upper()} UNDER PRESSURE ---")
        print(e.head(12)[["rank", "name", "rating", "rating_lo", "rating_hi",
                          "press_value", "base_value", "resilience",
                          "press_balls", "matches", "p_top10"]]
              .to_string(index=False, float_format=lambda v: f"{v:7.3f}"))

    json.dump(diag, open(os.path.join(out_dir, "rating_diagnostics.json"), "w"),
              indent=2, default=float)
    print("\nwrote ratings_bat.csv / ratings_bowl.csv")


if __name__ == "__main__":
    main(*sys.argv[1:5])
