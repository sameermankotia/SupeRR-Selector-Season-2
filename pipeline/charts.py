#!/usr/bin/env python3
"""
Stage 5a - Figures for the methodology report.

Colour tokens are the validated reference palette (dataviz skill):
categorical blue/orange/aqua, sequential blue ramp, diverging blue<->red with a
neutral gray midpoint. No dual-axis charts anywhere - where two measures of
different scale belong together they become small multiples.

Usage: python3 charts.py <out_dir> <fig_dir>
"""
import sys, os, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

SURFACE   = "#fcfcfb"
INK       = "#0b0b0b"
INK2      = "#52514e"
MUTED     = "#898781"
AXIS      = "#c3c2b7"
BLUE      = "#2a78d6"
ORANGE    = "#eb6834"
AQUA      = "#1baf7a"
RED       = "#e34948"
NEUTRAL   = "#f0efec"
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
       "#3987e5", "#2a78d6", "#256abf", "#184f95"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": AXIS,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": NEUTRAL, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "font.size": 9,
    "axes.titlesize": 10.5, "axes.titleweight": "600", "axes.titlelocation": "left",
    "axes.titlepad": 9, "figure.dpi": 160, "legend.frameon": False,
})


def style(ax, title=None, xlabel=None, ylabel=None, xgrid=False):
    if title:  ax.set_title(title, color=INK)
    if xlabel: ax.set_xlabel(xlabel)
    if ylabel: ax.set_ylabel(ylabel)
    ax.grid(axis="x" if xgrid else "y")
    ax.grid(axis="y" if xgrid else "x", visible=False)
    ax.tick_params(length=0)
    return ax


def save(fig, path):
    fig.tight_layout(pad=1.1)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print("  wrote", os.path.basename(path))


# ---------------------------------------------------------------- 1. validation
def fig_validation(out, figs):
    d = json.load(open(os.path.join(out, "pressure_diagnostics.json")))
    vb = pd.DataFrame(d["validation_bat"]).T.reset_index(drop=True)
    vw = pd.DataFrame(d["validation_bowl"]).T.reset_index(drop=True)
    fig, axes = plt.subplots(2, 2, figsize=(9.8, 6.8))
    panels = [
        (axes[0, 0], vb, "runs_per_wkt",  "Batting: runs per wicket",
         "Broadly flat, then a 39% collapse in the top decile"),
        (axes[0, 1], vb, "wkt_pct",       "Batting: dismissal rate (%)",
         "Wickets fall 77% more often in the top decile"),
        (axes[1, 0], vw, "runs_per_ball", "Bowling: runs conceded per ball",
         "Steady, monotone rise: +20% from decile 1 to 10"),
        (axes[1, 1], vw, "balls_per_wkt", "Bowling: balls per wicket",
         "Wickets come faster too - the death cuts both ways"),
    ]
    for ax, dd, col, title, sub in panels:
        x = np.arange(1, len(dd) + 1)
        # exactly one ramp step per decile: light (low pressure) -> dark (high)
        ax.bar(x, dd[col], color=SEQ[:len(dd)], width=0.72, zorder=3,
               edgecolor=SURFACE, linewidth=1.2)
        ax.set_title(title, color=INK, pad=24)
        ax.text(0, 1.035, sub, transform=ax.transAxes, fontsize=8.2, color=MUTED)
        ax.set_xlabel("Pressure decile  (10 = most pressure)")
        ax.grid(axis="y"); ax.grid(axis="x", visible=False)
        ax.tick_params(length=0)
        ax.set_xticks(x)
        ax.margins(y=0.17)
        for xi, v in zip([x[0], x[-1]], [dd[col].iloc[0], dd[col].iloc[-1]]):
            ax.annotate(f"{v:.1f}", (xi, v), textcoords="offset points",
                        xytext=(0, 4), ha="center", fontsize=8.4, color=INK,
                        fontweight="700")
    fig.suptitle("Does the Pressure Index isolate genuinely harder cricket?",
                 x=0.005, ha="left", fontsize=13, fontweight="700", color=INK)
    fig.tight_layout(pad=1.2, rect=(0, 0, 1, 0.955))
    fig.savefig(os.path.join(figs, "fig1_validation.png"), bbox_inches="tight")
    plt.close(fig)
    print("  wrote fig1_validation.png")


