# IU Roster Analyzer

A dashboard for building a hypothetical 2026-27 Indiana roster and seeing:
where the team is above/below average (real box-score stats, not a composite
rating), an AI-generated breakdown, projected record / Big Ten standings /
NCAA tournament odds, and how it all changes when you swap players or adjust
minutes.

## Running it

```bash
cd "IU MBB/app"
../.venv/bin/python3 -m streamlit run Home.py
```

**Do not `source ../.venv/bin/activate`.** The project folder's parent
directory has a literal colon in its name (`Illinois:OSU:IU`), and colon is
the shell's PATH separator — activating splits `$VIRTUAL_ENV` apart and
corrupts your PATH, so `pip`, `python`, even the shell's own builtins can
stop resolving. You'll see the venv name in your prompt but `streamlit: command
not found`. If this already happened, run `deactivate` or open a fresh
terminal, then use the direct-path form above — never activate, just call
`../.venv/bin/python3` (or `../.venv/bin/pip`) directly for anything in this
project (installs included: `../.venv/bin/python3 -m pip install ...`).

Open http://localhost:8501 in a browser.

## Enabling the AI Breakdown tab

Without an API key, that tab shows the assembled prompt for manual
copy-paste into Claude or ChatGPT. To enable live calls:

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
2. Add a real `ANTHROPIC_API_KEY`
3. Restart the app

## What's synthetic / a placeholder (read before presenting results)

- **Schedule**: the real 2026-27 schedule wasn't posted anywhere on ESPN as
  of the last data scrape (confirmed directly). The Season Projection tab
  uses each Big Ten team's actual 2025-26 regular-season schedule instead
  (real opponents, real home/away splits, real non-conference slate — see
  `lib/simulate_season.py`'s `build_schedule_from_last_season`, cutoff at
  2026-03-09 to exclude conference/NCAA tournament games). Team *strength*
  is still this year's, via each team's projected 2026-27 roster — only the
  who/when/home-or-away comes from last season. Drop a real schedule CSV at
  `../data/b1g_schedule_2627_override.csv` (columns:
  `team_a,team_b,a_is_home[,is_conference]`) once the actual 2026-27
  schedule is released, and the sim will use it automatically instead.
- **Every team's strength (Indiana included)**: projected from BartTorvik
  RosterCast's actual 2026-27 roster (`data/rostercast_2627.csv`) —
  minutes-weighted Ortg for offense (`lib/league_model.py`'s
  `_next_season_team_proxy` for opponents, weighted by RosterCast's own
  projected Mins; `_iu_roster_proxy_from_rostercast` for Indiana, weighted
  by the coach's live per-slot MPG instead). RosterCast has no per-player
  defensive projection, so defense uses each player's own last-season
  `adj_drtg` where they played D1 last year (matched by name, works the
  same whether the player is a returning IU player, a transfer, or an
  opponent). For true newcomers with no last-season record, defense falls
  back to the average `adj_drtg` of last season's real D1 players who
  share the same position group and a similar RecruiT-Rank tier
  (`_drtg_fallback_for`/`_drtg_fallback_tables` — RecruiT-Rank is scraped
  from a tooltip on every RosterCast player row, so a returning-player
  reference set and an unranked/newcomer target both read from the same
  scale; position comes from BartTorvik's `role` where available, else
  ESPN's coarser position, else `recruit_config.py`'s hand-verified
  position for IU's own 4 HS/international recruits specifically, who
  aren't on ESPN's roster pages yet). That backs off to a position-only
  average, then the flat D1 average, if a (position, rank-tier) bucket has
  too few reference players to trust. Everyone (Indiana included) falls
  back to a replay of their 2025-26 actual roster (the older EvanMiya
  OBPR/DBPR-based formula) only if RosterCast has no data for them at
  all — this keeps every team, including Indiana's live roster, on the
  exact same rating scale. Rerun `scrapers/build_rostercast_2627.py`
  periodically as transfers/recruits settle over the summer.
- **Indiana's default MPGs** (`lib/roster_state.py`'s `default_roster`) use
  a fixed set of 11 minute values (32/29/27/26/25/25/13/12/7/4/0 —
  originally derived from RosterCast's own projected Indiana depth chart,
  rescaled to this roster's 200-minute target), assigned to players by
  their own net rating (RosterCast Ortg minus last-season adj_drtg-or-
  fallback), highest net getting the most minutes — except Markus Burton
  and Aiden Sherrell are pinned to the top 2 slots by explicit choice,
  regardless of where their own net rating would otherwise place them.
  That pin is why Burton (mid-pack by net) outranks Darren Harris (the
  roster's single highest net rating) in minutes; Harris still gets the
  next-best slot among everyone else. Still just a starting point, not a
  claim of the "optimal" lineup — the sliders are there to keep tuning
  from here.
- **Recruit ratings** (`lib/recruit_config.py`'s `RECRUIT_RANK_TO_NET_PROXY`):
  starting values based on a rank-tier pattern, not fit to data. Tune if they
  look off.
- **Tournament odds curve** (`lib/simulate_season.py`'s
  `estimate_tournament_odds`): a starting heuristic, not calibrated against
  historical at-large data.

## Design notes

- The **Team Breakdown** tab only ever shows real, interpretable box-score
  stats (points/rebounds/assists/etc. per 40 minutes, shooting splits) as a
  percentile vs. all D1 players — never a composite rating.
- A hidden internal number (built from each player's `ortg`/`adj_drtg`) drives
  win probabilities behind the scenes, but it's never labeled or shown
  anywhere in the UI — only the resulting record/standings/odds are surfaced.
- The 4 HS/international recruits render as distinct "Recruiting Profile"
  cards (real HS/pro stats + recruiting rank, sourced) rather than being
  forced into the D1 percentile bars, since they have no college stats yet.
