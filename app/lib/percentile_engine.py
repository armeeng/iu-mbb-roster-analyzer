"""The coach-facing team breakdown: raw box-score stats only, shown as
percentile-vs-D1-average. Mirrors Illinois MBB/tools/pregame_report.py's
_percentile_rank() pattern exactly (returns None for NaN/missing, never a
fabricated low percentile).

Recruits (from the unified player pool, lib/data_loader.load_player_pool)
are aggregated identically to real D1 players — their hardcoded estimated
stats flow into these same percentile bars, flagged via is_estimate.

"Team Stats Projections" shows genuine per-game team totals, not per-40
rates: counting stats (points/rebounds/assists/steals/blocks/turnovers) are
SUMMED across the roster, each player's per-40 rate scaled by their assigned
minutes (team_stat_aggregate_per_game), since 5 players contribute
simultaneously over a real 40-minute game — a per-40 rate describes one
archetypal player, not the team. Shooting/usage percentages stay MPG-
weighted averages. Because the scale changed (a team's points/game is ~5x
any individual player's), the comparison population changed too:
compute_team_population() builds one row per real D1 team (their actual
2025-26 roster, same per-game formula) so the hypothetical roster is ranked
against real TEAMS, not individual players.

STAT_COLS is a hard whitelist — bpr/obpr/dbpr/any *_proj_* column must
never appear there. PRODUCTION_COL is the one deliberate exception: by
explicit user choice, "Positional Production" uses BPR directly (a single
composite rating) rather than a blend of STAT_COLS, trading some
interpretability for a more holistic per-position value read. Real IU
roster players' BPR is nudged forward one season via
team_strength.developed_obpr_dbpr before being ranked (see that module for
the empirical development-curve source); recruits and the same-position
comparison population are unaffected.
"""
import pandas as pd
import streamlit as st

from lib.data_loader import load_d1_master
from lib.position_groups import position_group
from lib.team_strength import developed_obpr_dbpr

STAT_COLS = [
    "pts_40", "reb_40", "ast_40", "stl_40", "blk_40", "tov_40",
    "fta_40", "three_pa_40", "efg_pct", "three_pct", "ft_pct", "usg_pct",
]
# Counting stats are SUMMED across the roster to a per-game team total (5
# players contribute simultaneously over a real 40-minute game); shooting/
# usage percentages stay MPG-weighted averages (a percentage can't be
# summed across players). See team_stat_aggregate_per_game. fta_40/
# three_pa_40 (shot attempt volume, from stats.csv — d1_master itself only
# has shooting percentages, no attempt counts) are counting stats too.
PER_GAME_SUM_COLS = {
    "pts_40", "reb_40", "ast_40", "stl_40", "blk_40", "tov_40",
    "fta_40", "three_pa_40",
}
LOWER_IS_BETTER = {"tov_40"}
STAT_LABELS = {
    "pts_40": "Points / 40 min",
    "reb_40": "Rebounds / 40 min",
    "ast_40": "Assists / 40 min",
    "stl_40": "Steals / 40 min",
    "blk_40": "Blocks / 40 min",
    "tov_40": "Turnovers / 40 min",
    "fta_40": "FT Attempts / 40 min",
    "three_pa_40": "3PT Attempts / 40 min",
    "efg_pct": "Effective FG%",
    "three_pct": "3-Point %",
    "ft_pct": "Free Throw %",
    "usg_pct": "Usage %",
}
# Separate labels for the team-level per-game projection (compute_team_
# breakdown's `stats` dict) — STAT_LABELS above stays "/ 40 min" for
# individual-player display (ai_breakdown.py's per-player stat lines are
# still raw per-40 values, unrelated to this per-game team total).
TEAM_STAT_LABELS = {
    "pts_40": "Points / Game",
    "reb_40": "Rebounds / Game",
    "ast_40": "Assists / Game",
    "stl_40": "Steals / Game",
    "blk_40": "Blocks / Game",
    "tov_40": "Turnovers / Game",
    "fta_40": "FT Attempts / Game",
    "three_pa_40": "3PT Attempts / Game",
    "efg_pct": "Effective FG%",
    "three_pct": "3-Point %",
    "ft_pct": "Free Throw %",
    "usg_pct": "Usage %",
}
SIZE_COLS = ["height_in"]
EXPERIENCE_COLS = ["class_year_num"]
PRODUCTION_COL = "bpr"
MIN_GAMES_FOR_POPULATION = 10
LIMITED_SAMPLE_GAMES = 15
LIMITED_ROLE_MPG = 15.0


