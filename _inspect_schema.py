from google.cloud import bigquery
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID, DATASET
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file(
    'credentials.json', scopes=['https://www.googleapis.com/auth/bigquery'])
bq = bigquery.Client(project=PROJECT_ID, credentials=creds)

tables = list(bq.list_tables(f'{PROJECT_ID}.{DATASET}'))
print('Tables in bronze:')
for t in tables:
    print(f'  {t.table_id}')
print()

for t in tables:
    tbl_ref = f'{PROJECT_ID}.{DATASET}.{t.table_id}'
    try:
        schema = bq.get_table(tbl_ref)
        cols = [f.name for f in schema.schema]
        cnt = bq.query(f'SELECT COUNT(*) as n FROM `{tbl_ref}`').to_dataframe()['n'][0]
        print(f'{t.table_id} ({cnt:,} rows):')
        print(f'  {cols}')
        print()
    except Exception as e:
        print(f'{t.table_id}: ERROR - {e}')
