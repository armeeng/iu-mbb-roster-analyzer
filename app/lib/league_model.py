"""Builds a 2026-27 offense/defense proxy for any set of teams, so the
season simulator has an opponent for every one of IU's games — Big Ten and
non-conference alike.

Every team is projected from BartTorvik's RosterCast (their actual,
currently-known 2026-27 roster — returning players, transfers, and
recruits): _next_season_team_proxy for everyone else, weighted by
RosterCast's own projected Mins; _iu_roster_proxy_from_rostercast for
Indiana, weighted by the coach's live per-slot MPG instead, since that's
the one team this tool is actually built to let you reshape. Both pull
offense from RosterCast's Ortg and defense from the same last-season-
adj_drtg-or-D1-average lookup, so Indiana sits on the exact same rating
scale as every opponent — no more mixing in the EvanMiya-based OBPR/DBPR
formula in team_strength.py, which now only serves as a last-resort
fallback for any team (Indiana included) RosterCast has no data for.

Non-IU proxies are cached (RosterCast/last year's rosters don't change on
every interaction; only IU's roster does), so only IU's own proxy is
recomputed on every roster edit.
"""
import pandas as pd
import streamlit as st

from lib.data_loader import (
    load_d1_master, load_player_pool, load_rostercast_2627, load_rosters_2627, load_teams,
)
from lib.name_match import clean_name
from lib.position_groups import position_group
from lib.team_strength import BPR_BASELINE, net_proxy, team_offense_defense_proxy

MIN_GAMES_FOR_DRTG_AVG = 10  # same floor as percentile_engine's D1 comparison population
N_RANK_TIERS = 4  # quartiles of the reference population's RecruiT-Rank
MIN_BUCKET_SAMPLES = 15  # below this, a (position, tier) bucket collapses to position-only

B1G_TEAMS = [
    "Indiana Hoosiers", "Purdue Boilermakers", "Illinois Fighting Illini",
    "Iowa Hawkeyes", "Michigan Wolverines", "Michigan State Spartans",
    "Ohio State Buckeyes", "Penn State Nittany Lions", "Wisconsin Badgers",
    "Minnesota Golden Gophers", "Nebraska Cornhuskers", "Northwestern Wildcats",
    "Maryland Terrapins", "Rutgers Scarlet Knights", "UCLA Bruins",
    "USC Trojans", "Oregon Ducks", "Washington Huskies",
]


def _last_season_team_proxy(espn_team_name: str, d1_master_df: pd.DataFrame) -> tuple[float, float]:
    """Fallback only — used when RosterCast has no 2026-27 data for this
    team (see _next_season_team_proxy, which is tried first). 5x the
    MPG-weighted average OBPR/DBPR from every 2025-26 player who actually
    played for this team — real stats only, no placeholders needed. Same
    BPR-based formula as team_strength.team_offense_defense_proxy, so a
    team that falls back here still sits on the same rating scale as
    Indiana's live roster (though not the same scale as RosterCast-sourced
    teams — see _next_season_team_proxy's docstring)."""
    team_df = d1_master_df[d1_master_df["espn_team"] == espn_team_name]
    off_weight = off_value = def_weight = def_value = 0.0
    for _, row in team_df.iterrows():
        mpg = pd.to_numeric(row.get("mpg"), errors="coerce")
        obpr = pd.to_numeric(row.get("obpr"), errors="coerce")
        dbpr = pd.to_numeric(row.get("dbpr"), errors="coerce")
        if pd.isna(mpg) or mpg <= 0:
            continue
        weight = float(mpg)
        if pd.notna(obpr):
            off_weight += weight
            off_value += weight * float(obpr)
        if pd.notna(dbpr):
            def_weight += weight
            def_value += weight * float(dbpr)

    avg_obpr = (off_value / off_weight) if off_weight else 0.0
    avg_dbpr = (def_value / def_weight) if def_weight else 0.0
    offense_proxy = BPR_BASELINE + 5.0 * avg_obpr
    defense_proxy = BPR_BASELINE - 5.0 * avg_dbpr
    return offense_proxy, defense_proxy


@st.cache_data
def _espn_to_torvik_team() -> dict[str, str]:
    teams_df = load_teams()
    return dict(zip(teams_df["team_name"], teams_df["torvik_team"]))


