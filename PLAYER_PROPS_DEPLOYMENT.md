# Player Props V1.0 Deployment

This deployment is additive. Do not edit or replace the existing Game Pick or HR Pick scripts or workflows.

## GitHub root files

Upload these files to the repository root:

- `run_daily_mlb_player_props.py`
- `player_props_math.py`
- `requirements_player_props.txt`
- `PLAYER_PROPS_MODEL.md`

## GitHub test file

Upload `tests/test_player_props_math.py` inside the existing `tests` folder.

## GitHub workflow file

Upload `.github/workflows/player_props.yml` inside the existing `.github/workflows` folder.

## First model run

1. Open the repository's **Actions** tab.
2. Select **Daily MLB Player Props**.
3. Choose **Run workflow** on the `main` branch.
4. Confirm that the job finishes with a green check.
5. Confirm the Google Sheet now contains:
   - `Player Props`
   - `Player Props Model Results`
   - `Player Props Email Summary`
   - `Player Props Integrity Log`
   - `Player Props Run Log`

## Apps Script email addition

1. Open the existing `MLB Daily Pick Email` Apps Script project.
2. Add a new script file named `PlayerPropsEmail`.
3. Paste the contents of `AppsScript_PlayerProps_Addition.js` into that file and save.
4. Run `sendTestDailyMlbPlayerPropsEmail` once from the editor and approve permissions if prompted.
5. Confirm the test email layout and values.
6. Add an hourly time-driven trigger for `sendPlayerPropsEmailIfFresh`.

The fresh-date and send-once safeguards prevent stale or duplicate daily Player Props emails.
