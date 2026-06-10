"""Check remaining SerpAPI quota before collection run."""
import requests
from test_apis import SERPAPI_KEY

resp = requests.get(
    "https://serpapi.com/account",
    params={"api_key": SERPAPI_KEY},
    timeout=10,
)
resp.raise_for_status()
d = resp.json()
print(f"Plan:            {d.get('plan_name')}")
print(f"Searches used:   {d.get('searches_per_month_used')}")
print(f"Searches left:   {d.get('searches_per_month_remaining')}")
print(f"Account email:   {d.get('account_email')}")
