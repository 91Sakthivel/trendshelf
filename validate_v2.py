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

# Q1: velocity Ã— lifecycle Ã— opportunity_tier Ã— macro_risk_flag distribution
run('Q1: Velocity x Lifecycle x Opportunity Tier x Macro Risk', f"""
SELECT
  demand_velocity_direction,
  category_lifecycle,
  opportunity_tier,
  macro_risk_flag,
  COUNT(*) as row_count
FROM `{P}.{D}.mart_action_queue`
GROUP BY 1,2,3,4
ORDER BY row_count DESC
LIMIT 15
""")

# Q2: overall_opportunity_score by category
run('Q2: Opportunity score by category', f"""
SELECT
  aq.category_name,
  ROUND(AVG(aq.overall_opportunity_score), 1) as avg_opportunity_score,
  MIN(aq.opportunity_tier) as opportunity_tier,
  COUNT(*) as store_count
FROM `{P}.{D}.mart_action_queue` aq
JOIN `{P}.{D}.dim_category` dc ON aq.category_name = dc.category_name
GROUP BY 1
ORDER BY avg_opportunity_score DESC
""")

# Q3: seasonality guard check
run('Q3: Seasonality guard â€” rows where action was downgraded', f"""
SELECT
  category_name,
  action_type,
  seasonality_adjusted_action,
  seasonality_flag,
  overall_confidence_score,
  COUNT(*) as row_count
FROM `{P}.{D}.mart_action_queue`
WHERE seasonality_flag = 'Possible Seasonal Spike'
GROUP BY 1,2,3,4,5
ORDER BY row_count DESC
LIMIT 10
""")

# Q4: demand_reason_code and risk_reason_code distribution
run('Q4: Reason code distributions', f"""
SELECT
  demand_reason_code,
  risk_reason_code,
  COUNT(*) as row_count
FROM `{P}.{D}.mart_action_queue`
GROUP BY 1,2
ORDER BY row_count DESC
""")

# Q5: competitive_intensity distribution in mart_pricing_intelligence
run('Q5: competitive_intensity in mart_pricing_intelligence', f"""
SELECT
  competitive_intensity,
  COUNT(*) as row_count,
  ROUND(AVG(pricing_power_score), 1) as avg_power,
  COUNT(DISTINCT category_name) as categories
FROM `{P}.{D}.mart_pricing_intelligence`
GROUP BY 1
ORDER BY row_count DESC
""")
