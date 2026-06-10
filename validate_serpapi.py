from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file('credentials.json')
client = bigquery.Client(PROJECT = PROJECT_ID, credentials=creds)
P = PROJECT_ID
D = 'bronze'

def run(label, sql):
    print(f'\n=== {label} ===')
    for r in client.query(sql).result():
        print(dict(r))

run('Q1: Raw table check', f"""
SELECT
  category,
  competitor_store,
  walmart_store_id,
  COUNT(*) as products,
  ROUND(AVG(competitor_price), 2) as avg_price,
  ROUND(MIN(competitor_price), 2) as min_price,
  ROUND(MAX(competitor_price), 2) as max_price,
  COUNTIF(price_per_unit IS NOT NULL) as has_unit_price
FROM `{P}.{D}.serpapi_prices_raw`
GROUP BY 1, 2, 3
ORDER BY 1
""")

run('Q2: Price position breakdown (mart_pricing_intelligence)', f"""
SELECT
  price_position,
  ROUND(AVG(kroger_avg_price), 2) as avg_kroger,
  ROUND(AVG(competitor_avg_price), 2) as avg_walmart,
  ROUND(AVG(price_gap_pct), 1) as avg_gap_pct,
  COUNT(*) as row_count
FROM `{P}.{D}.mart_pricing_intelligence`
GROUP BY 1
ORDER BY row_count DESC
""")

run('Q3: Price action distribution (mart_pricing_intelligence)', f"""
SELECT
  recommended_price_action,
  action_confidence_level,
  signal_type,
  COUNT(*) as row_count,
  ROUND(COUNT(*) / SUM(COUNT(*)) OVER() * 100, 1) as pct
FROM `{P}.{D}.mart_pricing_intelligence`
GROUP BY 1, 2, 3
ORDER BY row_count DESC
""")
