from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file('credentials.json')
client = bigquery.Client(PROJECT = PROJECT_ID, credentials=creds)
T = f'{PROJECT_ID}.bronze.mart_pricing_intelligence'

q = f"""
SELECT
  ROUND(MIN(price_opportunity_score),1) as opp_min,
  ROUND(AVG(price_opportunity_score),1) as opp_avg,
  ROUND(MAX(price_opportunity_score),1) as opp_max,
  ROUND(MIN(markdown_risk_score),1) as mdr_min,
  ROUND(AVG(markdown_risk_score),1) as mdr_avg,
  ROUND(MAX(markdown_risk_score),1) as mdr_max,
  ROUND(MIN(pricing_power_score),1) as pp_min,
  ROUND(AVG(pricing_power_score),1) as pp_avg,
  ROUND(MAX(pricing_power_score),1) as pp_max,
  ROUND(MIN(competitive_threat_risk),1) as ctr_min,
  ROUND(AVG(competitive_threat_risk),1) as ctr_avg,
  ROUND(MAX(competitive_threat_risk),1) as ctr_max,
  ROUND(MIN(demand_gap_score),1) as dg_min,
  ROUND(AVG(demand_gap_score),1) as dg_avg,
  ROUND(MAX(demand_gap_score),1) as dg_max
FROM `{T}`
"""

for r in client.query(q).result():
    d = dict(r)
    print(f"price_opportunity:   min={d['opp_min']} avg={d['opp_avg']} max={d['opp_max']}")
    print(f"markdown_risk:       min={d['mdr_min']} avg={d['mdr_avg']} max={d['mdr_max']}")
    print(f"pricing_power:       min={d['pp_min']}  avg={d['pp_avg']}  max={d['pp_max']}")
    print(f"competitive_threat:  min={d['ctr_min']} avg={d['ctr_avg']} max={d['ctr_max']}")
    print(f"demand_gap:          min={d['dg_min']}  avg={d['dg_avg']}  max={d['dg_max']}")
