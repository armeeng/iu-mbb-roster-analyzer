"""
Append season-2027 rows to players.csv from rosters_2627.csv.

torvik_name/torvik_height/torvik_team stay blank for season 2027 rows unless
a player already has a season-2026 mapping row with the same espn_player_id
(returning players and transfers keep their ESPN ID) — in that case we carry
the torvik_name forward, since BartTorvik has no 2026-27 data until the
season starts (~November) and can't be matched yet.

Run:
  python scrapers/build_players_2627.py
"""
import re
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
PLAYERS_CSV = DATA / "players.csv"
ROSTERS_CSV = DATA / "rosters_2627.csv"

SEASON = 2027

players = pd.read_csv(PLAYERS_CSV, dtype=str)
rosters = pd.read_csv(ROSTERS_CSV, dtype={"espn_player_id": str, "team_id": str})

prior = players[players["season"] == "2026"].set_index("espn_player_id")


def conv_height(h):
    """'6' 10\"' -> '6-10'; already-clean '6-10' passes through."""
    if pd.isna(h) or not str(h).strip():
        return None
    m = re.match(r"(\d+)'\s*(\d+)", str(h))
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return str(h) if "-" in str(h) else None


# A handful of transfers still show up on their OLD team's ESPN roster page
# (ESPN hasn't removed them yet) as well as the portal-commitment row for
# their NEW team. Prefer the portal-commitment row — it reflects where the
# player is actually headed for 2026-27 — over a stale espn_roster listing.
SOURCE_PRIORITY = {"portal_commitment_pending_espn": 0, "espn_roster": 1}
rosters = rosters.assign(_prio=rosters["source"].map(SOURCE_PRIORITY).fillna(9))
rosters = rosters.sort_values("_prio")

rows = []
seen = set()
for _, r in rosters.iterrows():
    pid = str(r["espn_player_id"]) if pd.notna(r["espn_player_id"]) else None
    if not pid or pid in seen:
        continue
    seen.add(pid)
    carried_torvik_name = prior.loc[pid, "torvik_name"] if pid in prior.index else None
    rows.append({
        "espn_player_id": pid,
        "season": str(SEASON),
        "espn_name": r["name"],
        "espn_height": conv_height(r.get("height_display")),
        "espn_weight": r.get("weight_lbs"),
        "espn_team": r["espn_team"],
        "torvik_name": carried_torvik_name,
        "torvik_height": None,
        "torvik_team": None,
    })

new_df = pd.DataFrame(rows, columns=players.columns)
combined = pd.concat([players, new_df], ignore_index=True)
combined = combined.drop_duplicates(subset=["espn_player_id", "season"], keep="last")
combined.to_csv(PLAYERS_CSV, index=False)

n_carried = new_df["torvik_name"].notna().sum()
print(f"[PLAYERS] Added {len(new_df)} season-{SEASON} rows "
      f"({n_carried} with a carried-forward torvik_name from 2026, "
      f"{len(new_df) - n_carried} freshmen/new — torvik_name blank until BartTorvik publishes {SEASON}).")
print(f"[PLAYERS] players.csv now has {len(combined)} total rows.")

iu = combined[(combined["season"] == str(SEASON)) & (combined["espn_team"] == "Indiana Hoosiers")]
print(f"\n[CHECK] Indiana Hoosiers {SEASON} rows: {len(iu)}")
print(iu[["espn_name", "torvik_name"]].to_string(index=False))
