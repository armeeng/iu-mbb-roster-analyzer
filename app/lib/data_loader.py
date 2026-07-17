"""Cached reads of the CSVs in IU MBB/data/ (all read-only inputs)."""
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

CLASS_YEAR_TO_NUM = {"fr": 1, "so": 2, "jr": 3, "sr": 4}


@st.cache_data
def _load_attempt_volume_per40() -> pd.DataFrame:
    """Final-season FTA/3PA per-40 rates per player. d1_master_2026.csv has
    no attempt-volume columns (only shooting percentages), so this pulls
    from stats_latest.csv — each player's LATEST daily cumulative snapshot
    from BartTorvik's full 2025-26 season file (stats.csv, 2025-11-03
    through 2026-04-07 — confirmed complete), precomputed by
    scrapers/build_stats_latest.py since the full daily history (352MB) is
    too large to ship with the app. Note stats.csv mixes representations:
    `fta`/`tpa` are cumulative season totals, but `mp` is already a
    per-game average (not total minutes) — verified against a known player
    (Markus Burton: fta=48, gp=10, mp=30.1 gives fta_40=6.38; his pts=18.5
    per-game times 40/30.1 exactly reproduces d1_master's pts_40=24.58,
    confirming `mp` is per-game). So per-40 = total / (gp * mp) * 40, not
    total / mp * 40."""
    latest = pd.read_csv(
        DATA_DIR / "stats_latest.csv",
        dtype={"espn_player_id": str},
    )
    total_minutes = latest["mp"] * latest["gp"]
    fta_40 = (latest["fta"] / total_minutes * 40).where(total_minutes > 0)
    three_pa_40 = (latest["tpa"] / total_minutes * 40).where(total_minutes > 0)
    two_pa_40 = (latest["two_pa"] / total_minutes * 40).where(total_minutes > 0)
    return pd.DataFrame({
        "espn_id": latest["espn_player_id"],
        "fta_40": fta_40,
        "three_pa_40": three_pa_40,
        # fga_40 = total field goal attempts/40 (2PA + 3PA) — not displayed
        # as its own stat, only used to attempt-weight eFG% below.
        "fga_40": two_pa_40 + three_pa_40,
    })


# Hand-corrected BartTorvik `role` values, keyed by espn_id — applied on
# load so every role consumer (position tags, positional percentile buckets,
# league model, AI prompt) sees the same correction. Values must be spelled
# exactly as the CSV spells them (see position_groups.ROLE_TO_POSGROUP).
MANUAL_ROLE_OVERRIDES: dict[str, str] = {
    "5107375": "PF/C",  # Sam Alexis — Torvik says C; the staff views him as a PF
}


@st.cache_data
def load_d1_master() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "d1_master_2026.csv", dtype={"espn_id": str})
    df["class_year_num"] = df["class_year"].astype(str).str.strip().str.lower().map(CLASS_YEAR_TO_NUM)
    df = df.merge(_load_attempt_volume_per40(), on="espn_id", how="left")
    df["role"] = df["espn_id"].map(MANUAL_ROLE_OVERRIDES).fillna(df["role"])
    return df


@st.cache_data
def load_player_pool() -> pd.DataFrame:
    """d1_master's real 2025-26 D1 players plus the 4 IU recruits (hardcoded
    estimated stat lines, is_estimate=True) — one unified table so every
    downstream module (percentile breakdown, league model, win-probability
    engine) can treat every player identically, real or recruit."""
    from lib.recruit_config import RECRUITS, recruit_as_pool_row

    d1 = load_d1_master().copy()
    if "is_estimate" not in d1.columns:
        d1["is_estimate"] = False
    recruit_rows = pd.DataFrame([recruit_as_pool_row(k) for k in RECRUITS])
    return pd.concat([d1, recruit_rows], ignore_index=True)


@st.cache_data
def load_rosters_2627() -> pd.DataFrame:
    return pd.read_csv(
        DATA_DIR / "rosters_2627.csv",
        dtype={"espn_player_id": str, "team_id": str},
    )


@st.cache_data
def load_teams() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "teams.csv", dtype=str)


@st.cache_data
def load_rostercast_2627() -> pd.DataFrame:
    """BartTorvik RosterCast's projected 2026-27 roster for every D1 team
    (scrapers/build_rostercast_2627.py) — per-player projected minutes,
    Ortg, and usage%, keyed by torvik_team (see teams.csv for the
    espn_team <-> torvik_team mapping)."""
    return pd.read_csv(DATA_DIR / "rostercast_2627.csv", dtype={"torvik_team": str, "player": str})


def headshot_path(espn_id: str | None) -> Path | None:
    if not espn_id or str(espn_id) in ("nan", "None", ""):
        return None
    path = DATA_DIR / "headshots" / f"{espn_id}.png"
    return path if path.exists() else None
