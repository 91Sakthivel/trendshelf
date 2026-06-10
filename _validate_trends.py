from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID, DATASET
from google.oauth2 import service_account
import warnings
warnings.filterwarnings("ignore")

creds = service_account.Credentials.from_service_account_file(
    'credentials.json', scopes=['https://www.googleapis.com/auth/bigquery'])
bq = bigquery.Client(project=PROJECT_ID, credentials=creds)

df = bq.query("""
    SELECT
        search_keyword,
        category,
        COUNT(*) as row_count,
        MIN(trend_date) as earliest,
        MAX(trend_date) as latest
    FROM `{PROJECT_ID}.bronze.google_trends_raw`
    GROUP BY 1, 2
    ORDER BY 2
""").to_dataframe()

print(df.to_string(index=False))
print(f"\nTotal rows : {df['row_count'].sum():,}")
print(f"Categories : {df['category'].nunique()}/10")
