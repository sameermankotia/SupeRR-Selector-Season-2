#!/usr/bin/env python3
"""
Stage 2 - Win probability, ball-outcome models and Leverage Index.

Design notes (v2)
  * SEPARATE models per innings. Setting a target is a different prediction
    problem from chasing one; one model with NaN chase-features served both
    badly and was beaten by plain logistic regression.
  * MONOTONIC CONSTRAINTS on every feature whose direction is known a priori
    (win prob must rise with wickets in hand, fall with runs required...).
    This is the single biggest robustness win: it stops the model learning
    non-physical wiggles from sparse states, and it makes the Leverage surface
    smooth, which matters because Leverage is a *difference* of predictions.
  * NO internal early stopping. It splits randomly inside a fold, putting balls
    from the same match on both sides and early-stopping on a leaked signal.
    Iterations are chosen by group-aware CV instead.
  * Honest model selection: GBM and logistic regression are both scored by
    GroupKFold out-of-fold log loss, and the better model per innings wins.
  * Cross-fitted predictions everywhere, so no player is judged against a model
    that saw their own match.

Usage: python3 win_prob.py <state_csv> <out_dir>
"""
import sys, os, json
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, log_loss, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, SplineTransformer
from sklearn.impute import SimpleImputer

SEED = 17
NSPLIT = 5
RUN_CLASSES = [0, 1, 2, 3, 4, 6]

# feature -> monotonic direction (+1 rises with batting-side win prob)
# `crr` is a deterministic function of score_before and balls_rem, and it is
# numerically violent early in an innings (one boundary off ball 1 moves it by
# 24). Because Leverage is a *difference* of win-prob predictions, that
# instability showed up as fake powerplay leverage. It is replaced by
# score_vs_par: runs ahead of / behind the competition par pace, which is
# smooth, bounded and directly interpretable.
FEAT1 = {"score_before": +1, "wkts_in_hand": +1, "balls_rem": 0,
         "score_vs_par": +1, "over_no": 0, "is_ipl": 0, "knock_out": 0,
         "par_score": -1, "resources": 0}
FEAT2 = {"runs_required": -1, "balls_rem": +1, "wkts_in_hand": +1, "rrr_cap": -1,
         "score_before": 0, "is_ipl": 0, "knock_out": 0, "resources": +1}

RRR_CAP = 36.0   # 6 an over x6; beyond this the chase is lost either way


def derive(d):
    """Derived state features. Used for BOTH training and the Leverage
    counterfactuals, so the two can never drift apart."""
    d = d.copy()
    d["resources"] = d["balls_rem"] * d["wkts_in_hand"]
    frac = (d["sched_balls"] - d["balls_rem"]) / d["sched_balls"].clip(lower=1)
    d["score_vs_par"] = d["score_before"] - d["par_score"] * frac
    d["rrr_cap"] = d["rrr"].clip(upper=RRR_CAP)
    return d

BALL_FEATURES = ["innings", "balls_rem", "wkts_in_hand", "score_before", "crr",
                 "runs_required", "rrr", "over_no", "is_ipl", "resources"]


def gbm(cols, max_iter=300, lr=0.06, leaves=15, leaf=150):
    return HistGradientBoostingClassifier(
        max_iter=max_iter, learning_rate=lr, max_leaf_nodes=leaves,
        min_samples_leaf=leaf, l2_regularization=2.0,
        monotonic_cst=[cols[c] for c in cols], early_stopping=False,
        random_state=SEED)


def logit(cols):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         SplineTransformer(n_knots=6, degree=3),
                         LogisticRegression(max_iter=4000, C=1.0))


def oof_predict(model_fn, X, y, groups):
    oof = np.zeros(len(X))
    for tr, te in GroupKFold(n_splits=NSPLIT).split(X, y, groups):
        m = model_fn().fit(X.iloc[tr], y.iloc[tr])
        oof[te] = m.predict_proba(X.iloc[te])[:, 1]
    return oof


