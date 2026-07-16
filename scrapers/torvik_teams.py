import requests, pandas as pd, io
from rapidfuzz import process, fuzz
from pathlib import Path

TEAMS            = Path(__file__).parent.parent / "data" / "teams.csv"
AMBIGUOUS        = Path(__file__).parent.parent / "data" / "ambiguous_teams.txt"
UNMATCHED_TORVIK = Path(__file__).parent.parent / "data" / "unmatched_torvik_teams.txt"
UNMATCHED_ESPN   = Path(__file__).parent.parent / "data" / "unmatched_espn_teams.txt"

NAME_CUTOFF      = 70
AMBIGUOUS_DELTA  = 5

r = requests.get("https://barttorvik.com/getadvstats.php", params={"year": 2026, "csv": 1}, timeout=30)
raw = pd.read_csv(io.StringIO(r.text), header=None)
torvik_team_list = sorted(set(raw[1].dropna().astype(str).tolist()))

espn_df = pd.read_csv(TEAMS, dtype=str)
espn_name_list = espn_df["team_name"].tolist()
ambiguous = []


def best_match(espn_name: str) -> str | None:
    candidates = process.extract(
        espn_name, torvik_team_list,
        scorer=fuzz.token_set_ratio,
        score_cutoff=NAME_CUTOFF,
    )
    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_name, best_sc, _ = candidates[0]

    if len(candidates) > 1 and (best_sc - candidates[1][1]) < AMBIGUOUS_DELTA:
        ambiguous.append(
            f"{espn_name}: {best_name} ({best_sc:.1f}) vs "
            f"{candidates[1][0]} ({candidates[1][1]:.1f})"
        )

    return best_name


espn_df["torvik_team"] = espn_df["team_name"].apply(best_match)
espn_df.to_csv(TEAMS, index=False)

if ambiguous:
    AMBIGUOUS.write_text("\n".join(ambiguous))
    print(f"Wrote {len(ambiguous)} ambiguous mappings → {AMBIGUOUS}")

matched_torvik = set(espn_df["torvik_team"].dropna().tolist())

unmatched_torvik = sorted(t for t in torvik_team_list if t not in matched_torvik)
if unmatched_torvik:
    UNMATCHED_TORVIK.write_text("\n".join(unmatched_torvik))
    print(f"Wrote {len(unmatched_torvik)} unmatched Torvik teams → {UNMATCHED_TORVIK}")

unmatched_espn = espn_df[espn_df["torvik_team"].isna()]["team_name"].tolist()
if unmatched_espn:
    UNMATCHED_ESPN.write_text("\n".join(unmatched_espn))
    print(f"Wrote {len(unmatched_espn)} unmatched ESPN teams → {UNMATCHED_ESPN}")

print(f"Matched {espn_df['torvik_team'].notna().sum()} / {len(espn_df)} teams")