@st.cache_data
def _last_year_drtg_by_clean_name() -> dict[str, float]:
    """Best last-season (2025-26) adj_drtg per player, keyed by
    clean_name(bt_player) — used to give RosterCast's 2026-27 players (who
    carry no defensive projection of their own) a real defensive number
    when they played D1 last season, regardless of which team, since
    transfers changed teams. Name collisions (~31 known across D1, per
    roster_state.py) are resolved by keeping the higher-games-played row —
    RosterCast gives no player ID to match on, and a bigger sample is the
    more likely real match."""
    d1 = load_d1_master()
    d1 = d1[d1["adj_drtg"].notna() & d1["bt_player"].notna()].copy()
    d1["_clean"] = d1["bt_player"].map(clean_name)
    d1["_games"] = pd.to_numeric(d1["games"], errors="coerce").fillna(0)
    d1 = d1.sort_values("_games", ascending=False).drop_duplicates("_clean", keep="first")
    return dict(zip(d1["_clean"], pd.to_numeric(d1["adj_drtg"], errors="coerce")))


@st.cache_data
def _d1_avg_adj_drtg() -> float:
    """Fallback defensive rating for RosterCast players with no matching
    last-season D1 record (true freshmen, JUCO/international transfers) —
    the mean adj_drtg among last season's real rotation players (>= 10
    games, same floor as percentile_engine's D1 comparison population)."""
    d1 = load_d1_master()
    games = pd.to_numeric(d1["games"], errors="coerce")
    pool = d1[games >= MIN_GAMES_FOR_DRTG_AVG]
    return float(pd.to_numeric(pool["adj_drtg"], errors="coerce").mean())


def _next_season_team_proxy(espn_team_name: str) -> tuple[float, float] | None:
    """2026-27 offense/defense proxy for one non-IU team, built from
    BartTorvik RosterCast's actual projected roster (data/rostercast_2627.
    csv): offense = minutes-weighted average of RosterCast's own projected
    Ortg (a real per-player 2026-27 offensive projection — returning
    production, transfer/level adjustment, and recruit-rank-based estimates
    for incoming freshmen, all computed by Torvik). RosterCast has no
    matching defensive projection, so defense = minutes-weighted average of
    each player's own last-season adj_drtg where they played D1 last year
    (_last_year_drtg_by_clean_name), else a same-position/similar-
    recruiting-rank peer average (_drtg_fallback_for) for true newcomers.

    Both are already absolute points-per-100-possessions numbers — unlike
    team_strength.py's EvanMiya-based obpr/dbpr, which are plus-minus deltas
    added to BPR_BASELINE — so no baseline transform is applied here, just
    the minutes-weighted average directly. Indiana's own live roster is
    scored the same way (see _iu_roster_proxy_from_rostercast), so every
    team in the model sits on this one scale now.

    Returns None if RosterCast has no rows for this team (scrape gap, or a
    team outside Torvik's tracked universe) so the caller can fall back to
    _last_season_team_proxy.
    """
    torvik_team = _espn_to_torvik_team().get(espn_team_name)
    if not torvik_team:
        return None
    rc = load_rostercast_2627()
    team_rows = rc[(rc["torvik_team"] == torvik_team) & rc["mins"].notna()]
    if team_rows.empty:
        return None

    drtg_by_name = _last_year_drtg_by_clean_name()

    off_weight = off_value = def_weight = def_value = 0.0
    for _, row in team_rows.iterrows():
        mins = pd.to_numeric(row.get("mins"), errors="coerce")
        if pd.isna(mins) or mins <= 0:
            continue

        ortg = pd.to_numeric(row.get("ortg"), errors="coerce")
        if pd.notna(ortg):
            off_weight += mins
            off_value += mins * float(ortg)

        player_name = row.get("player", "")
        drtg = drtg_by_name.get(clean_name(player_name))
        if drtg is None:
            drtg = _drtg_fallback_for(player_name)
        def_weight += mins
        def_value += mins * float(drtg)

    if off_weight == 0 or def_weight == 0:
        return None
    return (off_value / off_weight, def_value / def_weight)


