# MLB Results Tracking

This addition is deliberately downstream from the Game, HR, Player Props, and Best Card models.

## Non-interference boundary

- `run_daily_mlb_game_picks.py` is unchanged.
- `run_daily_mlb_hr_picks.py` is unchanged.
- Their two existing GitHub Actions workflows are unchanged.
- Selection scripts, ranking logic, Apps Script, and email-summary tabs are not modified by grading.
- No odds, sportsbook lines, implied probabilities, or market data are read.
- The tracker reads only already-published selections and official MLB results.

`FROZEN_MODEL_BASELINE.json` and `tests/test_frozen_model_files.py` enforce this boundary.

## New spreadsheet tabs

- `Tracking - Game Picks`: the seven Game Picks published in the email, plus official results.
- `Tracking - HR Picks`: the nine HR targets/watchlist players published in the email, plus official results.
- `Tracking - Player Props`: the 20 published Player Props, milestones, and official boxscore results.
- `Tracking - Best Card`: the three published same-game stacks, all four component results, and the complete 4-for-4 stack result.
- `Tracking - Performance`: overall and segment-level accuracy/hit rate.
- `Tracking - Run Log`: snapshot/grading status and counts.

Prediction fields are written once. Later runs update only result fields.
Deterministic prediction IDs prevent duplicate rows when the tracker retries.

## Schedule

`.github/workflows/results_tracking.yml` runs at 13:15 and 15:15 UTC. These are
post-model runs with an idempotent retry. Each run snapshots the current Eastern-date
published card and grades all pending historical rows whose games are final.

The workflow can also be run manually in `snapshot`, `grade`, or `both` mode, with an
optional `YYYY-MM-DD` snapshot date.

## Result policy

- Final game winners are graded Yes/No.
- HR targets are graded from the official game boxscore.
- Hits, total bases, RBIs, and pitcher strikeouts are graded against their published dynamic thresholds.
- Each Best Card row separately grades the game winner, HR, Prop 1, and Prop 2.
- A Best Card is a successful complete stack only when all four components hit.
- Best Card component accuracy and complete-stack accuracy are reported separately.
- A player with no plate appearance is marked `DNP`, not a miss.
- A strikeout target with no innings pitched is marked `DNP`, not a miss.
- An unmatched player is marked `DNP/Unmatched`, not a miss, and retained for review.
- Postponed or cancelled games are marked `Void`.
- Non-final games remain `Pending`.

## Deployment

Commit the new files without altering the four files listed in
`FROZEN_MODEL_BASELINE.json`. The existing `GOOGLE_SERVICE_ACCOUNT_JSON` secret and
spreadsheet permissions are reused. No new secret is required.
