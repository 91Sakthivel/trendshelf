"""
BigQuery schema creation + idempotent load.

Dataset: rag_corpus (same project as `bronze`, separate dataset — not part
of the dbt DAG, never referenced by any model).

Idempotency: each document's chunks are deleted-then-reinserted, scoped to
that document_id, every run. Re-running produces byte-identical output, not
duplicates.

content_hash drift policy (per source_class):
  - external: FAIL the run. Upstream content changed; report it, don't
    silently ingest a changed external source.
  - internal: auto-reingest. Our own docs changing is expected and desired.

contains_numeric_claim ASSERTION (not just an audit flag): any external
chunk flagged contains_numeric_claim=TRUE MUST have a non-null source_url.
Fails the load otherwise — every retrievable external number must be
structurally traceable to its origin.
"""

import hashlib
import re
from datetime import datetime, timezone

from google.cloud import bigquery

DATASET = "rag_corpus"

NUMERIC_CLAIM_PATTERN = re.compile(
    r"\$\s?\d|\d+(\.\d+)?\s?%|\b\d{1,3}(,\d{3})+(\.\d+)?\b|\b\d+\.\d+\b|"
    r"\b\d+\s?(million|billion|basis points|bps)\b",
    re.IGNORECASE,
)


class LoadError(Exception):
    pass


def contains_numeric_claim(text: str) -> bool:
    return bool(NUMERIC_CLAIM_PATTERN.search(text))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(document_id: str, chunk_index: int) -> str:
    return sha256(f"{document_id}:{chunk_index}")


DOCUMENTS_SCHEMA = [
    bigquery.SchemaField("document_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_class", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_tier", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("doc_title", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_url", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("published_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("retrieved_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("fetch_method", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_text", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("content_hash", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]

CHUNKS_SCHEMA = [
    bigquery.SchemaField("chunk_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("document_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("chunk_index", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("chunk_text", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("token_count", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("section_heading", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
    bigquery.SchemaField("embedding_model", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("embedding_dim", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("contains_numeric_claim", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("fetch_method", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_class", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_tier", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("doc_title", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_url", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("published_date", "DATE", mode="NULLABLE"),
    bigquery.SchemaField("retrieved_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
]


def ensure_dataset_and_tables(client: bigquery.Client, project: str):
    dataset_ref = bigquery.DatasetReference(project, DATASET)
    try:
        ds = client.get_dataset(dataset_ref)
    except Exception:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = "US"
        ds = client.create_dataset(ds)
    assert ds.default_table_expiration_ms is None, (
        f"rag_corpus dataset has a default_table_expiration_ms set "
        f"({ds.default_table_expiration_ms}) — refusing to proceed, this "
        f"would silently expire every table created in it."
    )

    for table_name, schema in [("documents", DOCUMENTS_SCHEMA), ("chunks", CHUNKS_SCHEMA)]:
        table_ref = bigquery.TableReference(dataset_ref, table_name)
        try:
            table = client.get_table(table_ref)
        except Exception:
            table = bigquery.Table(table_ref, schema=schema)
            table.expires = None
            table = client.create_table(table)
        assert table.expires is None, (
            f"rag_corpus.{table_name} has an expiration_timestamp set "
            f"({table.expires}) — this is the exact sandbox-TTL failure mode "
            f"this pipeline is required to guard against. Refusing to load."
        )

    # staleness view — computed at query time, never stored (see design doc)
    view_ref = bigquery.TableReference(dataset_ref, "chunks_with_staleness")
    view = bigquery.Table(view_ref)
    view.view_query = f"""
        SELECT *,
          CASE source_tier
            WHEN 'earnings_call'     THEN DATE_DIFF(CURRENT_DATE(), published_date, DAY) > 120
            WHEN 'sec_filing'        THEN DATE_DIFF(CURRENT_DATE(), published_date, DAY) > 400
            WHEN 'industry_research' THEN DATE_DIFF(CURRENT_DATE(), published_date, DAY) > 180
            WHEN 'gov_methodology'   THEN FALSE
            WHEN 'internal_doc'      THEN FALSE
            ELSE NULL
          END AS staleness_flag
        FROM `{project}.{DATASET}.chunks`
    """
    try:
        client.get_table(view_ref)
    except Exception:
        client.create_table(view)


def get_existing_document(client: bigquery.Client, project: str, document_id: str):
    query = f"""
        SELECT document_id, source_class, content_hash
        FROM `{project}.{DATASET}.documents`
        WHERE document_id = @doc_id
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("doc_id", "STRING", document_id)]
        ),
    )
    rows = list(job.result())
    return rows[0] if rows else None


def load_document_and_chunks(client: bigquery.Client, project: str, document: dict, chunks: list[dict]):
    """document: dict matching DOCUMENTS_SCHEMA fields (minus ingested_at).
    chunks: list of dicts matching CHUNKS_SCHEMA fields (minus chunk_id/ingested_at)."""

    existing = get_existing_document(client, project, document["document_id"])
    if existing is not None and existing["content_hash"] != document["content_hash"]:
        if existing["source_class"] == "external":
            raise LoadError(
                f"{document['document_id']}: content_hash changed for an EXTERNAL "
                f"source since last ingest ({existing['content_hash'][:12]}... -> "
                f"{document['content_hash'][:12]}...). Failing per policy — upstream "
                f"content changed, report and inspect before re-ingesting."
            )
        # internal: auto-reingest, fall through.

    # Structural assertion: every external+numeric-claim chunk must have a source_url.
    for c in chunks:
        if document["source_class"] == "external" and c["contains_numeric_claim"] and not document["source_url"]:
            raise LoadError(
                f"{document['document_id']}: chunk {c['chunk_index']} is external and "
                f"contains a numeric claim, but the document has no source_url. Every "
                f"retrievable external number must be traceable to its origin."
            )

    now = datetime.now(timezone.utc)

    # Batch load jobs, not streaming inserts: streaming rows sit in a buffer
    # that blocks DML (DELETE) for up to ~90 minutes, which would break the
    # delete-then-reinsert idempotency this function depends on. Load jobs
    # are immediately visible to DML.
    doc_row = dict(document)
    doc_row["ingested_at"] = now.isoformat()

    client.query(
        f"DELETE FROM `{project}.{DATASET}.documents` WHERE document_id = @doc_id",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("doc_id", "STRING", document["document_id"])]
        ),
    ).result()
    client.load_table_from_json(
        [doc_row], f"{project}.{DATASET}.documents",
        job_config=bigquery.LoadJobConfig(schema=DOCUMENTS_SCHEMA, write_disposition="WRITE_APPEND"),
    ).result()

    client.query(
        f"DELETE FROM `{project}.{DATASET}.chunks` WHERE document_id = @doc_id",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("doc_id", "STRING", document["document_id"])]
        ),
    ).result()

    chunk_rows = []
    for c in chunks:
        row = dict(c)
        row["chunk_id"] = chunk_id(document["document_id"], c["chunk_index"])
        row["ingested_at"] = now.isoformat()
        chunk_rows.append(row)

    if chunk_rows:
        client.load_table_from_json(
            chunk_rows, f"{project}.{DATASET}.chunks",
            job_config=bigquery.LoadJobConfig(schema=CHUNKS_SCHEMA, write_disposition="WRITE_APPEND"),
        ).result()

    return len(chunk_rows)
