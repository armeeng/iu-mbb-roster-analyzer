"""The coach-editable roster: 11 slots (7 known D1 players + 4 recruits by
default), each with an MPG slider. Manual-balance UX — moving one slider
never rescales the others; a live total (target 200) is shown separately.

Every slot is keyed by player_id (espn_id, or "recruit_<key>" for the 4
recruits) — the unique identity used for every lookup into the unified
player pool (load_player_pool()). `name` is display-only. Player names are
NOT unique across D1 (31 known collisions, e.g. two different "Jake Davis"
on different teams) — matching on name alone silently pulls the wrong
player's stats, which is why player_id is the real key everywhere.
"""
from dataclasses import dataclass

import streamlit as st

TARGET_TOTAL_MPG = 200.0
MPG_WARN_TOLERANCE = 5.0  # within +/-5 of 200 = "warn" (yellow), beyond = "bad" (red)


@dataclass
class RosterSlot:
    slot_id: int
    name: str        # espn_name, display only
    player_id: str    # espn_id (or "recruit_<key>") — unique key into the player pool
    mpg: float


def default_roster() -> list[RosterSlot]:
    """The 7 known IU players + 4 recruits, MPG summing to 200. espn_ids are
    hardcoded here (rather than resolved by name lookup at init time) since
    all 7 real names are confirmed unique in the pool — but the id, not the
    name, is what every downstream lookup actually uses.

    MPGs are the coach's own hand-tuned baseline (set live in the app's
    Roster tab, then saved here as the new default), not derived from any
    formula — supersedes the earlier net-rating-ranked scheme. Sums to
    199.5, not exactly 200, which is fine: minutes_status treats anything
    within +/-2 of TARGET_TOTAL_MPG as "ok"."""
    return [
        RosterSlot(0, "Markus Burton", "5101623", 30.0),
        RosterSlot(1, "Bryce Lindsay", "5174291", 26.0),
        RosterSlot(2, "Jaeden Mustaf", "5060730", 24.0),
        RosterSlot(3, "Darren Harris", "4873107", 30.0),
        RosterSlot(4, "Aiden Sherrell", "4873184", 30.0),
        RosterSlot(5, "Samet Yigitoglu", "5238184", 23.0),
        RosterSlot(6, "Trent Sisley", "5101827", 13.0),
        RosterSlot(7, "Prince-Alexander Moody", "recruit_moody", 5.5),
        RosterSlot(8, "Vaughn Karvala", "recruit_karvala", 9.0),
        RosterSlot(9, "Trevor Manhertz", "recruit_manhertz", 9.0),
        RosterSlot(10, "Clemens Sokolov", "recruit_sokolov", 0.0),
    ]


def init_session_state() -> None:
    if "roster" not in st.session_state:
        st.session_state.roster = default_roster()


def total_minutes(roster: list[RosterSlot]) -> float:
    return sum(s.mpg for s in roster)


def minutes_status(total: float) -> str:
    diff = abs(total - TARGET_TOTAL_MPG)
    if diff <= 2.0:
        return "ok"
    if diff <= MPG_WARN_TOLERANCE:
        return "warn"
    return "bad"


def set_mpg(slot_id: int, mpg: float) -> None:
    for s in st.session_state.roster:
        if s.slot_id == slot_id:
            s.mpg = mpg
            return


def swap_slot(slot_id: int, name: str, player_id: str) -> None:
    for s in st.session_state.roster:
        if s.slot_id == slot_id:
            s.name = name
            s.player_id = player_id
            return
