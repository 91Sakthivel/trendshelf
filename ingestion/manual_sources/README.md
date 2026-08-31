Drop manually-obtained source files here (PDF or plain text) for documents
where scripted fetch isn't reliable — see `ingestion/sources.py` entries with
`"fetch": "manual"` and the Phase 1 report for which sources these are and
why.

Every file placed here must have a matching entry in
`ingestion/manual_sources_manifest.yaml`, or `run_ingest.py` reports it as
PENDING and does not ingest it — no orphan text.
