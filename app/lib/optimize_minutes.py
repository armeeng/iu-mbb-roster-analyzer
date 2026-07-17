"""Minutes optimizer behind the Roster card's "Optimize minutes" button.

Maximizes each player's optimizer value (league_model.player_optimizer_
value: the season sim's own net — RosterCast projected Ortg minus
last-season adj_drtg — blended 50/50 with projected BPR, since sim net
alone over-trusts noisy small-sample last-season defensive numbers) minus
a soft fatigue penalty. Soft penalty with NO hard per-player cap is a
staff decision (chosen over caps when this was specced): no artificial
ceiling, but every half-minute past FATIGUE_FREE_MPG costs quadratically
more, so a heavy load has to be earned by a real rating edge. The penalty
lives only inside this objective; the sim itself stays linear in minutes
and scores whatever allocation is actually applied.

Two lineup-structure floors (also staff-chosen) keep the answer
basketball-shaped: combined PG+Combo minutes >= HANDLER_FLOOR and combined
PF+C minutes >= BIG_FLOOR. Without them the unconstrained optimum happily
fields a guard-less rotation (it benched Markus Burton outright when this
was prototyped). Floors use combined groups because strict per-position
40-minute floors are infeasible on rosters with a single true PG.

Solved greedily in STEP-minute increments, each going to the highest
marginal gain. The objective is separable and concave (linear value,
convex penalty), so greedy marginal allocation is exact, not heuristic;
floors are honored by restricting candidates to deficit groups once the
remaining minutes equal the remaining floor deficit.
"""
from dataclasses import dataclass

from lib.league_model import player_optimizer_value
from lib.percentile_engine import pool_row
from lib.position_groups import position_group
from lib.roster_state import TARGET_TOTAL_MPG

STEP = 0.5              # matches the MPG slider's step
SLIDER_MAX_MPG = 40.0   # matches the MPG slider's range
HANDLER_GROUPS = {"PG", "Combo"}
BIG_GROUPS = {"PF", "C"}
HANDLER_FLOOR = 60.0
BIG_FLOOR = 60.0

# Fatigue penalty: FATIGUE_LAMBDA * max(0, mpg - FATIGUE_FREE_MPG)^2 per
# player, in the same team-net-rating units as the objective. Tuned on the
# default roster so the top players land in the low 30s and the rotation
# keeps a realistic shape (~7-8 players), rather than the best five pinned
# at 40 the way the penalty-free optimum comes out.
FATIGUE_FREE_MPG = 24.0
FATIGUE_LAMBDA = 0.005


@dataclass
class OptimizedSlot:
    slot_id: int
    name: str
    net: float | None   # blended optimizer value (see player_optimizer_value); None = no projected Ortg
    current_mpg: float
    mpg: float          # optimized minutes


@dataclass
class OptimizeResult:
    slots: list[OptimizedSlot]  # roster order
    warnings: list[str]


def _marginal_gain(net: float, mpg: float) -> float:
    """Objective gain from giving this player the next STEP minutes: linear
    value (their share of the minutes-weighted team net) minus the convex
    fatigue increment."""
    value = net / TARGET_TOTAL_MPG * STEP
    over_before = max(0.0, mpg - FATIGUE_FREE_MPG)
    over_after = max(0.0, mpg + STEP - FATIGUE_FREE_MPG)
    return value - FATIGUE_LAMBDA * (over_after**2 - over_before**2)


def optimize_minutes(roster, player_pool) -> OptimizeResult:
    """Optimal TARGET_TOTAL_MPG-minute allocation across the current roster
    slots (players are taken as given — this reallocates minutes, it never
    swaps anyone). Players with no projected Ortg get 0: the sim credits
    them zero offense, so any minute they take is a minute the objective
    can't score."""
    warnings: list[str] = []
    entries = []
    for s in roster:
        row = pool_row(s.player_id, player_pool)
        net = player_optimizer_value(s.name, row)
        group = position_group(row.get("role")) if row is not None else None
        entries.append({"slot": s, "net": net, "group": group, "mpg": 0.0})
        if net is None:
            warnings.append(
                f"{s.name} has no projected Ortg (the sim can't score his offense) — set to 0 minutes."
            )

    eligible = [e for e in entries if e["net"] is not None]
    if not eligible:
        warnings.append("No rostered player has a projected Ortg — nothing to optimize.")
        return _result(entries, warnings)

    # Clamp each floor to what its group can physically supply.
    handler_deficit = _clamped_floor(eligible, HANDLER_GROUPS, HANDLER_FLOOR, "Ball-handler", warnings)
    big_deficit = _clamped_floor(eligible, BIG_GROUPS, BIG_FLOOR, "Big-man", warnings)

    remaining = TARGET_TOTAL_MPG
    while remaining > 1e-6:
        deficit = max(handler_deficit, 0.0) + max(big_deficit, 0.0)
        restricted = deficit >= remaining - 1e-6

        def in_deficit_group(e) -> bool:
            return (handler_deficit > 0 and e["group"] in HANDLER_GROUPS) or (
                big_deficit > 0 and e["group"] in BIG_GROUPS
            )

        cands = [
            e for e in eligible
            if e["mpg"] < SLIDER_MAX_MPG - 1e-6 and (not restricted or in_deficit_group(e))
        ]
        if not cands:
            warnings.append(
                f"{remaining:.0f} minutes could not be assigned — every scoreable player is at the "
                f"{SLIDER_MAX_MPG:.0f}-minute slider max."
            )
            break

        best = max(cands, key=lambda e: _marginal_gain(e["net"], e["mpg"]))
        best["mpg"] += STEP
        remaining -= STEP
        if best["group"] in HANDLER_GROUPS:
            handler_deficit -= STEP
        elif best["group"] in BIG_GROUPS:
            big_deficit -= STEP

    return _result(entries, warnings)


def _clamped_floor(eligible, groups, floor, label, warnings) -> float:
    capacity = sum(SLIDER_MAX_MPG for e in eligible if e["group"] in groups)
    if capacity >= floor:
        return floor
    warnings.append(
        f"{label} floor ({floor:.0f} min) exceeds what this roster can supply "
        f"({capacity:.0f}) — clamped."
    )
    return capacity


def _result(entries, warnings) -> OptimizeResult:
    return OptimizeResult(
        slots=[
            OptimizedSlot(
                slot_id=e["slot"].slot_id,
                name=e["slot"].name,
                net=e["net"],
                current_mpg=float(e["slot"].mpg),
                mpg=e["mpg"],
            )
            for e in entries
        ],
        warnings=warnings,
    )
