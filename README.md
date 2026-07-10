# Home Loan Tracker

Streamlit app for month-wise tracking of your home loan using your bank statement style entries:

- `-x` interest charged each month
- `+y` EMI paid each month
- optional extra principal payment

## Current baseline (hardcoded)

- Disbursed principal: **₹11,25,000**
- Disbursement date: **2022-05-31**
- Repayment starts: **2022-06**
- Tenure: **15 years**

## What the app does

- Auto month sequence from `2022-06` onward.
- Auto-calculated columns in entry table:
   - `Principal from EMI (auto)`
   - `Interest % p.a. (auto)`
- Summary of total paid, principal, interest, and current outstanding.
- Projection toggle for future schedule.
- Pie charts and trend charts.
- CSV export of full amortization.
- Saves data to `data/loan_data.json`.

## Local run

```powershell
python -m pip install -r requirements.txt --upgrade
python -m streamlit run app.py
```

## Permanent deployment (recommended)

### Option A: Streamlit Community Cloud (free + easiest)

1. Push this repo to GitHub.
2. Go to Streamlit Community Cloud.
3. Click **New app** and select your repo.
4. Set main file path to `app.py`.
5. Deploy.

After that, you get a permanent URL and every GitHub push auto-redeploys.

### Option B: Render / other cloud

- Build command: install from `requirements.txt`
- Start command: `python -m streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`

## Keep everything in repo

This repo now includes deployment-ready files:

- `.streamlit/config.toml` (host-friendly Streamlit config + theme)
- `.gitignore` (clean repo; keeps core project files)
- `runtime.txt` (Python runtime pin for hosted environment)

If you want your actual loan history versioned too, commit `data/loan_data.json`.

## Permanent data on Streamlit Cloud (important)

By default, files written on Streamlit Cloud reset on every redeploy/restart.
To make your entries **permanent**, this app can save data back to GitHub
(`data/loan_data.json`) using the GitHub API.

### One-time setup

1. Create a **fine-grained Personal Access Token**:
   - Go to https://github.com/settings/tokens?type=beta
   - **Repository access**: only `Home-Loan-Tracker`
   - **Permissions → Contents**: Read and write
   - Generate and copy the token.

2. In Streamlit Cloud → your app → **Settings → Secrets**, paste:

   ```toml
   [github]
   token = "ghp_your_token_here"
   repo = "starksteve/Home-Loan-Tracker"
   path = "data/loan_data.json"
   branch = "main"
   ```

3. Save. The app will now read/write your loan data directly in GitHub,
   so it survives redeploys and every device sees the same data.

> Running locally? Copy `.streamlit/secrets.toml.example` to
> `.streamlit/secrets.toml` and fill the token (this file is gitignored).
> Without secrets, the app just uses the local `data/loan_data.json` file.

## Tests

```powershell
python -m pytest -q
```
