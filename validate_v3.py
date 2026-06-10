from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file('credentials.json')
client = bigquery.Client(PROJECT = PROJECT_ID, credentials=creds)
T = f'{PROJECT_ID}.bronze.mart_pricing_intelligence'

def run(label, sql):
    print(f'\n=== {label} ===')
    for r in client.query(sql).result():
        print(dict(r))

# Q1: Intelligence layer â€” category Ã— elasticity Ã— demand Ã— situation Ã— action Ã— confidence
run('Q1: Intelligence layer per category', f"""
SELECT
  category_name,
  elasticity_tier,
  demand_signal,
  pricing_situation,
  recommended_price_action,
  action_confidence_level,
  COUNT(*) as store_count,
  ROUND(AVG(pricing_power_score), 1) as avg_power,
  ROUND(AVG(adjusted_price_gap_pct), 1) as avg_adj_gap
FROM `{T}`
GROUP BY 1,2,3,4,5,6
ORDER BY category_name, recommended_price_action
""")

# Q2: Price action distribution with intensity and confidence
run('Q2: Action distribution', f"""
SELECT
  recommended_price_action,
  action_confidence_level,
  price_reduction_intensity,
  COUNT(*) as row_count,
  ROUND(COUNT(*) / SUM(COUNT(*)) OVER() * 100, 1) as pct
FROM `{T}`
GROUP BY 1,2,3
ORDER BY row_count DESC
""")

# Q3: Top 5 most actionable rows (non-Monitor/Investigate, ordered by confidence + power)
run('Q3: Top 5 most actionable rows', f"""
SELECT
  category_name,
  store_city,
  recommended_price_action,
  price_reduction_intensity,
  action_confidence_level,
  ROUND(pricing_power_score, 1)      as power,
  ROUND(kroger_avg_price, 2)         as kroger_price,
  ROUND(competitor_avg_price, 2)     as walmart_price,
  ROUND(adjusted_price_gap_pct, 1)   as adj_gap_pct,
  price_gap_confidence,
  elasticity_tier,
  pricing_situation,
  price_action_reason
FROM `{T}`
WHERE recommended_price_action NOT IN ('Monitor', 'Investigate')
ORDER BY action_confidence_score DESC, pricing_power_score DESC
LIMIT 5
""")
