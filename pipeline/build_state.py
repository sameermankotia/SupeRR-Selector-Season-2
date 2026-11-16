#!/usr/bin/env python3
"""
Stage 1 - Match state reconstruction.

Reads the raw RR data pack and emits one enriched row per legal-or-illegal
delivery with the full match situation as it stood BEFORE that ball was bowled.

Everything downstream (win probability, leverage, pressure, ratings) is built
on this file, so it is validated against official match results here.

Usage:  python3 -I build_state.py <data_pack_dir> <out_csv>
"""
import csv, sys, os
from collections import defaultdict

SUPER_OVER_INNINGS = {"3", "4"}
BOWLER_WICKETS = {"Caught", "Bowled", "LBW", "Stump", "Hit Wicket"}  # excl RunOut/Retire/Obstruct


def num(x, d=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return d


def total_runs(r):
    """Runs credited to the batting team off this delivery."""
    return num(r["runs"]) + num(r["extras1_runs"]) + num(r["extras_2_runs"])


def is_legal(r):
    """Wides and no-balls do not consume a delivery; byes/legbyes do."""
    return r["extras_type"] not in ("wide", "Overstep")


def phase_of(over):
    if over <= 6:
        return "powerplay"
    if over <= 15:
        return "middle"
    return "death"


def main(pack, out_path):
    comps = {r["comp_id"]: r for r in csv.DictReader(open(os.path.join(pack, "competitions.csv")))}
    matches = {r["match_id"]: r for r in csv.DictReader(open(os.path.join(pack, "matches.csv")))}

    # ---- group deliveries by innings, ordered by innings_ball_num ----
    innings = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(pack, "ball_by_ball.csv"))):
        innings[(r["match_id"], r["innings"])].append(r)
    for k in innings:
        innings[k].sort(key=lambda r: num(r["innings_ball_num"]))

    # ---- innings totals (needed for 2nd-innings targets) ----
    inn_total = {k: sum(total_runs(r) for r in rows) for k, rows in innings.items()}

    def scheduled_balls(mid, inns):
        """Balls available in this innings, honouring DLS-revised overs."""
        m = matches.get(mid, {})
        fld = "first_inn_revised_overs" if inns == "1" else "second_inn_revised_overs"
        ov = num(m.get(fld), 0)
        return ov * 6 if ov > 0 else 120

    rows_out = []
    for (mid, inns), balls in sorted(innings.items()):
        if inns in SUPER_OVER_INNINGS:
            continue
        m = matches.get(mid)
        if not m:
            continue
        comp = comps.get(m["comp_id"], {})
        comp_name = comp.get("comp_name", "")
        is_ipl = 1 if comp_name.startswith("IPL") else 0
        dls = 1 if (num(m.get("revised_target"), 0) > 0
                    or num(m.get("first_inn_revised_overs"), 0) > 0
                    or num(m.get("second_inn_revised_overs"), 0) > 0) else 0

        sched = scheduled_balls(mid, inns)

        # target for a chase: DLS revised target wins, else 1st innings + 1
        target = ""
        if inns == "2":
            rt = num(m.get("revised_target"), 0)
            if rt > 0:
                target = rt
            elif (mid, "1") in inn_total:
                target = inn_total[(mid, "1")] + 1

        bat_team = balls[0]["batting_team_id"]
        win_team = m.get("win_team_id", "")
        bat_won = "" if not win_team else (1 if win_team == bat_team else 0)

        score = 0          # batting-side runs before this ball
        wkts = 0           # wickets lost before this ball
        legal_done = 0     # legal deliveries completed before this ball

        for r in balls:
            over_no = legal_done // 6 + 1
            balls_rem = max(sched - legal_done, 0)
            wkts_in_hand = max(10 - wkts, 0)
            crr = (score * 6.0 / legal_done) if legal_done else ""

            if inns == "2" and target != "":
                need = max(target - score, 0)
                rrr = (need * 6.0 / balls_rem) if balls_rem > 0 else ""
            else:
                need, rrr = "", ""

            wkt = 1 if r["is_wicket"] == "true" else 0
            rows_out.append({
                "ball_uid": len(rows_out),
                "match_id": mid, "innings": inns, "comp_id": m["comp_id"],
                "comp_name": comp_name, "is_ipl": is_ipl,
                "season": comp.get("season", ""), "match_date": m.get("match_date", ""),
                "knock_out": num(m.get("knock_out"), 0), "dls": dls,
                "batting_team_id": bat_team, "bowling_team_id": r["bowling_team_id"],
                "striker_id": r["striker_id"], "striker_name": r["striker_name"],
                "bowler_id": r["bowler_id"], "bowler_name": r["bowler_name"],
                "batting_type": r["batting_type"], "bowling_type": r["bowling_type"],
                "pace_or_spin": r["pace_or_spin"], "batting_order": r["batting_order"],
                # --- state BEFORE the ball ---
                "over_no": over_no, "phase": phase_of(over_no),
                "legal_done": legal_done, "balls_rem": balls_rem,
                "score_before": score, "wkts_before": wkts,
                "wkts_in_hand": wkts_in_hand, "crr": crr,
                "target": target, "runs_required": need, "rrr": rrr,
                # --- outcome of the ball ---
                "bat_runs": num(r["runs"]), "team_runs": total_runs(r),
                "is_legal": 1 if is_legal(r) else 0,
                "is_wicket": wkt,
                "bowler_wicket": 1 if (wkt and r["dismissal_type"] in BOWLER_WICKETS) else 0,
                "dismissal_type": r["dismissal_type"],
                "extras_type": r["extras_type"],
                "extras": num(r["extras1_runs"]) + num(r["extras_2_runs"]),
                # --- match outcome, for the win-probability model ---
                "bat_team_won": bat_won,
                "innings_final_score": inn_total[(mid, inns)],
                "sched_balls": sched,
            })

            score += total_runs(r)
            wkts += wkt
            if is_legal(r):
                legal_done += 1

    cols = list(rows_out[0].keys())
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows_out)

    # ---------------- validation ----------------
    print(f"wrote {len(rows_out):,} deliveries -> {out_path}")
    ok = bad = skip = 0
    mismatch = []
    for mid in sorted({k[0] for k in innings}):
        a, b = inn_total.get((mid, "1")), inn_total.get((mid, "2"))
        m = matches.get(mid)
        if a is None or b is None or not m:
            skip += 1
            continue
        res = m.get("result", "").lower()
        if "wicket" in res:
            actual = "chase"
        elif "run" in res:
            actual = "defend"
        else:
            skip += 1
            continue
        recon = "chase" if b > a else "defend" if a > b else "tie"
        if recon == actual:
            ok += 1
        else:
            bad += 1
            mismatch.append((mid, a, b, m.get("result", "")))

    print(f"result validation: {ok} correct / {bad} mismatched / {skip} not applicable")
    if ok + bad:
        print(f"accuracy: {ok/(ok+bad):.3%}")
    dls_ids = {mid for mid, *_ in mismatch if "d/l" in _[2].lower() or "dls" in _[2].lower()} if mismatch else set()
    print(f"remaining mismatches (expected: DLS + Super Over): {len(mismatch)}")
    for e in mismatch:
        print("   ", e)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
