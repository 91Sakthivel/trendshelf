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

print("=" * 65)
print("DIAG 1a â€” fact_market_signals null counts")
print("=" * 65)
df = q(f"""
    SELECT
        COUNT(*) as total_rows,
        COUNTIF(retail_price IS NULL) as null_count,
        COUNTIF(retail_price IS NOT NULL) as populated_count
    FROM `{P}.{D}.fact_market_signals`
""")
print(df.to_string(index=False))

print()
print("=" * 65)
print("DIAG 1b â€” stg_kroger_prices categories")
print("=" * 65)
df_kc = q(f"SELECT DISTINCT category FROM `{P}.{D}.stg_kroger_prices` ORDER BY 1")
print(df_kc.to_string(index=False))

print()
print("=" * 65)
print("DIAG 1c â€” fact_market_signals category_key values (join side)")
print("=" * 65)
df_fc = q(f"""
    SELECT f.category_key, dc.category_name
    FROM `{P}.{D}.fact_market_signals` f
    LEFT JOIN `{P}.{D}.dim_category` dc ON f.category_key = dc.category_key
    GROUP BY 1, 2
    ORDER BY 1
""")
print(df_fc.to_string(index=False))

print()
print("=" * 65)
print("DIAG 1d â€” dim_category contents")
print("=" * 65)
df_dim = q(f"SELECT * FROM `{P}.{D}.dim_category` ORDER BY category_key")
print(df_dim.to_string(index=False))

print()
print("=" * 65)
print("DIAG 1e â€” sample of kroger join keys (store_id, category)")
print("=" * 65)
df_kk = q(f"""
    SELECT store_id, category, COUNT(*) as cnt
    FROM `{P}.{D}.stg_kroger_prices`
    GROUP BY 1, 2
    ORDER BY 1, 2
    LIMIT 20
""")
print(df_kk.to_string(index=False))

print()
print("=" * 65)
print("DIAG 1f â€” sample of fact_market_signals join keys")
print("=" * 65)
df_fk = q(f"""
    SELECT location_key, category_key, date_key, COUNT(*) as cnt
    FROM `{P}.{D}.fact_market_signals`
    GROUP BY 1, 2, 3
    ORDER BY 1, 2, 3
    LIMIT 20
""")
print(df_fk.to_string(index=False))

print()
print("=" * 65)
print("DIAG 2 â€” stg_bls_cpi columns and sample")
print("=" * 65)
df_bls = q(f"SELECT * FROM `{P}.{D}.stg_bls_cpi` LIMIT 5")
print(df_bls.to_string(index=False))

print()
print("DIAG 2b â€” BLS CPI distinct period/category info")
df_bls2 = q(f"""
    SELECT reference_date, period_name, cpi_value, series_id
    FROM `{P}.{D}.stg_bls_cpi`
    ORDER BY reference_date DESC
    LIMIT 8
""")
print(df_bls2.to_string(index=False))

print()
print("=" * 65)
print("DIAG 3 â€” mart_confidence_layer competitor_avg_price nulls")
print("=" * 65)
df_cl = q(f"""
    SELECT
        COUNTIF(competitor_avg_price IS NULL)     as no_competitor_price,
        COUNTIF(competitor_avg_price IS NOT NULL) as has_competitor_price,
        COUNT(*) as total
    FROM `{P}.{D}.mart_confidence_layer`
""")
print(df_cl.to_string(index=False))

print()
print("DIAG 3b â€” confidence score distribution")
df_conf = q(f"""
    SELECT
        ROUND(overall_confidence_score / 10) * 10 as score_bucket,
        COUNT(*) as cnt
    FROM `{P}.{D}.mart_confidence_layer`
    GROUP BY 1
    ORDER BY 1
""")
print(df_conf.to_string(index=False))

print()
print("DIAG 3c â€” source counts distribution (how many sources per row?)")
df_src = q(f"""
    SELECT source_count,
           COUNT(*) as rows,
           ROUND(AVG(overall_confidence_score), 1) as avg_confidence
    FROM `{P}.{D}.mart_confidence_layer`
    GROUP BY 1
    ORDER BY 1
""")
print(df_src.to_string(index=False))
