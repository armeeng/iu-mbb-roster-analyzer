"""HS/international recruit data — gathered via web research (sources cited
inline), plus a hardcoded ESTIMATED debut-year per-40 stat line for each.

None of these 4 players have a row in d1_master_2026.csv (no D1 stats
exist), so `recruit_as_pool_row()` fabricates one, in the same schema as a
real d1_master row, so the rest of the app (percentile breakdown, league
model, win-probability engine) can treat every player — real or recruit —
identically, with no special-casing.

The stat lines are NOT derived from real games. They're rough freshman-year
archetypes informed by recruiting tier and position (a 4-star wing shooter
projects differently than a raw international project center) — a
judgment call, not a measurement. Every recruit row carries `is_estimate:
True` so the UI can flag it as such wherever it appears, rather than
presenting it as verified production.
"""

RECRUITS: dict[str, dict] = {
    "moody": {
        "display_name": "Prince-Alexander Moody",
        "position_group": "Combo",
        "role": "Combo G",
        "height": "6'4\"",
        "height_in": 76,
        "weight": 185,
        "rank_247": 107,
        "rank_rivals": 132,
        "stars": 4,
        "hs_school": "Bishop McNamara HS (MD)",
        "recruiting_lines": [
            "2025 EYBL (Team Takeover): 14.3 ppg, 3.1 rpg, 1.8 apg",
            "HS career: 1,075 points, 119 made 3-pointers across 85 games",
        ],
        "sources": ["247Sports Composite", "Rivals"],
        "stats": {
            "pts_40": 13.5, "reb_40": 3.5, "ast_40": 2.8, "stl_40": 1.1,
            "blk_40": 0.2, "tov_40": 2.3, "efg_pct": 48.0, "three_pct": 32.0,
            "ft_pct": 75.0, "usg_pct": 19.0, "ortg": 101.0, "adj_drtg": 104.0,
            "bpr": 0.3,
        },
    },
    "karvala": {
        "display_name": "Vaughn Karvala",
        "position_group": "Wing",
        "role": "Wing G",
        "height": "6'7\"",
        "height_in": 79,
        "weight": 190,
        "rank_247": 47,
        "stars": 4,
        "hs_school": "Bella Vista Prep (AZ)",
        "recruiting_lines": [
            "Junior year: 26.5 ppg, 9.5 rpg, 3.8 apg, 1.6 spg, 53.5% FG, 41.9% 3PT",
            "2025 EYBL (Team HERRO): 14.7 ppg, 4.3 rpg, 34.3% 3PT",
        ],
        "sources": ["247Sports Composite"],
        "stats": {
            "pts_40": 15.5, "reb_40": 5.8, "ast_40": 2.0, "stl_40": 1.3,
            "blk_40": 0.5, "tov_40": 2.0, "efg_pct": 52.0, "three_pct": 36.0,
            "ft_pct": 76.0, "usg_pct": 21.0, "ortg": 107.0, "adj_drtg": 101.0,
            "bpr": 1.5,
        },
    },
    "manhertz": {
        "display_name": "Trevor Manhertz",
        "position_group": "PF",
        "role": "Stretch 4",
        "height": "6'8\"",
        "height_in": 80,
        "weight": 185,
        "rank_247": 52,
        "stars": 4,
        "hs_school": "Christ School (NC)",
        "recruiting_lines": [
            "EYBL Scholastic League senior year: 18.8 ppg (4th in league)",
            "Led league in made 3-pointers (3.8/g), 42% 3PT",
        ],
        "sources": ["247Sports Composite (ranked 15th-best SF nationally)"],
        "stats": {
            "pts_40": 14.0, "reb_40": 6.8, "ast_40": 1.4, "stl_40": 0.9,
            "blk_40": 0.9, "tov_40": 1.7, "efg_pct": 54.0, "three_pct": 38.0,
            "ft_pct": 78.0, "usg_pct": 18.0, "ortg": 106.0, "adj_drtg": 100.0,
            "bpr": 1.2,
        },
    },
    "sokolov": {
        "display_name": "Clemens Sokolov",
        "position_group": "C",
        "role": "C",
        "height": "7'0\"",
        "height_in": 84,
        "weight": None,
        "rank_247": None,
        "stars": None,
        "international": True,
        "hs_school": None,
        "recruiting_lines": [
            "Würzburg ProB (Germany, 3rd tier men's pro league): 6.4 ppg, 5.0 rpg",
            "FIBA U17 / U18 national team experience (Germany)",
            "Scouted as a long-term development backup center",
        ],
        "sources": ["Würzburg ProB box scores", "FIBA event rosters"],
        "wide_uncertainty": True,  # no composite recruiting rank to anchor on
        "stats": {
            "pts_40": 9.0, "reb_40": 7.5, "ast_40": 0.6, "stl_40": 0.3,
            "blk_40": 1.6, "tov_40": 1.9, "efg_pct": 52.0, "three_pct": None,
            "ft_pct": 62.0, "usg_pct": 14.0, "ortg": 97.0, "adj_drtg": 106.0,
            "bpr": -1.0,
        },
    },
}


def recruit_as_pool_row(recruit_key: str) -> dict:
    """A dict in d1_master's schema, so this recruit can be treated exactly
    like a real player everywhere else in the app (aggregation, percentile
    breakdown, league model). espn_team is fixed to Indiana Hoosiers since
    these 4 only ever play for IU in this tool."""
    r = RECRUITS[recruit_key]
    row = {
        "espn_id": f"recruit_{recruit_key}",
        "espn_name": r["display_name"],
        "espn_team": "Indiana Hoosiers",
        "conf": "B10",
        "role": r["role"],
        "class_year": "Fr",
        "class_year_num": 1,
        "height_in": r["height_in"],
        "height_display": r["height"],
        "games": 0,
        "mpg": 0.0,
        "is_estimate": True,
    }
    row.update(r["stats"])
    if "bpr" in row and "obpr" not in row:
        # No real OBPR/DBPR split exists for a player with zero college
        # possessions — split the hardcoded overall bpr evenly. The win-prob
        # engine only ever uses their difference (net_proxy), which comes
        # out identical either way, so this even split costs nothing.
        row["obpr"] = row["bpr"] / 2
        row["dbpr"] = row["bpr"] / 2
    return row


def is_wide_uncertainty(recruit_key: str) -> bool:
    """True for recruits with no composite recruiting rank to anchor on."""
    return RECRUITS[recruit_key].get("wide_uncertainty", False)
