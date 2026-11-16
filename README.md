# Pressure Performance Framework

A method for measuring how T20 batters and bowlers perform when the match is genuinely on the line, built on ball-by-ball IPL and T20I data.

The question it answers: *which players hold up under pressure, and how much of what looks like "clutch" is actually repeatable?*

---

## The model

Pressure is scored on every delivery as **leverage × urgency**.

### Leverage — can this ball change the result?

Leverage comes from a win-probability model trained on the ball data itself. For each delivery it takes the outcomes that ball could produce (0, 1, 2, 3, 4, 6, wicket), weights each by its modelled likelihood in that exact state, and measures the spread of win probability across them.

A ball that cannot move the result scores near zero however late in the innings it is bowled. This is what keeps a dead-rubber death over from being counted as pressure.

### Urgency — and who is actually being squeezed

Urgency is a transparent composite of match-situation signals, combined with a probabilistic OR so simultaneous squeezes compound.

It is deliberately **computed twice, once per side**. This is the central design decision. The obvious approach — a single pressure flag applied to batters and bowlers alike — gets one of the two groups backwards: a chase needing 15 an over is desperate for the *batter* and comfortable for the *bowler*, and when the same chase needs six the pressure has moved across. The framework therefore models:

- **Batting urgency** — required rate above par, wickets lost beyond the league norm for that stage, being behind par when setting a total, and the innings endgame.
- **Bowling urgency** — the chase on track with wickets in hand, being scored off above par, defending at the death, and a small total to defend.

### Measuring performance

Each delivery is scored against the model's expectation for that exact state:

```
value = (runs − E[runs]) − wicket_cost × (wicket − P[wicket])
```

`wicket_cost` is **not a constant**. It is estimated from a monotonic model of runs still to come in the innings, differenced across losing one wicket, so an early wicket is correctly priced higher than a late one — there are more balls left to lose. A flat wicket cost systematically over-punishes top-order batters and flatters death bowlers.

### Reliability calibration

The runs term and the wicket term are kept separate rather than summed. A wicket is worth several runs and dismissals are rare, so the wicket term carries far more variance per unit of repeatable signal; summing first can yield a composite less reliable than either part.

Instead, each component is shrunk by its **own measured reliability**:

1. Split the matches in half at random, 60 times; correlate each component's per-player rate across halves → `r_half`
2. Spearman-Brown up to the full sample → `r_full = 2r/(1+r)`
3. Reliability is the signal share, so `true_var = r_full × observed_var`, with each player's error variance scaling inversely with their effective sample
4. `shrink = true_var / (true_var + err_var)`

A component that does not replicate collapses toward the league mean on its own evidence rather than on anyone's judgement. Split-half is taken at **match** level, so it also absorbs the within-match correlation an independence assumption would miss.

The same measurement sets the per-side rating weights in `WEIGHTS` — re-measure before changing them, and do not carry them to another dataset.

### Auction relevance, not just performance

Two filters apply that a pure performance ranking misses, and both are part of the model rather than a post-hoc edit:

- **Players who cannot be signed.** Boards whose players are ineligible for the target competition are excluded outright — however well someone rates, an unsignable player is not an actionable recommendation.
- **Players with almost no evidence in the target competition.** A rating built almost entirely on international cricket is an extrapolation into a franchise league, often against materially weaker attacks. `MIN_IPL_PRESS_BALLS` sets a floor on pressure deliveries in the target competition itself. The floor is deliberately not tuned: check that a range of values produces the same outcome before trusting it, and treat sensitivity to the exact number as a warning sign.

Both filters are applied before the rankings are read, and the run reports who they removed and why.

## Validation built into the pipeline

The pressure definition is tested before it is used for anything. `pressure.py` reports:

- **Outcome gradients across pressure deciles** — runs per wicket, dismissal rate, runs conceded per ball, balls per wicket. Note that raw strike rate is the *wrong* test for batting pressure: under a squeeze batters attempt more, so scoring rate rises even as the situation gets harder. The honest signals are risk-adjusted.
- **Per-player splits** — `player_cards.py` reports each ranked player against their own baseline on strike rate, boundary and dot rate, survival, phase mix, pace-versus-spin, and share of evidence from the target competition. Raw economy in particular is confounded by phase: a bowler who works mostly at the death will show a worse pressure economy than his own baseline while still being strongly positive against expectation for the states he bowls in.
- **A within-player paired test** — each player against his own non-pressure baseline, with a Wilcoxon signed-rank test. Comparing a player to himself removes every player-quality confound.
- **Independence of the two indices** — the correlation between batting and bowling pressure, and the share of deliveries flagged for both.