@st.cache_data
def compute_d1_population(min_games: int = MIN_GAMES_FOR_POPULATION) -> pd.DataFrame:
    """Real D1 players only (recruits are never part of the comparison
    baseline — they have games=0 and wouldn't pass this filter anyway)."""
    df = load_d1_master()
    games = pd.to_numeric(df["games"], errors="coerce")
    return df[games >= min_games]


TEAM_MINUTES_PER_GAME = 200.0  # 5 players x 40 minutes — one real game's floor time


def _sum_per_game(pairs: list[tuple[float, float]]) -> float | None:
    """pairs = [(per_40_value, mpg), ...]. Sums each player's mpg-scaled
    share to a team total, then rescales by (200 / actual total MPG) to a
    canonical 200 team-minutes. Without this, real teams' tracked rosters
    essentially never sum to exactly 200: injuries, transfers, and lineup
    changes mid-season mean the player who missed games and their
    replacement BOTH show a full rate for the games they individually
    played, so summing everyone's own per-game rate double-counts shared
    roster minutes (verified: real D1 teams' total roster MPG averages
    ~235, not 200, ranging up to ~300). Left uncorrected, this inflated
    every per-game team total by ~15-20% league-wide, which is what made a
    good-but-not-elite 84 points/game read as a mediocre 37th percentile."""
    if not pairs:
        return None
    total_mpg = sum(m for _, m in pairs)
    if total_mpg <= 0:
        return None
    raw_total = sum(v * m / 40.0 for v, m in pairs)
    return raw_total * (TEAM_MINUTES_PER_GAME / total_mpg)


def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    """pairs = [(value, weight), ...]. Weighted average — used for shooting/
    usage percentages, which can't be summed across players."""
    total_w = sum(w for _, w in pairs)
    if total_w == 0:
        return None
    return sum(v * w for v, w in pairs) / total_w


# Shooting percentages are weighted by actual shot volume, not raw minutes
# played — a player who logs heavy minutes but rarely shoots (e.g. a 25%
# FT shooter who takes almost no FTs) shouldn't move the team percentage
# much, which a minutes-only weight would let happen. usg_pct has no
# natural "attempt" denominator, so it stays MPG-weighted.
WEIGHT_COL_FOR_PCT = {
    "efg_pct": "fga_40",
    "three_pct": "three_pa_40",
    "ft_pct": "fta_40",
}


def _pct_weight(row, stat_col: str, mpg: float) -> float:
    """Weight for row's contribution to stat_col's team-level weighted
    average: expected shot attempts this game (attempt_rate * mpg/40) for
    the 3 shooting percentages, falling back to raw mpg for usg_pct or for
    anyone missing attempt-rate data (e.g. the 4 hardcoded recruits, who
    have no real attempt-volume data from stats.csv to draw on)."""
    weight_col = WEIGHT_COL_FOR_PCT.get(stat_col)
    if weight_col is not None:
        rate = pd.to_numeric(row.get(weight_col), errors="coerce")
        if pd.notna(rate):
            return float(rate) * mpg / 40.0
    return mpg


def team_stat_aggregate_per_game(roster, player_pool_df: pd.DataFrame, stat_col: str) -> float | None:
    """This roster's projected per-game team total for stat_col (counting
    stats, summed) or weighted average (percentages — attempt-weighted for
    shooting stats, MPG-weighted otherwise)."""
    pairs = []
    for slot in roster:
        if slot.mpg <= 0:
            continue
        row = pool_row(slot.player_id, player_pool_df)
        if row is None:
            continue
        val = pd.to_numeric(row.get(stat_col), errors="coerce")
        if pd.isna(val):
            continue
        weight = slot.mpg if stat_col in PER_GAME_SUM_COLS else _pct_weight(row, stat_col, slot.mpg)
        pairs.append((float(val), weight))
    return _sum_per_game(pairs) if stat_col in PER_GAME_SUM_COLS else _weighted_avg(pairs)


