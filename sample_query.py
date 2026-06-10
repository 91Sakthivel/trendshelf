from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file('credentials.json')
client = bigquery.Client(PROJECT = PROJECT_ID, credentials=creds)

q = """SELECT
  recommended_action,
  decision_strength,
  reason_code,
  LEFT(action_reason, 120) as action_reason_preview
FROM `{PROJECT_ID}.bronze.mart_action_queue`
ORDER BY action_priority
LIMIT 10"""

for r in client.query(q).result():
    d = dict(r)
    print(f"[{d['recommended_action']}] [{d['decision_strength']}] code={d['reason_code']}")
    print(f"  reason: {d['action_reason_preview']}")
    print()

