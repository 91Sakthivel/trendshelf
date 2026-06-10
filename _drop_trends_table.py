"""Drop google_trends_raw so the next WRITE_APPEND recreates it with the new schema."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID, DATASET
from google.cloud import bigquery
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file(
    'credentials.json', scopes=['https://www.googleapis.com/auth/bigquery'])
bq = bigquery.Client(project=PROJECT_ID, credentials=creds)

tbl = f'{PROJECT_ID}.{DATASET}.google_trends_raw'
bq.delete_table(tbl, not_found_ok=True)
print(f"Dropped: {tbl}")
print("Next collect_apis.py run will recreate with the new schema (+ category column).")