# ---------------------------------------------------------------- 2. calibration
def fig_calibration(out, figs):
    d = json.load(open(os.path.join(out, "model_diagnostics.json")))
    fig, ax = plt.subplots(figsize=(5.4, 4.3))
    ax.plot([0, 1], [0, 1], color=AXIS, lw=1.4, ls=(0, (4, 3)), zorder=2,
            label="perfect calibration")
    for key, colr, lbl in (("innings1", ORANGE, "1st innings (setting)"),
                           ("innings2", BLUE, "2nd innings (chasing)")):
            if key not in d: continue
            r = pd.DataFrame(d[key]["reliability"])
            ax.plot(r["pred"], r["actual"], color=colr, lw=2, marker="o",
                    ms=5.5, mec=SURFACE, mew=1.4, zorder=4,
                    label=f"{lbl}  AUC {d[key]['oof_auc']:.3f}")
    style(ax, "Win-probability model is well calibrated",
          "Predicted win probability", "Observed win rate")
    ax.grid(True); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.legend(loc="upper left", fontsize=8.2)
    ax.text(0, -0.17, "Out-of-fold predictions, GroupKFold by match.",
            transform=ax.transAxes, fontsize=7.8, color=MUTED)
    save(fig, os.path.join(figs, "fig2_calibration.png"))


# ---------------------------------------------------------------- 3. leverage
def fig_leverage(out, figs):
    df = pd.read_csv(os.path.join(out, "balls_pressure.csv"),
                     usecols=["phase", "innings", "leverage"], low_memory=False)
    p = df.pivot_table(index="phase", columns="innings", values="leverage",
                       aggfunc="mean").reindex(["powerplay", "middle", "death"])
    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    x = np.arange(len(p)); w = 0.36
    ax.bar(x - w/2, p[1], w, label="1st innings (setting)", color=ORANGE,
           zorder=3, edgecolor=SURFACE, linewidth=1.2)
    ax.bar(x + w/2, p[2], w, label="2nd innings (chasing)", color=BLUE,
           zorder=3, edgecolor=SURFACE, linewidth=1.2)
    ax.axhline(1.0, color=MUTED, lw=1, ls=(0, (3, 3)), zorder=2)
    ax.annotate("league-average ball", (len(p) - 0.45, 1.0),
                textcoords="offset points", xytext=(0, 5), fontsize=7.6,
                color=MUTED, ha="right")
    style(ax, "Leverage: how much one ball can swing the match",
          None, "Mean Leverage Index")
    ax.set_xticks(x); ax.set_xticklabels([s.title() for s in p.index])
    ax.legend(fontsize=8.2, ncols=2)
    for xi, v in zip(x - w/2, p[1]):
        ax.annotate(f"{v:.2f}", (xi, v), textcoords="offset points",
                    xytext=(0, 3), ha="center", fontsize=7.6, color=INK2)
    for xi, v in zip(x + w/2, p[2]):
        ax.annotate(f"{v:.2f}", (xi, v), textcoords="offset points",
                    xytext=(0, 3), ha="center", fontsize=7.6, color=INK2)
    save(fig, os.path.join(figs, "fig3_leverage.png"))


# ---------------------------------------------------------------- 4. quadrant
def declutter(fig, ax, texts, step=1.3, iters=260):
    """Nudge overlapping labels apart vertically until none collide."""
    for _ in range(iters):
        fig.canvas.draw()
        r = fig.canvas.get_renderer()
        bbs = [t.get_window_extent(r) for t in texts]
        moved = False
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                if bbs[i].overlaps(bbs[j]):
                    moved = True
                    lo, hi = (i, j) if bbs[i].y0 < bbs[j].y0 else (j, i)
                    dx, dy = texts[lo].xyann; texts[lo].xyann = (dx, dy - step)
                    dx, dy = texts[hi].xyann; texts[hi].xyann = (dx, dy + step)
        if not moved:
            break