@st.cache_data
def compute_team_population() -> pd.DataFrame:
    """One row per real D1 team (2025-26 actual roster/minutes), using the
    same per-game formula as team_stat_aggregate_per_game — so the
    hypothetical IU roster's projected per-game stats are benchmarked
    against real TEAM totals, not individual players (whose own per-game
    numbers are on a much smaller, incomparable scale — a team's points/
    game reflects 5 players' combined output, not one player's)."""
    d1 = load_d1_master()
    rows = []
    for team, team_df in d1.groupby("espn_team"):
        mpg = pd.to_numeric(team_df["mpg"], errors="coerce")
        valid = team_df[mpg > 0].copy()
        valid_mpg = pd.to_numeric(valid["mpg"], errors="coerce")
        row = {"espn_team": team}
        for col in STAT_COLS:
            vals = pd.to_numeric(valid[col], errors="coerce")
            if col in PER_GAME_SUM_COLS:
                weights = valid_mpg
            else:
                weight_col = WEIGHT_COL_FOR_PCT.get(col)
                if weight_col is not None:
                    rate = pd.to_numeric(valid[weight_col], errors="coerce")
                    weights = (rate * valid_mpg / 40.0).where(rate.notna(), valid_mpg)
                else:
                    weights = valid_mpg
            mask = vals.notna() & weights.notna()
            pairs = list(zip(vals[mask], weights[mask]))
            row[col] = _sum_per_game(pairs) if col in PER_GAME_SUM_COLS else _weighted_avg(pairs)
        rows.append(row)
    return pd.DataFrame(rows)


def percentile_rank(value, col: str, population: pd.DataFrame) -> int | None:
    """Percentile = share of the population with a worse value. Returns
    None for NaN/missing (e.g. a center who's never attempted a 3) — never
    a fabricated 0th percentile."""
    if col not in population.columns:
        return None
    series = pd.to_numeric(population[col], errors="coerce").dropna()
    if series.empty:
        return None
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(fval):
        return None
    if col in LOWER_IS_BETTER:
        return int(round((series > fval).sum() / len(series) * 100))
    return int(round((series < fval).sum() / len(series) * 100))


def ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', 11-13 -> 'th' (the
    standard English-ordinal exception), etc."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def tier_for_percentile(pct: int | None, lower_is_better: bool = False) -> str | None:
    if pct is None:
        return None
    eff = (100 - pct) if lower_is_better else pct
    if eff >= 80:
        return "elite"
    if eff >= 60:
        return "strong"
    if eff >= 40:
        return "average"
    if eff >= 20:
        return "weak"
    return "poor"


def pool_row(player_id: str, player_pool_df: pd.DataFrame) -> pd.Series | None:
    """Looked up by espn_id, not name — player names collide across D1 (31
    known duplicates, e.g. two different "Jake Davis" on different teams),
    so name-based matching can silently return the wrong player."""
    hit = player_pool_df[player_pool_df["espn_id"] == player_id]
    return hit.iloc[0] if len(hit) else None


def projected_class_year_num(row: pd.Series) -> float | None:
    """class_year_num reflects each player's last-season (2025-26) class —
    this roster projects the 2026-27 season, one year later, so a real IU
    roster player is bumped +1 (a 'So' becomes a 3, projecting to Jr).
    Recruits are exempt: their class_year is already 'Fr' for 2026-27 since
    they have no last-season row to begin with. Seniors are also exempt —
    a 'Sr' is already at the experience ceiling, with no further class to
    project into, so they keep their raw class_year_num (4) unchanged
    (same reasoning as team_strength.DEVELOPMENT_CURVE having no 'Sr'
    entry). Only ever applied to whoever currently fills an IU roster slot
    — swap the slot and the +1 moves with it, since this is computed fresh
    from the live roster every call."""
    val = pd.to_numeric(row.get("class_year_num"), errors="coerce")
    if pd.isna(val):
        return None
    if bool(row.get("is_estimate")):
        return float(val)
    if str(row.get("class_year") or "").strip().lower() == "sr":
        return float(val)
    return float(val) + 1


