"""The hidden win-probability engine. Built from minutes-weighted individual
`obpr`/`dbpr` — EvanMiya's Bayesian Performance Rating offense/defense
components (see https://evanmiya.com), scraped into d1_master_2026.csv and
already in the unified player pool (recruits get an even split of their
hardcoded `bpr` — see lib/recruit_config.py). Already fully opponent- and
teammate-adjusted by EvanMiya's own regularized-adjusted-plus-minus model,
no further adjustment needed.

Switched from BartTorvik's ortg/adj_drtg: those are individual box-composite
efficiency ratings, not built to be summed across a lineup to predict a
scoring margin. BPR is — EvanMiya's own possession formula is literally
"sum the 5 offensive players' OBPR, subtract the 5 defensive players'
DBPR" — which is exactly the aggregation this module needs.

This module's outputs (offense_proxy, defense_proxy, net_proxy) must NEVER be
rendered with a label anywhere in the UI — only the downstream win
probabilities / record / standings / tournament-odds outputs are shown to
the coach.

Real (non-recruit) IU roster players' obpr/dbpr are also nudged forward one
season via DEVELOPMENT_CURVE (see developed_obpr_dbpr) — d1_master's BPR
reflects last season, and a returning/transfer player entering 2026-27 is
expected to be slightly better than that snapshot, same reasoning as
percentile_engine.py's +1 experience-year bump.
"""
import pandas as pd
from scipy.stats import norm

BPR_BASELINE = 104.0   # avg D1 points/100 poss (EvanMiya's own intercept) — mathematically
                        # inert for net_proxy (cancels in the offense-defense subtraction),
                        # kept only so the raw hidden numbers read as realistic point rates.

# BPR is denominated in points per 100 possessions; a real D1 game runs
# ~68 possessions per team (standard, well-established pace figure). Home-
# court advantage (3.0 real points) and game-margin SD (11.0 real points,
# both standard CBB constants) are converted into net_proxy's native
# per-100-possession units by the same factor, which preserves their
# original relative weighting exactly — only the common scale changes.
# We can't fit this empirically against real outcomes: games.csv has no
# scores, only schedules, so there's no local ground truth to regress
# against; this pace conversion is the analytically-grounded alternative.
_POSSESSIONS_PER_GAME = 68.0
_PACE_SCALE = 100.0 / _POSSESSIONS_PER_GAME  # ~1.47

HOME_COURT_ADJ = 3.0 * _PACE_SCALE    # ~4.41, in net_proxy's per-100-poss units
NET_RATING_SD = 11.0 * _PACE_SCALE    # ~16.18, in net_proxy's per-100-poss units

# Empirical same-school year-over-year BPR deltas (Fr->So, So->Jr, Jr->Sr),
# recomputed directly from OSUPortal's own multi-season BartTorvik+EvanMiya
# cache (data/raw/barttorvik_players_{2022-2026}.csv + evanmiya_bpr_{2022-
# 2026}.csv), matching players by name AND requiring the SAME team in
# consecutive seasons, to isolate real development from transfer effects
# (~7,400 matched player-seasons across 4 season-pairs). Deliberately NOT
# OSUPortal's own config.py DEVELOPMENT_CURVE (Fr+2.0/So+1.2/Jr+0.5/Sr+0.0
# combined) — that's a hand-set literature prior (Miyakawa/538/DARKO)
# roughly 2x more optimistic than what this exact BPR data source's own
# history shows. Std dev per class is ~1.5-1.7, so this is deliberately a
# slight central-tendency nudge, not a precise per-player forecast.
#
# No "Sr" entry: a senior is already at the experience ceiling (same reason
# percentile_engine.projected_class_year_num doesn't add +1 for seniors
# either) — there's no further class to develop into, so seniors keep their
# raw, un-nudged obpr/dbpr. The empirical Sr->5th-yr delta measured +0.334/
# +0.071, for reference, but it's deliberately unused here.
DEVELOPMENT_CURVE = {
    # class_year: (delta_obpr, delta_dbpr)
    "fr": (0.592, 0.233),
    "so": (0.387, 0.130),
    "jr": (0.366, 0.123),
}


def _pool_row(player_id: str, player_pool_df: pd.DataFrame) -> pd.Series | None:
    """Looked up by espn_id, not name — player names collide across D1 (31
    known duplicates), so name-based matching can silently return the wrong
    player's obpr/dbpr."""
    hit = player_pool_df[player_pool_df["espn_id"] == player_id]
    return hit.iloc[0] if len(hit) else None


def developed_obpr_dbpr(row: pd.Series) -> tuple[float | None, float | None]:
    """A real (non-recruit) IU roster player's obpr/dbpr, nudged by
    DEVELOPMENT_CURVE — d1_master's obpr/dbpr reflect last season
    (2025-26); this roster projects one season forward, same reasoning as
    percentile_engine.projected_class_year_num's +1 year. Recruits are
    exempt: their hardcoded bpr already represents a 2026-27 debut
    projection, not a past season to develop from. Only ever applied to
    whoever currently fills an IU roster slot, computed fresh every call —
    swap the slot and the bump moves with it, same as the experience +1."""
    obpr = pd.to_numeric(row.get("obpr"), errors="coerce")
    dbpr = pd.to_numeric(row.get("dbpr"), errors="coerce")
    if bool(row.get("is_estimate")):
        return (
            float(obpr) if pd.notna(obpr) else None,
            float(dbpr) if pd.notna(dbpr) else None,
        )
    cy = str(row.get("class_year") or "").strip().lower()
    d_obpr, d_dbpr = DEVELOPMENT_CURVE.get(cy, (0.0, 0.0))
    return (
        float(obpr) + d_obpr if pd.notna(obpr) else None,
        float(dbpr) + d_dbpr if pd.notna(dbpr) else None,
    )


def team_offense_defense_proxy(roster, player_pool_df: pd.DataFrame) -> tuple[float, float]:
    """5x the MPG-weighted average OBPR/DBPR across the roster — the
    expected sum of the 5 players actually on the floor at any moment.
    Roster minutes are normalized to a 200 (5x40) target, so a player's
    MPG share of 200 is exactly 1/5 of their share of the floor; scaling
    the weighted average back up by 5 recovers the "sum of the 5 on-court
    players" that EvanMiya's own possession formula sums directly."""
    off_weight = off_value = def_weight = def_value = 0.0
    for slot in roster:
        if slot.mpg <= 0:
            continue
        row = _pool_row(slot.player_id, player_pool_df)
        if row is None:
            continue
        obpr, dbpr = developed_obpr_dbpr(row)
        if obpr is not None:
            off_weight += slot.mpg
            off_value += slot.mpg * obpr
        if dbpr is not None:
            def_weight += slot.mpg
            def_value += slot.mpg * dbpr

    avg_obpr = (off_value / off_weight) if off_weight else 0.0
    avg_dbpr = (def_value / def_weight) if def_weight else 0.0
    offense_proxy = BPR_BASELINE + 5.0 * avg_obpr
    defense_proxy = BPR_BASELINE - 5.0 * avg_dbpr
    return offense_proxy, defense_proxy


def net_proxy(offense_proxy: float, defense_proxy: float) -> float:
    return offense_proxy - defense_proxy


def win_probability(net_a: float, net_b: float, a_is_home: bool = False, b_is_home: bool = False) -> float:
    """P(team A beats team B) via normal-CDF on net-rating margin."""
    hca = HOME_COURT_ADJ if a_is_home else (-HOME_COURT_ADJ if b_is_home else 0.0)
    return float(norm.cdf((net_a - net_b + hca) / NET_RATING_SD))