def fig_quadrant(out, figs, side, label):
    e = pd.read_csv(os.path.join(out, f"ratings_{side}.csv"))
    fig, ax = plt.subplots(figsize=(7.6, 5.8))
    mx, my = e["resilience"].mean(), e["press_value"].mean()
    rest, top = e.iloc[10:], e.iloc[:10]
    ax.scatter(rest["resilience"], rest["press_value"], s=26, color=MUTED,
               alpha=0.42, zorder=3, linewidths=0, label="other eligible players")
    ax.scatter(top["resilience"], top["press_value"], s=88, color=BLUE,
               zorder=5, edgecolor=SURFACE, linewidth=1.6, label="top 10")
    style(ax, f"{label}: absolute pressure value vs resilience",
          "Resilience  (pressure value - own baseline, runs/ball)",
          "Pressure performance  (shrunk value, runs/ball)")
    ax.grid(True)
    # headroom so labels and corner captions have somewhere to live
    ax.margins(x=0.30, y=0.20)
    ax.axvline(mx, color=AXIS, lw=1, zorder=2)
    ax.axhline(my, color=AXIS, lw=1, zorder=2)

    texts = []
    for _, r in top.iterrows():
        texts.append(ax.annotate(
            f"{int(r['rank'])}. {r['name']}", (r["resilience"], r["press_value"]),
            textcoords="offset points", xytext=(9, 3), fontsize=7.9,
            color=INK, fontweight="700", zorder=7))
    declutter(fig, ax, texts)

    xl, yl = ax.get_xlim(), ax.get_ylim()
    for tx, ty, t, ha, va in (
            (xl[1], yl[1], "CLUTCH STARS", "right", "top"),
            (xl[0], yl[1], "FRONT-RUNNERS", "left", "top"),
            (xl[1], yl[0], "PRESSURE SPECIALISTS", "right", "bottom"),
            (xl[0], yl[0], "AVOID", "left", "bottom")):
        ax.text(tx, ty, t, ha=ha, va=va, fontsize=7.4, color=AXIS,
                fontweight="700", zorder=1)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.255), ncols=2, fontsize=8.2)
    save(fig, os.path.join(figs, f"fig4_quadrant_{side}.png"))


# ---------------------------------------------------------------- 5. top 10 + CI
def fig_top10(out, figs):
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 5.0))
    for ax, side, label in ((axes[0], "bat", "Batters"), (axes[1], "bowl", "Bowlers")):
        e = pd.read_csv(os.path.join(out, f"ratings_{side}.csv")).head(10)
        y = np.arange(len(e))[::-1]
        ax.hlines(y, e["rating_lo"], e["rating_hi"], color=SEQ[3], lw=3.4,
                  zorder=3, capstyle="round")
        ax.scatter(e["rating"], y, s=74, color=BLUE, zorder=5,
                   edgecolor=SURFACE, linewidth=1.6)
        ax.set_yticks(y)
        ax.set_yticklabels([f"{int(r['rank'])}. {r['name']}" for _, r in e.iterrows()],
                           fontsize=8.6, color=INK)
        style(ax, f"{label} under pressure", "Composite pressure rating (z)", None, xgrid=True)
        xmax = e["rating_hi"].max()
        for yi, pv in zip(y, e["p_top10"].values):
            ax.annotate(f"{pv*100:.0f}%", (xmax, yi), textcoords="offset points",
                        xytext=(14, -3), fontsize=7.6, color=MUTED)
        ax.annotate("P(top 10)", (e["rating_hi"].max(), y[0]),
                    textcoords="offset points", xytext=(12, 13),
                    fontsize=7.4, color=MUTED, fontweight="600")
        ax.margins(x=0.18)
    fig.suptitle("Final rankings with 90% bootstrap intervals (resampled by match)",
                 x=0.005, ha="left", fontsize=12, fontweight="700", color=INK)
    fig.subplots_adjust(top=0.88)
    save(fig, os.path.join(figs, "fig5_top10.png"))