def compute_team_breakdown(
    roster, player_pool_df: pd.DataFrame, population_df: pd.DataFrame,
    team_population: pd.DataFrame | None = None,
) -> dict:
    """Returns {'stats': {col: {...}}, 'by_position_production': {pos: avg_bpr_pct|None},
    'by_position_size': {pos: avg_height_pct|None}, 'by_position_experience':
    {pos: avg_class_year_pct|None}}. by_position_production is BPR-percentile
    based (PRODUCTION_COL); the others are height/projected-class-year. None
    of the by-position dicts are MPG-weighted — every player in a group
    counts equally regardless of minutes played.

    team_population scopes the `stats` comparison (e.g. all D1 teams vs.
    just the Big Ten) — defaults to all D1 if not given. Positional
    production/size/experience always compare against same-position D1
    players regardless of this scope; that's a separate toggle-independent
    comparison."""
    if team_population is None:
        team_population = compute_team_population()
    stats = {}
    for col in STAT_COLS:
        team_val = team_stat_aggregate_per_game(roster, player_pool_df, col)
        pct = percentile_rank(team_val, col, team_population) if team_val is not None else None
        stats[col] = {
            "label": TEAM_STAT_LABELS[col],
            "team_value": team_val,
            "percentile": pct,
            "tier": tier_for_percentile(pct, col in LOWER_IS_BETTER),
        }

    # Positional production/size/experience are compared against same-position
    # D1 players only (e.g. a PG's percentile is relative to other PGs, not
    # centers) — computed once per position group, not the whole-D1
    # `population_df` used by the team-wide `stats` block above.
    pop_pos_group = population_df["role"].apply(position_group)

    by_position_production: dict[str, list[int]] = {}
    by_position_size: dict[str, list[int]] = {}
    by_position_experience: dict[str, list[int]] = {}
    for slot in roster:
        row = pool_row(slot.player_id, player_pool_df)
        if row is None:
            continue
        pg = position_group(row.get("role"))
        if pg is None:
            continue
        pos_population = population_df[pop_pos_group == pg]

        dev_obpr, dev_dbpr = developed_obpr_dbpr(row)
        dev_bpr = (dev_obpr + dev_dbpr) if dev_obpr is not None and dev_dbpr is not None else None
        production_pct = percentile_rank(dev_bpr, PRODUCTION_COL, pos_population)
        if production_pct is not None:
            by_position_production.setdefault(pg, []).append(production_pct)

        size_pcts = [
            p for col in SIZE_COLS
            if (p := percentile_rank(row.get(col), col, pos_population)) is not None
        ]
        if size_pcts:
            by_position_size.setdefault(pg, []).extend(size_pcts)

        exp_pct = percentile_rank(projected_class_year_num(row), EXPERIENCE_COLS[0], pos_population)
        if exp_pct is not None:
            by_position_experience.setdefault(pg, []).append(exp_pct)

    def _avg(d: dict[str, list[int]]) -> dict[str, int | None]:
        return {pg: (round(sum(v) / len(v)) if v else None) for pg, v in d.items()}

    return {
        "stats": stats,
        "by_position_production": _avg(by_position_production),
        "by_position_size": _avg(by_position_size),
        "by_position_experience": _avg(by_position_experience),
    }


def player_flags(row: pd.Series) -> list[str]:
    """Plain-text context flags — transparency, not adjustment."""
    if bool(row.get("is_estimate")):
        return ["Estimated debut production — recruiting profile, no college games played"]
    flags = []
    games = pd.to_numeric(row.get("games"), errors="coerce")
    mpg = pd.to_numeric(row.get("mpg"), errors="coerce")
    if pd.notna(games) and games < LIMITED_SAMPLE_GAMES:
        flags.append(f"Limited sample ({int(games)} games)")
    if pd.notna(mpg) and mpg < LIMITED_ROLE_MPG:
        flags.append(f"Limited role last season ({mpg:.1f} MPG)")
    return flags
