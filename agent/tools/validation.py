"""
agent/tools/validation.py -- identifier existence checks against the dims.

Distinguishes "store_id/category doesn't exist" (a typo -- a real error)
from "exists but has no data for this period" (a valid NULL/found=False
result). See the Phase 2 proposal, point 3.

Deliberately NOT a hardcoded Literal/enum against config.py's KROGER_STORES
/ CATEGORIES -- those lists can grow without a schema redeploy, and dim_
location / dim_category are already the single source of truth dbt itself
derives from staging data.
"""

from google.cloud import bigquery

from agent import bq
import config


def store_exists(store_id: str) -> bool:
    rows = bq.run_query(
        f"SELECT 1 FROM `{config.PROJECT_ID}.{config.DATASET}.dim_location` "
        f"WHERE store_id = @store_id LIMIT 1",
        params=[bigquery.ScalarQueryParameter("store_id", "STRING", store_id)],
    )
    return len(rows) > 0


def category_exists(category: str) -> bool:
    rows = bq.run_query(
        f"SELECT 1 FROM `{config.PROJECT_ID}.{config.DATASET}.dim_category` "
        f"WHERE category_name = @category LIMIT 1",
        params=[bigquery.ScalarQueryParameter("category", "STRING", category)],
    )
    return len(rows) > 0