@st.cache_data
def _rostercast_by_clean_name() -> pd.DataFrame:
    """RosterCast rows deduped to one per clean_name(player) — ties keep the
    row with the most projected minutes, the most likely real match absent
    any player ID from RosterCast. Shared base for the Ortg and
    recruit-rank lookups below."""
    rc = load_rostercast_2627().copy()
    rc["_clean"] = rc["player"].map(clean_name)
    rc["_mins"] = pd.to_numeric(rc["mins"], errors="coerce").fillna(0)
    return rc.sort_values("_mins", ascending=False).drop_duplicates("_clean", keep="first")


@st.cache_data
def _ortg_by_clean_name() -> dict[str, float]:
    """Best projected 2026-27 Ortg per player, keyed by clean_name(player),
    across every team's RosterCast page — not just Indiana's own — so a
    player swapped into an IU slot from anywhere in D1 (lib/roster_state.
    swap_slot) still carries a real projected offensive number."""
    rc = _rostercast_by_clean_name()
    rc = rc[rc["ortg"].notna()]
    return dict(zip(rc["_clean"], pd.to_numeric(rc["ortg"], errors="coerce")))


def rostercast_scoreable_names() -> set[str]:
    """The clean_name keys the season-sim proxy can score offense for — i.e.
    players with a usable projected RosterCast Ortg, read from the exact
    lookup _iu_roster_proxy_from_rostercast uses (_ortg_by_clean_name).
    Home.py gates the player dropdown on this set so every selectable player
    carries the projected Ortg the win-probability engine needs; anyone
    outside it would contribute zero offense weight to the IU proxy,
    silently distorting the season simulation. Defense needs no equivalent
    gate — _drtg_fallback_for always produces a number."""
    return set(_ortg_by_clean_name())


@st.cache_data
def _recruit_rank_by_clean_name() -> dict[str, float]:
    """Torvik's own RecruiT-Rank per player (~0-100+, roughly a percentile;
    0 or near-0 means unranked) — scraped from the title tooltip on every
    RosterCast player row (scrapers/build_rostercast_2627.py), for
    returning players, transfers, and true freshmen alike, so a reference
    player (matched to a real last-season adj_drtg) and an unmatched
    target player both read from the same rank scale."""
    rc = _rostercast_by_clean_name()
    rc = rc[rc["recruit_rank"].notna()]
    return dict(zip(rc["_clean"], pd.to_numeric(rc["recruit_rank"], errors="coerce")))


@st.cache_data
def _position_group_by_clean_name() -> dict[str, str]:
    """Best position-group guess per player, keyed by clean_name — used
    only to bucket the DRTG fallback (_drtg_fallback_for) by position.
    BartTorvik `role` (from a last-season d1_master row) is the precise
    source and wins on overlap; rosters_2627.csv's coarser ESPN position
    (G/F/C/PG/SG/SF/PF/ATH) fills in transfers/freshmen with no
    last-season row; recruit_config.py's hand-researched position_group
    fills in IU's own 4 HS/international recruits, who (as of this data's
    scrape) have no ESPN roster page yet and so aren't in rosters_2627.csv
    either — same gap noted in app/README.md. Same name-matching tradeoffs
    as every other lookup in this module — no player ID to key on, so
    collisions are possible but rare."""
    rosters = load_rosters_2627().copy()
    rosters["_clean"] = rosters["name"].map(clean_name)
    rosters["_pg"] = rosters["position"].map(lambda p: position_group(None, p))
    espn_map = {
        k: v for k, v in zip(rosters["_clean"], rosters["_pg"]) if k and pd.notna(v)
    }

    d1 = load_d1_master().copy()
    d1["_clean"] = d1["bt_player"].map(clean_name)
    d1["_pg"] = d1["role"].map(lambda r: position_group(r, None))
    role_map = {
        k: v for k, v in zip(d1["_clean"], d1["_pg"]) if k and pd.notna(v)
    }

    from lib.recruit_config import RECRUITS
    recruit_map = {
        clean_name(r["display_name"]): r["position_group"] for r in RECRUITS.values()
    }

    espn_map.update(role_map)  # role-based match is more precise, wins on overlap
    espn_map.update(recruit_map)  # hand-verified, wins over any name-match guess
    return espn_map


