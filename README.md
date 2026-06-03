# Daily MLB HR Picks Automation

This package runs the MLB HR model automatically and writes the daily picks to your Google Sheet.

## What it does

- Runs every morning at 7:50 AM Pacific via GitHub Actions
- Writes the picks to `Daily MLB HR Picks Scorecard`
- Apps Script then emails the latest picks at 8:00 AM

## Setup

1. Create a GitHub repository.
2. Upload these files:
   - `run_daily_mlb_hr_picks.py`
   - `requirements.txt`
   - `.github/workflows/daily_mlb_hr_picks.yml`

3. Create a Google Cloud service account.
4. Enable Google Sheets API and Google Drive API.
5. Create a JSON key for the service account.
6. In GitHub, go to:
   `Repo → Settings → Secrets and variables → Actions → New repository secret`

   Add:
   - Name: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Value: paste the entire service account JSON

7. Share the Google Sheet `Daily MLB HR Picks Scorecard` with the service account email address.

8. In GitHub Actions, run the workflow manually once to test.

## Email

Use the updated Apps Script emailer with `matt@blvd.vegas`.
Set the email trigger for 8:00 AM Pacific.
