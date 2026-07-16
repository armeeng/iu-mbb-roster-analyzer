"""Season schedule + Monte Carlo simulation.

The real 2026-27 Big Ten schedule was confirmed empty on ESPN as of this
project's data scrape (checked directly across Nov 2026-Feb 2027 — zero
games posted anywhere). In its place, this module uses each Big Ten team's
ACTUAL 2025-26 regular-season schedule (from data/games.csv) — real
opponents, real home/away splits, real non-conference slate — as a far
better proxy for scheduling structure than a synthetic round-robin. Team
STRENGTH is still this year's (via league_model's proxies); only the
who/when/home-or-away comes from last season.

A file-based override hook is kept for when the real 2026-27 schedule drops.

Tournament odds are a heuristic finish-rank -> at-large-probability curve —
explicitly a starting proposal, not a fitted/precise model.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from lib.data_loader import DATA_DIR
from lib.team_strength import net_proxy, win_probability

SCHEDULE_OVERRIDE_PATH = DATA_DIR / "b1g_schedule_2627_override.csv"  # columns: team_a,team_b,a_is_home
N_ITERATIONS = 5000

# Empirically chosen from the 2025-26 games.csv date histogram: game volume
# holds at 30-90/day through March 8, then drops as conference tournaments
# take over (Mar 9+), followed by Selection Sunday (Mar 15) and the NCAA
# tournament. Games on/after this date are excluded as postseason.
REGULAR_SEASON_CUTOFF = "2026-03-09"
LAST_SEASON = 2026  # the 2025-26 season, as labeled in games.csv


def build_schedule_from_last_season(target_teams: list[str]) -> pd.DataFrame:
    """Every regular-season game involving at least one of target_teams,
    from last season's real schedule. Returns columns [team_a (home),
    team_b (away), a_is_home=True, is_conference] — is_conference is True
    only when BOTH sides are in target_teams (i.e. both Big Ten)."""
    games = pd.read_csv(DATA_DIR / "games.csv", dtype=str)
    teams_df = pd.read_csv(DATA_DIR / "teams.csv", dtype=str)
    id_to_name = dict(zip(teams_df["team_id"], teams_df["team_name"]))

    games["season"] = pd.to_numeric(games["season"], errors="coerce")
    g = games[games["season"] == LAST_SEASON].copy()
    g["game_date"] = pd.to_datetime(g["game_date"])
    g = g[g["game_date"] < REGULAR_SEASON_CUTOFF]

    g["away_team"] = g["away_team_id"].map(id_to_name)
    g["home_team"] = g["home_team_id"].map(id_to_name)
    g = g.dropna(subset=["away_team", "home_team"])

    target_set = set(target_teams)
    mask = g["away_team"].isin(target_set) | g["home_team"].isin(target_set)
    g = g[mask]

    return pd.DataFrame({
        "team_a": g["home_team"],
        "team_b": g["away_team"],
        "a_is_home": True,
        "is_conference": g["away_team"].isin(target_set) & g["home_team"].isin(target_set),
    }).reset_index(drop=True)


def build_synthetic_schedule(teams: list[str], seed: int = 42) -> pd.DataFrame:
    """Fallback only (used if last season's schedule data is unavailable):
    17 round-robin games/team + 3 resampled repeats = 20 games/team, all
    tagged is_conference=True."""
    rng = np.random.default_rng(seed)
    games = []
    for i, team_a in enumerate(teams):
        for team_b in teams[i + 1:]:
            games.append((team_a, team_b, bool(rng.integers(0, 2))))
    for _ in range(3):
        shuffled = list(teams)
        rng.shuffle(shuffled)
        for i in range(0, len(shuffled), 2):
            games.append((shuffled[i], shuffled[i + 1], bool(rng.integers(0, 2))))
    df = pd.DataFrame(games, columns=["team_a", "team_b", "a_is_home"])
    df["is_conference"] = True
    return df


def load_or_build_schedule(target_teams: list[str]) -> pd.DataFrame:
    if SCHEDULE_OVERRIDE_PATH.exists():
        df = pd.read_csv(SCHEDULE_OVERRIDE_PATH)
        if "is_conference" not in df.columns:
            df["is_conference"] = True
        return df
    try:
        schedule = build_schedule_from_last_season(target_teams)
        if len(schedule) > 0:
            return schedule
    except FileNotFoundError:
        pass
    return build_synthetic_schedule(target_teams)


def monte_carlo_season(
    schedule_df: pd.DataFrame,
    team_proxies: dict[str, tuple[float, float]],
    standings_teams: list[str],
    n_iterations: int = N_ITERATIONS,
    seed: int = 42,
) -> pd.DataFrame:
    """Simulates every scheduled game n_iterations times. Returns one row
    per team in standings_teams with both conference-only wins (for the
    Big Ten standings table) and overall wins (conference + non-conference,
    for the overall-record estimate)."""
    rng = np.random.default_rng(seed)
    n_games = len(schedule_df)

    win_probs = np.array([
        win_probability(
            net_proxy(*team_proxies[row.team_a]),
            net_proxy(*team_proxies[row.team_b]),
            a_is_home=row.a_is_home,
        )
        for row in schedule_df.itertuples()
    ])
    draws = rng.random((n_iterations, n_games))
    a_wins = draws < win_probs

    overall_wins = {t: np.zeros(n_iterations, dtype=int) for t in standings_teams}
    conf_wins = {t: np.zeros(n_iterations, dtype=int) for t in standings_teams}
    overall_games = {t: 0 for t in standings_teams}
    conf_games = {t: 0 for t in standings_teams}

    for gi, row in enumerate(schedule_df.itertuples()):
        a_win_iter = a_wins[:, gi].astype(int)
        b_win_iter = (~a_wins[:, gi]).astype(int)
        if row.team_a in overall_wins:
            overall_wins[row.team_a] += a_win_iter
            overall_games[row.team_a] += 1
            if row.is_conference:
                conf_wins[row.team_a] += a_win_iter
                conf_games[row.team_a] += 1
        if row.team_b in overall_wins:
            overall_wins[row.team_b] += b_win_iter
            overall_games[row.team_b] += 1
            if row.is_conference:
                conf_wins[row.team_b] += b_win_iter
                conf_games[row.team_b] += 1

    conf_matrix = np.column_stack([conf_wins[t] for t in standings_teams])
    ranks = (-conf_matrix).argsort(axis=1).argsort(axis=1) + 1  # 1 = best, by conference wins

    rows = []
    for i, team in enumerate(standings_teams):
        rows.append({
            "team": team,
            "conf_games": conf_games[team],
            "mean_conf_wins": round(float(conf_wins[team].mean()), 1),
            "p10_wins": int(np.percentile(conf_wins[team], 10)),
            "p90_wins": int(np.percentile(conf_wins[team], 90)),
            "mean_finish_rank": round(float(ranks[:, i].mean()), 1),
            "overall_games": overall_games[team],
            "mean_overall_wins": round(float(overall_wins[team].mean()), 1),
            "net_proxy": round(net_proxy(*team_proxies[team]), 1),
        })
    return pd.DataFrame(rows).sort_values("mean_conf_wins", ascending=False).reset_index(drop=True)


def estimate_tournament_odds(d1_net_rank: int) -> float:
    """Logistic curve on Indiana's net-proxy rank among all D1 teams
    (1 = best): 1 / (1 + e^((x-45)/8)) — 50% at rank 45, an ~8-rank-wide
    transition band around it."""
    return float(1.0 / (1.0 + np.exp((d1_net_rank - 45) / 8)))
