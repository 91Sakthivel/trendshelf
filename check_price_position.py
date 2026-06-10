from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file('credentials.json')
client = bigquery.Client(PROJECT = PROJECT_ID, credentials=creds)
T = f'{PROJECT_ID}.bronze.mart_pricing_intelligence'

print('=== Price position breakdown ===')
for r in client.query(f"""
SELECT
  price_position,
  ROUND(AVG(kroger_avg_price), 2) as avg_kroger,
  ROUND(AVG(competitor_avg_price), 2) as avg_walmart,
  ROUND(AVG(price_gap_pct), 1) as avg_gap_pct,
  COUNT(*) as row_count
FROM `{T}`
GROUP BY 1
ORDER BY row_count DESC
""").result():
    print(dict(r))

print()
print('=== Price action distribution ===')
for r in client.query(f"""
SELECT
  recommended_price_action,
  COUNT(*) as row_count,
  ROUND(COUNT(*) / SUM(COUNT(*)) OVER() * 100, 1) as pct
FROM `{T}`
GROUP BY 1
ORDER BY row_count DESC
""").result():
    print(dict(r))

print()
print('=== Category-level price gap (top 10 by opportunity score) ===')
for r in client.query(f"""
SELECT
  category_name,
  price_position,
  ROUND(AVG(kroger_avg_price), 2) as avg_kroger,
  ROUND(AVG(competitor_avg_price), 2) as avg_walmart,
  ROUND(AVG(price_gap_pct), 1) as avg_gap_pct,
  recommended_price_action,
  COUNT(*) as row_count
FROM `{T}`
GROUP BY 1,2,6
ORDER BY AVG(price_opportunity_score) DESC
LIMIT 10
""").result():
    print(dict(r))
