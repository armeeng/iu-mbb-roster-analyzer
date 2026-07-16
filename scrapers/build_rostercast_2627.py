"""
Build 2026-27 opponent-strength inputs from BartTorvik's RosterCast
(https://barttorvik.com/rostercast.php) — per-player projected minutes,
offensive rating (Ortg), usage%, and recruiting rank for every team's
incoming 2026-27 roster: returning players, transfers (re-rated on their
new team's context), and recruits (rank-projected), all as Torvik has them
today.

Every player row's "Yr" cell carries a `title="RecruiT-Rank: N"` tooltip —
Torvik's own composite recruiting/portal-value score (~0-100+, roughly a
percentile; 0 or near-0 means unranked) — for returning players, transfers,
and true freshmen alike. league_model.py uses it to fall back a player's
defensive rating to same-position/similar-recruiting-rank peers instead of
a flat D1 average when that player has no matched last-season adj_drtg.

RosterCast has no per-player defensive projection of its own (Torvik's Adj.
DE is team-level only) — league_model.py fills that gap itself at read time
(last season's adj_drtg from d1_master_2026.csv, matched by name), so this
scraper only needs to capture what RosterCast actually shows.

The site gates first-time visitors behind a JS "verifying browser" page that
auto-submits a hidden form; POSTing that form once and keeping the session
cookie is enough to fetch every team afterward (verified manually).

Run:
  python scrapers/build_rostercast_2627.py
"""
import re
import time
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).parent.parent / "data"
TEAMS_CSV = DATA / "teams.csv"
OUT_CSV = DATA / "rostercast_2627.csv"

BASE_URL = "https://barttorvik.com/rostercast.php"
YEAR = "2027"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQUEST_DELAY_SEC = 0.3

TABLE_RE = re.compile(r'<table\s+id="tblData".*?</table>', re.S)
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"(<t[dh][^>]*>)(.*?)</t[dh]>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
RECRUIT_RANK_RE = re.compile(r"RecruiT-Rank:\s*([\d.]+)")


def _cells(row_html: str) -> tuple[list[str], float | None]:
    """Cell texts, plus the RecruiT-Rank value pulled from the 2nd cell's
    (Yr) title attribute, if present."""
    matches = CELL_RE.findall(row_html)
    texts = [TAG_RE.sub("", inner).strip() for _, inner in matches]
    recruit_rank = None
    if len(matches) >= 2:
        m = RECRUIT_RANK_RE.search(matches[1][0])
        if m:
            recruit_rank = float(m.group(1))
    return texts, recruit_rank


def _bypass_bot_check(session: requests.Session) -> None:
    session.get(BASE_URL, timeout=15)
    session.post(BASE_URL, data={"js_test_submitted": "1"}, timeout=15)


def fetch_team(session: requests.Session, torvik_team: str) -> list[dict]:
    """One team's RosterCast rows. `in_rotation=True` rows have Torvik's
    projected Mins/Ortg/Usage; the "Others in system" players below them
    (walk-ons, deep bench, unresolved depth chart) get only Yr/Ht — they're
    kept (in_rotation=False) for completeness but carry no minutes weight
    downstream since RosterCast itself gives them none."""
    resp = session.get(BASE_URL, params={"year": YEAR, "team": torvik_team}, timeout=20)
    resp.raise_for_status()
    m = TABLE_RE.search(resp.text)
    if not m:
        return []

    rows = ROW_RE.findall(m.group(0))[1:]  # skip header row
    out = []
    in_rotation = True
    for row_html in rows:
        cells, recruit_rank = _cells(row_html)
        if not cells or not cells[0]:
            continue
        if cells[0].startswith("Others in system"):
            in_rotation = False
            continue
        if cells[0].startswith("Please report"):
            break

        player, yr, ht = cells[0], cells[1], cells[2]
        mins = ortg = usage = None
        if in_rotation and len(cells) >= 6:
            mins, ortg, usage = cells[3] or None, cells[4] or None, cells[5] or None
        out.append({
            "torvik_team": torvik_team,
            "player": player,
            "yr": yr,
            "height_display": ht,
            "mins": mins,
            "ortg": ortg,
            "usage_pct": usage,
            "recruit_rank": recruit_rank,
            "in_rotation": in_rotation,
        })
    return out


def main():
    teams_df = pd.read_csv(TEAMS_CSV, dtype=str)
    torvik_teams = sorted(teams_df["torvik_team"].dropna().unique())
    print(f"[ROSTERCAST] Scraping {len(torvik_teams)} teams for {YEAR} from {BASE_URL}...")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    _bypass_bot_check(session)

    rows = []
    failed = []
    for i, team in enumerate(torvik_teams, start=1):
        try:
            team_rows = fetch_team(session, team)
            if not team_rows:
                failed.append(team)
            rows.extend(team_rows)
        except Exception as e:
            print(f"  [WARN] {team}: {e}")
            failed.append(team)
        if i % 50 == 0:
            print(f"  ...{i}/{len(torvik_teams)} teams")
        time.sleep(REQUEST_DELAY_SEC)

    out_df = pd.DataFrame(rows, columns=[
        "torvik_team", "player", "yr", "height_display",
        "mins", "ortg", "usage_pct", "recruit_rank", "in_rotation",
    ])
    out_df.to_csv(OUT_CSV, index=False)
    print(f"[ROSTERCAST] Wrote {len(out_df)} rows, {out_df['torvik_team'].nunique()} teams -> {OUT_CSV}")
    if failed:
        preview = failed[:20]
        more = "..." if len(failed) > 20 else ""
        print(f"[ROSTERCAST] {len(failed)} teams returned no data (site gap or scrape miss): {preview}{more}")


if __name__ == "__main__":
    main()
