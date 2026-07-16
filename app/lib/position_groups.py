"""Position-group mapping: PG / Combo / Wing / PF / C (Coach DeVries' scheme).

Single source of truth — used by the breakdown's positional table, the
roster editor's position-scoped swap dropdown, and league_model.py when
building every other Big Ten team's roster.
"""

POSITION_GROUPS = ["PG", "Combo", "Wing", "PF", "C"]

# BartTorvik `role` (as it appears in d1_master_2026.csv) -> position group.
# Stretch 4 and PF/C both map to "PF" — matches how Ryan Carr himself labeled
# Sherrell (PF/C -> PF) and Sisley (Stretch 4 -> PF) in his roster email.
ROLE_TO_POSGROUP: dict[str, str] = {
    "pure pg": "PG",
    "scoring pg": "PG",
    "combo g": "Combo",
    "wing g": "Wing",
    "wing f": "Wing",
    "stretch 4": "PF",
    "pf/c": "PF",
    "c": "C",
}

# Coarse fallback for rosters_2627.csv rows with no d1_master match (true
# freshmen/internationals on OTHER Big Ten teams) — rosters_2627's `position`
# column is ESPN's coarse G/F/C/PG/SG/SF/PF/ATH, not BartTorvik's finer role.
ESPN_POS_TO_POSGROUP: dict[str, str] = {
    "pg": "PG",
    "sg": "Combo",
    "g": "Combo",
    "sf": "Wing",
    "ath": "Wing",
    "f": "PF",
    "pf": "PF",
    "c": "C",
}


def position_group(role: str | None, espn_position: str | None = None) -> str | None:
    """BartTorvik `role` takes priority; falls back to ESPN's coarser
    position label only when `role` is unavailable (no d1_master row)."""
    if role and str(role).strip().lower() not in ("nan", "", "none"):
        pg = ROLE_TO_POSGROUP.get(str(role).strip().lower())
        if pg:
            return pg
    if espn_position and str(espn_position).strip().lower() not in ("nan", "", "none"):
        return ESPN_POS_TO_POSGROUP.get(str(espn_position).strip().lower())
    return None