def _rank_tier(rank: float, cutoffs: list[float]) -> int:
    """0 = no recruiting profile (RecruiT-Rank == 0 — the large majority of
    walk-ons/unranked bench players; RecruiT-Rank is bimodal, not a smooth
    0-100 scale, so this needs its own bucket rather than folding into a
    plain quantile split). 1..len(cutoffs)+1 = evenly-sized tiers of the
    *ranked* (rank > 0) players only, lowest to highest."""
    if rank <= 0:
        return 0
    tier = 1
    for c in cutoffs:
        if rank > c:
            tier += 1
    return tier


@st.cache_data
def _drtg_fallback_tables() -> dict:
    """Builds the position + recruiting-rank DRTG fallback (_drtg_fallback_
    for): the reference population is every RosterCast player who (a) has a
    matched last-season adj_drtg (_last_year_drtg_by_clean_name) and (b) a
    resolvable position group — i.e. real, measured defenders, each already
    carrying their own RecruiT-Rank on the same scale a fallback target's
    rank will be read from. Rank is split into N_RANK_TIERS - 1 even tiers
    of the reference population's *ranked* (RecruiT-Rank > 0) players, plus
    a separate tier 0 for the unranked (see _rank_tier) — so tiers reflect
    the actual (bimodal) distribution rather than a guessed scale.

    Returns {'cutoffs': [...], 'bucket': {(pos,tier): avg_drtg},
    'position': {pos: avg_drtg}, 'overall': float}. A lookup tries
    'bucket' first, then 'position', then 'overall', backing off whenever a
    (position, tier) bucket has fewer than MIN_BUCKET_SAMPLES reference
    players to be meaningful — same no-fabricated-precision philosophy as
    percentile_engine.percentile_rank."""
    drtg_by_name = _last_year_drtg_by_clean_name()
    pos_by_name = _position_group_by_clean_name()
    rank_by_name = _recruit_rank_by_clean_name()
    overall = _d1_avg_adj_drtg()

    rows = [
        {"pos": pos_by_name[name], "rank": rank_by_name[name], "drtg": drtg}
        for name, drtg in drtg_by_name.items()
        if name in pos_by_name and name in rank_by_name
    ]
    ref = pd.DataFrame(rows)
    if ref.empty:
        return {"cutoffs": [], "bucket": {}, "position": {}, "overall": overall}

    ranked = ref[ref["rank"] > 0]
    n_ranked_tiers = N_RANK_TIERS - 1
    if not ranked.empty and n_ranked_tiers > 1:
        qs = [i / n_ranked_tiers for i in range(1, n_ranked_tiers)]
        cutoffs = [float(c) for c in ranked["rank"].quantile(qs)]
    else:
        cutoffs = []
    ref["tier"] = ref["rank"].map(lambda r: _rank_tier(r, cutoffs))

    position_avg = {pos: float(v) for pos, v in ref.groupby("pos")["drtg"].mean().items()}
    bucket_avg = {
        key: float(grp["drtg"].mean())
        for key, grp in ref.groupby(["pos", "tier"])
        if len(grp) >= MIN_BUCKET_SAMPLES
    }
    return {"cutoffs": cutoffs, "bucket": bucket_avg, "position": position_avg, "overall": overall}


def _drtg_fallback_for(player_name: str) -> float:
    """A player's DRTG fallback when they have no matched last-season
    adj_drtg: same-position, similar-recruiting-rank peers' average
    last-season adj_drtg (_drtg_fallback_tables), backing off to a
    position-only average and finally the flat D1 average if the specific
    bucket is too thin to trust."""
    tables = _drtg_fallback_tables()
    name = clean_name(player_name)
    pos = _position_group_by_clean_name().get(name)
    rank = _recruit_rank_by_clean_name().get(name)

    if pos is not None and rank is not None:
        tier = _rank_tier(rank, tables["cutoffs"])
        val = tables["bucket"].get((pos, tier))
        if val is not None:
            return val
    if pos is not None and pos in tables["position"]:
        return tables["position"][pos]
    return tables["overall"]


