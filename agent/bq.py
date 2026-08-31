"""
agent/bq.py -- shared read-only BigQuery client for every agent tool.

Every tool query goes through run_query() so config.AGENT_MAX_BYTES_BILLED
is applied uniformly -- no tool can accidentally issue an unbounded query.
"""

from google.cloud import bigquery
from google.oauth2 import service_account

import config

_client: bigquery.Client | None = None


def get_client() -> bigquery.Client:
    global _client
    if _client is None:
        creds = service_account.Credentials.from_service_account_file(
            config.AGENT_CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        _client = bigquery.Client(project=config.PROJECT_ID, credentials=creds)
    return _client


def run_query(sql: str, params: list | None = None) -> list[bigquery.table.Row]:
    job_config = bigquery.QueryJobConfig(
        query_parameters=params or [],
        maximum_bytes_billed=config.AGENT_MAX_BYTES_BILLED,
    )
    return list(get_client().query(sql, job_config=job_config).result())
