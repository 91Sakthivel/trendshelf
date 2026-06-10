from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file('credentials.json')
client = bigquery.Client(PROJECT = PROJECT_ID, credentials=creds)
P = PROJECT_ID
D = 'bronze'
T = f'{P}.{D}.mart_pricing_intelligence'

def run(label, sql):
    print(f'\n=== {label} ===')
    for r in client.query(sql).result():
        print(dict(r))

run('Q1: Row count and coverage', f"""
SELECT
  COUNT(*) as total_rows,
  COUNTIF(competitor_avg_price IS NULL) as no_competitor_price,
  COUNTIF(competitor_avg_price IS NOT NULL) as has_competitor_price,
  COUNTIF(signal_type = 'MEASURED') as measured_rows,
  COUNTIF(signal_type = 'PROXY') as proxy_rows
FROM `{T}`
""")

run('Q2: Price action distribution', f"""
SELECT
  recommended_price_action,
  price_action_confidence,
  signal_type,
  COUNT(*) as row_count,
  ROUND(COUNT(*) / SUM(COUNT(*)) OVER() * 100, 1) as pct
FROM `{T}`
GROUP BY 1, 2, 3
ORDER BY row_count DESC
""")

run('Q3: Price position breakdown', f"""
SELECT
  price_position,
  ROUND(AVG(kroger_avg_price), 2) as avg_kroger_price,
  ROUND(AVG(competitor_avg_price), 2) as avg_competitor_price,
  ROUND(AVG(price_gap_pct), 1) as avg_gap_pct,
  COUNT(*) as row_count
FROM `{T}`
GROUP BY 1
ORDER BY row_count DESC
""")

run('Q4: Sample 5 rows with reasons', f"""
SELECT
  store_city,
  category_name,
  price_position,
  recommended_price_action,
  price_action_confidence,
  price_action_reason,
  reason_code
FROM `{T}`
ORDER BY price_opportunity_score DESC
LIMIT 5
""")
