import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PROJECT_ID, DATASET, CREDENTIALS_PATH

from google.oauth2 import service_account
from google.cloud import bigquery

creds = service_account.Credentials.from_service_account_file(
    CREDENTIALS_PATH, scopes=["https://www.googleapis.com/auth/bigquery"]
)
client = bigquery.Client(project=PROJECT_ID, credentials=creds)
rows = list(client.query(
    f"SELECT DISTINCT opportunity_tier, COUNT(*) as cnt "
    f"FROM `{PROJECT_ID}.{DATASET}.mart_action_queue` "
    f"GROUP BY 1 ORDER BY 2 DESC"
).result())
for r in rows:
    print(r["opportunity_tier"], r["cnt"])
