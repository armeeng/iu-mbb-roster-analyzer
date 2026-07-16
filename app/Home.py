"""IU Roster Analyzer — Streamlit entry point.

Run:
  cd "IU MBB/app" && ../.venv/bin/python3 -m streamlit run Home.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import streamlit as st

from lib.data_loader import load_player_pool
from lib.position_groups import POSITION_GROUPS, position_group
from lib.recruit_config import is_wide_uncertainty
from lib.roster_state import (
    init_session_state, total_minutes, minutes_status, set_mpg, swap_slot,
    TARGET_TOTAL_MPG,
)
from lib.percentile_engine import (
    compute_d1_population, compute_team_breakdown, compute_team_population,
    player_flags, pool_row, ordinal,
)
from lib.league_model import build_team_proxies, compute_iu_d1_net_rank, B1G_TEAMS
from lib.simulate_season import (
    load_or_build_schedule, monte_carlo_season, estimate_tournament_odds,
)
from lib.ai_breakdown import build_ai_prompt, generate_breakdown, api_key_available

st.set_page_config(page_title="IU Roster Analyzer", layout="wide")

CSS = """
<style>
.block-container {
    padding-top: 1.1rem;
    padding-bottom: 1rem;
    max-width: 1700px;
}
h1 { font-size: 1.4rem !important; font-weight: 700 !important; margin: 0 0 0.6rem 0 !important; }
.section-label {
    font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.07em; color: #990000; border-bottom: 2px solid #990000;
    padding-bottom: 3px; margin: 0 0 6px 0;
}
.sub-label {
    font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.05em; color: #999; margin: 8px 0 3px 0;
}
.pos-tag {
    font-size: 0.66rem; font-weight: 600; color: #990000;
    white-space: nowrap; padding-top: 8px; display: block;
}
.min-val { font-size: 0.78rem; color: #333; padding-top: 6px; display: block; }
.minutes-badge { font-size: 0.82rem; margin-bottom: 6px; }
.stat-row { font-size: 0.78rem; margin-bottom: 5px; }
.stat-row .top { display: flex; justify-content: space-between; color: #333; }
.stat-row .top .v { color: #888; }
.stat-bar { background: #eee; border-radius: 3px; height: 5px; width: 100%; margin-top: 2px; }
.stat-bar .fill { background: #990000; height: 5px; border-radius: 3px; }
.pos-table { width: 100%; border-collapse: collapse; font-size: 0.76rem; table-layout: fixed; margin-bottom: 4px; }
.pos-table th, .pos-table td { text-align: center; padding: 4px 2px; color: #333; }
.pos-table thead th { color: #999; font-weight: 600; font-size: 0.68rem; border-bottom: 1px solid #eee; }
.pos-table th.rowhead, .pos-table td.rowlabel { text-align: left; color: #666; font-weight: 600; width: 30%; }
.pos-table tbody tr:not(:last-child) td { border-bottom: 1px solid #f5f5f5; }
[data-testid="stElementContainer"] { margin-bottom: 0 !important; }
div[data-testid="stSelectbox"] label, div[data-testid="stSlider"] label { display: none; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 8px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

init_session_state()
player_pool = load_player_pool()
population = compute_d1_population()


def _player_options() -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Returns (ids, label_by_id, name_by_id). ids are espn_id — the unique
    key used everywhere else in the app (player names collide across D1: 31
    known duplicates, e.g. two different "Jake Davis" on different teams).
    label_by_id disambiguates the dropdown with a team suffix only when a
    name collides; name_by_id is always the plain espn_name, stored on the
    roster slot for display elsewhere (AI prompt, captions)."""
    games = pd.to_numeric(player_pool["games"], errors="coerce")
    is_estimate = player_pool.get("is_estimate", False).fillna(False)
    pool = player_pool[(games >= 5) | is_estimate].dropna(subset=["espn_name", "espn_id"]).copy()
    is_dupe = pool["espn_name"].duplicated(keep=False)
    pool["label"] = pool["espn_name"]
    pool.loc[is_dupe, "label"] = (
        pool.loc[is_dupe, "espn_name"] + " (" + pool.loc[is_dupe, "espn_team"].astype(str) + ")"
    )
    pool = pool.sort_values("label")
    ids = pool["espn_id"].tolist()
    label_by_id = dict(zip(pool["espn_id"], pool["label"]))
    name_by_id = dict(zip(pool["espn_id"], pool["espn_name"]))
    return ids, label_by_id, name_by_id


def _player_context(player_id: str, row) -> str:
    if row is None:
        return "No match in player pool"
    if bool(row.get("is_estimate")):
        recruit_key = player_id.removeprefix("recruit_")
        note = "Recruit — estimated production, no college games played"
        if is_wide_uncertainty(recruit_key):
            note += " (wide uncertainty)"
        return note
    parts = [
        f"{row.get('espn_team')} — {row.get('mpg'):.1f} MPG last season, "
        f"{int(row.get('games'))} games"
    ]
    parts.extend(player_flags(row))
    return "  |  ".join(parts)


def _stat_bar(label: str, value_str: str, pct: int | None) -> str:
    if pct is None:
        return (
            f'<div class="stat-row"><div class="top"><span>{label}</span>'
            f'<span class="v">N/A</span></div></div>'
        )
    pct_c = max(0, min(100, pct))
    return (
        f'<div class="stat-row"><div class="top"><span>{label}</span>'
        f'<span class="v">{value_str} · {ordinal(pct)} percentile</span></div>'
        f'<div class="stat-bar"><div class="fill" style="width:{pct_c}%;"></div></div></div>'
    )


def run_season_simulation(roster):
    """Builds the real last-season-derived schedule, proxies for every team
    it involves (18 B1G + real non-conference opponents), and simulates.
    Returns (standings_df, iu_row, ncaa_odds)."""
    schedule = load_or_build_schedule(B1G_TEAMS)
    all_teams = sorted(set(schedule["team_a"]) | set(schedule["team_b"]))
    proxies = build_team_proxies(all_teams, roster)
    standings = monte_carlo_season(schedule, proxies, standings_teams=B1G_TEAMS)
    iu_row = standings[standings["team"] == "Indiana Hoosiers"].iloc[0]
    d1_net_rank = compute_iu_d1_net_rank(roster)
    ncaa_odds = estimate_tournament_odds(d1_net_rank)
    return standings, iu_row, ncaa_odds


st.markdown("<h1>Indiana 2026-27 Roster Analyzer</h1>", unsafe_allow_html=True)

roster = st.session_state.roster
player_ids, player_label_by_id, player_name_by_id = _player_options()

col_roster, col_stats, col_season = st.columns([1.25, 1, 1.15])

# ── Roster ───────────────────────────────────────────────────────────────
with col_roster:
    with st.container(border=True):
        st.markdown('<div class="section-label">Roster</div>', unsafe_allow_html=True)

        total = total_minutes(roster)
        status = minutes_status(total)
        badge_color = {"ok": "#1a7a1a", "warn": "#b8860b", "bad": "#990000"}[status]
        st.markdown(
            f'<div class="minutes-badge">Total minutes: '
            f'<span style="color:{badge_color};font-weight:700;">{total:.0f} / {TARGET_TOTAL_MPG:.0f}</span></div>',
            unsafe_allow_html=True,
        )
        for slot in roster:
            row = pool_row(slot.player_id, player_pool)
            pos_label = (position_group(row.get("role")) if row is not None else None) or "-"

            c_name, c_pos, c_slider, c_min = st.columns([3.1, 0.9, 3.6, 0.9])

            with c_name:
                default_idx = player_ids.index(slot.player_id) if slot.player_id in player_ids else 0
                chosen_id = st.selectbox(
                    "Player", player_ids, index=default_idx,
                    format_func=lambda pid: player_label_by_id.get(pid, pid),
                    key=f"player_{slot.slot_id}", label_visibility="collapsed",
                    help=_player_context(slot.player_id, row),
                )
                if chosen_id != slot.player_id:
                    swap_slot(slot.slot_id, player_name_by_id[chosen_id], chosen_id)

            with c_pos:
                st.markdown(f'<span class="pos-tag">{pos_label}</span>', unsafe_allow_html=True)

            with c_slider:
                mpg = st.slider(
                    "Minutes", 0.0, 40.0, float(slot.mpg), 0.5,
                    key=f"mpg_{slot.slot_id}", label_visibility="collapsed",
                )
                if mpg != slot.mpg:
                    set_mpg(slot.slot_id, mpg)

            with c_min:
                st.markdown(f'<span class="min-val">{mpg:.0f} min</span>', unsafe_allow_html=True)

roster = st.session_state.roster  # re-read after any edits above

# ── Team stats ───────────────────────────────────────────────────────────
stats_card = col_stats.container(border=True)
with stats_card:
    st.markdown(
        '<div class="section-label" title="Projected per-game team totals (not per-40 '
        'rates) — real box-score production only.">Team Stats Projections</div>',
        unsafe_allow_html=True,
    )
    stats_scope = st.radio(
        "Compared to:", ["All D1", "Big Ten"], horizontal=True,
        key="team_stats_scope",
    )

team_population_all = compute_team_population()
team_population_b1g = team_population_all[team_population_all["espn_team"].isin(B1G_TEAMS)]
population_b1g = population[population["espn_team"].isin(B1G_TEAMS)]

breakdown_all_d1 = compute_team_breakdown(roster, player_pool, population, team_population=team_population_all)
breakdown_b1g = compute_team_breakdown(roster, player_pool, population_b1g, team_population=team_population_b1g)
breakdown = breakdown_b1g if stats_scope == "Big Ten" else breakdown_all_d1

with stats_card:
    scope_label = "all real D1 teams'" if stats_scope == "All D1" else "the 18 real Big Ten teams'"
    st.caption(f"Percentile vs. {scope_label} actual 2025-26 per-game output.")
    display_stats = [(c, info) for c, info in breakdown["stats"].items() if c != "usg_pct"]
    bars_html = "".join(
        _stat_bar(
            info["label"],
            f"{info['team_value']:.1f}" if info["team_value"] is not None else "N/A",
            info["percentile"],
        )
        for _, info in display_stats
    )
    st.markdown(bars_html, unsafe_allow_html=True)

    st.markdown(
        '<div class="sub-label" style="color:#000;font-weight:700;" '
        'title="Percentile vs. D1 players at the same position only '
        '(e.g. a PG is compared to other PGs, not centers). Unweighted — every player in a '
        'group counts equally regardless of minutes played. Production is BPR percentile; '
        'Size is height percentile; Experience is projected class-year percentile.">'
        'Percentile vs. same-position D1 players</div>',
        unsafe_allow_html=True,
    )
    pos_rows = [
        ("Production", breakdown["by_position_production"]),
        ("Size", breakdown["by_position_size"]),
        ("Experience", breakdown["by_position_experience"]),
    ]
    header_html = "".join(f"<th>{pg}</th>" for pg in POSITION_GROUPS)
    body_html = ""
    for label, d in pos_rows:
        cells = "".join(
            f"<td>{ordinal(v)}</td>" if (v := d.get(pg)) is not None else "<td>N/A</td>"
            for pg in POSITION_GROUPS
        )
        body_html += f'<tr><td class="rowlabel">{label}</td>{cells}</tr>'
    st.markdown(
        f'<table class="pos-table"><thead><tr><th class="rowhead"></th>{header_html}</tr></thead>'
        f'<tbody>{body_html}</tbody></table>',
        unsafe_allow_html=True,
    )

# ── Season projection ────────────────────────────────────────────────────
with col_season:
    with st.container(border=True):
        st.markdown(
            '<div class="section-label" title="Schedule: each team\'s actual 2025-26 regular-season '
            'games (closest available proxy since the real 2026-27 schedule isn\'t posted yet). '
            'Opponent teams use their actual 2025-26 rosters; Indiana uses the roster on the left.">'
            'Season Projection</div>',
            unsafe_allow_html=True,
        )

        with st.spinner("Simulating..."):
            standings, iu_row, ncaa_odds = run_season_simulation(roster)

        overall_wins = iu_row["mean_overall_wins"]
        overall_games = iu_row["overall_games"]

        m1, m2, m3 = st.columns(3)
        m1.metric("Record", f"{overall_wins:.1f}-{overall_games - overall_wins:.1f}")
        m2.metric("B1G Finish", f"#{iu_row['mean_finish_rank']:.0f}")
        m3.metric("At-Large", f"{ncaa_odds * 100:.0f}%")

        st.markdown('<div class="sub-label">Big Ten standings</div>', unsafe_allow_html=True)
        display_standings = standings[["team", "mean_conf_wins", "conf_games", "mean_finish_rank"]].copy()
        display_standings["Wins"] = display_standings["mean_conf_wins"]
        display_standings["Losses"] = display_standings["conf_games"] - display_standings["mean_conf_wins"]
        display_standings = display_standings.rename(columns={"team": "Team", "mean_finish_rank": "Avg. Finish"})
        display_standings = display_standings[["Team", "Wins", "Losses", "Avg. Finish"]]
        table_height = int(35 * (len(display_standings) + 1)) + 3
        st.dataframe(
            display_standings.style.apply(
                lambda row: ["background-color: #F5EAEA" if row["Team"] == "Indiana Hoosiers" else "" for _ in row],
                axis=1,
            ).format({"Wins": "{:.1f}", "Losses": "{:.1f}", "Avg. Finish": "{:.1f}"}),
            hide_index=True, use_container_width=True, height=table_height,
        )

# ── AI summary ───────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown('<div class="section-label">AI Summary</div>', unsafe_allow_html=True)
    prompt_text = build_ai_prompt(roster, breakdown_all_d1, breakdown_b1g, player_pool, population, population_b1g)

    if not api_key_available():
        st.write("No API key configured. Copy the prompt below into Claude or ChatGPT manually.")
        st.text_area("Prompt", prompt_text, height=250, label_visibility="collapsed")
    else:
        button_label = "Regenerate" if "ai_result" in st.session_state else "Generate Summary"
        if st.button(button_label):
            generate_breakdown.clear()
            with st.spinner("Generating..."):
                try:
                    st.session_state["ai_result"] = generate_breakdown(prompt_text)
                    st.session_state.pop("ai_error", None)
                except Exception as e:
                    print(f"[AI SUMMARY] generation failed: {e}")
                    st.session_state.pop("ai_result", None)
                    st.session_state["ai_error"] = True

        if st.session_state.get("ai_error"):
            st.error("AI summary tool not currently available, please try again later.")
        elif "ai_result" in st.session_state:
            st.write(st.session_state["ai_result"])
