"""TrendShelf Phase 1 — document corpus ingestion pipeline.

Separate from the dbt pipeline: writes to the `rag_corpus` BigQuery dataset,
never touches `bronze`, not part of the dbt DAG. Run via:

    python -m ingestion.run_ingest
"""
