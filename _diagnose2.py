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

print("=== Source count distribution in mart_confidence_layer ===")
df = q(f"""
    SELECT source_count,
           COUNT(*) as row_count,
           ROUND(AVG(overall_confidence_score), 1) as avg_confidence,
           MIN(overall_confidence_score) as min_conf,
           MAX(overall_confidence_score) as max_conf
    FROM `{P}.{D}.mart_confidence_layer`
    GROUP BY source_count
    ORDER BY source_count
""")
print(df.to_string(index=False))

print()
print("=== fact_market_signals: which months have retail_price populated? ===")
df2 = q(f"""
    SELECT
        f.reference_month_str,
        COUNT(*) as total_rows,
        COUNTIF(retail_price IS NOT NULL) as has_price,
        COUNTIF(ppi_value IS NOT NULL) as has_ppi,
        COUNTIF(cpi_value IS NOT NULL) as has_cpi
    FROM (
        SELECT
            FORMAT_DATE('%Y-%m', date_key_decoded) as reference_month_str,
            retail_price, ppi_value, cpi_value
        FROM `{P}.{D}.fact_market_signals` f
        JOIN `{P}.{D}.dim_date` d ON f.date_key = d.date_key
    )
    GROUP BY 1
    ORDER BY 1
    LIMIT 30
""")
print(df2.to_string(index=False))
