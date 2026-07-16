"""AI-generated team breakdown via the Google Gemini API (Google AI Studio).

Never the hidden ortg/adj_drtg/net_proxy win-probability engine or any
*_proj_* column — but per-player production rating (BPR under the hood,
both raw and development-curve-projected) is included, same exception as
Positional Production's visible percentile. The term "BPR" itself is kept
out of the prompt text and explicitly disallowed in the model's output
(see the closing instructions and generate_breakdown's system_instruction)
— coaches see "Production", not the underlying metric name. Degrades
gracefully with no API key configured — shows the assembled prompt for
manual copy-paste instead of erroring, mirroring Illinois MBB/tools/
pregame_report.py's original manual-workflow pattern.

Deliberately excludes each player's configured minutes (slot.mpg) — the
prompt is meant to characterize who the players ARE, not how the coach has
currently split time between them.
"""
import os

import pandas as pd
import streamlit as st

from lib.position_groups import position_group
from lib.percentile_engine import (
    player_flags, pool_row, percentile_rank, projected_class_year_num, ordinal,
    STAT_COLS, STAT_LABELS, PRODUCTION_COL, SIZE_COLS,
)
from lib.team_strength import developed_obpr_dbpr

MODEL_ID = "gemini-3.5-flash"  # verified working against a live key 2026-07; cheap/fast, swap here anytime

_CLASS_NUM_TO_LABEL = {1: "Fr", 2: "So", 3: "Jr", 4: "Sr", 5: "5th-yr"}


def _fmt(v, decimals: int = 1) -> str:
    return "N/A" if v is None or pd.isna(v) else f"{v:.{decimals}f}"


def _pct_str(p: int | None) -> str:
    return "N/A" if p is None else f"{ordinal(p)} percentile"


def api_key_available() -> bool:
    try:
        if st.secrets.get("GOOGLE_API_KEY"):
            return True
    except Exception:
        pass
    return bool(os.environ.get("GOOGLE_API_KEY"))


def _get_api_key() -> str:
    try:
        key = st.secrets.get("GOOGLE_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GOOGLE_API_KEY", "")


def _dual_pct(val_d1: int | None, val_b1g: int | None) -> str:
    d1_str = f"{ordinal(val_d1)} percentile" if val_d1 is not None else "N/A"
    b1g_str = f"{ordinal(val_b1g)} percentile" if val_b1g is not None else "N/A"
    return f"{d1_str} vs. all D1, {b1g_str} vs. Big Ten"


