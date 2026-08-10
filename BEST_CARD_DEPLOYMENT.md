# Best Card V1.0 Deployment

This deployment is additive. Do not replace the existing Game, HR, Player Props, or
results-tracking workflows.

## Repository root

- `run_daily_mlb_best_card.py`
- `best_card_math.py`
- `requirements_best_card.txt`
- `BEST_CARD_MODEL.md`
- `BEST_CARD_DEPLOYMENT.md`

## Test

Upload `tests/test_best_card_math.py` into the existing `tests` folder.

## Workflow

Upload `.github/workflows/best_card.yml` into `.github/workflows`.

For an evening manual validation, enter the source date explicitly. Scheduled morning
runs leave the optional date blank.

## Apps Script

Create `BestCardEmail.gs`, paste `AppsScript_BestCard_Addition.js`, send a test email,
then add an hourly trigger for `sendBestCardEmailIfFresh`.