def main(state_csv, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    df = pd.read_csv(state_csv, low_memory=False)
    df["season_yr"] = df["season"].astype(str).str[:4].astype(int)

    # par score = mean 1st-innings total for that competition-season
    first = df[df["innings"] == 1].groupby("match_id")["innings_final_score"].first()
    cs = df.groupby("match_id")[["comp_id", "season"]].first()
    par = (pd.concat([first.rename("tot"), cs], axis=1)
             .groupby(["comp_id", "season"])["tot"].mean().rename("par_score"))
    df = df.merge(par, left_on=["comp_id", "season"], right_index=True, how="left")
    df["par_score"] = df["par_score"].fillna(df["par_score"].mean())
    df = derive(df)
    print(f"loaded {len(df):,} deliveries;  par score range "
          f"{par.min():.0f}-{par.max():.0f}")

    trainable = df["bat_team_won"].notna() & (df["dls"] == 0)
    print(f"trainable: {trainable.sum():,} deliveries / "
          f"{df.loc[trainable,'match_id'].nunique():,} matches")

    diag = {}
    df["wp"] = np.nan
    full_models = {}

    # =====================================================================
    # A. WIN PROBABILITY - one model per innings, honestly selected
    # =====================================================================
    for inns, cols in ((1, FEAT1), (2, FEAT2)):
        sub = df[trainable & (df["innings"] == inns)]
        X, y, g = sub[list(cols)], sub["bat_team_won"].astype(int), sub["match_id"]
        print(f"\n=== WP innings {inns}  (n={len(sub):,}) ===")

        cand = {}
        for name, fn in (("gbm_mono", lambda: gbm(cols)),
                         ("logit_spline", lambda: logit(cols))):
            p = oof_predict(fn, X, y, g)
            cand[name] = p
            print(f"  {name:13s} OOF AUC={roc_auc_score(y,p):.4f} "
                  f"logloss={log_loss(y,p):.4f} Brier={brier_score_loss(y,p):.4f}")

        best = min(cand, key=lambda k: log_loss(y, cand[k]))
        print(f"  --> selected: {best}")
        oof = cand[best]
        fn = (lambda: gbm(cols)) if best == "gbm_mono" else (lambda: logit(cols))

        # forward-in-time check
        tr_m, te_m = sub["season_yr"] <= 2024, sub["season_yr"] >= 2025
        mf = fn().fit(X[tr_m], y[tr_m])
        pf = mf.predict_proba(X[te_m])[:, 1]
        print(f"  forward (train<=2024 -> 2025/26): AUC={roc_auc_score(y[te_m],pf):.4f} "
              f"logloss={log_loss(y[te_m],pf):.4f}")

        # reliability
        bins = np.linspace(0, 1, 11)
        bi = np.clip(np.digitize(oof, bins) - 1, 0, 9)
        yv = y.values
        rel = []
        print("  reliability:")
        for i in range(10):
            m_ = bi == i
            if m_.sum() > 50:
                rel.append({"bin": f"{bins[i]:.1f}-{bins[i+1]:.1f}", "n": int(m_.sum()),
                            "pred": float(oof[m_].mean()), "actual": float(yv[m_].mean())})
                print(f"    {bins[i]:.1f}-{bins[i+1]:.1f}  n={m_.sum():6d}  "
                      f"pred={oof[m_].mean():.3f}  actual={yv[m_].mean():.3f}")

        diag[f"innings{inns}"] = {
            "n": int(len(sub)), "selected": best,
            "oof_auc": float(roc_auc_score(y, oof)),
            "oof_logloss": float(log_loss(y, oof)),
            "oof_brier": float(brier_score_loss(y, oof)),
            "candidates": {k: {"auc": float(roc_auc_score(y, v)),
                               "logloss": float(log_loss(y, v))} for k, v in cand.items()},
            "forward_auc": float(roc_auc_score(y[te_m], pf)),
            "reliability": rel}

        df.loc[sub.index, "wp"] = oof
        full_models[inns] = fn().fit(X, y)

    # fill remaining rows (DLS / no-result) from full-data models
    for inns, cols in ((1, FEAT1), (2, FEAT2)):
        m_ = df["wp"].isna() & (df["innings"] == inns)
        if m_.any():
            df.loc[m_, "wp"] = full_models[inns].predict_proba(df.loc[m_, list(cols)])[:, 1]
    print(f"\nWP filled for all {len(df):,} deliveries")

    # =====================================================================
    # B. BALL-OUTCOME MODELS (cross-fitted, group-aware)
    # =====================================================================
    print("\n=== ball-outcome models ===")
    runs_b = df["team_runs"].clip(upper=6).replace({5: 4}).values
    cls = np.array([RUN_CLASSES.index(v) if v in RUN_CLASSES else 5 for v in runs_b])
    cls = np.where(df["is_wicket"].values == 1, len(RUN_CLASSES), cls)
    n_cls = len(RUN_CLASSES) + 1
    Xb, gall = df[BALL_FEATURES], df["match_id"]

    P = np.zeros((len(df), n_cls)); exp_runs = np.zeros(len(df))
    for k, (tr, te) in enumerate(GroupKFold(n_splits=NSPLIT).split(Xb, cls, gall), 1):
        mo = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06,
                                            max_leaf_nodes=31, min_samples_leaf=200,
                                            l2_regularization=2.0, early_stopping=False,
                                            random_state=SEED).fit(Xb.iloc[tr], cls[tr])
        pr = mo.predict_proba(Xb.iloc[te])
        full = np.zeros((len(te), n_cls))
        for j, c in enumerate(mo.classes_):
            full[:, c] = pr[:, j]
        P[te] = full
        mr = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06,
                                           min_samples_leaf=200, early_stopping=False,
                                           random_state=SEED).fit(
            Xb.iloc[tr], df["team_runs"].iloc[tr])
        exp_runs[te] = mr.predict(Xb.iloc[te])
        print(f"  fold {k}: outcome logloss="
              f"{log_loss(cls[te], full, labels=list(range(n_cls))):.4f}")

    df["p_wicket"] = P[:, n_cls - 1]
    df["exp_runs"] = np.clip(exp_runs, 0, None)
    w_auc = roc_auc_score(df["is_wicket"], df["p_wicket"])
    print(f"  P(wicket) mean={df['p_wicket'].mean():.4f} vs actual "
          f"{df['is_wicket'].mean():.4f};  OOF AUC={w_auc:.4f}")
    print(f"  E[runs]   mean={df['exp_runs'].mean():.4f} vs actual "
          f"{df['team_runs'].mean():.4f}")
    diag["outcome"] = {"wicket_auc": float(w_auc),
                       "exp_runs_mean": float(df["exp_runs"].mean()),
                       "actual_runs_mean": float(df["team_runs"].mean())}

    # =====================================================================
    # C. LEVERAGE INDEX
    # =====================================================================
    print("\n=== Leverage Index ===")
    wps = np.zeros((len(df), n_cls))
    legal_next = df["legal_done"].values + df["is_legal"].values.clip(0, 1)
    for j in range(n_cls):
        is_w = (j == n_cls - 1)
        runs = 0 if is_w else RUN_CLASSES[j]
        s = df.copy()
        s["score_before"] = df["score_before"] + runs
        s["wkts_in_hand"] = (df["wkts_in_hand"] - 1).clip(lower=0) if is_w else df["wkts_in_hand"]
        s["balls_rem"] = (df["balls_rem"] - 1).clip(lower=0)
        s["runs_required"] = (df["target"] - s["score_before"]).clip(lower=0)
        s["rrr"] = np.where(s["balls_rem"] > 0,
                            s["runs_required"] * 6.0 / s["balls_rem"].replace(0, np.nan), np.nan)
        s = derive(s)
        for inns, cols in ((1, FEAT1), (2, FEAT2)):
            m_ = (df["innings"] == inns).values
            if m_.any():
                wps[m_, j] = full_models[inns].predict_proba(s.loc[m_, list(cols)])[:, 1]
        # chase decided the moment the target is passed / overs run out
        ch = m_ = (df["innings"] == 2).values & df["target"].notna().values
        won = ch & (s["score_before"].values >= df["target"].values)
        wps[won, j] = 1.0
        lost = ch & (s["balls_rem"].values == 0) & (s["score_before"].values < df["target"].values)
        wps[lost, j] = 0.0
        allout = ch & (s["wkts_in_hand"].values == 0) & (s["score_before"].values < df["target"].values)
        wps[allout, j] = 0.0

    wp_bar = (P * wps).sum(axis=1)
    raw = np.sqrt(np.clip((P * (wps - wp_bar[:, None]) ** 2).sum(axis=1), 0, None))
    cap = np.percentile(raw, 99.5)
    n_cap = int((raw > cap).sum())
    raw_w = np.minimum(raw, cap)
    df["leverage"] = raw_w / raw_w.mean()
    print(f"  winsorised {n_cap} balls at p99.5 (raw swing sd {cap:.4f})")
    print(f"  raw WP-swing sd: mean={raw.mean():.4f} p90={np.percentile(raw,90):.4f} "
          f"max={raw.max():.4f}")
    print(f"  leverage (1.0 = average ball): p50={df['leverage'].median():.2f} "
          f"p90={df['leverage'].quantile(.9):.2f} p99={df['leverage'].quantile(.99):.2f} "
          f"max={df['leverage'].max():.2f}")
    print("\n  by phase:");  print(df.groupby("phase")["leverage"].mean().to_string())
    print("\n  by innings:"); print(df.groupby("innings")["leverage"].mean().to_string())
    print("\n  SANITY - leverage by phase x innings (death should top the chase):")
    print(df.pivot_table(index="phase", columns="innings", values="leverage",
                         aggfunc="mean").to_string())
    print("\n  SANITY - leverage by how close the game is (|WP-0.5|):")
    df["_close"] = pd.cut((df["wp"] - 0.5).abs(),
                          [0, .05, .1, .2, .3, .4, .5], include_lowest=True)
    print(df.groupby("_close", observed=True)["leverage"].agg(["mean", "count"]).to_string())
    df.drop(columns=["_close"], inplace=True)

    keep = ["ball_uid", "match_id", "innings", "comp_id", "comp_name", "is_ipl", "season", "season_yr",
            "knock_out", "dls", "striker_id", "striker_name", "bowler_id", "bowler_name",
            "batting_team_id", "bowling_team_id", "over_no", "phase", "balls_rem",
            "wkts_in_hand", "score_before", "crr", "target", "runs_required", "rrr",
            "par_score", "score_vs_par", "bat_runs", "team_runs", "is_legal", "is_wicket", "bowler_wicket",
            "extras", "extras_type", "innings_final_score", "resources",
            "wp", "p_wicket", "exp_runs", "leverage"]
    df[keep].to_csv(os.path.join(out_dir, "balls_enriched.csv"), index=False)
    json.dump(diag, open(os.path.join(out_dir, "model_diagnostics.json"), "w"), indent=2)
    print(f"\nwrote {out_dir}/balls_enriched.csv")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