# ---------------------------------------------------------------- 6. pressure share
def fig_share(out, figs):
    df = pd.read_csv(os.path.join(out, "balls_pressure.csv"),
                     usecols=["phase", "press_bat", "press_bowl"], low_memory=False)
    p = (df.groupby("phase")[["press_bat", "press_bowl"]].mean() * 100
         ).reindex(["powerplay", "middle", "death"])
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    x = np.arange(len(p)); w = 0.36
    ax.bar(x - w/2, p["press_bat"], w, label="batting pressure", color=BLUE,
           zorder=3, edgecolor=SURFACE, linewidth=1.2)
    ax.bar(x + w/2, p["press_bowl"], w, label="bowling pressure", color=ORANGE,
           zorder=3, edgecolor=SURFACE, linewidth=1.2)
    style(ax, "The two sides are squeezed at different moments",
          None, "% of deliveries flagged as pressure")
    ax.set_xticks(x); ax.set_xticklabels([s.title() for s in p.index])
    ax.legend(fontsize=8.2, ncols=2)
    ax.text(0, -0.2, "Powerplay pressure sits on the BOWLER; the death squeezes both.",
            transform=ax.transAxes, fontsize=7.8, color=MUTED)
    save(fig, os.path.join(figs, "fig6_share.png"))


# ---------------------------------------------------------------- 7. RR squad gap
def fig_rr_gap(out, figs):
    """Pool as a jittered strip up top; RR players get named axis rows, so
    their labels cannot collide however tightly their values cluster."""
    import json
    pc = json.load(open(os.path.join(out, "player_cards.json")))
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.6))
    rng = np.random.default_rng(3)
    for ax, side, label in ((axes[0], "batters", "Batters"),
                            (axes[1], "bowlers", "Bowlers")):
        r = pd.read_csv(os.path.join(out,
              "ratings_bat.csv" if side == "batters" else "ratings_bowl.csv"))
        rr = sorted(pc[f"rr_{side}"], key=lambda x: -x["press_value"])
        n = len(rr)
        strip_y = n + 0.9
        isrr = r["name"].isin({x["name"] for x in rr}).values
        ax.scatter(r["press_value"][~isrr],
                   strip_y + rng.normal(0, .14, (~isrr).sum()),
                   s=26, color=MUTED, alpha=.45, linewidths=0, zorder=3)
        ax.text(r["press_value"].min(), strip_y + 0.62,
                f"all {len(r)} eligible players", fontsize=7.6, color=MUTED)
        for i, x in enumerate(rr):
            yy = n - 1 - i
            ax.hlines(yy, r["press_value"].min(), x["press_value"],
                      color=NEUTRAL, lw=1.2, zorder=2)
            ax.scatter([x["press_value"]], [yy], s=86, color=ORANGE, zorder=5,
                       edgecolor=SURFACE, linewidth=1.5)
            ax.annotate(f"{int(x['rank'])}/{x['of']}", (x["press_value"], yy),
                        textcoords="offset points", xytext=(10, -3),
                        fontsize=7.4, color=INK2, fontweight="700")
        ax.set_yticks(list(range(n)) + [strip_y])
        ax.set_yticklabels([x["name"] for x in rr][::-1] + [""], fontsize=8.4)
        ax.tick_params(axis="y", length=0)
        ax.set_ylim(-0.9, strip_y + 1.1)
        style(ax, f"{label}: RR squad vs the market",
              "Pressure performance (shrunk value, runs/ball)", None, xgrid=True)
        ax.spines["left"].set_visible(False)
        ax.margins(x=0.13)
    fig.suptitle("RR's current pressure coverage, and the gap to the top of the market",
                 x=0.005, ha="left", fontsize=12, fontweight="700", color=INK)
    fig.text(0.005, -0.01, "Orange: RR's IPL 2026 squad members who clear the "
             "eligibility threshold. Labels give their rank within the pool.",
             fontsize=7.8, color=MUTED)
    fig.tight_layout(pad=1.1, rect=(0, 0.01, 1, .93))
    fig.savefig(os.path.join(figs, "fig7_rr_gap.png"), bbox_inches="tight")
    plt.close(fig)
    print("  wrote fig7_rr_gap.png")


def main(out, figs):
    os.makedirs(figs, exist_ok=True)
    print("building figures...")
    fig_validation(out, figs)
    fig_calibration(out, figs)
    fig_leverage(out, figs)
    fig_share(out, figs)
    fig_quadrant(out, figs, "bat", "Batters")
    fig_quadrant(out, figs, "bowl", "Bowlers")
    fig_top10(out, figs)
    fig_rr_gap(out, figs)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