`ratings.py` additionally reports split-half reliability for every component and for the final composite, bootstrap confidence intervals, and a cross-check against win-probability added as a second, independent currency.

## Robustness practices

These are the choices that stop the numbers being optimistic:

- **GroupKFold by match, everywhere.** Balls within a match are heavily correlated; a random split leaks the result and inflates every metric.
- **Cross-fitted expectation models.** No player is ever scored by a model that trained on their own match.
- **Separate win-probability models per innings.** Setting a total and chasing one are different problems; one model with NaN chase-features was beaten by plain logistic regression.
- **Monotonic constraints** wherever the direction is known a priori — win probability must rise with wickets in hand and fall with runs required. This matters most because leverage is a *difference* of two predictions, so any non-physical wiggle learned in a sparse state gets amplified.
- **No internal early stopping.** It splits randomly inside a fold, putting balls from the same match on both sides and stopping on a leaked signal.
- **Honest model selection.** Gradient boosting and spline logistic regression are both scored by out-of-fold log loss; the better model per innings wins.
- **Forward-in-time holdout** as well as cross-validation, since the task projects onto a future season.
- **Cluster bootstrap by match** for intervals and rank stability, with winsorised leverage so a handful of freak deliveries cannot dominate weighted means.
- **Empirical calibration over assumption** — shrinkage strength, component weights and the reliability of the ranking itself are all measured, not asserted.

## Pipeline

| Stage | Does |
|---|---|
| `pipeline/build_state.py` | Reconstructs pre-ball match state from the raw ball data; self-validates against official match results |
| `pipeline/win_prob.py` | Win-probability, ball-outcome and leverage models, with calibration diagnostics |
| `pipeline/pressure.py` | The two pressure indices plus the validation suite |
| `pipeline/ratings.py` | Value components, reliability calibration, shrinkage, bootstrap |
| `pipeline/player_cards.py` | Per-player pressure evidence and squad-gap profiling for a named franchise |
| `pipeline/charts.py` | Figures |

Each stage writes to `out/` and reads the previous stage's output, so any stage can be re-run alone.

## Data handling

Conventions the ball data requires, each of which silently corrupts results if missed:

- Team runs are `runs + extras1 + extras2` — the `runs` column is off the bat only.
- Wides and no-balls do not consume a delivery; byes and leg-byes do.
- Bowlers are charged wides and no-balls, but not byes or leg-byes.
- Run-outs are excluded from bowler wicket credit.
- Super Over innings are dropped; DLS-affected matches are flagged and excluded from model training.
- Deliveries are keyed by a stable `ball_uid` assigned at stage 1, so later stages join on it rather than on row position.

## Running it

The data pack is **not redistributed here**. Place it at `Data Pack/`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p out figs

.venv/bin/python pipeline/build_state.py "Data Pack" out/state.csv
.venv/bin/python pipeline/win_prob.py   out/state.csv out
.venv/bin/python pipeline/pressure.py   out/balls_enriched.csv out
.venv/bin/python pipeline/ratings.py    out/balls_pressure.csv out/state.csv out
.venv/bin/python pipeline/player_cards.py out "Data Pack" out/player_cards.json
.venv/bin/python pipeline/charts.py     out figs
```

Every stage is seeded and prints its own diagnostics. Generated output is gitignored — the repository holds the method, not its results.

## Known limitations

- The wicket signal is weak; dismissals under pressure are close to irreducible noise at realistic sample sizes, so ratings lean on scoring above expectation.
- First-innings win probability is materially harder to model than a chase, making first-innings leverage the softer half of the index.
- Bootstrap intervals overlap substantially outside the very top of each ranking.
- No venue, weather or pitch adjustment; par score is modelled per competition-season, not per ground.
- Opposition strength is a coarse team-level proxy rather than a bowler-versus-batter matchup.
- Player availability is out of scope.
