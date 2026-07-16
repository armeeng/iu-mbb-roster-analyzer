"""
Pull the 2026-27 D1 schedule from ESPN's scoreboard endpoint, day by day.

As of this script's last run (season SEASON below), ESPN had not yet posted
any 2026-27 games (checked Nov 2026 - Feb 2027 dates, all returned 0 events —
typical for July; non-con games trickle in over the summer and Big Ten
pairings/dates usually post later). Safe to re-run anytime — it skips dates
already present in games.csv for this season and only appends new rows.

Run:
  python scrapers/espn_games_and_teams.py
"""
import requests, pandas as pd, time
from datetime import date, timedelta, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ET = ZoneInfo("America/New_York")
SEASON = 2027   # the 2026-27 season

DATA = Path(__file__).parent.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"

games_out = DATA / "games.csv"
teams_out = DATA / "teams.csv"

existing_games = pd.read_csv(games_out, dtype=str) if games_out.exists() else pd.DataFrame(columns=["game_id", "game_date", "away_team_id", "home_team_id", "season"])
existing_teams = pd.read_csv(teams_out, dtype=str) if teams_out.exists() else pd.DataFrame(columns=["team_id", "team_name"])
if "season" not in existing_games.columns:
    existing_games["season"] = None

fetched_dates = set(existing_games.loc[existing_games["season"] == str(SEASON), "game_date"].unique())
seen_ids = set(existing_teams["team_id"].tolist())

game_rows, team_rows = [], []
d = date(2026, 11, 1)
while d <= date(2027, 4, 15):
    dstr = d.strftime("%Y%m%d")
    if d.strftime("%Y-%m-%d") not in fetched_dates:
        r = requests.get(URL, params={"dates": dstr, "limit": 200, "groups": 50}, timeout=15).json()
        for ev in r.get("events", []):
            comp = ev["competitions"][0]
            sides = {c["homeAway"]: c["team"]["id"] for c in comp["competitors"]}
            utc_dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            game_date = utc_dt.astimezone(ET).strftime("%Y-%m-%d")
            game_rows.append({"game_id": ev["id"], "game_date": game_date,
                              "away_team_id": sides.get("away"), "home_team_id": sides.get("home"),
                              "season": SEASON})
            for c in comp["competitors"]:
                team = c["team"]
                if team["id"] not in seen_ids:
                    team_rows.append({"team_id": team["id"], "team_name": team["displayName"]})
                    seen_ids.add(team["id"])
        time.sleep(0.2)
    d += timedelta(days=1)

pd.concat([existing_games, pd.DataFrame(game_rows)]).drop_duplicates("game_id", keep="last").to_csv(games_out, index=False)
pd.concat([existing_teams, pd.DataFrame(team_rows)]).drop_duplicates("team_id", keep="last").to_csv(teams_out, index=False)
print(f"Saved {len(existing_games) + len(game_rows)} games ({len(game_rows)} new for {SEASON}), {len(seen_ids)} teams")
