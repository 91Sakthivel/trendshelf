# TrendShelf — Setup Guide

## Prerequisites
- Python 3.12
- Google Cloud account with BigQuery enabled and a service-account JSON key
- Kroger Developer API credentials (https://developer.kroger.com)
- SerpAPI account — free tier: 100 searches/month (https://serpapi.com)
- FRED API key — free (https://fred.stlouisfed.org/docs/api/api_key.html)

## Quick Start

### 1. Clone the repo
```bash
git clone https://github.com/91Sakthivel/trendshelf
cd trendshelf
```

### 2. Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Mac / Linux
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 5. Add BigQuery credentials
Place your service-account JSON file as `credentials.json` in the project root.

### 6. Export env vars for dbt (profiles.yml uses env_var())
```bash
# Windows PowerShell
$env:GCP_PROJECT_ID = (Get-Content .env | Select-String "GCP_PROJECT_ID").ToString().Split("=")[1]
$env:GCP_DATASET    = "bronze"
$env:GCP_CREDENTIALS_PATH = "credentials.json"

# Mac / Linux
export $(grep -v '^#' .env | xargs)
```

### 7. Run dbt
```bash
dbt deps
dbt run --profiles-dir .
dbt test --profiles-dir .
```

### 8. Collect data (optional — existing BigQuery data already present)
```bash
python collect_apis.py
```

### 9. Launch dashboard
```bash
streamlit run dashboard/app.py
```
Dashboard runs at http://localhost:8501

---

## Data Collection Schedule

| Source | Cadence | Notes |
|--------|---------|-------|
| Kroger prices | Monthly | 200 API calls per run (20 stores × 10 categories) |
| Google Trends | Monthly | Rate-limited — wait 2+ hours between full runs |
| FRED PPI | Monthly | Government lag ~2 months |
| BLS CPI | Monthly | Government lag ~2 months |
| SerpAPI Walmart | Monthly | 10 searches/run; 80/month on free tier |

## API Quota Notes
- **Google Trends**: `COLLECT_GOOGLE_TRENDS=False` by default to protect quota. Enable manually when refreshing.
- **SerpAPI**: 80 searches/month on free tier. Script limits to 10 searches/run with 7-day category cache.
- **Kroger API**: No rate limit issues observed at 200 calls/month.
- **FRED / BLS**: Public APIs — no significant rate limits.

## dbt Score Weights
All scoring thresholds and weights are centralized in `dbt_project.yml` under `vars:`.
To tune thresholds after accumulating 6+ months of data, edit the vars block and re-run `dbt run`.
