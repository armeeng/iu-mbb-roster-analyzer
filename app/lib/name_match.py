"""Player name-matching between rosters_2627.csv and d1_master_2026.csv.

`clean_name` is ported verbatim from OSUPortal/analysis/portal_ranker.py
(a 5-line pure function, no BPR coupling — safe to copy). The rest is new,
reimplementing the *logic shape* of OSUPortal/models/projections.py's
`_find_player` (first-initial+last-name fallback) without importing that
module, which pulls in BPR/dev-curve constants that are out of scope here.
"""
import pandas as pd

_SUFFIXES = {"jr.", "sr.", "ii", "iii", "iv", "v", "jr", "sr"}


def clean_name(name: str) -> str:
    parts = str(name).lower().strip().split()
    while parts and parts[-1] in _SUFFIXES:
        parts = parts[:-1]
    return " ".join(parts)


def find_in_d1_master(
    espn_player_id: str | None, name: str, d1_master_df: pd.DataFrame
) -> pd.Series | None:
    """Try, in order: (1) exact espn_id match, (2) clean-name exact match,
    (3) first-initial + last-name match, only if exactly one candidate."""
    if espn_player_id and str(espn_player_id) not in ("nan", "None", ""):
        hit = d1_master_df[d1_master_df["espn_id"] == str(espn_player_id)]
        if len(hit) == 1:
            return hit.iloc[0]

    target = clean_name(name)
    if not target:
        return None

    cleaned = d1_master_df["espn_name"].map(clean_name)
    hit = d1_master_df[cleaned == target]
    if len(hit) == 1:
        return hit.iloc[0]
    if len(hit) > 1:
        return hit.iloc[0]  # ambiguous but same cleaned name — take first, good enough

    target_parts = target.split()
    if len(target_parts) >= 2:
        first_initial, last = target_parts[0][0], target_parts[-1]
        candidates = d1_master_df[
            cleaned.str.split().map(
                lambda p: bool(p) and len(p) >= 2 and p[0][0] == first_initial and p[-1] == last
            )
        ]
        if len(candidates) == 1:
            return candidates.iloc[0]

    return None


def build_team_roster_rows(
    espn_team_name: str, rosters_df: pd.DataFrame, d1_master_df: pd.DataFrame
) -> pd.DataFrame:
    """All rosters_2627 rows for one team, left-joined to d1_master.
    Adds a `matched` bool column; unmatched rows are true freshmen/
    internationals with no current-season D1 stats (routed to
    league_model.py's flat placeholder)."""
    team_rows = rosters_df[rosters_df["espn_team"] == espn_team_name]
    out = []
    for _, r in team_rows.iterrows():
        match = find_in_d1_master(r.get("espn_player_id"), r.get("name", ""), d1_master_df)
        out.append({
            "name": r.get("name"),
            "espn_player_id": r.get("espn_player_id"),
            "roster_position": r.get("position"),
            "matched": match is not None,
            "d1_row": match,
        })
    return pd.DataFrame(out)
