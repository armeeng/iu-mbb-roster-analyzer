"""
Build 2026-27 D1 rosters (rosters_2627.csv).

Two sources, combined:
  1. ESPN team roster pages — current as of scrape date. As of July 2026 these
     mostly reflect returning players + signed HS recruits; transfer-portal
     commitments often lag behind on ESPN's roster pages.
  2. Portal commitments from data/d1_master_2026.csv (bt_to_team) — fills the
     gap for players ESPN hasn't posted to their new team yet.

Run:
  python scrapers/build_rosters_2627.py
"""
import requests, pandas as pd, time, sys
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
TEAMS_CSV  = DATA / "teams.csv"
MASTER_CSV = DATA / "d1_master_2026.csv"
OUT_CSV    = DATA / "rosters_2627.csv"
ESPN_CACHE = DATA / "_espn_roster_cache.csv"

ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{tid}/roster"

teams_df = pd.read_csv(TEAMS_CSV, dtype=str)
team_id_to_name = dict(zip(teams_df["team_id"], teams_df["team_name"]))

COLS = ["espn_player_id", "team_id", "espn_team", "name", "position",
        "class_year", "height_display", "weight_lbs", "source"]

if "--skip-espn-fetch" in sys.argv and ESPN_CACHE.exists():
    espn_df = pd.read_csv(ESPN_CACHE, dtype={"espn_player_id": str, "team_id": str})
    print(f"[ROSTERS] Using cached ESPN roster pull: {len(espn_df)} rows")
else:
    rows = []
    n_teams = len(teams_df)
    print(f"[ROSTERS] Pulling ESPN rosters for {n_teams} teams...")
    for i, (tid, team_name) in enumerate(team_id_to_name.items(), start=1):
        try:
            r = requests.get(ROSTER_URL.format(tid=tid), timeout=15)
            athletes = r.json().get("athletes", []) if r.ok else []
        except Exception as e:
            print(f"  [WARN] {team_name} ({tid}): {e}")
            athletes = []
        for a in athletes:
            pos = (a.get("position") or {}).get("abbreviation", "")
            exp = (a.get("experience") or {}).get("displayValue", "")
            rows.append({
                "espn_player_id": a["id"],
                "team_id": tid,
                "espn_team": team_name,
                "name": a.get("displayName", ""),
                "position": pos,
                "class_year": exp,
                "height_display": a.get("displayHeight", ""),
                "weight_lbs": a.get("weight"),
                "source": "espn_roster",
            })
        if i % 100 == 0:
            print(f"  ...{i}/{n_teams} teams")
        time.sleep(0.08)

    espn_df = pd.DataFrame(rows, columns=COLS)
    espn_df.to_csv(ESPN_CACHE, index=False)
    print(f"[ROSTERS] ESPN roster rows: {len(espn_df)}")

# ── Fill gaps with portal commitments not yet reflected on ESPN team pages ────
master = pd.read_csv(MASTER_CSV, dtype={"espn_id": str})
committed = master[
    master["in_portal"].eq(True) &
    master["bt_to_team"].notna() &
    (master["bt_to_team"].astype(str).str.strip() != "")
].copy()
print(f"[ROSTERS] Portal commitments in master data: {len(committed)}")

espn_by_team = {
    team: set(g["name"].str.lower().str.strip())
    for team, g in espn_df.groupby("espn_team")
}
# bt_to_team is the BartTorvik short team name (e.g. "Indiana") — match it
# exactly against teams.csv's torvik_team column, not by substring on the
# full ESPN display name (a substring match on "Indiana" wrongly hits
# "IU Indianapolis Jaguars").
torvik_to_espn_name = dict(zip(teams_df["torvik_team"].str.lower().str.strip(),
                                teams_df["team_name"]))
torvik_to_team_id = dict(zip(teams_df["torvik_team"].str.lower().str.strip(),
                              teams_df["team_id"]))

added = 0
extra_rows = []
for _, prow in committed.iterrows():
    dest_team = str(prow["bt_to_team"]).strip()
    name = str(prow["espn_name"]).strip()
    dest_key = dest_team.lower()
    matched_team = torvik_to_espn_name.get(dest_key)
    already_on_espn = matched_team and name.lower() in espn_by_team.get(matched_team, set())
    if already_on_espn:
        continue
    extra_rows.append({
        "espn_player_id": prow.get("espn_id"),
        "team_id": torvik_to_team_id.get(dest_key),
        "espn_team": matched_team or dest_team,
        "name": name,
        "position": prow.get("pos_abbr") or prow.get("role"),
        "class_year": prow.get("class_year"),
        "height_display": prow.get("height_display"),
        "weight_lbs": prow.get("weight_lbs"),
        "source": "portal_commitment_pending_espn",
    })
    added += 1

print(f"[ROSTERS] Portal commitments added (not yet on ESPN page): {added}")

full_df = pd.concat([espn_df, pd.DataFrame(extra_rows, columns=COLS)], ignore_index=True)
full_df = full_df.drop_duplicates(subset=["espn_player_id", "espn_team"], keep="first")
full_df.to_csv(OUT_CSV, index=False)
print(f"\n✅  Saved → {OUT_CSV}  ({len(full_df)} rows, {full_df['espn_team'].nunique()} teams)")

iu_check = full_df[full_df["espn_team"].str.contains("Indiana Hoosiers", na=False)]
print(f"\n[CHECK] Indiana Hoosiers roster rows: {len(iu_check)}")
print(iu_check[["name", "position", "class_year", "source"]].to_string(index=False))