def _iu_roster_proxy_from_rostercast(roster) -> tuple[float, float] | None:
    """Indiana's live, coach-edited roster (lib/roster_state.RosterSlot
    list), rated on the exact same RosterCast-based scale as every other
    team (_next_season_team_proxy) rather than team_strength.py's EvanMiya
    OBPR/DBPR formula: offense = MPG-weighted average RosterCast Ortg
    (matched by name across all of RosterCast, so a player swapped in from
    another team still carries a real number); defense = MPG-weighted
    average of each player's last-season adj_drtg (matched by name) or a
    same-position/similar-recruiting-rank peer average for true newcomers —
    identical sourcing to every opponent's defense proxy. RosterCast's Ortg
    is already a 2026-27 projection, so no extra development-curve bump
    (team_strength.developed_obpr_dbpr) is applied here.

    Weighted by the coach's own slot.mpg, not RosterCast's own projected
    Mins — the whole point of this roster being "live" is that the coach's
    minutes allocation, not Torvik's, drives the proxy.

    Returns None (caller falls back to team_offense_defense_proxy) only if
    literally no slot's player matches anything in RosterCast — in
    practice the default roster is sourced straight from RosterCast's own
    Indiana page, so this is a safety net, not the expected path.
    """
    ortg_by_name = _ortg_by_clean_name()
    drtg_by_name = _last_year_drtg_by_clean_name()

    off_weight = off_value = def_weight = def_value = 0.0
    for slot in roster:
        if slot.mpg <= 0:
            continue
        name = clean_name(slot.name)

        ortg = ortg_by_name.get(name)
        if ortg is not None:
            off_weight += slot.mpg
            off_value += slot.mpg * float(ortg)

        drtg = drtg_by_name.get(name)
        if drtg is None:
            drtg = _drtg_fallback_for(slot.name)
        def_weight += slot.mpg
        def_value += slot.mpg * float(drtg)

    if off_weight == 0 or def_weight == 0:
        return None
    return (off_value / off_weight, def_value / def_weight)


@st.cache_data
def _cached_static_team_proxies(team_names: tuple[str, ...]) -> dict[str, tuple[float, float]]:
    """Proxies for every team EXCEPT Indiana (whose roster is live-edited
    and must never be cached). team_names is a tuple so it's hashable for
    st.cache_data. Prefers _next_season_team_proxy (RosterCast's actual
    2026-27 projected roster); falls back to _last_season_team_proxy (2025-
    26 actual roster replay) only for teams RosterCast has no data for."""
    d1_master_df = load_d1_master()
    proxies = {}
    for team in team_names:
        if team == "Indiana Hoosiers":
            continue
        proxies[team] = _next_season_team_proxy(team) or _last_season_team_proxy(team, d1_master_df)
    return proxies


def build_team_proxies(team_names: list[str], iu_roster) -> dict[str, tuple[float, float]]:
    """Proxies for an arbitrary list of teams (Big Ten + any non-conference
    opponents pulled from last season's real schedule). Indiana always uses
    the live coach roster (RosterCast-sourced, same as everyone else — see
    _iu_roster_proxy_from_rostercast); everyone else is cached."""
    static = _cached_static_team_proxies(tuple(sorted(set(team_names) - {"Indiana Hoosiers"})))
    proxies = dict(static)
    if "Indiana Hoosiers" in team_names:
        proxies["Indiana Hoosiers"] = (
            _iu_roster_proxy_from_rostercast(iu_roster)
            or team_offense_defense_proxy(iu_roster, load_player_pool())
        )
    return proxies


def build_all_b1g_team_proxies(iu_roster) -> dict[str, tuple[float, float]]:
    """Back-compat convenience wrapper: proxies for just the 18 B1G teams."""
    return build_team_proxies(B1G_TEAMS, iu_roster)


@st.cache_data
def _all_d1_team_names() -> tuple[str, ...]:
    d1_master_df = load_d1_master()
    return tuple(sorted(d1_master_df["espn_team"].dropna().unique()))


def compute_iu_d1_net_rank(iu_roster) -> int:
    """Indiana's net-proxy rank among all ~362 D1 teams (1 = best). Every
    team, Indiana included, is scored from BartTorvik RosterCast's 2026-27
    projected roster (see build_team_proxies) — same proxy source and
    rating scale across the board."""
    all_teams = _all_d1_team_names()
    proxies = build_team_proxies(list(all_teams), iu_roster)
    ranked = sorted(proxies.items(), key=lambda kv: net_proxy(*kv[1]), reverse=True)
    for rank, (team, _) in enumerate(ranked, start=1):
        if team == "Indiana Hoosiers":
            return rank
    return len(ranked)
