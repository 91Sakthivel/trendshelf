from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID, DATASET
from google.oauth2 import service_account
import warnings
warnings.filterwarnings("ignore")

creds = service_account.Credentials.from_service_account_file(
    'credentials.json', scopes=['https://www.googleapis.com/auth/bigquery'])
bq = bigquery.Client(project=PROJECT_ID, credentials=creds)

def q(sql):
    return bq.query(sql).to_dataframe()

P = PROJECT_ID
D = "bronze"

print("CONFIDENCE LEVEL BREAKDOWN:")
df3b = q(f"""
    SELECT
        confidence_level,
        COUNT(*) as row_count,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct,
        ROUND(AVG(overall_confidence_score), 1) as avg_score
    FROM `{P}.{D}.mart_confidence_layer`
    GROUP BY confidence_level
    ORDER BY avg_score DESC
""")
print(df3b.to_string(index=False))

print()
print("=" * 65)
print("VALIDATION 4 â€” mart_action_queue action type breakdown")
print("=" * 65)
df4 = q(f"""
    SELECT
        action_type,
        COUNT(*) as row_count,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
    FROM `{P}.{D}.mart_action_queue`
    GROUP BY action_type
    ORDER BY row_count DESC
""")
print(df4.to_string(index=False))

print()
print("=" * 65)
print("VALIDATION 5 â€” competitor_avg_price coverage in confidence layer")
print("=" * 65)
df5 = q(f"""
    SELECT
        COUNTIF(competitor_avg_price IS NULL) as no_competitor_price,
        COUNTIF(competitor_avg_price IS NOT NULL) as has_competitor_price,
        COUNT(*) as total,
        ROUND(COUNTIF(competitor_avg_price IS NOT NULL) * 100.0 / COUNT(*), 1) as coverage_pct
    FROM `{P}.{D}.mart_confidence_layer`
""")
print(df5.to_string(index=False))

print()
print("=" * 65)
print("VALIDATION 6 â€” mart_demand_gap_scores null rates")
print("=" * 65)
df6 = q(f"""
    SELECT
        COUNT(*) as total,
        COUNTIF(retail_price IS NULL) as retail_null,
        COUNTIF(cpi_value IS NULL) as cpi_null,
        COUNTIF(ppi_value IS NULL) as ppi_null,
        ROUND(COUNTIF(retail_price IS NULL) / COUNT(*) * 100, 1) as retail_null_pct,
        ROUND(COUNTIF(cpi_value IS NULL) / COUNT(*) * 100, 1) as cpi_null_pct,
        ROUND(COUNTIF(ppi_value IS NULL) / COUNT(*) * 100, 1) as ppi_null_pct
    FROM `{P}.{D}.mart_demand_gap_scores`
""")
print(df6.to_string(index=False))

print()
print("=" * 65)
print("VALIDATION 7 â€” action_type by urgency")
print("=" * 65)
df7 = q(f"""
    SELECT
        action_type,
        urgency,
        COUNT(*) as row_count,
        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
    FROM `{P}.{D}.mart_action_queue`
    GROUP BY 1, 2
    ORDER BY row_count DESC
""")
print(df7.to_string(index=False))

print()
print("=" * 65)
print("NOTE â€” fact_market_signals: cpi/ppi null")
print("=" * 65)
df8 = q(f"""
    SELECT
        COUNT(*) as total,
        COUNTIF(retail_price IS NOT NULL) as has_retail,
        COUNTIF(ppi_value IS NOT NULL) as has_ppi,
        COUNTIF(cpi_value IS NOT NULL) as has_cpi,
        MIN(DATE(load_timestamp)) as loaded_date
    FROM `{P}.{D}.fact_market_signals`
""")
print(df8.to_string(index=False))
print()
print("Explanation: June 2026 has no FRED/BLS data yet (both lag ~2 months).")
print("PPI and CPI for June 2026 will populate on next monthly collect run.")
