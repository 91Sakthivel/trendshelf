"""One-off: re-collect produce category with 'bagged salad mix' query."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from config import PROJECT_ID
import requests
import datetime
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from datetime import timezone
from test_apis import SERPAPI_KEY

PROJECT = PROJECT_ID
DATASET = 'bronze'
TABLE   = f'{PROJECT}.{DATASET}.serpapi_prices_raw'

creds = service_account.Credentials.from_service_account_file(
    'credentials.json',
    scopes=['https://www.googleapis.com/auth/bigquery'],
)
client = bigquery.Client(project=PROJECT, credentials=creds)
RUN_TS = datetime.datetime.now(timezone.utc)

resp = requests.get(
    'https://serpapi.com/search',
    params={
        'engine':   'walmart',
        'query':    'bagged salad mix',
        'store_id': '2105',
        'api_key':  SERPAPI_KEY,
        'sort':     'best_match',
    },
    timeout=15,
)
resp.raise_for_status()
results = resp.json().get('organic_results', [])

rows = []
prices = []
for item in results:
    if item.get('out_of_stock') or item.get('sponsored'):
        continue
    primary = item.get('primary_offer', {})
    price = primary.get('offer_price')
    if not price:
        # fallback to top-level price field
        raw = item.get('price', '')
        try:
            price = float(str(raw).replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            price = None
    if not price or float(price) <= 0:
        continue
    price_float = float(price)
    prices.append(price_float)
    rows.append({
        'product_name':       item.get('title', '')[:500],
        'competitor_store':   'Walmart DFW',
        'walmart_store_id':   '2105',
        'competitor_price':   price_float,
        'price_per_unit':     None,
        'price_per_unit_str': None,
        'category':           'produce',
        'search_query':       'bagged salad mix',
        'search_date':        datetime.date.today(),
        'collected_at':       RUN_TS,
        'load_timestamp':     RUN_TS,
    })

print(f'Raw results: {len(results)}  |  Usable prices: {len(rows)}')

if not rows:
    print('ERROR: no rows parsed â€” check API response')
    raise SystemExit(1)

df = pd.DataFrame(rows)
df['competitor_price'] = pd.to_numeric(df['competitor_price'], errors='coerce')
df['price_per_unit']   = pd.to_numeric(df['price_per_unit'],   errors='coerce')

# DML not available on free tier â€” read full table, drop old produce rows, rewrite
existing = client.query(f'SELECT * FROM `{TABLE}`').to_dataframe()
print(f'Existing rows: {len(existing)}  (produce: {(existing["category"] == "produce").sum()})')
non_produce = existing[existing['category'] != 'produce'].copy()
combined = pd.concat([non_produce, df], ignore_index=True)
print(f'Combined rows after swap: {len(combined)}')

job_config = bigquery.LoadJobConfig(write_disposition='WRITE_TRUNCATE')
client.load_table_from_dataframe(combined, TABLE, job_config=job_config).result()

print(f'Done â€” {len(df)} produce rows uploaded')
print(f'Avg price : ${df["competitor_price"].mean():.2f}')
print(f'Min price : ${df["competitor_price"].min():.2f}')
print(f'Max price : ${df["competitor_price"].max():.2f}')
print()
print('Top 5 products:')
for _, r in df.nsmallest(5, 'competitor_price').iterrows():
    print(f'  ${r["competitor_price"]:.2f}  {r["product_name"][:80]}')