def build_ai_prompt(
    roster, breakdown_all_d1: dict, breakdown_b1g: dict,
    player_pool_df: pd.DataFrame, population_df: pd.DataFrame, population_b1g_df: pd.DataFrame,
) -> str:
    """breakdown_all_d1/breakdown_b1g are compute_team_breakdown() results
    scoped to all D1 and to just the Big Ten respectively (independent of
    whichever scope the coach currently has the UI toggle set to) — the
    model gets both cuts so it can speak to national and conference
    standing at once. team_value is identical between the two (it's the
    roster's own projection, not population-dependent); only the
    percentiles differ. population_df/population_b1g_df give the same
    dual treatment to every individual player's own stat lines, not just
    the team-level aggregates."""
    lines = [
        "You are a college basketball analyst writing a concise scouting breakdown "
        "of a hypothetical Indiana Hoosiers roster for the coaching staff.",
        "",
        "Team stat projections (per-game team totals; percentiles given vs. both "
        "all of D1 and the Big Ten specifically):",
    ]
    for col, info_d1 in breakdown_all_d1["stats"].items():
        info_b1g = breakdown_b1g["stats"][col]
        val_str = f"{info_d1['team_value']:.1f}" if info_d1["team_value"] is not None else "N/A"
        lines.append(f"- {info_d1['label']}: {val_str} ({_dual_pct(info_d1['percentile'], info_b1g['percentile'])})")

    lines.append("")
    lines.append("Positional production (percentile among same-position D1 players):")
    for pg, val_d1 in breakdown_all_d1["by_position_production"].items():
        val_b1g = breakdown_b1g["by_position_production"].get(pg)
        lines.append(f"- {pg}: {_dual_pct(val_d1, val_b1g)}")

    lines.append("")
    lines.append("Positional size (height percentile among same-position D1 players):")
    for pg, val_d1 in breakdown_all_d1["by_position_size"].items():
        val_b1g = breakdown_b1g["by_position_size"].get(pg)
        lines.append(f"- {pg}: {_dual_pct(val_d1, val_b1g)}")

    lines.append("")
    lines.append("Positional experience (class-year percentile among same-position D1 players):")
    for pg, val_d1 in breakdown_all_d1["by_position_experience"].items():
        val_b1g = breakdown_b1g["by_position_experience"].get(pg)
        lines.append(f"- {pg}: {_dual_pct(val_d1, val_b1g)}")

    pop_pos_group = population_df["role"].apply(position_group)
    pop_pos_group_b1g = population_b1g_df["role"].apply(position_group)

    lines.append("")
    lines.append(
        "Individual player detail (minutes/rotation configuration deliberately "
        "omitted — these are player characteristics only; percentiles given vs. "
        "both all of D1 and the Big Ten specifically):"
    )
    for slot in roster:
        row = pool_row(slot.player_id, player_pool_df)
        if row is None:
            continue
        pg = position_group(row.get("role"))
        pos_population = population_df[pop_pos_group == pg] if pg is not None else population_df.iloc[0:0]
        pos_population_b1g = (
            population_b1g_df[pop_pos_group_b1g == pg] if pg is not None else population_b1g_df.iloc[0:0]
        )

        if bool(row.get("is_estimate")):
            context = "; ".join(player_flags(row)) or "Incoming recruit"
        else:
            context = (
                f"{row.get('espn_team')} ({row.get('conf')}), "
                f"{_fmt(row.get('mpg'))} MPG last season, {_fmt(row.get('games'), 0)} games"
            )
            flags = player_flags(row)
            if flags:
                context += "  [" + "; ".join(flags) + "]"

        lines.append("")
        lines.append(f"{slot.name} — {pg or 'Unknown position'}")
        lines.append(f"  Context: {context}")
        lines.append(
            f"  Height: {row.get('height_display')} ({_fmt(row.get('height_in'), 0)} in)"
        )

        stat_bits = []
        for col in STAT_COLS:
            val = row.get(col)
            pct_d1 = percentile_rank(val, col, population_df)
            pct_b1g = percentile_rank(val, col, population_b1g_df)
            stat_bits.append(f"{STAT_LABELS[col]} {_fmt(val)} ({_dual_pct(pct_d1, pct_b1g)})")
        lines.append("  Torvik per-40 (10+ games): " + "; ".join(stat_bits))
        lines.append(
            f"  Torvik ratings: ORTG {_fmt(row.get('ortg'))}, Adj DRTG {_fmt(row.get('adj_drtg'))}"
        )

        raw_obpr = pd.to_numeric(row.get("obpr"), errors="coerce")
        raw_dbpr = pd.to_numeric(row.get("dbpr"), errors="coerce")
        raw_bpr = raw_obpr + raw_dbpr if pd.notna(raw_obpr) and pd.notna(raw_dbpr) else None
        dev_obpr, dev_dbpr = developed_obpr_dbpr(row)
        dev_bpr = dev_obpr + dev_dbpr if dev_obpr is not None and dev_dbpr is not None else None
        global_before_d1 = percentile_rank(raw_bpr, PRODUCTION_COL, population_df)
        global_before_b1g = percentile_rank(raw_bpr, PRODUCTION_COL, population_b1g_df)
        global_after_d1 = percentile_rank(dev_bpr, PRODUCTION_COL, population_df)
        global_after_b1g = percentile_rank(dev_bpr, PRODUCTION_COL, population_b1g_df)
        pos_production_d1 = percentile_rank(dev_bpr, PRODUCTION_COL, pos_population)
        pos_production_b1g = percentile_rank(dev_bpr, PRODUCTION_COL, pos_population_b1g)
        lines.append(
            f"  Production rating — last season: Offensive {_fmt(raw_obpr)}, "
            f"Defensive {_fmt(raw_dbpr)}, Overall {_fmt(raw_bpr)} (global {_dual_pct(global_before_d1, global_before_b1g)})"
        )
        lines.append(
            f"  Production rating — projected 2026-27: Offensive {_fmt(dev_obpr)}, "
            f"Defensive {_fmt(dev_dbpr)}, Overall {_fmt(dev_bpr)} (global {_dual_pct(global_after_d1, global_after_b1g)}, "
            f"positional production {_dual_pct(pos_production_d1, pos_production_b1g)})"
        )

        size_d1 = percentile_rank(row.get(SIZE_COLS[0]), SIZE_COLS[0], pos_population)
        size_b1g = percentile_rank(row.get(SIZE_COLS[0]), SIZE_COLS[0], pos_population_b1g)
        lines.append(f"  Positional size percentile: {_dual_pct(size_d1, size_b1g)}")

        proj_class_num = projected_class_year_num(row)
        proj_class_label = (
            _CLASS_NUM_TO_LABEL.get(int(proj_class_num), str(proj_class_num))
            if proj_class_num is not None else "N/A"
        )
        exp_d1 = percentile_rank(proj_class_num, "class_year_num", pos_population)
        exp_b1g = percentile_rank(proj_class_num, "class_year_num", pos_population_b1g)
        if bool(row.get("is_estimate")):
            lines.append(
                f"  Experience — no prior college season (incoming recruit) -> "
                f"2026-27 class: {proj_class_label} ({_fmt(proj_class_num, 0)}) "
                f"(positional experience {_dual_pct(exp_d1, exp_b1g)})"
            )
        else:
            raw_class_num = pd.to_numeric(row.get("class_year_num"), errors="coerce")
            lines.append(
                f"  Experience — last season: {row.get('class_year')} ({_fmt(raw_class_num, 0)}) -> "
                f"projected 2026-27: {proj_class_label} ({_fmt(proj_class_num, 0)}) "
                f"(positional experience {_dual_pct(exp_d1, exp_b1g)})"
            )

    lines.append("")
    lines.append(
        "Write 3-5 team strengths and 3-5 weaknesses. Back claims with the "
        "percentiles given — cite both the D1 and Big Ten percentile where relevant "
        "(e.g. a team stat can be strong nationally but middling in-conference, or "
        "vice versa). Third-person analyst voice, no first-person pronouns. Never "
        "use the term 'BPR' — refer to that rating as 'Production' instead."
    )
    return "\n".join(lines)


@st.cache_data(show_spinner=False)
def generate_breakdown(prompt_text: str, model_id: str = MODEL_ID) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_get_api_key())
    resp = client.models.generate_content(
        model=model_id,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are a college basketball analytics scout writing for a D1 coaching "
                "staff. Be concise and back claims with the percentiles given. Never use "
                "the term 'BPR' — refer to that rating as 'Production' instead."
            ),
            max_output_tokens=2048,
            # Gemini 3.x models spend part of max_output_tokens on hidden "thinking"
            # tokens before the visible answer — left enabled, that ate ~90% of a
            # 1024 budget and truncated the response to a couple sentences. This
            # task (read structured stats, write a scouting summary) doesn't need
            # deep reasoning, so thinking is disabled to give the full budget to
            # the actual output.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return resp.text
