# IU MBB

Deliverables for Ryan Carr (Indiana MBB), built from copies of the OSUPortal
and Illinois MBB projects. Neither source project was modified — everything
here is a copy or net-new file.

## Deliverable 1 — 2026 Transfer Portal Production Report by Position

`deck/build_position_deck.py` → `output/iu_portal_report_by_position.pptx` / `.pdf`

Top 15 Guards / Wings / Bigs from the 2025-26 portal class, ranked by 2025-26
BPR (no projections). Built from `data/d1_master_2026.csv` (copied from
OSUPortal, unmodified upstream). IU crimson branding. 55 slides.

Rerun: `python deck/build_position_deck.py` (uses OSUPortal's venv for
`python-pptx`/`pandas`/`numpy`/`requests` — no local install needed if that
venv still exists at `../OSUPortal/venv`).

## Deliverable 2 — data for the IU roster analyzer (data only; app not built yet)

All scraped/assembled 2026-07-13.

| File | Contents | Status |
|---|---|---|
| `data/games.csv` | 2025-26 schedule (6,318 games, complete) + `season` column. 2026-27: **0 games** — confirmed via direct ESPN scoreboard checks (Nov 2026 – Feb 2027, all dates), not yet posted anywhere. Normal for July; rerun `scrapers/espn_games_and_teams.py` periodically as the slate fills in (it only fetches dates not already cached). |
| `data/teams.csv` | ESPN↔Torvik team mapping, 728 rows. Diffed against ESPN's live D1 (groups=50) list of 362 current teams — **zero new/missing teams**, no realignment changes needed. |
| `data/rosters_2627.csv` | 2026-27 rosters, 12,542 rows, 739 teams. Two sources merged: ESPN team pages (`source=espn_roster`) + transfer-portal commitments from `d1_master_2026.csv`'s `bt_to_team` not yet reflected on ESPN (`source=portal_commitment_pending_espn`). **Important:** ESPN's roster pages lag transfers — 6 of IU's incoming transfers (Burton, Sherrell, Harris, Mustaf, Yigitoglu, Lindsay) still show on their old schools' ESPN pages as of this scrape; the portal-commitment merge is what surfaces them under Indiana. Rerun `scrapers/build_rosters_2627.py` periodically — ESPN pages will catch up over the summer. 11 portal rows have no `team_id` because their destination is a non-D1 program (D2/JUCO) not in `teams.csv` — expected, not an error. |
| `data/players.csv` | ESPN↔Torvik player ID/name mapping, now 24,453 rows (12,324 season-2026 + 12,129 season-2027). Season-2027 `torvik_name` is carried forward from 2026 only where a player already had one — BartTorvik has zero 2026-27 data until the season starts (~November); rerun `scrapers/build_players_2627.py` after that to backfill the rest via a fresh Torvik scrape. Carry-forward rate is 48.0%, matching the 46.6% baseline match rate already in the season-2026 data (not a regression — Torvik matching is sparse for low-minute players in the source data). |
| `data/stats.csv` | 2025-26 daily per-player stats, byte-identical copy of `Illinois MBB/data/stats.csv` (checksum-verified). Nothing to update — season is final. 2026-27 stats can't exist until games are played; `scrapers/torvik_stats.py` (copied, unmodified) is the tool to resume daily pulls once the season starts. |
| `data/rostercast_2627.csv` | BartTorvik RosterCast's projected 2026-27 roster for every D1 team (`rostercast.php`) — per-player projected minutes, Ortg, usage%, and RecruiT-Rank (Torvik's own recruiting/portal-value score, scraped from a tooltip on each player row). Used by `app/lib/league_model.py` to build every team's (Indiana included) 2026-27 offense/defense proxy for the Season Projection tab, instead of replaying last season's actual roster. RosterCast has no per-player defensive projection; the app fills that in itself — last season's `adj_drtg` from `d1_master_2026.csv` (matched by name), else the average `adj_drtg` of last season's D1 players sharing the same position and a similar RecruiT-Rank tier, else the flat D1 average as a last resort. Rerun `scrapers/build_rostercast_2627.py` periodically as transfers/recruits settle. |

**Known name-quality issue inherited from source data:** `players.csv` maps
Indiana's Jordan Rayford to torvik_name "Jordan Watford" — a pre-existing
fuzzy-match error in the original `Illinois MBB/data/players.csv`, not
introduced here. Worth a manual fix if this player matters for the analyzer
(search/replace his `torvik_name` once you know the correct Torvik record).

### Scrapers (`scrapers/`)

- `build_rosters_2627.py` — builds `rosters_2627.csv` (see above). Caches the
  raw ESPN pull to `data/_espn_roster_cache.csv` when run with
  `--skip-espn-fetch` against an existing cache (delete the cache to force a
  full re-pull).
- `build_players_2627.py` — builds the season-2027 rows in `players.csv` from
  `rosters_2627.csv`.
- `espn_games_and_teams.py` — 2026-27 schedule puller (season hardcoded to
  2027, date range Nov 2026–Apr 2027). Safe to rerun; only fetches new dates.
- `espn_players.py`, `torvik_teams.py`, `torvik_stats.py` — copied unmodified
  from Illinois MBB for later use (Torvik backfill once the 2026-27 season
  starts publishing data, ~November).
- `build_rostercast_2627.py` — builds `rostercast_2627.csv` (see above) by
  scraping `barttorvik.com/rostercast.php` for all ~365 D1 teams, including
  each player's RecruiT-Rank (pulled from a `title` attribute, not visible
  table text). Handles the site's JS "verifying browser" bot check (a
  one-time form POST). Safe to rerun as often as needed.

### Suggested next re-run cadence

- Weekly through August/September: `build_rosters_2627.py` (ESPN pages catch
  up on transfers) and `espn_games_and_teams.py` (non-con schedule fills in).
- Late summer: re-check `espn_games_and_teams.py` once Big Ten releases
  conference pairings/dates.
- November (season start): `torvik_teams.py` + `torvik_stats.py` to begin
  pulling 2026-27 Torvik data, then rerun `build_players_2627.py` to backfill
  `torvik_name`/`torvik_height`/`torvik_team` for the season-2027 rows.
