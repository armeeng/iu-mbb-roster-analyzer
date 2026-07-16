"""Derives data/stats_latest.csv from data/stats.csv.

stats.csv is BartTorvik's full daily cumulative snapshot history (352MB,
706k rows) — too large to commit to git for deployment. The app
(lib/data_loader.py's _load_attempt_volume_per40) only ever needs each
player's LATEST snapshot, on the 6 columns below. This script extracts
that down to a file small enough to commit (~1MB).

Rerun whenever stats.csv is refreshed (see torvik_stats.py).
"""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

if __name__ == "__main__":
    stats = pd.read_csv(
        DATA_DIR / "stats.csv",
        usecols=["espn_player_id", "date", "fta", "tpa", "two_pa", "mp", "gp"],
        dtype={"espn_player_id": str},
    )
    stats["date"] = pd.to_datetime(stats["date"])
    latest = stats.sort_values("date").groupby("espn_player_id", as_index=False).tail(1)
    latest = latest.sort_values("espn_player_id")
    out_path = DATA_DIR / "stats_latest.csv"
    latest.to_csv(out_path, index=False)
    print(f"Wrote {len(latest)} rows to {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")
